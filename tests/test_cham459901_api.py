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


class TestProcessFolderEndpoint:
    @pytest.fixture(autouse=True)
    def _mo_pham_vi(self, monkeypatch, tmp_path):
        """/process_folder chỉ quét trong CHAM459901_FOLDER_ROOTS — mở đúng tmp_path
        của từng test. Phần kiểm phạm vi nằm ở TestProcessFolderPhamVi bên dưới."""
        monkeypatch.setenv("CHAM459901_FOLDER_ROOTS", str(tmp_path))

    def test_folder_with_gl02_zip_processes_successfully(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "out")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        zip_bytes = _make_gl02_zip([_gl02_row("REF1", dr="100000")])
        (src_dir / "GL02_20260601_1000.zip").write_bytes(zip_bytes)

        r = admin_client.post(
            "/api/cham459901/process_folder",
            json={"folder_path": str(src_dir)},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["unrecognized"] == []
        assert body["hub_partial"] is False

        prog = _wait_done(admin_client, body["task_token"])
        assert prog["error"] is None
        assert prog["result"]["hub_provided"] is False

    def test_nonexistent_folder_returns_400(self, admin_client, tmp_path):
        r = admin_client.post(
            "/api/cham459901/process_folder",
            json={"folder_path": str(tmp_path / "khong-ton-tai")},
        )
        assert r.status_code == 400
        assert "không tồn tại" in r.json()["detail"]

    def test_multiple_gl02_zip_in_folder_are_merged(self, admin_client, monkeypatch, tmp_path):
        """Cùng hành vi GỘP như /process (test_cham459901_nhieu_zip.py) — không phải
        'trùng loại, chỉ dùng file cuối' như PR#63 làm với file GL02 chính."""
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "out")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.zip").write_bytes(_make_gl02_zip([_gl02_row("REF1", dr="100000")]))
        (src_dir / "b.zip").write_bytes(_make_gl02_zip([_gl02_row("REF2", dr="200000")]))

        r = admin_client.post(
            "/api/cham459901/process_folder",
            json={"folder_path": str(src_dir)},
        )
        assert r.status_code == 200
        prog = _wait_done(admin_client, r.json()["task_token"])
        assert prog["error"] is None, prog["error"]
        assert prog["result"]["n_files"] == 2
        assert prog["result"]["total_rows"] == 2

    def test_unrecognized_file_bytes_never_read(self, admin_client, monkeypatch, tmp_path):
        """Vá lỗi RAM/DoS của PR#63: `process_folder` từng đọc byte MỌI file trong thư
        mục trước khi lọc theo tên. Đặt 1 file không khớp mẫu nào (đuôi lạ) mà mở ra là
        lỗi — nếu code vẫn cố đọc nó, test này phải fail."""
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "out")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "GL02_1000.zip").write_bytes(
            _make_gl02_zip([_gl02_row("REF1", dr="100000")])
        )

        file_khong_duoc_doc = src_dir / "khong_lien_quan.bin"
        file_khong_duoc_doc.write_bytes(b"x" * 1024)
        goc_read_bytes = type(file_khong_duoc_doc).read_bytes

        def _chan_doc(self):
            if self.name == "khong_lien_quan.bin":
                raise AssertionError(
                    "process_folder đã đọc byte của file không khớp mẫu nào — "
                    "đúng lỗi RAM/DoS mà PR#63 mắc phải."
                )
            return goc_read_bytes(self)

        import pathlib
        monkeypatch.setattr(pathlib.Path, "read_bytes", _chan_doc)

        r = admin_client.post(
            "/api/cham459901/process_folder",
            json={"folder_path": str(src_dir)},
        )
        assert r.status_code == 200
        assert r.json()["unrecognized"] == ["khong_lien_quan.bin"]

    def test_folder_without_zip_returns_400(self, admin_client, tmp_path):
        """Không file nào có đuôi GL02 hợp lệ trong thư mục -> 400 ngay."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "bao_cao.pdf").write_bytes(b"%PDF-1.4")

        r = admin_client.post(
            "/api/cham459901/process_folder",
            json={"folder_path": str(src_dir)},
        )
        assert r.status_code == 400
        assert "GL02" in r.json()["detail"]


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


class TestProcessFolderPhamVi:
    """`folder_path` là đường dẫn do người dùng gõ và server tự đọc file theo đó.
    Không giới hạn gốc thì endpoint vừa dò được thư mục nào có thật trên máy chủ,
    vừa trả về TÊN mọi file lạ trong đó qua `unrecognized`."""

    def test_ngoai_pham_vi_bi_chan_403(self, admin_client, monkeypatch, tmp_path):
        goc = tmp_path / "cho_phep"
        goc.mkdir()
        monkeypatch.setenv("CHAM459901_FOLDER_ROOTS", str(goc))

        ngoai = tmp_path / "rieng_tu"
        ngoai.mkdir()
        (ngoai / "GL02.zip").write_bytes(_make_gl02_zip([_gl02_row("REF1", dr="100000")]))
        (ngoai / "bang_luong_2026.xlsx").write_bytes(b"stub")

        r = admin_client.post(
            "/api/cham459901/process_folder", json={"folder_path": str(ngoai)},
        )
        assert r.status_code == 403
        # Không được hé lộ tên file nào nằm trong thư mục ngoài phạm vi.
        assert "bang_luong_2026" not in r.text

    def test_khong_lo_thu_muc_co_that_hay_khong(self, admin_client, monkeypatch, tmp_path):
        """Ngoài phạm vi thì thư mục CÓ THẬT và KHÔNG CÓ THẬT phải trả về cùng một
        câu trả lời — khác nhau là đủ để dò cây thư mục của máy chủ."""
        goc = tmp_path / "cho_phep"
        goc.mkdir()
        monkeypatch.setenv("CHAM459901_FOLDER_ROOTS", str(goc))
        co_that = tmp_path / "co_that"
        co_that.mkdir()

        r1 = admin_client.post(
            "/api/cham459901/process_folder", json={"folder_path": str(co_that)},
        )
        r2 = admin_client.post(
            "/api/cham459901/process_folder", json={"folder_path": str(tmp_path / "khong_co")},
        )
        assert r1.status_code == r2.status_code == 403
        assert r1.json()["detail"] == r2.json()["detail"]

    def test_di_nguoc_ra_khoi_goc_bi_chan(self, admin_client, monkeypatch, tmp_path):
        goc = tmp_path / "cho_phep"
        goc.mkdir()
        monkeypatch.setenv("CHAM459901_FOLDER_ROOTS", str(goc))

        r = admin_client.post(
            "/api/cham459901/process_folder",
            json={"folder_path": str(goc / ".." / "rieng_tu")},
        )
        assert r.status_code == 403

    def test_thu_muc_con_cua_goc_van_chay(self, admin_client, monkeypatch, tmp_path):
        goc = tmp_path / "cho_phep"
        con = goc / "thang_06"
        con.mkdir(parents=True)
        monkeypatch.setenv("CHAM459901_FOLDER_ROOTS", str(goc))
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "out")
        (con / "GL02.zip").write_bytes(_make_gl02_zip([_gl02_row("REF1", dr="100000")]))

        r = admin_client.post(
            "/api/cham459901/process_folder", json={"folder_path": str(con)},
        )
        assert r.status_code == 200

    def test_chua_cau_hinh_thi_khoa_va_noi_ro_phai_lam_gi(self, admin_client, monkeypatch, tmp_path):
        monkeypatch.delenv("CHAM459901_FOLDER_ROOTS", raising=False)
        src = tmp_path / "src"
        src.mkdir()

        r = admin_client.post(
            "/api/cham459901/process_folder", json={"folder_path": str(src)},
        )
        assert r.status_code == 400
        assert "CHAM459901_FOLDER_ROOTS" in r.json()["detail"]
