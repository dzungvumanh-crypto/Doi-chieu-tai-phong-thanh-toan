"""Bản sao lưu KHÔNG toàn vẹn không được chiếm chỗ bản tốt (rà soát 23/09/2026).

Trước đây `_verify()` chê thì chỉ ghi ERROR, bản hỏng vẫn mang tên `ksnb_YYYYMMDD_HHMM`
và chiếm một suất "bản của ngày" trong vòng giữ 7 ngày. File chính hỏng liên tục 7 ngày
(hỏng thường phát hiện muộn) là bản TỐT cuối cùng bị `_rotate()` xoá.
"""
import sqlite3

import pytest

from backend.core.config import settings
from backend.services import backup_service as bs


def _db_mau(duong_dan):
    c = sqlite3.connect(duong_dan)
    c.execute("CREATE TABLE user_tttt (id INTEGER, pwd_hash TEXT)")
    c.execute("INSERT INTO user_tttt VALUES (1, 'h')")
    c.commit()
    c.close()


@pytest.fixture
def thu_muc(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_BACKUP_DIR", tmp_path)
    monkeypatch.delenv("BACKUP_PASSWORD", raising=False)
    _db_mau(str(tmp_path / "goc.db"))
    return tmp_path


def test_ban_hong_duoc_cat_rieng(thu_muc, monkeypatch):
    monkeypatch.setattr(bs, "_verify", lambda *a: False)
    ra = bs.run_backup(str(thu_muc / "goc.db"))
    assert ra.name.startswith("HONG_ksnb_") and ra.exists()
    assert bs._ban_tu_sinh(thu_muc) == []                 # không vào vòng giữ
    tt = bs.last_backup_info()
    assert tt["exists"] is False                          # không thành "bản gần nhất"
    assert tt["count_thu_cong"] == 0                      # cũng không bị coi là bản đặt tay


def test_ban_hong_khong_chep_sang_thu_muc_phu(thu_muc, tmp_path_factory, monkeypatch):
    phu = tmp_path_factory.mktemp("phu")
    monkeypatch.setattr(settings, "BACKUP_EXTRA_DIR", str(phu))
    monkeypatch.setattr(bs, "_verify", lambda *a: False)
    bs.run_backup(str(thu_muc / "goc.db"))
    assert list(phu.iterdir()) == []


def test_ban_tot_van_chep_sang_thu_muc_phu(thu_muc, tmp_path_factory, monkeypatch):
    phu = tmp_path_factory.mktemp("phu")
    monkeypatch.setattr(settings, "BACKUP_EXTRA_DIR", str(phu))
    ra = bs.run_backup(str(thu_muc / "goc.db"))
    assert ra.name.startswith("ksnb_")
    assert [p.name for p in phu.iterdir()] == [ra.name]


def test_hong_nhieu_ngay_lien_tiep_van_con_ban_tot(tmp_path):
    """Kịch bản đúng lỗi: 7 ngày tốt, rồi 10 ngày liền bản nào cũng hỏng."""
    for ngay in range(1, 8):
        (tmp_path / f"ksnb_202609{ngay:02d}_0900.db").write_bytes(b"tot")
    for ngay in range(8, 18):
        (tmp_path / f"HONG_ksnb_202609{ngay:02d}_0900.db").write_bytes(b"hong")
    bs._rotate(tmp_path)
    bs._don_ban_hong(tmp_path)
    con = sorted(p.name for p in tmp_path.iterdir())
    assert [n for n in con if n.startswith("ksnb_")] == [
        f"ksnb_202609{ngay:02d}_0900.db" for ngay in range(1, 8)]
    # Bản hỏng chỉ giữ 3 bản mới nhất để điều tra
    assert [n for n in con if n.startswith("HONG_")] == [
        f"HONG_ksnb_202609{ngay:02d}_0900.db" for ngay in (15, 16, 17)]
