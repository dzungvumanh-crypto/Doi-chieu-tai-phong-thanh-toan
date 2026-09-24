"""P4 (23/09/2026): dọn index thừa thời ORM + cập nhật thống kê truy vấn định kỳ."""
import re
import sqlite3
from pathlib import Path

from backend.services import log_cleanup_service as lc

_GOC = Path(__file__).resolve().parents[1]


def test_index_bi_xoa_khong_con_cho_nao_tao_lai():
    """DROP mà chỗ khác vẫn CREATE cùng tên thì mỗi lần khởi động là xoá–tạo vòng quanh."""
    ma = (_GOC / "backend" / "db" / "migrations.py").read_text(encoding="utf-8")
    bi_xoa = set(re.findall(r"DROP INDEX IF EXISTS (\w+)", ma))
    assert "ix_login_logs_created_at" in bi_xoa
    toan_bo = "\n".join(p.read_text(encoding="utf-8")
                        for p in (_GOC / "backend").rglob("*.py"))
    for ten in bi_xoa:
        assert not re.search(rf"CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?{ten}\b", toan_bo), ten


def test_giu_index_trung_rang_buoc_unique():
    """Ba index này trùng UNIQUE trên DB mới, nhưng DB tạo từ bản cũ có thể chỉ
    còn chúng giữ tính duy nhất — không được lọt vào danh sách xoá."""
    ma = (_GOC / "backend" / "db" / "migrations.py").read_text(encoding="utf-8")
    bi_xoa = set(re.findall(r"DROP INDEX IF EXISTS (\w+)", ma))
    assert not bi_xoa & {"ix_public_holidays_date", "ix_duty_staff_meta_user",
                         "ux_dtbb_reports_date_branch", "ux_so_truc_active_date"}


def test_don_nhat_ky_cap_nhat_thong_ke(tmp_path):
    p = str(tmp_path / "t.db")
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE login_logs (id INTEGER PRIMARY KEY, username TEXT, created_at TEXT);
        CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, actor_id INTEGER, created_at TEXT);
        CREATE TABLE leave_records (id INTEGER PRIMARY KEY, staff_id INTEGER);
        CREATE INDEX ix_lr_staff ON leave_records(staff_id);
    """)
    c.executemany("INSERT INTO leave_records (staff_id) VALUES (?)", [(i % 7,) for i in range(300)])
    c.commit()
    c.close()

    lc.run_cleanup(p)

    c = sqlite3.connect(p)
    try:
        bang = {r[0] for r in c.execute("SELECT tbl FROM sqlite_stat1")}
    finally:
        c.close()
    # Bảng KHÔNG bị kết nối dọn nhật ký truy vấn cũng phải có thống kê (cờ 0x10000)
    assert "leave_records" in bang
