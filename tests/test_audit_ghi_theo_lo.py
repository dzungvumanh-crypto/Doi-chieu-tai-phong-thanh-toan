"""Luồng ghi audit gom các dòng đang chờ vào MỘT giao dịch (P3, 23/09/2026).

Trước đây mỗi dòng một commit (synchronous FULL → một lần ép ghi đĩa và một lần giành
khoá ghi mỗi dòng). Canh: đủ dòng, đúng thứ tự, số commit ít, lô lỗi được thử lại.
"""
import sqlite3

import pytest

from backend.core import audit_queue


class _DemCommit:
    """Bọc kết nối thật, đếm số lần commit (sqlite3.Connection không vá được thuộc tính)."""

    def __init__(self, con, loi_lan_dau=False):
        self._con, self.so_commit, self._loi = con, 0, loi_lan_dau

    def execute(self, *a):
        return self._con.execute(*a)

    def commit(self):
        if self._loi:
            self._loi = False
            raise sqlite3.OperationalError("database is locked")
        self.so_commit += 1
        self._con.commit()

    def close(self):
        self._con.close()


@pytest.fixture
def db_tam(tmp_path, monkeypatch):
    p = str(tmp_path / "audit.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
        target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT,
        created_at TIMESTAMP)""")
    con.commit()
    con.close()
    monkeypatch.setattr(audit_queue, "DB_PATH", p)
    # Hàng đợi toàn cục có thể còn dòng của test khác — xả trước
    while not audit_queue._q.empty():
        audit_queue._q.get()
        audit_queue._q.task_done()
    return p


def _chay(n: int) -> None:
    for i in range(n):
        audit_queue.enqueue("POST", f"/api/x/{i}", 200, "", "10.0.0.9", "127.0.0.1", actor_id=1)
    audit_queue.start()           # bật SAU khi xếp hàng → cả n dòng đang chờ sẵn
    try:
        audit_queue._q.join()
    finally:
        audit_queue.stop()


def _duong_dan(p):
    con = sqlite3.connect(p)
    try:
        return [r[0] for r in con.execute("SELECT target_type FROM audit_logs ORDER BY id")]
    finally:
        con.close()


def test_dong_dang_cho_ghi_trong_mot_commit(db_tam, monkeypatch):
    ket_noi = []
    goc = audit_queue._mo_ket_noi
    monkeypatch.setattr(audit_queue, "_mo_ket_noi",
                        lambda: ket_noi.append(_DemCommit(goc())) or ket_noi[-1])
    _chay(50)
    assert _duong_dan(db_tam) == [f"/api/x/{i}" for i in range(50)]
    assert sum(k.so_commit for k in ket_noi) == 1


def test_lo_loi_lan_dau_thi_thu_lai_du_dong(db_tam, monkeypatch):
    ket_noi = []
    goc = audit_queue._mo_ket_noi

    def _mo():
        # Kết nối ĐẦU TIÊN hỏng lúc commit (khoá CSDL), kết nối mở lại thì bình thường
        ket_noi.append(_DemCommit(goc(), loi_lan_dau=not ket_noi))
        return ket_noi[-1]

    monkeypatch.setattr(audit_queue, "_mo_ket_noi", _mo)
    _chay(20)
    assert _duong_dan(db_tam) == [f"/api/x/{i}" for i in range(20)]
    assert len(ket_noi) == 2


def test_ket_noi_ghi_dat_synchronous_normal(db_tam):
    con = audit_queue._mo_ket_noi()
    try:
        assert con.execute("PRAGMA synchronous").fetchone()[0] == 1   # NORMAL
    finally:
        con.close()
