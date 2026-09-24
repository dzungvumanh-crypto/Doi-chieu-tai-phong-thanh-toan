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
def _doi_chieu_chay_trong_luong(monkeypatch):
    """Mặc định mọi test chạy pipeline đối chiếu TRONG LUỒNG, không tách tiến trình.

    Tiến trình con import lại module nên không thấy `monkeypatch` của test: test vá
    `svc.TEMP_DIR` sang thư mục tạm mà chạy tiến trình thật là ghi kết quả vào
    `data/temp_*` THẬT (đã xảy ra 18/09/2026 — 19 thư mục 459901, đã dọn).
    Test cần tiến trình thật thì xin fixture `tien_trinh_that`."""
    monkeypatch.setenv("DOI_CHIEU_TIEN_TRINH", "0")


@pytest.fixture
def tien_trinh_that(monkeypatch):
    """Bật chạy tách tiến trình thật — chỉ dùng khi test KHÔNG vá biến toàn cục của module."""
    monkeypatch.delenv("DOI_CHIEU_TIEN_TRINH", raising=False)


@pytest.fixture(autouse=True)
def _don_job_ach():
    """Xoá sổ job của CẢ BỐN module đối chiếu trước/sau mỗi test.

    `ach_service._jobs` là dict toàn cục trong RAM, sống suốt phiên pytest. Từ khi
    `/api/ach/start` chặn "một phiên tại một thời điểm" (409), một job do test trước
    để lại ở trạng thái awaiting_confirmation sẽ làm test sau bị từ chối — lỗi hiện
    ra ở file test hoàn toàn khác, rất khó lần.

    Nay chốt đó dùng chung cho cả bốn module (backend/core/phien_doi_chieu.py), nên
    ba module kia dính đúng cái bẫy ấy: một lượt 459901 mà luồng nền chưa kịp đặt
    `done=True` trước lúc test kết thúc sẽ làm mọi test 459901 SAU đó ăn 409. Đã xảy
    ra thật khi thêm chốt — 7 test đỏ ở file không liên quan gì tới thay đổi.

    Dọn từng sổ chứ không gọi hàm dọn của service: hàm đó còn xoá thư mục kết quả
    theo mốc thời gian, không phải việc của test."""
    from backend.services import (
        ach_service,
        cham459901_service,
        doi_chieu_song_phuong_kenh_core_service as sp_service,
        ilo1000_service,
    )
    so = (ach_service._jobs, ilo1000_service._jobs,
          sp_service._jobs, cham459901_service._progress)
    for s in so:
        s.clear()
    yield
    for s in so:
        s.clear()


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
