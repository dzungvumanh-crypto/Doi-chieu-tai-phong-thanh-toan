# -*- coding: utf-8 -*-
"""Backup lúc khởi động bỏ qua nếu vừa có bản cách đây chưa lâu.

`run.py` tự khởi động lại tới MAX_RESTARTS=5 lần khi gặp sự cố, mà mỗi lần lên là
chép nguyên file CSDL (70,6 MB trên máy chủ) và giữ khoá đọc trong lúc chép —
đúng lúc hệ thống đang trục trặc thì nó làm việc đó 5 lần liên tiếp.
"""
from datetime import datetime, timedelta

import pytest

from backend.services import backup_service as bs


@pytest.fixture()
def thu_muc(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_BACKUP_DIR", tmp_path)
    return tmp_path


def _tao_ban(thu_muc, gio_truoc: float, duoi: str = "zip"):
    moc = datetime.now() - timedelta(hours=gio_truoc)
    p = thu_muc / f"ksnb_{moc:%Y%m%d_%H%M}.{duoi}"
    p.write_bytes(b"x")
    return p


# ── Đọc mốc bản gần nhất ─────────────────────────────────────────────────────
def test_chua_co_ban_nao_tra_none(thu_muc):
    assert bs._gio_ke_tu_ban_gan_nhat() is None


def test_doc_dung_so_gio(thu_muc):
    _tao_ban(thu_muc, 3)
    gio = bs._gio_ke_tu_ban_gan_nhat()
    assert 2.9 < gio < 3.2


def test_lay_ban_MOI_NHAT_khong_phai_ban_dau_danh_sach(thu_muc):
    _tao_ban(thu_muc, 30)
    _tao_ban(thu_muc, 2)
    assert bs._gio_ke_tu_ban_gan_nhat() < 3


def test_ban_dat_tay_khong_duoc_tinh(thu_muc):
    """`ksnb_truoc_nhomA_20260728.db` là bản người đặt tay. Tính nó vào đây thì
    một bản cũ đặt tay hôm nào đó có thể chặn mất lượt backup thật."""
    (thu_muc / "ksnb_truoc_nhomA_20260728.db").write_bytes(b"x")
    assert bs._gio_ke_tu_ban_gan_nhat() is None


def test_ten_la_khong_lam_no(thu_muc):
    (thu_muc / "ksnb_99999999_9999.zip").write_bytes(b"x")
    # Không ném; coi như chưa có bản → thà backup thừa còn hơn thiếu
    assert bs._gio_ke_tu_ban_gan_nhat() is None


# ── Quyết định chạy hay bỏ qua ───────────────────────────────────────────────
def _chay_initial(monkeypatch, thu_muc):
    """Gọi đúng nhánh `_initial` của start_scheduler, không dựng thread/timer."""
    da_chay = []
    monkeypatch.setattr(bs, "run_backup", lambda p="x": da_chay.append(p))
    monkeypatch.setattr(bs.threading, "Thread",
                        lambda target, **kw: type("T", (), {"start": staticmethod(target)})())
    monkeypatch.setattr(bs, "_schedule_next", lambda p: None)
    bs.start_scheduler("data/ksnb.db")
    return da_chay


def test_bo_qua_khi_vua_backup_cach_day_it_phut(monkeypatch, thu_muc):
    """Đúng kịch bản bão khởi động lại."""
    _tao_ban(thu_muc, 0.05)          # 3 phút trước
    assert _chay_initial(monkeypatch, thu_muc) == []


def test_van_chay_khi_ban_gan_nhat_da_cu(monkeypatch, thu_muc):
    _tao_ban(thu_muc, 25)
    assert len(_chay_initial(monkeypatch, thu_muc)) == 1


def test_van_chay_khi_chua_co_ban_nao(monkeypatch, thu_muc):
    assert len(_chay_initial(monkeypatch, thu_muc)) == 1


def test_nam_ngay_tren_nguong_van_chay(monkeypatch, thu_muc):
    _tao_ban(thu_muc, bs._TOI_THIEU_GIO + 0.5)
    assert len(_chay_initial(monkeypatch, thu_muc)) == 1


def test_backup_hong_duoc_ghi_log_khong_nuot_tron(monkeypatch, thu_muc, caplog):
    """Bản cũ dùng `except Exception: pass` — hỏng là im lặng tuyệt đối."""
    def _no(p="x"):
        raise OSError("đĩa đầy")
    monkeypatch.setattr(bs, "run_backup", _no)
    monkeypatch.setattr(bs.threading, "Thread",
                        lambda target, **kw: type("T", (), {"start": staticmethod(target)})())
    monkeypatch.setattr(bs, "_schedule_next", lambda p: None)
    bs.start_scheduler("data/ksnb.db")
    assert any(r.levelname == "ERROR" and "đĩa đầy" in r.getMessage()
               for r in caplog.records)


# ── _verify(): integrity_check là điều kiện CẦN, không đủ ────────────────────
import sqlite3


def _db_co(duong_dan, so_dong: int):
    c = sqlite3.connect(str(duong_dan))
    c.execute("CREATE TABLE user_tttt (id INTEGER, username TEXT)")
    for i in range(so_dong):
        c.execute("INSERT INTO user_tttt VALUES (?, ?)", (i, f"u{i}"))
    c.commit(); c.close()


def test_ban_backup_rong_bi_coi_la_hong(tmp_path):
    """Đã gặp thật: data/backups/ksnb_20260910_1404.db nặng 12,7 MB,
    `PRAGMA integrity_check` trả "ok", mà bên trong KHÔNG có bảng nào."""
    p = tmp_path / "rong.db"
    sqlite3.connect(str(p)).close()
    assert sqlite3.connect(str(p)).execute(
        "PRAGMA integrity_check").fetchone()[0] == "ok", "tiền đề: file rỗng vẫn 'ok'"
    assert bs._verify(p, 78) is False


def test_chep_thieu_dong_bi_coi_la_hong(tmp_path):
    """Backup dừng giữa chừng: đọc được, integrity ok, nhưng hụt dữ liệu."""
    p = tmp_path / "thieu.db"
    _db_co(p, 40)
    assert bs._verify(p, 78) is False


def test_may_moi_cai_chua_co_tai_khoan_van_qua(tmp_path):
    """0 dòng mà nguồn cũng 0 dòng là ĐÚNG — bắt lỗi ở đây là đẻ ra một dòng
    ERROR giả ngay lần chạy đầu sau khi cài."""
    p = tmp_path / "moi.db"
    _db_co(p, 0)
    assert bs._verify(p, 0) is True


def test_ban_du_du_lieu_thi_qua(tmp_path):
    p = tmp_path / "du.db"
    _db_co(p, 78)
    assert bs._verify(p, 78) is True


def test_file_khong_phai_sqlite_bi_coi_la_hong(tmp_path):
    p = tmp_path / "rac.db"
    p.write_bytes(b"day khong phai sqlite")
    assert bs._verify(p, 78) is False
