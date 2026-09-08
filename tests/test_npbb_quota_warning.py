"""Cảnh báo hạn mức không đủ cho NPBB (nghỉ phép bắt buộc) + ứng phép năm sau
+ tự động hủy đúng ngày đăng ký nếu vẫn không đủ hạn mức.

Khoá lại đúng các lỗi đã tìm và sửa qua rà soát 2026-09-08:
1. get_npbb_quota_warning và confirm_npbb_borrow trước đây đo "còn lại" bằng
   2 công thức khác nhau (lệch đúng leave_days) — sau khi "Tiếp tục" thành
   công, cảnh báo vẫn hiện lại y nguyên vĩnh viễn vì remaining luôn về đúng 0
   theo công thức cũ. Nay dùng chung 1 hàm _npbb_remaining_excl.
2. confirm_npbb_borrow không chặn khi đơn đang có đơn điều chỉnh còn hiệu
   lực — ghi 1 giá trị vô tác dụng (bị _NO_ACTIVE_ADJ_SQL loại khỏi mọi phép
   tính) dù API trả 200 "thành công".
3. NPBB không bị chặn hạn mức lúc tạo nên chỉ thật sự "tiêu" hạn mức đúng
   ngày đăng ký (start_date) — đơn đã duyệt nhưng ngày nghỉ còn ở tương lai
   không được tính vào "đã dùng" cho tới đúng ngày đó (_calc_used_days).
4. Tự động hủy đơn NPBB đúng ngày đăng ký nếu hạn mức (không tính NPBB) vẫn
   không đủ — trừ khi đã "Tiếp tục" (ứng năm sau) từ trước.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_npbb_quota_warning.py -v
"""
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.db.migrations import _create_tables, _ensure_indexes
from backend.main import app


_DB_PATH_HOLDER: dict = {}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test_npbb_quota.db")
    import backend.database as dbmod
    import backend.db.migrations as mig
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(mig, "DB_PATH", path)
    _create_tables(path)
    _ensure_indexes()

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _DB_PATH_HOLDER["path"] = path
    yield conn
    conn.close()
    _DB_PATH_HOLDER.clear()


@pytest.fixture
def staff(db):
    dept_id = db.execute(
        "INSERT INTO departments (code, name, is_source, is_active) VALUES ('SWIFT','Phong Swift',1,1)"
    ).lastrowid
    staff_id = db.execute(
        """INSERT INTO user_tttt (employee_code, full_name, role, department_id,
               is_active, username, pwd_hash) VALUES (?,?,?,?,?,?,?)""",
        ("E10", "GDV Test NPBB", "chuyen_vien", dept_id, 1, "u_e10", "x"),
    ).lastrowid
    db.commit()
    return staff_id


def _client(db, staff_id, role="chuyen_vien"):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": staff_id, "role": role, "username": "u_e10", "join_industry_date": None,
    }
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def _set_quota(db, staff_id, year, days):
    db.execute("DELETE FROM leave_quotas WHERE staff_id=? AND year=?", (staff_id, year))
    db.execute("INSERT INTO leave_quotas (staff_id, year, quota_days) VALUES (?,?,?)", (staff_id, year, days))
    db.commit()


def _insert_leave(db, staff_id, leave_type, start, end, status="approved", adjusts_leave_id=None):
    cur = db.execute(
        """INSERT INTO leave_records
               (staff_id, leave_type, start_date, end_date, status, reason, created_at, updated_at,
                other_deduct_quota, adjusts_leave_id)
           VALUES (?,?,?,?,?, 'test', datetime('now'), datetime('now'), 1, ?)""",
        (staff_id, leave_type, start, end, status, adjusts_leave_id),
    )
    db.commit()
    return cur.lastrowid


# Mốc ngày cố định, không phụ thuộc "hôm nay" thật — dùng năm xa trong tương
# lai (2032/2033) để không đụng dữ liệu/kỳ vọng nào khác, và luôn nằm chắc
# chắn ở tương lai so với ngày chạy test thật.
FAR_FUTURE_YEAR = 2032
PAST_WEEK_YEAR = 2020  # chắc chắn đã qua so với "hôm nay" thật


def test_npbb_tuong_lai_khong_tinh_vao_han_muc(db, staff):
    """Đơn NPBB đã duyệt nhưng start_date còn ở tương lai — _calc_used_days
    không được tính, dù trạng thái approved (khác mọi loại nghỉ khác)."""
    from backend.api.leaves import _calc_used_days
    future_start = f"{FAR_FUTURE_YEAR}-06-07"  # Thu 2032-06-07 la thu Hai
    future_end = f"{FAR_FUTURE_YEAR}-06-11"
    _insert_leave(db, staff, "bat_buoc", future_start, future_end)
    used = _calc_used_days(staff, FAR_FUTURE_YEAR, db, include_pending=True)
    assert used == 0.0, f"NPBB chua toi ngay khong duoc tinh, thuc te used={used}"


