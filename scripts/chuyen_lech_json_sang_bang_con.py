# -*- coding: utf-8 -*-
"""Chuyển `doi_soat_citad_history.lech_json` sang bảng con `doi_soat_citad_lech`.

Vì sao cần: đo trên máy chủ 10/09/2026, cột `lech_json` chiếm 62,9/68,2 MB —
92% toàn bộ CSDL — và mở một dòng ra tốn 97 MB RAM cho mỗi lần bấm "Xem chi
tiết". Mã nguồn nay ghi vào bảng con; script này lo phần dữ liệu đã có.

CHẠY BA BƯỚC RIÊNG, không gộp. Mỗi bước phải xong và đúng mới sang bước sau:

    python scripts/chuyen_lech_json_sang_bang_con.py chuyen    # chép sang bảng con
    python scripts/chuyen_lech_json_sang_bang_con.py doi_chieu # đối chiếu từng dòng
    python scripts/chuyen_lech_json_sang_bang_con.py don       # xoá lech_json + VACUUM

Tách `don` ra khỏi `chuyen` là cố ý: xoá dữ liệu gốc là việc KHÔNG lùi lại được.
Người vận hành phải nhìn thấy kết quả đối chiếu bằng mắt rồi mới tự quyết định
xoá — không để một lệnh vừa chép vừa xoá.

`chuyen` chạy lại nhiều lần được: dòng nào đã có trong bảng con thì bỏ qua.
"""
import json
import sqlite3
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if _s is not None and (getattr(_s, "encoding", "") or "").lower() not in ("utf-8", "utf8"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "ksnb.db"
sys.path.insert(0, str(BASE_DIR))

from backend.services.doi_soat_citad.history_service import (  # noqa: E402
    _COT_LECH, _ghep_ban_ghi, _tach_ban_ghi,
)

VACH = "─" * 74


def _mo_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _co_bang_con(db: sqlite3.Connection) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='doi_soat_citad_lech'"
    ).fetchone() is not None


# ── Bước 1: chép sang bảng con ──────────────────────────────────────────────
def chuyen(db: sqlite3.Connection) -> int:
    hang = db.execute(
        "SELECT id, n_lech, LENGTH(lech_json) n FROM doi_soat_citad_history "
        "WHERE lech_json IS NOT NULL AND LENGTH(lech_json) > 2 ORDER BY id"
    ).fetchall()
    if not hang:
        print("  Không còn dòng nào cần chuyển.")
        return 0

    sql = (f"INSERT INTO doi_soat_citad_lech (history_id, seq, {', '.join(_COT_LECH)}, extra_json) "
           f"VALUES ({', '.join('?' * (len(_COT_LECH) + 3))})")
    tong = 0
    for r in hang:
        hid = r["id"]
        da_co = db.execute(
            "SELECT COUNT(*) FROM doi_soat_citad_lech WHERE history_id=?", (hid,)
        ).fetchone()[0]
        if da_co:
            print(f"  id={hid:<4} bỏ qua — bảng con đã có {da_co:,} dòng")
            continue

        raw = db.execute(
            "SELECT lech_json FROM doi_soat_citad_history WHERE id=?", (hid,)
        ).fetchone()[0]
        ban_ghi = json.loads(raw)
        db.executemany(sql, [(hid, i) + _tach_ban_ghi(rec) for i, rec in enumerate(ban_ghi)])
        db.commit()
        tong += len(ban_ghi)
        print(f"  id={hid:<4} chuyển {len(ban_ghi):>7,} lệnh  ({r['n'] / 1048576:6.2f} MB)")
    print(f"\n  Tổng: {tong:,} lệnh lệch đã sang bảng con.")
    return tong


