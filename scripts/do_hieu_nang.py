# -*- coding: utf-8 -*-
"""Đo hiệu năng trên MÁY CHỦ THẬT — lấy số làm căn cứ trước/sau khi tối ưu.

Vì sao cần: mọi số đo trong phương án nâng cấp hiệu năng đều lấy trên máy phát
triển, mà máy đó chạy trên USB FAT32 — chậm hơn máy chủ khoảng 7 lần ở khâu mở
file. Thứ tự ưu tiên gần như chắc chắn không đổi, nhưng con số tuyệt đối thì
khác hẳn, nên không dùng để nghiệm thu được.

CHỈ ĐỌC. Script không chạy một câu lệnh ghi nào: không INSERT/UPDATE/DELETE,
không VACUUM, không tạo bảng, không đụng file backup.

    Lưu ý duy nhất: script mở CSDL ở chế độ đọc-ghi để tái hiện đúng chi phí mà
    `get_db()` phải trả (mở read-only nhanh hơn vì không phải gắn file -shm, đo
    kiểu đó là tự lừa mình). Khi đóng kết nối, nếu KHÔNG có tiến trình nào khác
    đang giữ CSDL, SQLite có thể tự dồn WAL vào file chính — đó là thao tác bảo
    trì bình thường, không làm đổi dữ liệu. Chạy khi backend đang bật thì cả
    điều đó cũng không xảy ra.

Chạy trên máy chủ (đứng ở thư mục gốc dự án):

    .venv\\Scripts\\python.exe scripts\\do_hieu_nang.py

Nên chạy lúc ít người dùng, và để backend ĐANG CHẠY — bộ nhớ đệm file lúc đó
mới giống trạng thái phục vụ thật.
"""
import json
import os
import sqlite3
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

