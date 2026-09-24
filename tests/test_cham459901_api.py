"""
Test API-level cho module Chấm 459901 — dùng FastAPI TestClient (không cần server
thật đang chạy, không cần đăng nhập thật). Đây là pattern mẫu để viết test API cho
các module khác trong dự án — xem tests/conftest.py::admin_client.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_cham459901_api.py -v
"""

import io
import time

import pandas as pd
import pyzipper
import pytest

from backend.services import cham459901_service as svc

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ZIP_MIME = "application/zip"
_MK = "matkhau-test-459901-api"


@pytest.fixture(autouse=True)
def _mat_khau_zip(monkeypatch):
    """Mật khẩu ZIP đọc từ .env (zip_password()) — không còn hằng số svc.ZIP_PASSWORD."""
    monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', _MK)


def _make_gl02_zip(rows: list[dict]) -> bytes:
    cols = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
            'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
            'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']
    df = pd.DataFrame(rows)[cols]
    csv_bytes = df.to_csv(index=False).encode('utf-8-sig')

    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                              encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_MK.encode())
        zf.writestr('data.csv', csv_bytes)
    return buf.getvalue()


def _gl02_row(ref, dr='0', cr='0'):
    return {
        'TRDATE': '20260601', 'TRBRCD': '1000', 'USERID': '1000API0', 'JOURSEQ': '1',
        'DYTRSEQ': '1', 'LOCAC': '459901', 'CCY': 'VND', 'BUSCD': 'EI', 'UNIT': 'AP',
        'TRCD': '', 'CUSTOMER': '1000-000007709', 'TRTP': 'Normal', 'REFERENCE': ref,
        'REMARK': '', 'DRAMOUNT': dr, 'CRAMOUNT': cr, 'CRTDTM': '',
    }


def _wait_done(admin_client, task_token, timeout_s=10):
    """Poll /progress cho tới khi done=True (BackgroundTasks của Starlette TestClient
    chạy đồng bộ ngay sau response, nhưng poll lặp lại vẫn an toàn/rõ ràng hơn)."""
    deadline = time.time() + timeout_s
    prog = None
    while time.time() < deadline:
        r = admin_client.get(f"/api/cham459901/progress/{task_token}")
        assert r.status_code == 200
        prog = r.json()
        if prog["done"]:
            return prog
        time.sleep(0.05)
    raise AssertionError(f"Job không hoàn thành sau {timeout_s}s: {prog}")


class TestProcessEndpoint:
    def test_single_gl02_zip_processes_successfully(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])

        r = admin_client.post(
            "/api/cham459901/process",
            files=[("files", ("GL02_20260601_1000.zip", zip_bytes, _ZIP_MIME))],
        )
        assert r.status_code == 200
        body = r.json()
        assert "task_token" in body
        assert body["unrecognized"] == []
        assert body["duplicates"] == {}
        assert body["hub_partial"] is False

        prog = _wait_done(admin_client, body["task_token"])
        assert prog["error"] is None
        assert prog["cancelled"] is False
        assert prog["result"]["hub_provided"] is False

    def test_missing_zip_returns_400(self, admin_client):
        """Không file nào có đuôi GL02 hợp lệ (.zip/.xlsx/...) -> 400 ngay, không chạy nền."""
        r = admin_client.post(
            "/api/cham459901/process",
            files=[("files", ("bao_cao.pdf", b"%PDF-1.4", "application/pdf"))],
        )
        assert r.status_code == 400
        assert "GL02" in r.json()["detail"]

    def test_unrecognized_file_reported_but_does_not_block(self, admin_client, monkeypatch, tmp_path):
        """File đuôi lạ (không .zip/.xlsx/...) bị bỏ qua, ghi vào `unrecognized`, không chặn
        cả lượt — khác với 1 file .xlsx nội dung hỏng (đó là main-data hợp lệ về ĐUÔI, sẽ
        được thử đọc và báo lỗi InputError khi xử lý, xem test_cham459901_excel.py)."""
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])

        r = admin_client.post(
            "/api/cham459901/process",
            files=[
                ("files", ("GL02_1000.zip", zip_bytes, _ZIP_MIME)),
                ("files", ("ghi_chu.docx", b"noidungkhac", "application/msword")),
            ],
        )
        assert r.status_code == 200
        assert r.json()["unrecognized"] == ["ghi_chu.docx"]
        # Chờ job xong TRƯỚC khi test kết thúc: luồng nền chạy tràn sang sau khi monkeypatch
        # trả TEMP_DIR về thư mục thật sẽ ghi kết quả vào data/temp_cham459901 (đo 18/09/2026).
        _wait_done(admin_client, r.json()["task_token"])

    def test_duplicate_hub_kind_reported(self, admin_client, monkeypatch, tmp_path):
        """2 file HUB đi trong cùng 1 lượt -> cảnh báo qua `duplicates`, không chặn (file GL02
        chính thì khác — nhiều file cùng lúc được GỘP, xem test_cham459901_nhieu_zip.py)."""
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])

        r = admin_client.post(
            "/api/cham459901/process",
            files=[
                ("files", ("GL02_1000.zip", zip_bytes, _ZIP_MIME)),
                ("files", ("Quay_danh sach giao dich chuyen tien di_1.xlsx", b"stub1", _XLSX_MIME)),
                ("files", ("Quay_danh sach giao dich chuyen tien di_2.xlsx", b"stub2", _XLSX_MIME)),
            ],
        )
        assert r.status_code == 200
        body = r.json()
        assert "hub_di" in body["duplicates"]
        assert set(body["duplicates"]["hub_di"]) == {
            "Quay_danh sach giao dich chuyen tien di_1.xlsx",
            "Quay_danh sach giao dich chuyen tien di_2.xlsx",
        }
        # Chờ job xong TRƯỚC khi test kết thúc: luồng nền chạy tràn sang sau khi monkeypatch
        # trả TEMP_DIR về thư mục thật sẽ ghi kết quả vào data/temp_cham459901 (đo 18/09/2026).
        _wait_done(admin_client, r.json()["task_token"])

    def test_only_one_hub_file_flagged_partial(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])

        r = admin_client.post(
            "/api/cham459901/process",
            files=[
                ("files", ("GL02_1000.zip", zip_bytes, _ZIP_MIME)),
                ("files", ("Quay_danh sach giao dich chuyen tien di_x.xlsx", b"stub", _XLSX_MIME)),
            ],
        )
        assert r.status_code == 200
        assert r.json()["hub_partial"] is True
        # Chờ job xong TRƯỚC khi test kết thúc: luồng nền chạy tràn sang sau khi monkeypatch
        # trả TEMP_DIR về thư mục thật sẽ ghi kết quả vào data/temp_cham459901 (đo 18/09/2026).
        _wait_done(admin_client, r.json()["task_token"])


