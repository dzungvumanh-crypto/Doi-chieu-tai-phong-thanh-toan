"""
Script migration dữ liệu nghỉ phép 2026.

Cách dùng (chạy từ thư mục gốc dự án):
    python seeds/migrate_leave_2026.py [--dry-run] [--excel PATH]

Tham số:
    --dry-run   In ra những gì sẽ làm, không ghi vào DB
    --excel     Đường dẫn file Excel (mặc định: seeds/bao_cao_nghi_phep_2026.xlsx)

Script sẽ:
  1. Đọc file Excel báo cáo nghỉ phép 2026
  2. Khớp từng người theo: tên đầy đủ + phòng (chuẩn hoá, bỏ dấu)
  3. Ghi hạn mức (leave_quotas): quota_days, carry_over_days
  4. Nếu đã nghỉ > 0: tạo 1 bản ghi khai báo hộ tổng hợp (leave_type='bat_buoc', status='approved')
  5. Cập nhật used_leave_days trên user_tttt
  6. In báo cáo: khớp / không khớp / bỏ qua
"""

import argparse
import sys
import os
import sqlite3
import unicodedata
import re
from datetime import date, timedelta
from pathlib import Path

# ── Resolve paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DB_PATH  = ROOT / "data" / "ksnb.db"
XLSX_DEFAULT = ROOT / "seeds" / "bao_cao_nghi_phep_2026.xlsx"

# ── Helpers ────────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Chuẩn hoá tên/phòng: bỏ dấu, lower, bỏ khoảng trắng thừa."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()

def _spread_dates(n_days: int, year: int = 2026) -> list[str]:
    """
    Sinh danh sách n_days ngày làm việc (thứ 2-6) bắt đầu từ 02/01/year.
    Dùng làm spread_dates cho bản ghi khai báo hộ tổng hợp.
    """
    dates = []
    d = date(year, 1, 2)
    while len(dates) < n_days:
        if d.weekday() < 5:   # thứ 2-6
            dates.append(d.isoformat())
        d += timedelta(days=1)
        if d.year > year:
            break
    return dates

def _vn_now() -> str:
    from datetime import datetime, timezone, timedelta as td
    return datetime.now(timezone(td(hours=7))).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")

