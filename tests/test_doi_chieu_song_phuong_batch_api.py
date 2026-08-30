"""
Test API-level cho chế độ hàng loạt (nhiều file / thư mục server) của module
Đối chiếu Song phương — Phân loại dữ liệu IPCAS.

Quyết định 2026-08-28: upload 1-file/lần "rất khó dùng" khi cần xử lý nhiều ngày — thêm
`/start_batch` (nhiều file qua trình duyệt) và `/start_folder` (thư mục server), theo đúng
pattern job nền + poll đã dùng ở `doi_chieu_song_phuong_kenh`/`_core`. `process_zip()` (business
logic định tuyến IPCAS) không đổi — chỉ thêm lớp orchestration chạy tuần tự nhiều ZIP.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_doi_chieu_song_phuong_batch_api.py -v
"""

import io
import time

import pandas as pd
import pyzipper

from backend.services import doi_chieu_song_phuong_service as svc

_COLS = ["TRBRCD", "CUSTOMER", "CRAMOUNT", "DRAMOUNT", "REFERENCE", "REMARK"]


def _make_ipcas_zip(rows: list[dict]) -> bytes:
    """ZIP IPCAS thật mã hoá AES (đúng `ZIP_PASSWORD` module đang dùng)."""
    df = pd.DataFrame(rows, columns=_COLS)
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, "w", compression=pyzipper.ZIP_DEFLATED,
                              encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(svc.ZIP_PASSWORD)
        zf.writestr("gl02.csv", df.to_csv(index=False).encode("utf-8-sig"))
    return buf.getvalue()


def _row(customer, cramount, dramount):
    return {"TRBRCD": "1000", "CUSTOMER": customer, "CRAMOUNT": cramount,
            "DRAMOUNT": dramount, "REFERENCE": "REF001", "REMARK": "TEST"}


# NH 202 (1000-003046328): 1 dòng ĐẾN (CRAMOUNT=0), 1 dòng ĐI (DRAMOUNT=0)
_ZIP_202 = _make_ipcas_zip([
    _row("1000-003046328", "0", "100000"),
    _row("1000-003046328", "200000", "0"),
])
# NH 201 (1000-003046287): 1 dòng ĐẾN
_ZIP_201 = _make_ipcas_zip([_row("1000-003046287", "0", "50000")])


def _wait_done(admin_client, job_id, timeout_s=15):
    deadline = time.time() + timeout_s
    prog = None
    while time.time() < deadline:
        r = admin_client.get(f"/api/doi_chieu_song_phuong/poll/{job_id}")
        assert r.status_code == 200
        prog = r.json()
        if prog["status"] in ("done", "error", "cancelled"):
            return prog
        time.sleep(0.05)
    raise AssertionError(f"Job không hoàn thành sau {timeout_s}s: {prog}")


class TestStartBatchEndpoint:
    def test_nhieu_file_xu_ly_tuan_tu(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "_out")

        r = admin_client.post(
            "/api/doi_chieu_song_phuong/start_batch",
            files=[
                ("files", ("ngay1.zip", _ZIP_202, "application/zip")),
                ("files", ("ngay2.zip", _ZIP_201, "application/zip")),
            ],
        )
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        prog = _wait_done(admin_client, job_id)
        assert prog["status"] == "done", prog
        results = prog["results"]
        assert len(results) == 2
        assert {r["source_name"] for r in results} == {"ngay1.zip", "ngay2.zip"}

        ngay1 = next(r for r in results if r["source_name"] == "ngay1.zip")
        stats_202 = next(s for s in ngay1["stats"] if s["ma_nh"] == "202")
        assert stats_202["so_lenh_den"] == 1
        assert stats_202["so_lenh_di"] == 1

        # Tải thử 1 file kết quả của ngay1 — token độc lập cho mỗi file nguồn
        r_dl = admin_client.get(
            f"/api/doi_chieu_song_phuong/download/{ngay1['token']}/202_DEN"
        )
        assert r_dl.status_code == 200
        assert "100000" in r_dl.text

    def test_khong_chon_file_bao_loi_ro(self, admin_client):
        # Không có multipart field "files" nào -> FastAPI tự trả 422 (thiếu tham số bắt
        # buộc) trước khi vào tới nhánh `if not files` của route.
        r = admin_client.post("/api/doi_chieu_song_phuong/start_batch", files=[])
        assert r.status_code == 422

    def test_1_file_loi_khong_chan_file_con_lai(self, admin_client, monkeypatch, tmp_path):
        """ZIP hỏng ở giữa danh sách không được làm crash cả job — các file lành vẫn ra
        kết quả (đúng triết lý 'bỏ qua lỗi 1 phần, không crash cả job' dùng chung toàn dự án)."""
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "_out")

        r = admin_client.post(
            "/api/doi_chieu_song_phuong/start_batch",
            files=[
                ("files", ("hong.zip", b"khong-phai-zip", "application/zip")),
                ("files", ("lanh.zip", _ZIP_201, "application/zip")),
            ],
        )
        job_id = r.json()["job_id"]
        prog = _wait_done(admin_client, job_id)
        assert prog["status"] == "done"
        results = prog["results"]
        assert len(results) == 2
        hong = next(r for r in results if r["source_name"] == "hong.zip")
        assert "error" in hong
        lanh = next(r for r in results if r["source_name"] == "lanh.zip")
        assert "error" not in lanh
        assert lanh["total_rows"] == 1


