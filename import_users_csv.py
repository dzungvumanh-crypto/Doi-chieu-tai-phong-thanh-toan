"""
Import data/user_tttt.csv vào bảng user_tttt của database.
Upsert theo employee_code: insert mới hoặc cập nhật nếu đã tồn tại.

Chạy: python import_users_csv.py
"""
import csv
import sqlite3
import sys
import os

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "user_tttt.csv")
DB_PATH  = os.path.join(os.path.dirname(__file__), "ksnb.db")

# Các cột integer — rỗng → NULL
INT_COLS = {"is_active", "department_id", "annual_leave_days",
            "used_leave_days", "must_change_password", "is_deleted"}


def _coerce(col: str, val: str):
    if val == "" or val is None:
        return None
    if col in INT_COLS:
        return int(val)
    return val.strip()


def main():
    if not os.path.exists(CSV_PATH):
        print(f"Không tìm thấy file: {CSV_PATH}")
        sys.exit(1)
    if not os.path.exists(DB_PATH):
        print(f"Không tìm thấy database: {DB_PATH}")
        sys.exit(1)

    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("File CSV rỗng.")
        sys.exit(0)

    # Bỏ cột id — để SQLite tự sinh hoặc giữ nguyên tùy chọn bên dưới
    cols_no_id = [c for c in rows[0].keys() if c != "id"]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    inserted = updated = skipped = 0
    for row in rows:
        emp_code = (row.get("employee_code") or "").strip()
        if not emp_code:
            skipped += 1
            continue

        existing = conn.execute(
            "SELECT id FROM user_tttt WHERE employee_code = ?", (emp_code,)
        ).fetchone()

        vals = [_coerce(c, row[c]) for c in cols_no_id]

        if existing:
            sets = ", ".join(f"{c} = ?" for c in cols_no_id if c != "employee_code")
            set_vals = [_coerce(c, row[c]) for c in cols_no_id if c != "employee_code"]
            conn.execute(
                f"UPDATE user_tttt SET {sets} WHERE employee_code = ?",
                set_vals + [emp_code],
            )
            updated += 1
        else:
            ph = ", ".join("?" * len(cols_no_id))
            conn.execute(
                f"INSERT INTO user_tttt ({', '.join(cols_no_id)}) VALUES ({ph})",
                vals,
            )
            inserted += 1

    conn.commit()
    conn.close()
    print(f"Hoàn tất: +{inserted} mới, ~{updated} cập nhật, {skipped} bỏ qua.")


if __name__ == "__main__":
    main()