class TestCancelEndpoint:
    def test_cancel_unknown_token_404(self, admin_client):
        r = admin_client.post("/api/cham459901/cancel/khong-ton-tai")
        assert r.status_code == 404

    def test_cancel_already_done_job_404(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])
        resp = admin_client.post(
            "/api/cham459901/process",
            files=[("files", ("GL02_1000.zip", zip_bytes, _ZIP_MIME))],
        )
        task_token = resp.json()["task_token"]
        _wait_done(admin_client, task_token)

        r = admin_client.post(f"/api/cham459901/cancel/{task_token}")
        assert r.status_code == 404


class TestProgressEndpoint:
    def test_unknown_token_returns_404(self, admin_client):
        r = admin_client.get("/api/cham459901/progress/khong-ton-tai")
        assert r.status_code == 404


class TestDeleteResultEndpoint:
    def test_delete_unknown_result_404(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        r = admin_client.delete("/api/cham459901/result/khong-ton-tai")
        assert r.status_code == 404

    def test_delete_existing_result_then_download_404(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])
        resp = admin_client.post(
            "/api/cham459901/process",
            files=[("files", ("GL02_1000.zip", zip_bytes, _ZIP_MIME))],
        )
        prog = _wait_done(admin_client, resp.json()["task_token"])
        token = prog["result"]["token"]

        # Tải được trước khi xóa
        r_ok = admin_client.get(f"/api/cham459901/download/{token}/huy")
        assert r_ok.status_code == 200

        r_del = admin_client.delete(f"/api/cham459901/result/{token}")
        assert r_del.status_code == 200

        r_after = admin_client.get(f"/api/cham459901/download/{token}/huy")
        assert r_after.status_code == 404


class TestDownloadEndpoint:
    def test_invalid_file_type_400(self, admin_client):
        r = admin_client.get("/api/cham459901/download/any-token/invalid_type")
        assert r.status_code == 400

    def test_unknown_token_404(self, admin_client):
        r = admin_client.get("/api/cham459901/download/khong-ton-tai/huy")
        assert r.status_code == 404


class TestTokenPathTraversalBlocked:
    """Regression test cho lỗ path traversal của PR#63: `token` ghép thẳng vào
    `TEMP_DIR / token` không qua `safe_filename()`, cho phép `DELETE
    /result/..%2F..` xoá bất kỳ thư mục nào trên máy chủ. Dựng thật một thư mục
    "bí mật" nằm NGOÀI `TEMP_DIR` rồi thử traversal — phải không đụng được tới,
    không chỉ kiểm tra không lỗi 500."""

    def test_delete_result_cannot_escape_temp_dir(self, admin_client, monkeypatch, tmp_path):
        temp_dir = tmp_path / "temp_cham459901"
        temp_dir.mkdir()
        monkeypatch.setattr(svc, "TEMP_DIR", temp_dir)

        bi_mat = tmp_path / "bi_mat"
        bi_mat.mkdir()
        (bi_mat / "khong_duoc_xoa.txt").write_text("du lieu quan trong")

        r = admin_client.delete("/api/cham459901/result/..%2Fbi_mat")
        assert r.status_code == 404
        assert bi_mat.exists(), "Thư mục ngoài TEMP_DIR không được đụng tới"
        assert (bi_mat / "khong_duoc_xoa.txt").exists()

    def test_download_result_cannot_escape_temp_dir(self, admin_client, monkeypatch, tmp_path):
        temp_dir = tmp_path / "temp_cham459901"
        temp_dir.mkdir()
        monkeypatch.setattr(svc, "TEMP_DIR", temp_dir)

        bi_mat = tmp_path / "bi_mat"
        bi_mat.mkdir()
        (bi_mat / "huy.xlsx").write_bytes(b"khong phai excel that")

        r = admin_client.get("/api/cham459901/download/..%2Fbi_mat/huy")
        assert r.status_code == 404


class TestKhongConCheDoThuMucServer:
    """17/09/2026 bỏ hẳn chế độ "Chọn thư mục server" — module cuối cùng còn giữ nó.
    Canh riêng cửa cũ; lưới toàn hệ thống nằm ở tests/test_khong_nhan_duong_dan_thu_muc.py."""

    def test_process_folder_da_go(self, admin_client, tmp_path):
        r = admin_client.post(
            "/api/cham459901/process_folder", json={"folder_path": str(tmp_path)},
        )
        assert r.status_code in (404, 405)
