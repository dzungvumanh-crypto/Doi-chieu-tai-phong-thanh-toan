"""Test mã hoá bản sao lưu (20/08/2026).

File .db trần chứa NGUYÊN cột `pwd_hash` của toàn bộ tài khoản. Ai đọc được thư
mục `data/backups` — hoặc share mạng `BACKUP_EXTRA_DIR` — là mang mã băm về dò
ngoại tuyến, không cần quyền gì trong phần mềm.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_backup_ma_hoa.py -v
"""

import sqlite3

import pyzipper
import pytest

from backend.services import backup_service as bs


_MAT_KHAU = "mat-khau-thu-nghiem"


def _db_mau(duong_dan):
    c = sqlite3.connect(duong_dan)
    c.execute("CREATE TABLE user_tttt (id INTEGER, pwd_hash TEXT)")
    c.execute("INSERT INTO user_tttt VALUES (1, '$2b$12$bam-mat-khau-that')")
    c.commit()
    c.close()


@pytest.fixture
def thu_muc(tmp_path, monkeypatch):
    """monkeypatch.setenv chứ không sửa .env: `backend.core.config` gọi
    load_dotenv(override=True) lúc IMPORT, nên biến đặt trước khi import sẽ bị
    .env ghi đè — đặt sau thì thắng. `_mat_khau()` đọc os.getenv lúc chạy."""
    monkeypatch.setattr(bs, "_BACKUP_DIR", tmp_path)
    _db_mau(str(tmp_path / "goc.db"))
    return tmp_path


class TestCoMatKhau:
    def test_ra_file_zip_va_khong_con_ban_db_tran(self, thu_muc, monkeypatch):
        monkeypatch.setenv("BACKUP_PASSWORD", _MAT_KHAU)
        ra = bs.run_backup(str(thu_muc / "goc.db"))
        assert ra.suffix == ".zip"
        assert not list(thu_muc.glob("ksnb_*.db")), "bản .db chưa mã hoá vẫn còn"

    def test_mo_duoc_bang_mat_khau_dung(self, thu_muc, monkeypatch):
        monkeypatch.setenv("BACKUP_PASSWORD", _MAT_KHAU)
        ra = bs.run_backup(str(thu_muc / "goc.db"))
        with pyzipper.AESZipFile(ra) as zf:
            zf.setpassword(_MAT_KHAU.encode())
            assert zf.read(zf.namelist()[0])

    def test_mat_khau_sai_thi_khong_mo_duoc(self, thu_muc, monkeypatch):
        """Nếu ca này xanh nhầm (mở được) thì file chỉ được NÉN chứ không mã
        hoá — nén thì ai cũng giải được, coi như chưa vá gì."""
        monkeypatch.setenv("BACKUP_PASSWORD", _MAT_KHAU)
        ra = bs.run_backup(str(thu_muc / "goc.db"))
        with pytest.raises(Exception):
            with pyzipper.AESZipFile(ra) as zf:
                zf.setpassword(b"mat-khau-sai")
                zf.read(zf.namelist()[0])

    def test_ban_zip_van_duoc_xoay_vong(self, thu_muc, monkeypatch):
        """Luật dọn bản cũ trước đây chỉ nhìn đuôi .db — đổi sang .zip mà quên
        sửa thì thư mục backup phình mãi, không ai xoá."""
        monkeypatch.setenv("BACKUP_PASSWORD", _MAT_KHAU)
        bs.run_backup(str(thu_muc / "goc.db"))
        ban = bs._ban_tu_sinh(thu_muc)
        assert len(ban) == 1 and ban[0][2].suffix == ".zip"
        assert bs.last_backup_info()["exists"] is True


class TestKhongCoMatKhau:
    """Thiếu cấu hình KHÔNG được làm mất bản sao lưu: mất dữ liệu thật nặng hơn
    hẳn việc bản sao lưu chưa mã hoá. Chỉ cảnh báo."""

    def test_van_backup_ra_file_db(self, thu_muc, monkeypatch):
        monkeypatch.delenv("BACKUP_PASSWORD", raising=False)
        ra = bs.run_backup(str(thu_muc / "goc.db"))
        assert ra.suffix == ".db" and ra.exists()

    def test_co_ghi_canh_bao(self, thu_muc, monkeypatch, caplog):
        monkeypatch.delenv("BACKUP_PASSWORD", raising=False)
        with caplog.at_level("WARNING"):
            bs.run_backup(str(thu_muc / "goc.db"))
        assert any("BACKUP_PASSWORD" in r.getMessage() for r in caplog.records),             "không có cảnh báo nào nhắc BACKUP_PASSWORD"
