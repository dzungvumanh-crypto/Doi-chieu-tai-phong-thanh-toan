"""Ảnh chữ ký cá nhân — /api/auth/signature (tải lên, xem, xóa)."""
import base64
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-image-body"


@pytest.fixture
def client():
    # check_same_thread=False: TestClient chạy endpoint sync ở thread khác, mà mọi
    # request trong 1 test phải dùng chung connection thì dữ liệu mới còn lại
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE user_signatures (
            staff_id   INTEGER PRIMARY KEY,
            filename   TEXT,
            image      BLOB NOT NULL,
            updated_at DATETIME
        );
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER, action TEXT, target_type TEXT, target_id INTEGER,
            detail TEXT, ip_address TEXT, created_at DATETIME
        );
        CREATE TABLE login_sessions (
            staff_id INTEGER PRIMARY KEY, ip_address TEXT, session_key TEXT, expires_at DATETIME
        );
    """)
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 7, "role": StaffRole.ADMIN, "username": "u7", "full_name": "Người Bảy"
    }
    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()
    conn.close()


def test_chua_co_chu_ky(client):
    r = client.get("/api/auth/signature")
    assert r.status_code == 200
    assert r.json() == {"has_signature": False}


def test_tai_len_va_doc_lai(client):
    r = client.post("/api/auth/signature", files={"file": ("khanhbui.png", PNG, "image/png")})
    assert r.status_code == 200, r.text

    r = client.get("/api/auth/signature")
    body = r.json()
    assert body["has_signature"] is True
    assert body["filename"] == "khanhbui.png"
    assert body["size"] == len(PNG)
    assert base64.b64decode(body["data_url"].split(",", 1)[1]) == PNG


def test_tai_len_lan_hai_ghi_de(client):
    client.post("/api/auth/signature", files={"file": ("cu.png", PNG, "image/png")})
    moi = PNG + b"-v2"
    client.post("/api/auth/signature", files={"file": ("moi.png", moi, "image/png")})

    body = client.get("/api/auth/signature").json()
    assert body["filename"] == "moi.png"
    assert body["size"] == len(moi)


def test_tu_choi_file_khong_phai_png(client):
    # .jpg đổi tên thành .png vẫn phải bị chặn (kiểm tra 8 byte đầu, không tin đuôi file)
    r = client.post("/api/auth/signature",
                    files={"file": ("chu_ky.png", b"\xff\xd8\xff\xe0 jpeg", "image/png")})
    assert r.status_code == 400
    assert "PNG" in r.json()["detail"]


def test_tu_choi_anh_qua_lon(client):
    to = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)
    r = client.post("/api/auth/signature", files={"file": ("to.png", to, "image/png")})
    assert r.status_code == 400
    assert "2 MB" in r.json()["detail"]


def test_xoa_chu_ky(client):
    client.post("/api/auth/signature", files={"file": ("a.png", PNG, "image/png")})
    assert client.request("DELETE", "/api/auth/signature").status_code == 200
    assert client.get("/api/auth/signature").json() == {"has_signature": False}
    # Xóa lần hai — không còn gì để xóa
    assert client.request("DELETE", "/api/auth/signature").status_code == 404
