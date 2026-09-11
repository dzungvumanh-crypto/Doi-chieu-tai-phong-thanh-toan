"""GET /health — công khai, chỉ báo backend + CSDL đọc được, không lộ gì thêm.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_health.py -v
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod


@pytest.fixture
def client():
    # KHÔNG dependency_overrides, KHÔNG đăng nhập: /health phải trả lời người chưa đăng nhập
    return TestClient(main_mod.app)


def test_db_doc_duoc_thi_ok_va_chi_hai_truong(client, tmp_path, monkeypatch):
    # Đường dẫn có dấu + khoảng trắng: as_uri() phải mã hoá đúng (máy thật có thể đặt ở đó)
    (tmp_path / "Thư mục có dấu").mkdir()
    db = tmp_path / "Thư mục có dấu" / "ksnb.db"
    sqlite3.connect(db).execute("CREATE TABLE user_tttt (id INTEGER)").connection.close()
    monkeypatch.setattr(main_mod, "DB_PATH", str(db))
    r = client.get("/health")
    assert r.status_code == 200
    # Công khai → đúng hai trường, không đường dẫn / phiên bản
    assert r.json() == {"status": "ok", "db_ok": True}


def test_mat_file_db_thi_503_va_khong_de_ra_db_moi(client, tmp_path, monkeypatch):
    # sqlite3.connect() thường sẽ TẠO file rỗng khi đường dẫn không có — /health mà làm
    # vậy thì báo "ok" trên một DB trắng, và backend khởi động lại sẽ dùng luôn file đó.
    # Thư mục CÓ THẬT, chỉ thiếu file — đúng trường hợp connect() thường sẽ tạo file mới.
    # (Để thư mục cha không tồn tại thì connect() thường cũng lỗi → test xanh cả khi bỏ mode=ro.)
    mat = tmp_path / "ksnb.db"
    monkeypatch.setattr(main_mod, "DB_PATH", str(mat))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db_ok": False}
    assert not mat.exists()


def test_file_0_byte_thi_503(client, tmp_path, monkeypatch):
    # SQLite coi file rỗng là DB rỗng HỢP LỆ — hỏi sqlite_master thì không lỗi, báo ok sai.
    rong = tmp_path / "ksnb.db"
    rong.write_bytes(b"")
    monkeypatch.setattr(main_mod, "DB_PATH", str(rong))
    assert client.get("/health").status_code == 503


def test_file_hong_thi_503(client, tmp_path, monkeypatch):
    hong = tmp_path / "hong.db"
    hong.write_bytes(b"day khong phai file sqlite " * 100)
    monkeypatch.setattr(main_mod, "DB_PATH", str(hong))
    r = client.get("/health")
    assert r.status_code == 503 and r.json()["db_ok"] is False
