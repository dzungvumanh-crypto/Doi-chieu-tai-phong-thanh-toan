"""Fixtures dùng chung cho toàn bộ test suite của dự án.

Chạy test: .venv\\Scripts\\python.exe -m pytest tests/ -v
(Lưu ý: dùng đúng .venv của dự án — Python hệ thống có thể thiếu dependency như
python-jose; .venv có thể thiếu pytest nếu chưa `pip install pytest` — cài 1 lần.)
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app


def cap_quyen(conn: sqlite3.Connection, staff_id: int, *feature_codes: str) -> None:
    """Gán mã quyền cho một nhân viên qua nhóm — dùng cho test đi qua require_feature().

    Mọi menu/thao tác đều gate bằng mã quyền (xem mục "Phân quyền" trong docs/DESIGN.md),
    nên test dựng người dùng "có quyền" phải gán thật chứ không chỉ đặt role/phòng.
    Mỗi lần gọi tạo một nhóm riêng — test không phải nghĩ tên nhóm."""
    gid = conn.execute(
        "INSERT INTO user_groups (name, is_active) VALUES (?, 1)",
        (f"test-grp-{staff_id}-{'-'.join(feature_codes)}",),
    ).lastrowid
    conn.execute("INSERT INTO group_members (group_id, staff_id) VALUES (?, ?)", (gid, staff_id))
    for code in feature_codes:
        conn.execute(
            "INSERT INTO group_features (group_id, feature_code) VALUES (?, ?)", (gid, code)
        )
    conn.commit()


def _fake_admin() -> dict:
    return {"id": 1, "role": StaffRole.ADMIN, "username": "test-admin", "full_name": "Test Admin"}


def _fake_db():
    """DB tạm trong RAM — không đụng tới data/*.db thật. Route nào thật sự cần
    query DB (không chỉ auth) nên override get_db lại trong test riêng với schema cần thiết."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _don_job_ach():
    """Xoá sổ job ACH trước/sau mỗi test.

    `ach_service._jobs` là dict toàn cục trong RAM, sống suốt phiên pytest. Từ khi
    `/api/ach/start` chặn "một phiên tại một thời điểm" (409), một job do test trước
    để lại ở trạng thái awaiting_confirmation sẽ làm test sau bị từ chối — lỗi hiện
    ra ở file test hoàn toàn khác, rất khó lần."""
    from backend.services import ach_service
    ach_service._jobs.clear()
    yield
    ach_service._jobs.clear()


@pytest.fixture
def admin_client():
    """TestClient đã "đăng nhập" sẵn với quyền admin — bypass JWT/session/DB thật bằng
    FastAPI dependency_overrides, KHÔNG chạy lifespan (không migrate DB thật, không start
    backup scheduler thread) vì không dùng `with TestClient(app) as client:`.

    Dùng cho mọi test API-level trong dự án — không riêng module nào."""
    app.dependency_overrides[get_current_staff] = _fake_admin
    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