# ── Đọc Excel ──────────────────────────────────────────────────────────────────
def read_excel(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        sys.exit("Thiếu thư viện openpyxl. Chạy: pip install openpyxl")

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    records = []

    for row in ws.iter_rows(values_only=True):
        stt, ho_ten, phong, chuc_vu, han_muc, chuyen_nam, _, da_nghi, *_ = (list(row) + [None]*11)[:11]

        # Bỏ qua header, dòng tiêu đề nhóm phòng, dòng rỗng
        if not isinstance(stt, int):
            continue
        if not ho_ten or not phong:
            continue
        if han_muc is None:
            continue

        records.append({
            "stt":       stt,
            "ho_ten":    str(ho_ten).strip(),
            "phong":     str(phong).strip(),
            "chuc_vu":   str(chuc_vu).strip() if chuc_vu else "",
            "han_muc":   int(han_muc),
            "chuyen_nam": int(chuyen_nam) if chuyen_nam else 0,
            "da_nghi":   int(da_nghi) if da_nghi else 0,
        })

    wb.close()
    return records

# ── Load staff từ DB ────────────────────────────────────────────────────────────
def load_staff(db: sqlite3.Connection) -> list[dict]:
    """Trả về list staff kèm tên phòng, chuẩn hoá sẵn."""
    rows = db.execute("""
        SELECT u.id, u.full_name, u.email, u.staff_code,
               d.name AS dept_name
        FROM user_tttt u
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE u.is_active = 1 AND u.role != 'admin'
    """).fetchall()
    return [
        {
            "id":         r["id"],
            "full_name":  r["full_name"],
            "email":      r["email"] or "",
            "staff_code": r["staff_code"] or "",
            "dept_name":  r["dept_name"] or "",
            "norm_name":  _norm(r["full_name"] or ""),
            "norm_dept":  _norm(r["dept_name"] or ""),
        }
        for r in rows
    ]

def find_staff(record: dict, staff_list: list[dict]) -> dict | None:
    """
    Khớp theo thứ tự ưu tiên:
      1. norm_name + norm_dept khớp chính xác
      2. norm_name khớp (bỏ qua phòng — phòng khác tên nhưng cùng người)
    """
    nr = _norm(record["ho_ten"])
    nd = _norm(record["phong"])

    # Ưu tiên 1: khớp cả tên lẫn phòng
    for s in staff_list:
        if s["norm_name"] == nr and s["norm_dept"] == nd:
            return s

    # Ưu tiên 2: chỉ khớp tên (báo warning)
    matches = [s for s in staff_list if s["norm_name"] == nr]
    if len(matches) == 1:
        return matches[0]

    return None

# ── Ghi DB ─────────────────────────────────────────────────────────────────────
def migrate_one(db: sqlite3.Connection, record: dict, staff: dict,
                dry_run: bool, year: int = 2026) -> str:
    staff_id = staff["id"]
    han_muc  = record["han_muc"]
    chuyen   = record["chuyen_nam"]
    da_nghi  = record["da_nghi"]
    now      = _vn_now()

    actions = []

    # 1. Ghi leave_quotas
    existing = db.execute(
        "SELECT id FROM leave_quotas WHERE staff_id=? AND year=?",
        (staff_id, year)
    ).fetchone()

    if not dry_run:
        if existing:
            db.execute(
                "UPDATE leave_quotas SET quota_days=?, carry_over_days=?, updated_at=? WHERE staff_id=? AND year=?",
                (han_muc, chuyen, now, staff_id, year)
            )
        else:
            db.execute(
                "INSERT INTO leave_quotas (staff_id, year, quota_days, carry_over_days, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (staff_id, year, han_muc, chuyen, now, now)
            )
    actions.append(f"quota={han_muc}+carry={chuyen}")

    # 2. Tạo bản ghi khai báo hộ nếu đã nghỉ > 0
    if da_nghi > 0:
        dates = _spread_dates(da_nghi, year)
        if dates:
            start_date = dates[0]
            end_date   = dates[-1]
            import json
            if not dry_run:
                # Kiểm tra xem đã có bản ghi migration chưa (tránh trùng)
                dup = db.execute(
                    "SELECT id FROM leave_records WHERE staff_id=? AND leave_type='bat_buoc' AND strftime('%Y',start_date)=?",
                    (staff_id, str(year))
                ).fetchone()
                if not dup:
                    db.execute("""
                        INSERT INTO leave_records
                          (staff_id, leave_type, start_date, end_date, spread_dates,
                           status, reason, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (
                        staff_id, "bat_buoc", start_date, end_date,
                        json.dumps(dates), "approved",
                        f"[Migration] Khai báo hộ tổng hợp {da_nghi} ngày đã nghỉ năm {year}",
                        now, now
                    ))
                    # Cập nhật used_leave_days
                    db.execute(
                        "UPDATE user_tttt SET used_leave_days = COALESCE(used_leave_days,0) + ? WHERE id=?",
                        (da_nghi, staff_id)
                    )
                    actions.append(f"tao_khai_bao_ho={da_nghi}ngay")
                else:
                    actions.append(f"da_co_khai_bao_ho_skip")
            else:
                actions.append(f"[dry] tao_khai_bao_ho={da_nghi}ngay")

    return ", ".join(actions)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Migration dữ liệu nghỉ phép 2026")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in, không ghi DB")
    parser.add_argument("--excel", default=str(XLSX_DEFAULT), help="Đường dẫn file Excel")
    args = parser.parse_args()

    xlsx_path = Path(args.excel)
    if not xlsx_path.exists():
        sys.exit(f"Không tìm thấy file Excel: {xlsx_path}")
    if not DB_PATH.exists():
        sys.exit(f"Không tìm thấy database: {DB_PATH}\nChạy python init_db.py trước.")

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Đọc Excel: {xlsx_path}")
    records = read_excel(xlsx_path)
    print(f"  → {len(records)} nhân viên trong Excel\n")

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    staff_list = load_staff(db)
    print(f"  → {len(staff_list)} nhân viên active trong DB\n")

    matched   = []
    unmatched = []

    for rec in records:
        staff = find_staff(rec, staff_list)
        if staff:
            matched.append((rec, staff))
        else:
            unmatched.append(rec)

    print(f"{'='*60}")
    print(f"  Khớp:      {len(matched)}")
    print(f"  Không khớp: {len(unmatched)}")
    print(f"{'='*60}\n")

    # Ghi DB
    try:
        for rec, staff in matched:
            action = migrate_one(db, rec, staff, dry_run=args.dry_run)
            print(f"  ✓ {rec['ho_ten']} ({rec['phong']}) → {action}")

        if not args.dry_run:
            db.commit()
            print(f"\n✅ Đã ghi {len(matched)} nhân viên vào DB.")
        else:
            print(f"\n[DRY RUN] Không ghi gì. Chạy lại không có --dry-run để áp dụng.")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Lỗi: {e}")
        import traceback; traceback.print_exc()
    finally:
        db.close()

    if unmatched:
        print(f"\n⚠️  Không tìm thấy trong DB ({len(unmatched)} người):")
        for r in unmatched:
            print(f"   - {r['ho_ten']} | {r['phong']}")
        print("\n  → Kiểm tra tên/phòng trong DB có khớp với Excel không.")
        print("    Có thể dùng staff_code hoặc email để khớp thủ công.")

if __name__ == "__main__":
    main()