class TestStartFolderEndpoint:
    def test_thu_muc_nhieu_zip(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "_out")
        day_dir = tmp_path / "ipcas"
        day_dir.mkdir()
        (day_dir / "20260821.zip").write_bytes(_ZIP_202)
        (day_dir / "20260822.zip").write_bytes(_ZIP_201)

        r = admin_client.post(
            "/api/doi_chieu_song_phuong/start_folder",
            json={"folder_path": str(day_dir)},
        )
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        prog = _wait_done(admin_client, job_id)
        assert prog["status"] == "done"
        assert len(prog["results"]) == 2

    def test_thu_muc_khong_ton_tai_tra_400(self, admin_client, tmp_path):
        r = admin_client.post(
            "/api/doi_chieu_song_phuong/start_folder",
            json={"folder_path": str(tmp_path / "khong-ton-tai")},
        )
        assert r.status_code == 400

    def test_thu_muc_rong_bao_loi_ro(self, admin_client, tmp_path):
        empty_dir = tmp_path / "rong"
        empty_dir.mkdir()
        r = admin_client.post(
            "/api/doi_chieu_song_phuong/start_folder",
            json={"folder_path": str(empty_dir)},
        )
        assert r.status_code == 400
        assert "zip" in r.json()["detail"].lower()


class TestDownloadEndpoint:
    def test_token_khong_phai_uuid_tra_400(self, admin_client):
        """Chặn dò đường dẫn qua token — lỗ hổng thật đã vá ở PR#63 cham459901
        (`token` ghép thẳng vào `TEMP_DIR / token / ...` không qua kiểm tra). `token` không phải
        UUID hợp lệ (dù không chứa `/`) phải bị chặn ngay, không được đi tới bước ghép đường dẫn."""
        r = admin_client.get(
            "/api/doi_chieu_song_phuong/download/khong-phai-uuid-hop-le/202_DEN"
        )
        assert r.status_code == 400

    def test_duong_dan_chua_dau_gach_cheo_khong_khop_route(self, admin_client):
        """`token` chứa `/` (kiểu dò đường dẫn `..%2F..%2F..`) không khớp route 2 tham số —
        FastAPI tự trả 404 trước khi vào tới handler."""
        r = admin_client.get(
            "/api/doi_chieu_song_phuong/download/..%2F..%2F..%2Fetc/202_DEN"
        )
        assert r.status_code == 404

    def test_token_gia_dang_uuid_tra_404_khong_500(self, admin_client):
        r = admin_client.get(
            "/api/doi_chieu_song_phuong/download/00000000-0000-0000-0000-000000000000/202_DEN"
        )
        assert r.status_code == 404


class TestPollEndpoint:
    def test_unknown_job_returns_404(self, admin_client):
        r = admin_client.get("/api/doi_chieu_song_phuong/poll/khong-ton-tai")
        assert r.status_code == 404


class TestCancelEndpoint:
    def test_unknown_job_returns_404(self, admin_client):
        r = admin_client.post("/api/doi_chieu_song_phuong/cancel/khong-ton-tai")
        assert r.status_code == 404