def test_npbb_da_qua_ngay_tinh_full_1_lan(db, staff):
    """Đơn NPBB có start_date đã ở QUÁ KHỨ (so với hôm nay thật) — phải được
    tính ĐỦ (không phải tính dần từng ngày) ngay khi start_date <= hôm nay."""
    from backend.api.leaves import _calc_used_days
    start = f"{PAST_WEEK_YEAR}-06-01"  # Mon
    end = f"{PAST_WEEK_YEAR}-06-05"    # Fri, 5 ngay lam viec
    _insert_leave(db, staff, "bat_buoc", start, end)
    used = _calc_used_days(staff, PAST_WEEK_YEAR, db, include_pending=True)
    assert used == 5.0, f"NPBB da qua ngay phai tinh du 5, thuc te used={used}"


def test_warning_khong_hien_khi_du_han_muc(db, staff):
    _set_quota(db, staff, FAR_FUTURE_YEAR, 12)
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{FAR_FUTURE_YEAR}-06-07", f"{FAR_FUTURE_YEAR}-06-11")
    r = _client(db, staff).get("/api/leaves/npbb-quota-warning")
    assert r.status_code == 200, r.text
    data = r.json()
    assert not any(x["id"] == npbb_id for x in data["pending"]), data


def test_warning_hien_dung_khi_khong_du(db, staff):
    """quota=12, don khac dung 8 ngay, NPBB can 5 ngay -> remaining_excl=4 <5 -> canh bao dung hien."""
    _set_quota(db, staff, FAR_FUTURE_YEAR, 12)
    _insert_leave(db, staff, "annual", f"{FAR_FUTURE_YEAR}-03-02", f"{FAR_FUTURE_YEAR}-03-11")  # 8 ngay lam viec
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{FAR_FUTURE_YEAR}-06-07", f"{FAR_FUTURE_YEAR}-06-11")

    r = _client(db, staff).get("/api/leaves/npbb-quota-warning")
    assert r.status_code == 200, r.text
    data = r.json()
    item = next((x for x in data["pending"] if x["id"] == npbb_id), None)
    assert item is not None, data
    assert item["remaining"] == 4.0, item
    assert item["leave_days"] == 5, item


def test_tiep_tuc_giai_quyet_vinh_vien_khong_lap_lai(db, staff):
    """Bug goc: sau khi 'Tiep tuc' thanh cong, canh bao KHONG duoc hien lai
    nua (truoc day remaining luon ve dung 0 -> van <5 -> lap vo han)."""
    _set_quota(db, staff, FAR_FUTURE_YEAR, 12)
    _set_quota(db, staff, FAR_FUTURE_YEAR + 1, 12)
    _insert_leave(db, staff, "annual", f"{FAR_FUTURE_YEAR}-03-02", f"{FAR_FUTURE_YEAR}-03-11")
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{FAR_FUTURE_YEAR}-06-07", f"{FAR_FUTURE_YEAR}-06-11")

    client = _client(db, staff)
    r0 = client.get("/api/leaves/npbb-quota-warning")
    assert any(x["id"] == npbb_id for x in r0.json()["pending"]), "canh bao phai hien truoc khi ung"

    r1 = client.post(f"/api/leaves/{npbb_id}/npbb-borrow-confirm", json={})
    assert r1.status_code == 200, r1.text
    assert r1.json()["borrow_next_year_days"] == 1.0  # 5 - 4

    r2 = client.get("/api/leaves/npbb-quota-warning")
    assert not any(x["id"] == npbb_id for x in r2.json()["pending"]), (
        f"BUG: canh bao van hien lai sau khi da ung thanh cong: {r2.json()}"
    )


def test_borrow_confirm_chan_khi_nam_sau_khong_du(db, staff):
    _set_quota(db, staff, FAR_FUTURE_YEAR, 12)
    _set_quota(db, staff, FAR_FUTURE_YEAR + 1, 0)
    _insert_leave(db, staff, "annual", f"{FAR_FUTURE_YEAR}-03-02", f"{FAR_FUTURE_YEAR}-03-11")
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{FAR_FUTURE_YEAR}-06-07", f"{FAR_FUTURE_YEAR}-06-11")

    r = _client(db, staff).post(f"/api/leaves/{npbb_id}/npbb-borrow-confirm", json={})
    assert r.status_code == 400, r.text


