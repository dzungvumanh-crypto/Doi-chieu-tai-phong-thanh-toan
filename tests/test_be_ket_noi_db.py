# -*- coding: utf-8 -*-
"""Bể kết nối CSDL — mượn/trả thay cho mở file mỗi request.

Canh những kiểu hỏng ÂM THẦM, không phải hiệu năng:
  1. Giao dịch dở của request này rò sang request sau (bản cũ đóng kết nối nên
     SQLite tự huỷ; nay kết nối sống tiếp).
  2. Sổ đếm lệch → bể teo dần rồi treo, hoặc phình quá trần.
  3. Hai request nhận CÙNG một kết nối cùng lúc.
"""
import sqlite3
import threading

import pytest

from backend import database as db_mod


@pytest.fixture()
def be(tmp_path, monkeypatch):
    """Bể riêng trỏ vào CSDL tạm — không đụng data/ksnb.db."""
    duong_dan = str(tmp_path / "thu.db")
    monkeypatch.setattr(db_mod, "DB_PATH", duong_dan)
    monkeypatch.setattr(db_mod, "_pool", db_mod.queue.LifoQueue())
    monkeypatch.setattr(db_mod, "_da_tao", 0)
    db_mod.khoi_tao_pool()
    with next(db_mod.get_db()) as _:
        pass
    conn = db_mod._muon()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    db_mod._tra(conn)
    yield db_mod
    db_mod.dong_pool()


def _dung(m):
    """Mượn qua generator get_db() — KHÔNG đi qua cổng `_qua_cong_db` (cổng là
    dependency async, chỉ FastAPI mới giải). Cổng có test riêng:
    tests/test_be_ket_noi_khoa_cheo.py."""
    g = m.get_db()
    return g, next(g)


def _tra_ve(g):
    try:
        next(g)
    except StopIteration:
        pass


# ── 1. Không rò giao dịch sang request sau ───────────────────────────────────
def test_ghi_chua_commit_khong_ro_sang_request_sau(be):
    g, conn = _dung(be)
    conn.execute("INSERT INTO t (v) VALUES ('chua commit')")
    _tra_ve(g)                       # request kết thúc, KHÔNG commit

    g2, conn2 = _dung(be)
    n = conn2.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    _tra_ve(g2)
    assert n == 0, "Phần ghi dở của request trước đã rò sang request sau"


def test_da_commit_thi_van_con(be):
    g, conn = _dung(be)
    conn.execute("INSERT INTO t (v) VALUES ('da commit')")
    conn.commit()
    _tra_ve(g)

    g2, conn2 = _dung(be)
    n = conn2.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    _tra_ve(g2)
    assert n == 1


def test_request_nem_loi_van_tra_ket_noi_ve_be(be):
    truoc = be.pool_stats()
    g = be.get_db()
    conn = next(g)
    conn.execute("INSERT INTO t (v) VALUES ('loi')")
    with pytest.raises(ValueError):
        g.throw(ValueError("hỏng giữa chừng"))
    assert be.pool_stats()["dang_muon"] == truoc["dang_muon"]

    g2, conn2 = _dung(be)
    n = conn2.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    _tra_ve(g2)
    assert n == 0


# ── 2. Sổ đếm ────────────────────────────────────────────────────────────────
def test_ket_noi_duoc_dung_lai_khong_tao_moi_moi_lan(be):
    for _ in range(20):
        g, _c = _dung(be)
        _tra_ve(g)
    assert be.pool_stats()["da_tao"] == 1, "Mỗi request lại tạo kết nối mới"


def test_khong_vuot_tran(be, monkeypatch):
    monkeypatch.setattr(be, "_POOL_MAX", 3)
    giu = [be._muon() for _ in range(3)]
    assert be.pool_stats()["da_tao"] == 3
    for c in giu:
        be._tra(c)
    assert be.pool_stats()["ranh"] == 3


def test_het_ket_noi_thi_bao_loi_ro_rang_khong_treo(be, monkeypatch):
    monkeypatch.setattr(be, "_POOL_MAX", 2)
    monkeypatch.setattr(be, "_POOL_CHO_GIAY", 0.2)
    giu = [be._muon() for _ in range(2)]
    with pytest.raises(RuntimeError, match="DB_POOL_SIZE"):
        be._muon()
    for c in giu:
        be._tra(c)


def test_ket_noi_hong_bi_loai_khoi_be(be):
    conn = be._muon()
    truoc = be.pool_stats()["da_tao"]
    conn.close()                     # giả lập kết nối chết
    be._tra(conn)
    assert be.pool_stats()["da_tao"] == truoc - 1
    assert be.pool_stats()["ranh"] == 0


# ── 3. Không hai request dùng chung một kết nối ──────────────────────────────
def test_hai_request_cung_luc_nhan_hai_ket_noi_khac_nhau(be):
    ra = []
    rao = threading.Barrier(2)

    def _chay():
        g, conn = _dung(be)
        rao.wait()                   # giữ cả hai cùng lúc
        ra.append(id(conn))
        rao.wait()
        _tra_ve(g)

    ts = [threading.Thread(target=_chay) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    assert len(ra) == 2 and ra[0] != ra[1]


def test_dong_pool_dong_het_va_ve_so_khong(be):
    for _ in range(3):
        be._tra(be._muon())
    be.dong_pool()
    assert be.pool_stats()["da_tao"] == 0
    assert be.pool_stats()["ranh"] == 0


# ── 4. WAL bật một lần, không lặp mỗi request ────────────────────────────────
def test_wal_duoc_bat(be):
    g, conn = _dung(be)
    che_do = conn.execute("PRAGMA journal_mode").fetchone()[0]
    _tra_ve(g)
    assert str(che_do).lower() == "wal"


def test_moi_ket_noi_van_co_foreign_keys(be):
    """`foreign_keys` là PRAGMA theo TỪNG kết nối — quên đặt lúc tạo thì ràng
    buộc khoá ngoại im lặng không có tác dụng, không lỗi nào báo."""
    g, conn = _dung(be)
    bat = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    _tra_ve(g)
    assert bat == 1