# Console Windows mặc định không đủ ký tự tiếng Việt — ép UTF-8 như backend/main.py,
# nếu không chỉ một dòng có dấu là script chết giữa chừng.
for _s in (sys.stdout, sys.stderr):
    if _s is not None and (getattr(_s, "encoding", "") or "").lower() not in ("utf-8", "utf8"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "ksnb.db"

# Số đo trên máy phát triển (USB FAT32 / NVMe) để đối chiếu — xem phương án hiệu năng.
DEV = {
    "open": 2.939,      # ms, trên NVMe
    "reuse": 0.007,     # ms
    "parse": 1178.4,    # ms
    "ram": 97.16,       # MB
    "db": 54.3,         # MB
}

VACH = "─" * 74


def _tieu_de(s: str) -> None:
    print(f"\n{VACH}\n  {s}\n{VACH}")


def _dong(nhan: str, gia_tri: str, dev: str = "") -> None:
    print(f"  {nhan:<44} {gia_tri:>14}  {dev}")


def _do(lan: int, fn) -> float:
    """Trả về mili-giây trung bình mỗi lần gọi. Chạy nháp 1 lần cho nóng cache."""
    fn()
    t = time.perf_counter()
    for _ in range(lan):
        fn()
    return (time.perf_counter() - t) / lan * 1000


# ── 1. Bối cảnh ─────────────────────────────────────────────────────────────
def phan_boi_canh(db: sqlite3.Connection) -> float:
    _tieu_de("1. BỐI CẢNH CƠ SỞ DỮ LIỆU")
    kich_thuoc = DB_PATH.stat().st_size / 1048576
    _dong("Kích thước ksnb.db", f"{kich_thuoc:.1f} MB", f"(máy dev: {DEV['db']:.1f} MB)")

    for ten, duoi in (("WAL", "-wal"), ("SHM", "-shm")):
        p = Path(str(DB_PATH) + duoi)
        if p.exists():
            _dong(f"File {ten}", f"{p.stat().st_size / 1048576:.2f} MB")

    ps = db.execute("PRAGMA page_size").fetchone()[0]
    pc = db.execute("PRAGMA page_count").fetchone()[0]
    fl = db.execute("PRAGMA freelist_count").fetchone()[0]
    _dong("page_size × page_count", f"{ps} × {pc}")
    _dong("Trang trống (freelist)", f"{fl}", "→ VACUUM thu hồi được" if fl > 500 else "")
    _dong("journal_mode", db.execute("PRAGMA journal_mode").fetchone()[0])
    return kich_thuoc


# ── 2. Dung lượng theo bảng ─────────────────────────────────────────────────
def phan_dung_luong(db: sqlite3.Connection, kich_thuoc: float) -> None:
    _tieu_de("2. DUNG LƯỢNG THEO BẢNG  (xác nhận lech_json có chiếm 87% không)")
    bang = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    ket = []
    for t in bang:
        cot = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
        if not cot:
            continue
        bieu_thuc = "+".join(f'COALESCE(LENGTH("{c}"),0)' for c in cot)
        try:
            tong = db.execute(f'SELECT SUM({bieu_thuc}) FROM "{t}"').fetchone()[0] or 0
            ket.append((tong, t))
        except sqlite3.Error as e:
            print(f"  (bỏ qua {t}: {e})")
    for tong, t in sorted(ket, reverse=True)[:6]:
        ty_le = tong / 1048576 / kich_thuoc * 100 if kich_thuoc else 0
        _dong(t, f"{tong / 1048576:.2f} MB", f"{ty_le:.0f}% CSDL")


# ── 3. Chi phí mở kết nối ───────────────────────────────────────────────────
def phan_ket_noi() -> None:
    _tieu_de("3. CHI PHÍ CỐ ĐỊNH MỖI REQUEST  (hạng mục 02)")
    duong_dan = str(DB_PATH)

    def nhu_get_db():
        c = sqlite3.connect(duong_dan, check_same_thread=False, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA synchronous=NORMAL")
        c.close()

    def khong_pragma():
        c = sqlite3.connect(duong_dan)
        c.execute("SELECT 1 FROM user_tttt LIMIT 1").fetchone()
        c.close()

    mo = _do(200, nhu_get_db)
    tran = _do(200, khong_pragma)

    conn = sqlite3.connect(duong_dan)
    conn.row_factory = sqlite3.Row
    tai_dung = _do(500, lambda: conn.execute("SELECT COUNT(*) FROM user_tttt").fetchone())
    conn.close()

    _dong("get_db() hiện tại: mở file + 4 PRAGMA", f"{mo:.3f} ms", f"(dev: {DEV['open']:.3f})")
    _dong("Mở file + 1 SELECT, KHÔNG pragma nào", f"{tran:.3f} ms", "← chứng minh bên dưới")
    _dong("Truy vấn trên kết nối tái dùng", f"{tai_dung:.4f} ms", f"(dev: {DEV['reuse']:.3f})")

    # Con số này phụ thuộc bộ nhớ đệm file của Windows rất mạnh — đo được chênh
    # tới 17 lần trên CÙNG một ổ giữa lúc đệm nguội và lúc đệm nóng. Nói rõ ra,
    # không thì người đọc tưởng đây là hằng số của phần cứng.
    print()
    print("  ⓘ Số này phụ thuộc mạnh vào bộ nhớ đệm file của Windows: cùng một ổ,")
    print("    đệm nguội so với đệm nóng chênh nhau hàng chục lần. Giá trị ở trên là")
    print("    trạng thái ĐỆM NÓNG — đúng với lúc máy chủ đang phục vụ liên tục.")
    print("    Muốn thấy trường hợp xấu nhất (sau khi khởi động lại máy), chạy script")
    print("    này ngay khi máy vừa bật, trước khi ai kịp đăng nhập.")

    print()
    if tran > mo * 0.8:
        print("  ✓ Bỏ hết PRAGMA vẫn tốn gần như y nguyên → chi phí nằm ở MỞ FILE.")
        print("    Cách sửa là tái dùng kết nối, KHÔNG phải cắt PRAGMA.")
    else:
        print("  ⚠ Trên máy này PRAGMA lại chiếm phần đáng kể — khác máy dev.")
        print("    Xem lại kết luận của hạng mục 02 trước khi làm.")
    if tai_dung > 0:
        print(f"  → Mở file đắt gấp {mo / tai_dung:,.0f} lần một truy vấn thường.")


# ── 4. Dòng lịch sử đối soát nặng nhất ──────────────────────────────────────
def phan_lech_json(db: sqlite3.Connection) -> None:
    _tieu_de("4. LỊCH SỬ ĐỐI SOÁT CITAD  (hạng mục 01 — rủi ro RAM)")
    try:
        hang = db.execute(
            "SELECT id, n_lech, LENGTH(lech_json) n FROM doi_soat_citad_history "
            "WHERE lech_json IS NOT NULL ORDER BY n DESC LIMIT 5"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"  Không đọc được bảng doi_soat_citad_history: {e}")
        return
    if not hang:
        print("  Chưa có dòng lịch sử nào — bỏ qua phần này.")
        return

    print("  5 dòng nặng nhất:")
    for r in hang:
        _dong(f"  id={r['id']}  ({r['n_lech']:,} lệnh lệch)", f"{r['n'] / 1048576:.2f} MB")

    nang = hang[0]
    print()
    t = time.perf_counter()
    raw = db.execute(
        "SELECT lech_json FROM doi_soat_citad_history WHERE id=?", (nang["id"],)
    ).fetchone()[0]
    doc_ms = (time.perf_counter() - t) * 1000

    tracemalloc.start()
    t = time.perf_counter()
    obj = json.loads(raw)
    parse_ms = (time.perf_counter() - t) * 1000
    _, dinh = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ram = dinh / 1048576

    _dong(f"Đọc dòng id={nang['id']} từ CSDL", f"{doc_ms:.1f} ms")
    _dong("json.loads()", f"{parse_ms:.1f} ms", f"(dev: {DEV['parse']:.0f})")
    _dong("Đỉnh RAM cho MỘT request", f"{ram:.1f} MB", f"(dev: {DEV['ram']:.1f})")
    _dong("Số bản ghi dựng trong RAM", f"{len(obj):,}")

    tran_heavy = int(os.getenv("MAX_HEAVY_TASKS") or 4)
    _dong(f"Đỉnh ước tính khi MAX_HEAVY={tran_heavy}", f"{ram * tran_heavy:.0f} MB",
          "← nhiều người bấm cùng lúc")
    del obj, raw


# ── 5. Tăng trưởng & ngân sách ghi đĩa ──────────────────────────────────────
def phan_ngan_sach(db: sqlite3.Connection, kich_thuoc: float) -> None:
    _tieu_de("5. NGÂN SÁCH GHI ĐĨA  (kiểm chứng: hao mòn SSD có đáng lo không)")
    for bang in ("audit_logs", "login_logs"):
        try:
            r = db.execute(
                f"SELECT MIN(created_at) a, MAX(created_at) b, COUNT(*) n FROM {bang}"
            ).fetchone()
            if not r["n"] or not r["a"]:
                continue
            ngay = (datetime.fromisoformat(str(r["b"])[:19])
                    - datetime.fromisoformat(str(r["a"])[:19])).days or 1
            _dong(f"{bang}", f"{r['n'] / ngay:.1f} dòng/ngày", f"({r['n']:,} dòng / {ngay} ngày)")
        except (sqlite3.Error, ValueError) as e:
            print(f"  (bỏ qua {bang}: {e})")

    # Mỗi lần backup ghi trọn file .db rồi mới nén — xem backup_service.run_backup().
    moi_lan = kich_thuoc + 2.4
    tong_ngay = moi_lan * 2 + 0.7 + 20      # 2 lần/ngày + log ứng dụng + WAL nghiệp vụ
    nam_gb = tong_ngay * 365 / 1024
    print()
    _dong("Một lần sao lưu (chép .db + nén .zip)", f"{moi_lan:.1f} MB")
    _dong("Ước tính ghi mỗi ngày", f"{tong_ngay:.1f} MB")
    _dong("Quy ra mỗi năm", f"{nam_gb:.1f} GB")
    tbw = 300
    _dong("Tiêu hao độ bền SSD (300 TBW)", f"{nam_gb / 1024 / tbw * 100:.4f} %/năm")
    _dong("Số năm để dùng hết độ bền", f"{tbw * 1024 / nam_gb:,.0f} năm")
    print("\n  → Hao mòn SSD không phải vấn đề. Đừng tối ưu vòng quanh nó.")


# ── 6. Quy mô dữ liệu có đáng tối ưu truy vấn không ─────────────────────────
def phan_quet_bang(db: sqlite3.Connection) -> None:
    _tieu_de("6. QUÉT TOÀN BẢNG  (có đáng thêm index / viết lại truy vấn không)")

    # Bỏ qua bảng chứa cột nặng: quét nó là kéo hàng chục MB lên RAM, đo ra con
    # số của việc đọc blob chứ không phải của việc duyệt bảng.
    NGUONG_BLOB = 5 * 1048576
    ung_vien = []
    for (t,) in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        cot = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
        if not cot:
            continue
        bt = "+".join(f'COALESCE(LENGTH("{c}"),0)' for c in cot)
        try:
            tai = db.execute(f'SELECT SUM({bt}) FROM "{t}"').fetchone()[0] or 0
            if tai > NGUONG_BLOB:
                print(f"  (bỏ qua {t}: {tai / 1048576:.0f} MB dữ liệu nặng, xem mục 4)")
                continue
            so_dong = db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            ung_vien.append((so_dong, t))
        except sqlite3.Error as e:
            print(f"  (bỏ qua {t}: {e})")

    for so_dong, t in sorted(ung_vien, reverse=True)[:5]:
        if not so_dong:
            continue
        ms = _do(20, lambda t=t: db.execute(f'SELECT * FROM "{t}"').fetchall())
        _dong(f"{t}  ({so_dong:,} dòng)", f"{ms:.2f} ms")

    # Join ba bảng nghiệp vụ chính — cột dùng ở đây là khoá, ổn định qua các bản.
    q = ("SELECT de.*, bi.bundle_id FROM document_entries de "
         "LEFT JOIN bundle_items bi ON bi.entry_id = de.id "
         "LEFT JOIN bundles b ON b.id = bi.bundle_id")
    try:
        n = len(db.execute(q).fetchall())
        ms = _do(20, lambda: db.execute(q).fetchall())
        _dong(f"Join 3 bảng ({n:,} dòng kết quả)", f"{ms:.2f} ms")
    except sqlite3.Error as e:
        # Không nuốt: schema đổi thì phải biết, không thì tưởng phép đo đã chạy.
        print(f"  Không chạy được phép join: {e}")

    print("\n  → Quét TRỌN bảng lớn nhất mà vẫn tính bằng mili-giây nghĩa là dữ liệu")
    print("    còn quá nhỏ để việc thêm index hay viết lại truy vấn có ý nghĩa.")
    print("    Dùng chính con số này để từ chối các đề xuất tối ưu truy vấn.")


# ── 7. Hệ số phình RAM của pandas ───────────────────────────────────────────
def phan_pandas() -> None:
    _tieu_de("7. HỆ SỐ PHÌNH RAM CỦA PANDAS  (hạng mục 02 — bốn module đối chiếu)")
    try:
        import pandas as pd
    except ImportError:
        print("  Không có pandas trong môi trường này — bỏ qua.")
        return

    import csv
    import random
    import string
    import tempfile

    # Dữ liệu tổng hợp mô phỏng file giao dịch: nhiều cột chuỗi ngắn. Không dùng
    # file thật vì file nguồn có mật khẩu và chạy thật sẽ đẻ dữ liệu nghiệp vụ.
    random.seed(1)
    cot = [f"c{i}" for i in range(11)]
    fd, duong_dan = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        with open(duong_dan, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cot)
            bang_chu = string.ascii_uppercase + string.digits
            for _ in range(100000):
                w.writerow(["".join(random.choices(bang_chu, k=12)) for _ in cot])

        mb = os.path.getsize(duong_dan) / 1048576
        tracemalloc.start()
        # dtype=str, keep_default_na=False — y hệt cham459901_service.py
        d = pd.read_csv(duong_dan, dtype=str, keep_default_na=False)
        _, dinh = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        sau = d.memory_usage(deep=True).sum() / 1048576

        _dong("File CSV tổng hợp trên đĩa", f"{mb:.2f} MB")
        _dong("DataFrame giữ trong RAM", f"{sau:.2f} MB", f"→ {sau / mb:.1f}× file")
        _dong("Đỉnh cấp phát lúc đọc", f"{dinh / 1048576:.2f} MB", f"→ {dinh / 1048576 / mb:.1f}× file")
        del d
        print(f"\n  → Trần upload một lượt là 500 MB. Nhân hệ số {sau / mb:.1f}× ra con số")
        print("    cần so với RAM máy chủ — rồi nhân tiếp với số lượt chạy song song")
        print("    được phép. Hiện chỉ ACH có chốt chặn; ba module kia thì không.")
    finally:
        try:
            os.remove(duong_dan)
        except OSError:
            pass


def main() -> int:
    if not DB_PATH.exists():
        print(f"Không tìm thấy CSDL: {DB_PATH}")
        print("Chạy script từ thư mục gốc dự án trên máy chủ.")
        return 1

    print(f"\n  ĐO HIỆU NĂNG — {datetime.now():%d/%m/%Y %H:%M}")
    print(f"  CSDL: {DB_PATH}")
    print("  Chế độ CHỈ ĐỌC — không có câu lệnh ghi nào được chạy.")

    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    try:
        kich_thuoc = phan_boi_canh(db)
        phan_dung_luong(db, kich_thuoc)
        phan_ket_noi()
        phan_lech_json(db)
        phan_ngan_sach(db, kich_thuoc)
        phan_quet_bang(db)
        phan_pandas()
    finally:
        db.close()

    print(f"\n{VACH}")
    print("  Chép toàn bộ kết quả trên vào phương án hiệu năng làm mốc TRƯỚC.")
    print("  Sau khi tối ưu, chạy lại chính script này để đối chiếu.")
    print(f"{VACH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