# ── Bước 2: đối chiếu ───────────────────────────────────────────────────────
def doi_chieu(db: sqlite3.Connection) -> bool:
    """So từng bản ghi đọc lại từ bảng con với bản gốc trong lech_json."""
    hang = db.execute(
        "SELECT id FROM doi_soat_citad_history "
        "WHERE lech_json IS NOT NULL AND LENGTH(lech_json) > 2 ORDER BY id"
    ).fetchall()
    if not hang:
        print("  Không còn dòng nào để đối chiếu.")
        return True

    tat_ca_khop = True
    for r in hang:
        hid = r["id"]
        goc = json.loads(db.execute(
            "SELECT lech_json FROM doi_soat_citad_history WHERE id=?", (hid,)
        ).fetchone()[0])
        moi = [_ghep_ban_ghi(x) for x in db.execute(
            "SELECT * FROM doi_soat_citad_lech WHERE history_id=? ORDER BY seq", (hid,)
        )]

        if len(goc) != len(moi):
            print(f"  ✗ id={hid}: LỆCH SỐ LƯỢNG — gốc {len(goc):,}, bảng con {len(moi):,}")
            tat_ca_khop = False
            continue

        lech = [i for i, (a, b) in enumerate(zip(goc, moi)) if a != b]
        if lech:
            tat_ca_khop = False
            print(f"  ✗ id={hid}: {len(lech):,}/{len(goc):,} bản ghi KHÁC nhau")
            i = lech[0]
            print(f"      dòng {i} gốc     : {goc[i]}")
            print(f"      dòng {i} bảng con: {moi[i]}")
        else:
            print(f"  ✓ id={hid:<4} {len(goc):>7,} bản ghi khớp từng khoá, từng giá trị")
    return tat_ca_khop


# ── Bước 3: xoá cột cũ + thu hồi dung lượng ─────────────────────────────────
def don(db: sqlite3.Connection) -> None:
    truoc = DB_PATH.stat().st_size / 1048576
    n = db.execute(
        "SELECT COUNT(*) FROM doi_soat_citad_history "
        "WHERE lech_json IS NOT NULL AND LENGTH(lech_json) > 2"
    ).fetchone()[0]
    print(f"  Sẽ xoá nội dung lech_json của {n} dòng.")

    db.execute("UPDATE doi_soat_citad_history SET lech_json = NULL")
    db.commit()

    # VACUUM phải chạy NGOÀI giao dịch và không được có kết nối nào khác đang
    # ghi — dừng backend trước khi chạy bước này.
    print("  Đang VACUUM (có thể mất một lúc)...")
    db.execute("VACUUM")
    db.commit()

    sau = DB_PATH.stat().st_size / 1048576
    print(f"\n  CSDL: {truoc:.1f} MB → {sau:.1f} MB   (thu hồi {truoc - sau:.1f} MB)")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("chuyen", "doi_chieu", "don"):
        print(__doc__)
        return 1
    if not DB_PATH.exists():
        print(f"Không tìm thấy CSDL: {DB_PATH}")
        return 1

    buoc = sys.argv[1]
    db = _mo_db()
    try:
        if not _co_bang_con(db):
            print("Chưa có bảng `doi_soat_citad_lech`. Khởi động backend một lần để")
            print("migration tạo bảng, rồi chạy lại script này.")
            return 1

        print(f"\n{VACH}\n  BƯỚC: {buoc}   —   {DB_PATH}\n{VACH}")
        if buoc == "chuyen":
            chuyen(db)
            print("\n  Tiếp theo: chạy bước `doi_chieu` để kiểm tra trước khi xoá gì.")
        elif buoc == "doi_chieu":
            if doi_chieu(db):
                print("\n  ✓ Toàn bộ khớp. Có thể chạy bước `don`.")
            else:
                print("\n  ✗ CÓ SAI LỆCH — ĐỪNG chạy bước `don`. Báo lại để tìm nguyên nhân.")
                return 2
        else:
            don(db)
            print("\n  Xong. Khởi động lại backend.")
    finally:
        db.close()
    print(f"{VACH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