def test_borrow_confirm_chan_khi_dang_co_dieu_chinh(db, staff):
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{FAR_FUTURE_YEAR}-06-07", f"{FAR_FUTURE_YEAR}-06-11")
    _insert_leave(db, staff, "bat_buoc", f"{FAR_FUTURE_YEAR}-07-05", f"{FAR_FUTURE_YEAR}-07-09",
                  status="pending_ksv", adjusts_leave_id=npbb_id)

    r = _client(db, staff).post(f"/api/leaves/{npbb_id}/npbb-borrow-confirm", json={})
    assert r.status_code == 409, r.text
    row = db.execute("SELECT borrow_next_year_days FROM leave_records WHERE id=?", (npbb_id,)).fetchone()
    assert row["borrow_next_year_days"] == 0.0

    # Va khong duoc hien trong pending trong luc dang co dieu chinh do dang
    r2 = _client(db, staff).get("/api/leaves/npbb-quota-warning")
    assert not any(x["id"] == npbb_id for x in r2.json()["pending"]), r2.json()


def test_auto_cancel_huy_khi_toi_han_van_khong_du(db, staff):
    from backend.api.leaves import _npbb_auto_cancel_check
    _set_quota(db, staff, PAST_WEEK_YEAR, 3)  # qua it, khong du 5 ngay NPBB
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{PAST_WEEK_YEAR}-06-01", f"{PAST_WEEK_YEAR}-06-05")

    n = _npbb_auto_cancel_check(db_path=_DB_PATH_HOLDER["path"])
    assert n == 1, f"ky vong huy dung 1 don, thuc te n={n}"
    row = db.execute("SELECT status FROM leave_records WHERE id=?", (npbb_id,)).fetchone()
    assert row["status"] == "cancelled"
    log = db.execute(
        "SELECT action FROM leave_action_logs WHERE leave_id=? AND action='npbb_auto_cancel_insufficient_quota'",
        (npbb_id,),
    ).fetchone()
    assert log is not None


def test_auto_cancel_bo_qua_don_da_ung_thanh_cong(db, staff):
    """Bug goc: neu da 'Tiep tuc' (borrow_next_year_days > 0) truoc do, den
    dung han KHONG duoc tu huy nua — truoc khi sua, cong thuc raw van thay
    'thieu' va huy oan don da duoc xu ly xong."""
    from backend.api.leaves import _npbb_auto_cancel_check
    _set_quota(db, staff, PAST_WEEK_YEAR, 3)
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{PAST_WEEK_YEAR}-06-01", f"{PAST_WEEK_YEAR}-06-05")
    # Mo phong da "Tiep tuc" thanh cong tu truoc: ung 2 ngay sang nam sau
    # (5 ngay - 3 con lai = thieu 2).
    db.execute("UPDATE leave_records SET borrow_next_year_days=2 WHERE id=?", (npbb_id,))
    db.commit()

    n = _npbb_auto_cancel_check(db_path=_DB_PATH_HOLDER["path"])
    assert n == 0, f"BUG: don da ung thanh cong nhung van bi tu huy, n={n}"
    row = db.execute("SELECT status FROM leave_records WHERE id=?", (npbb_id,)).fetchone()
    assert row["status"] == "approved"


def test_auto_cancel_bo_qua_khi_dang_co_dieu_chinh(db, staff):
    from backend.api.leaves import _npbb_auto_cancel_check
    _set_quota(db, staff, PAST_WEEK_YEAR, 3)
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{PAST_WEEK_YEAR}-06-01", f"{PAST_WEEK_YEAR}-06-05")
    _insert_leave(db, staff, "bat_buoc", f"{PAST_WEEK_YEAR}-07-06", f"{PAST_WEEK_YEAR}-07-10",
                  status="pending_ksv", adjusts_leave_id=npbb_id)

    n = _npbb_auto_cancel_check(db_path=_DB_PATH_HOLDER["path"])
    assert n == 0
    row = db.execute("SELECT status FROM leave_records WHERE id=?", (npbb_id,)).fetchone()
    assert row["status"] == "approved"


def test_auto_cancelled_hien_thong_bao_va_tat_sau_khi_ack(db, staff):
    from backend.api.leaves import _npbb_auto_cancel_check
    _set_quota(db, staff, PAST_WEEK_YEAR, 3)
    npbb_id = _insert_leave(db, staff, "bat_buoc", f"{PAST_WEEK_YEAR}-06-01", f"{PAST_WEEK_YEAR}-06-05")
    _npbb_auto_cancel_check(db_path=_DB_PATH_HOLDER["path"])

    client = _client(db, staff)
    r1 = client.get("/api/leaves/npbb-quota-warning")
    assert any(x["id"] == npbb_id for x in r1.json()["auto_cancelled"]), r1.json()

    r_ack = client.post(f"/api/leaves/{npbb_id}/npbb-auto-cancel-ack", json={})
    assert r_ack.status_code == 200, r_ack.text

    r2 = client.get("/api/leaves/npbb-quota-warning")
    assert not any(x["id"] == npbb_id for x in r2.json()["auto_cancelled"]), (
        f"BUG: thong bao van hien lai sau khi da ack: {r2.json()}"
    )
