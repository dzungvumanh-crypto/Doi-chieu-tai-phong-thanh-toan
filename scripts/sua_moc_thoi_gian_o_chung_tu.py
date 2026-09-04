# -*- coding: utf-8 -*-
"""Trả lại mốc thời gian gốc cho một ô chứng từ đã bị xoá rồi nhập lại.

Bối cảnh 03/09/2026: Nguyễn Thị Phương (id 43) nộp chứng từ ngày 27/08 nhưng điền
nhầm vào ô của Hoàng Thị Lan Anh (id 36); HKV đã xác nhận. Người vận hành xoá ô của
Lan Anh và nhập lại vào ô của Phương — nhưng `upsert_entry` xoá CỨNG cả
`document_entries` lẫn `entry_change_logs`, nên ô mới mang mốc thời gian của ngày
nhập lại (03/09) chứ không phải ngày nộp thật (28/08).

Vì sao là script chứ không chép đè file DB: DB trên máy phát triển là bản chép về,
máy chủ đã phát sinh dữ liệu mới sau đó. Chép đè để lấy một ô là đánh đổi sai
hướng. Thứ cần mang sang chỉ là mấy mốc thời gian dưới đây.

Vì sao xoá log cũ rồi chèn lại thay vì chèn thêm: màn Lịch sử ô hiện theo thứ tự
thời gian; để lẫn dòng của ngày nhập lại thì người xem đọc ra hai lần bàn giao cho
cùng một ô. Dấu vết can thiệp không mất — nó nằm ở dòng `audit_logs` script ghi.

Chạy trên máy chủ, trong thư mục dự án:
    python scripts/sua_moc_thoi_gian_o_chung_tu.py          # chỉ xem, không ghi
    python scripts/sua_moc_thoi_gian_o_chung_tu.py --ghi    # ghi thật (tự backup trước)
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Console Windows mặc định cp437/cp1252 — mọi câu tiếng Việt in ra sẽ ném
# UnicodeEncodeError và cắt ngang script giữa chừng. Ép UTF-8 ngay từ đầu.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Dữ liệu gốc lấy từ DB trước khi ô bị xoá ─────────────────────────────────
PHONG_CODE   = "PAYMENT"
NGAY_GD      = "2026-08-27"
STAFF_DUNG   = 43          # Nguyễn Thị Phương — người nộp thật
STAFF_NHAM   = 36          # Hoàng Thị Lan Anh — ô bị điền nhầm
SO_TO        = 173
NGUOI_NHAP   = 43
NGUOI_XAC_NHAN = 5
TS_NOP       = "2026-08-28 16:30:36.240246"
TS_XAC_NHAN  = "2026-08-28 17:03:18.729732"

LY_DO = (
    "Sửa tay mốc thời gian ô chứng từ: GDV Nguyễn Thị Phương nộp ngày 27/08 nhưng "
    "điền nhầm vào ô Hoàng Thị Lan Anh. Ô nhầm đã xoá, ô đúng nhập lại nên mang mốc "
    "thời gian ngày nhập lại. Trả về mốc gốc: nộp %s, xác nhận %s." % (TS_NOP, TS_XAC_NHAN)
)


def _ket_noi(duong_dan: str) -> sqlite3.Connection:
    db = sqlite3.connect(duong_dan)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _backup(duong_dan: str) -> Path:
    # Đặt cạnh chính DB được sửa, không cứng "data/backups": chạy với --db trỏ nơi
    # khác mà backup rơi vào data/ của máy này thì bản lưu nằm xa file nó bảo vệ.
    # Tên KHÔNG theo mẫu ksnb_YYYYMMDD_HHMM → _rotate() của backup_service không đụng tới.
    dich = Path(duong_dan).resolve().parent / "backups" / ("truoc_sua_o_%s.db" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    dich.parent.mkdir(parents=True, exist_ok=True)
    nguon = _ket_noi(duong_dan)
    dich_db = sqlite3.connect(str(dich))
    with dich_db:
        nguon.backup(dich_db)      # backup API: an toàn cả khi backend đang chạy
    dich_db.close()
    nguon.close()
    return dich


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/ksnb.db")
    ap.add_argument("--ghi", action="store_true", help="Ghi thật; không có cờ này chỉ in ra")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print("Không thấy DB: %s" % args.db)
        return 1

    db = _ket_noi(args.db)

    # ── Định vị phiếu bàn giao ───────────────────────────────────────────────
    phong = db.execute("SELECT id, name FROM departments WHERE code = ?", (PHONG_CODE,)).fetchone()
    if not phong:
        print("Không thấy phòng %s" % PHONG_CODE)
        return 1
    h = db.execute(
        "SELECT id FROM handovers WHERE department_id = ? AND handover_date = ?",
        (phong["id"], NGAY_GD),
    ).fetchone()
    if not h:
        print("Không thấy phiếu bàn giao %s ngày %s — dừng, cần kiểm tra tay." % (phong["name"], NGAY_GD))
        return 1
    handover_id = h["id"]

    # ── Chặn: ô nhầm còn tồn tại nghĩa là DB này chưa ở trạng thái ta nghĩ ────
    o_nham = db.execute(
        "SELECT id FROM document_entries WHERE handover_id=? AND staff_id=? AND transaction_date=?",
        (handover_id, STAFF_NHAM, NGAY_GD),
    ).fetchone()
    if o_nham:
        print("DỪNG: ô của Hoàng Thị Lan Anh (entry %s) vẫn còn. DB này chưa xoá ô nhầm —"
              " chạy tiếp sẽ tạo ra hai ô cho cùng một tập chứng từ." % o_nham["id"])
        return 2

    o = db.execute(
        "SELECT * FROM document_entries WHERE handover_id=? AND staff_id=? AND transaction_date=?",
        (handover_id, STAFF_DUNG, NGAY_GD),
    ).fetchone()

    if o is None:
        print("Ô của Nguyễn Thị Phương ngày %s CHƯA có → sẽ tạo mới %s tờ." % (NGAY_GD, SO_TO))
        viec = "insert"
    else:
        print("Ô hiện tại: entry %s, %s tờ, trạng thái %s, xác nhận lúc %s"
              % (o["id"], o["sheet_count"], o["entry_status"], o["confirmed_at"]))
        if o["sheet_count"] != SO_TO:
            print("DỪNG: số tờ trên DB (%s) khác số tờ gốc (%s) — không tự quyết, kiểm tra tay."
                  % (o["sheet_count"], SO_TO))
            return 2
        if o["entry_status"] not in ("confirmed", "pending"):
            print("DỪNG: trạng thái '%s' ngoài dự kiến — kiểm tra tay." % o["entry_status"])
            return 2
        viec = "update"

    print("\nSẽ đặt: nộp %s (id %s) — xác nhận %s (id %s)"
          % (TS_NOP, NGUOI_NHAP, TS_XAC_NHAN, NGUOI_XAC_NHAN))

    if not args.ghi:
        print("\n[Chế độ xem] Chưa ghi gì. Thêm --ghi để thực hiện.")
        return 0

    db.close()
    ban_luu = _backup(args.db)
    print("\nĐã backup: %s" % ban_luu)
    db = _ket_noi(args.db)

    try:
        db.execute("BEGIN")
        if viec == "insert":
            db.execute(
                "INSERT INTO document_entries (handover_id, staff_id, transaction_date, sheet_count,"
                " entry_status, entered_by_id, confirmed_by_id, confirmed_at)"
                " VALUES (?,?,?,?,'confirmed',?,?,?)",
                (handover_id, STAFF_DUNG, NGAY_GD, SO_TO, NGUOI_NHAP, NGUOI_XAC_NHAN, TS_XAC_NHAN),
            )
            entry_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        else:
            entry_id = o["id"]
            db.execute(
                "UPDATE document_entries SET entry_status='confirmed', entered_by_id=?,"
                " confirmed_by_id=?, confirmed_at=? WHERE id=?",
                (NGUOI_NHAP, NGUOI_XAC_NHAN, TS_XAC_NHAN, entry_id),
            )

        # Lịch sử: dựng lại đúng hai dòng gốc
        db.execute("DELETE FROM entry_change_logs WHERE entry_id = ?", (entry_id,))
        db.executemany(
            "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, old_sheet_count,"
            " new_sheet_count, timestamp) VALUES (?,?,?,?,?,?)",
            [
                (entry_id, "handover",  NGUOI_NHAP,     None, SO_TO, TS_NOP),
                (entry_id, "confirmed", NGUOI_XAC_NHAN, None, SO_TO, TS_XAC_NHAN),
            ],
        )

        db.execute(
            "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, ip_address, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (NGUOI_XAC_NHAN, "handover_entry_fix_timestamp", "document_entry", entry_id,
             LY_DO, None, str(datetime.now())),
        )
        db.execute("COMMIT")
    except Exception as loi:
        db.execute("ROLLBACK")
        print("LỖI, đã rollback: %s" % loi)
        return 1

    r = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    print("\nXong. entry %s — %s tờ, %s, xác nhận lúc %s"
          % (r["id"], r["sheet_count"], r["entry_status"], r["confirmed_at"]))
    for l in db.execute("SELECT action, performed_by_id, timestamp FROM entry_change_logs"
                        " WHERE entry_id=? ORDER BY timestamp", (entry_id,)):
        print("  %-10s người %-3s %s" % (l["action"], l["performed_by_id"], l["timestamp"]))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
