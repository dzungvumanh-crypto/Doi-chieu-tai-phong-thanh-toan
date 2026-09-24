"""Giám sát hệ thống — một màn tổng quan: tải, CSDL, ổ đĩa, sao lưu, nhật ký, người dùng.

Phần lớn số liệu ĐÃ CÓ sẵn nhưng nằm rải rác: dòng "Request chậm" (slow_request),
backup + lệch giờ ở màn Nhật ký, phiên đối chiếu trong phien_doi_chieu. Module này
chỉ gom lại và tự đánh giá ra danh sách cảnh báo — không đo thêm gì chạy nền.

Chỉ đọc, không có thao tác ghi. Gate bằng `menu.monitor`, KHÔNG dùng lại `menu.logs`:
xem tải máy chủ là việc của người vận hành, đọc nội dung nhật ký (ai làm gì) là
quyền khác — gộp chung thì cấp một cái là lộ cả hai.
"""
import logging
import os
import platform
import shutil
import socket
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import anyio.to_thread
from fastapi import APIRouter, Depends

from backend.core.config import BASE_DIR
from backend.core.deps import co_quyen, require_feature
from backend.database import DB_PATH, get_db, _vn_now

router = APIRouter()
_log = logging.getLogger(__name__)

# Mốc router được nạp = lúc backend khởi động (registry import mọi router khi dựng app)
_BAT_DAU = time.time()
_GB = 1024 ** 3
_CUA_SO_LOOP_GIAY = 60          # đo event loop trong 60 giây gần nhất
# Biểu đồ độ phản hồi: 5 phút = tuổi tối đa của deque mẫu trong slow_request; ô 5 giây
# → 60 cột, đủ thưa để nhìn ra cụm mà không thành hàng rào kẻ sọc
_CUA_SO_TRE_GIAY = 300
_BUOC_TRE_GIAY = 5

# ── Ngưỡng cảnh báo ──
_DIA_TRONG_LOI = (0.05, 2 * _GB)        # còn < 5 % HOẶC < 2 GB → lỗi
_DIA_TRONG_CANH_BAO = (0.15, 10 * _GB)  # còn < 15 % HOẶC < 10 GB → cảnh báo
_BACKUP_CANH_BAO_GIO = 26               # lịch 24 h/lần + 2 h dư
_BACKUP_LOI_GIO = 50                    # lỡ liền hai lượt
_WAL_CANH_BAO = 200 * 1024 ** 2         # WAL phình = checkpoint không chạy được (có kết nối giữ đọc lâu)
_RAM_CANH_BAO_PHAN_TRAM = 90
_LOOP_CHAN_CANH_BAO_MS = 1000
_DANG_NHAP_SAI_CANH_BAO = 20
_AUDIT_HANG_DOI_CANH_BAO = 0.1          # 10 % sức chứa hàng đợi nhật ký


# ── Windows: RAM + CPU qua ctypes (không thêm psutil vào requirements) ──
def _ram_may() -> dict | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _MS(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    ms = _MS()
    ms.dwLength = ctypes.sizeof(ms)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        return None
    return {"tong": ms.ullTotalPhys, "con_trong": ms.ullAvailPhys, "phan_tram": ms.dwMemoryLoad}


def _ram_backend() -> int | None:
    """Working set hiện tại của tiến trình backend (byte). Tiến trình con đối chiếu KHÔNG tính."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return pmc.WorkingSetSize
    return None


def _cpu_phan_tram(giay: float = 0.3) -> float | None:
    """CPU cả máy trong `giay` giây. Ngủ trong luồng — nhả GIL, không giữ gì khác."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    def _chup():
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        so = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime  # noqa: E731
        return so(idle), so(kernel), so(user)

    a = _chup()
    time.sleep(giay)
    b = _chup()
    if not a or not b:
        return None
    idle, kernel, user = (b[i] - a[i] for i in range(3))
    tong = kernel + user          # kernel time đã GỒM idle
    return round(100 * (tong - idle) / tong, 1) if tong else None


# ── Ổ đĩa ──
def _co_thu_muc(p: Path) -> int:
    tong = 0
    try:
        for e in os.scandir(p):
            try:
                if e.is_dir(follow_symlinks=False):
                    tong += _co_thu_muc(Path(e.path))
                else:
                    tong += e.stat(follow_symlinks=False).st_size
            except OSError:
                pass        # file bị xoá giữa lúc quét (dọn temp) — bỏ qua, chỉ là số ước lượng
    except OSError:
        pass                # thư mục không tồn tại / không đọc được — tính 0
    return tong


def _co_file(p: str) -> int | None:
    try:
        return os.path.getsize(p)
    except OSError:
        return None


def _dia(data_dir: Path, log_dir: Path) -> dict:
    try:
        du = shutil.disk_usage(data_dir)
        o_dia = {"tong": du.total, "con_trong": du.free, "o": os.path.splitdrive(str(data_dir.resolve()))[0] or "/"}
    except OSError:
        o_dia = None
    temp = {p.name: _co_thu_muc(p) for p in sorted(data_dir.glob("temp_*")) if p.is_dir()}
    ra = {
        "o_dia": o_dia,
        "csdl": _co_file(DB_PATH),
        "wal": _co_file(DB_PATH + "-wal"),
        "sao_luu": _co_thu_muc(data_dir / "backups"),
        "nhat_ky": _co_thu_muc(log_dir),
        "tam": sum(temp.values()),
        "tam_chi_tiet": temp,
    }
    # "khac" = phần ổ đĩa do THỨ KHÁC chiếm (Windows, phần mềm, dữ liệu người dùng).
    # Tính ở backend để biểu đồ thành phần không phải tự trừ — và để chốt ≥ 0: bốn mục
    # trên đều nằm dưới BASE_DIR nên tổng của chúng không bao giờ vượt phần đã dùng,
    # trừ khi thư mục logs nằm ở ổ khác (không phải cấu hình của dự án này).
    if o_dia:
        da_dung = o_dia["tong"] - o_dia["con_trong"]
        biet = sum(ra[k] or 0 for k in ("csdl", "wal", "sao_luu", "nhat_ky", "tam"))
        ra["da_dung"] = da_dung
        ra["khac"] = max(0, da_dung - biet)
    return ra


# ── Nhật ký app.log ──
# Không dùng regex của màn Nhật ký cho từng dòng: file tới 5 MB, trang này tự làm mới
# định kỳ — cắt chuỗi theo vị trí cố định của formatter nhanh hơn nhiều lần.
# Khuôn: "2026-09-22 10:00:00 WARNING  slow.request — nội dung"
def _khoa_gio(den: datetime, so_gio: int = 24) -> list[str]:
    """Khoá giờ 'YYYY-MM-DD HH' của `so_gio` giờ gần nhất, cũ → mới.

    Biểu đồ phải có đủ ô kể cả giờ không có bản ghi nào — thiếu ô là trục thời gian
    bị co lại, hai cột cách nhau 6 tiếng trông như hai cột liền nhau."""
    return [(den - timedelta(hours=i)).strftime("%Y-%m-%d %H") for i in range(so_gio - 1, -1, -1)]


def _quet_log(duong_dan: list[Path], moc: datetime, den: "datetime | None" = None,
              so_loi_gan: int = 5) -> dict:
    moc_s = moc.strftime("%Y-%m-%d %H:%M:%S")
    loi = canh_bao = cham = 0
    loi_gan: list[dict] = []
    tu_luc = None
    theo_gio: dict[str, dict] = {}
    for p in duong_dan:
        try:
            f = open(p, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            for dong in f:
                if len(dong) < 30 or dong[4] != "-" or dong[19] != " " or not dong[:4].isdigit():
                    continue                # dòng nối (traceback) — thuộc bản ghi phía trên
                ts = dong[:19]
                if tu_luc is None or ts < tu_luc:
                    tu_luc = ts
                if ts < moc_s:
                    continue
                muc = dong[20:28].strip()
                o = theo_gio.setdefault(ts[:13], {"loi": 0, "canh_bao": 0})
                if muc == "ERROR" or muc == "CRITICAL":
                    loi += 1
                    o["loi"] += 1
                    nguon, _, msg = dong[29:].partition(" — ")
                    loi_gan.append({"ts": ts, "nguon": nguon.strip(), "msg": msg.strip()[:300]})
                elif muc == "WARNING":
                    canh_bao += 1
                    o["canh_bao"] += 1
                    if dong[29:].startswith("slow.request "):
                        cham += 1
    loi_gan.sort(key=lambda x: x["ts"], reverse=True)
    # Dòng cũ nhất đọc được vẫn MỚI hơn mốc = log đã xoay vòng hết → số đếm chỉ phủ một phần
    return {"loi": loi, "canh_bao": canh_bao, "request_cham": cham,
            "loi_gan": loi_gan[:so_loi_gan], "tu_luc": tu_luc,
            "day_du": tu_luc is None or tu_luc <= moc_s,
            "theo_gio": [{"gio": k[11:13], **theo_gio.get(k, {"loi": 0, "canh_bao": 0})}
                         for k in _khoa_gio(den or moc + timedelta(hours=24))]}


_SO_BAN_XOAY = 3        # = backupCount của RotatingFileHandler trong backend/main.py


def _file_log(log_path: Path, moc: datetime) -> list[Path]:
    """app.log rồi lần lượt app.log.1…3 chừng nào file vừa đọc còn bắt đầu SAU mốc.

    Lúc có sự cố log tuôn ra nhiều, 24 giờ có thể trải qua vài lần xoay — chỉ đọc .1
    là đếm hụt lỗi đúng lúc cần biết nhất."""
    moc_s = moc.strftime("%Y-%m-%d %H:%M:%S")
    ds = []
    for i in range(_SO_BAN_XOAY + 1):
        p = log_path if i == 0 else log_path.with_name(f"{log_path.name}.{i}")
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                dau = f.readline()[:19]
        except OSError:
            break           # chưa có file (máy mới / chạy dưới pytest) — dừng ở đây
        ds.append(p)
        if dau <= moc_s:
            break           # file này đã phủ tới mốc, bản cũ hơn nằm ngoài cửa sổ
    return ds


# ── CSDL + người dùng ──
def _csdl(db: sqlite3.Connection) -> dict:
    t = time.perf_counter()
    try:
        db.execute("SELECT 1 FROM user_tttt LIMIT 1").fetchone()
        return {"ok": True, "ms": round((time.perf_counter() - t) * 1000, 1), "loi": None}
    except sqlite3.Error as e:
        return {"ok": False, "ms": None, "loi": str(e)}


def _nguoi_dung(db: sqlite3.Connection) -> dict:
    from backend.core.sessions import _utc_str, _utcnow

    now_utc = _utc_str(_utcnow())
    moc_vn = (_vn_now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    def dem(sql, *ts):
        try:
            return db.execute(sql, ts).fetchone()[0]
        except sqlite3.Error:
            return None     # bảng chưa có (DB cũ) — hiện "—", không làm hỏng cả màn

    # substr(...,1,13) chứ không strftime(): cột lưu qua adapter datetime nên có phần
    # thập phân giây, và substr không phải đoán khuôn ngày — cắt đúng "YYYY-MM-DD HH".
    def theo_gio():
        try:
            rows = db.execute(
                """SELECT substr(created_at, 1, 13) g,
                          SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) ok,
                          SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) sai
                   FROM login_logs WHERE created_at >= ? GROUP BY g""", (moc_vn,)).fetchall()
        except sqlite3.Error:
            return None
        o = {r[0]: (r[1], r[2]) for r in rows}
        return [{"gio": k[11:13], "ok": o.get(k, (0, 0))[0], "sai": o.get(k, (0, 0))[1]}
                for k in _khoa_gio(_vn_now())]

    # login_logs / audit_logs ghi giờ VN (_vn_now); login_sessions / rate_limit ghi giờ UTC
    return {
        "phien": dem("SELECT COUNT(*) FROM login_sessions WHERE expires_at > ?", now_utc),
        "dang_nhap_ok": dem("SELECT COUNT(*) FROM login_logs WHERE success = 1 AND created_at >= ?", moc_vn),
        "dang_nhap_sai": dem("SELECT COUNT(*) FROM login_logs WHERE success = 0 AND created_at >= ?", moc_vn),
        "bi_khoa": dem("SELECT COUNT(*) FROM login_rate_limit WHERE locked_until > ?", now_utc),
        "thao_tac": dem("SELECT COUNT(*) FROM audit_logs WHERE created_at >= ?", moc_vn),
        "theo_gio": theo_gio(),
    }


def _thu_thap_dong_bo(db: sqlite3.Connection, current: dict) -> dict:
    """Mọi phần đụng đĩa / CSDL / mạng — chạy trong luồng, không trên event loop."""
    from backend.services.backup_service import last_backup_info
    from backend.services.time_sync import check_drift
    from backend.api.logs import _LOG_PATH

    log_path = Path(_LOG_PATH)
    # Giờ trong app.log là giờ MÁY (logging dùng localtime), không phải _vn_now()
    moc_log = datetime.now() - timedelta(hours=24)
    ram = _ram_may()
    nhat_ky = _quet_log(_file_log(log_path, moc_log), moc_log, datetime.now())
    # Nội dung dòng lỗi là nội dung nhật ký — chỉ người có menu.logs mới đọc; số đếm thì ai cũng thấy
    nhat_ky["xem_noi_dung"] = co_quyen(db, current, "menu.logs")
    if not nhat_ky["xem_noi_dung"]:
        nhat_ky["loi_gan"] = []
    return {
        "may_chu": {
            "ten_may": socket.gethostname(),
            "python": platform.python_version(),
            "pid": os.getpid(),
            "chay_tu": datetime.fromtimestamp(_BAT_DAU).strftime("%Y-%m-%d %H:%M:%S"),
            "chay_giay": int(time.time() - _BAT_DAU),
            "cpu": _cpu_phan_tram(),
            "ram": ram,
            "ram_backend": _ram_backend(),
        },
        "csdl": _csdl(db),
        "dia": _dia(BASE_DIR / "data", log_path.parent),
        "sao_luu": last_backup_info(),
        "dong_ho": check_drift(),
        "nhat_ky": nhat_ky,
        "nguoi_dung": _nguoi_dung(db),
    }


def _tai_hien_tai() -> dict:
    """Số liệu trong RAM của backend — gọi trên event loop (bộ đếm luồng anyio cần loop)."""
    from backend.core import audit_queue, phien_doi_chieu, slow_request
    from backend.services import leave_pdf

    tai = slow_request.so_lieu_tai(time.monotonic() - _CUA_SO_LOOP_GIAY)
    # Chỉ trường để hiển thị — job_id / task_token dùng được cho /cancel, /download của module
    tai["doi_chieu"] = [{k: j.get(k) for k in ("module", "ten_module", "status", "tuoi_giay")}
                        for j in tai["doi_chieu"]]
    tai["doi_chieu_toi_da"] = phien_doi_chieu.MAX_SONG_SONG
    tai["doi_chieu_ngan_sach_ram_gb"] = phien_doi_chieu.NGAN_SACH_RAM_GB
    tai["hang_doi_nhat_ky"] = audit_queue._q.qsize()
    tai["hang_doi_nhat_ky_toi_da"] = audit_queue.MAX_QUEUE
    tai["word_nen"] = leave_pdf._server.alive()
    # Chuỗi cho biểu đồ độ phản hồi — nguồn duy nhất có sẵn lịch sử thật (deque ~5 phút
    # của task đo trễ), không phải dựng thêm bộ lấy mẫu chạy nền nào
    tai["tre_series"] = slow_request.chuoi_tre(_CUA_SO_TRE_GIAY, _BUOC_TRE_GIAY)
    tai["tre_buoc_giay"] = _BUOC_TRE_GIAY
    return tai


# ── Đánh giá ──
def danh_gia(d: dict) -> list[dict]:
    """Danh sách {muc: loi|canh_bao, nhom, noi_dung}. Hàm thuần — test được không cần máy thật."""
    ra: list[dict] = []

    def them(muc, nhom, noi_dung):
        ra.append({"muc": muc, "nhom": nhom, "noi_dung": noi_dung})

    if d["tai"] is None:
        them("loi", "Hiệu năng", "Không đọc được số liệu tải của backend — xem app.log")
    if not d["csdl"]["ok"]:
        them("loi", "CSDL", f"Không đọc được cơ sở dữ liệu: {d['csdl']['loi']}")

    od = d["dia"]["o_dia"]
    if not od:
        them("canh_bao", "Ổ đĩa", "Không đọc được dung lượng ổ đĩa")
    elif od["tong"]:
        ti_le = od["con_trong"] / od["tong"]
        gb = od["con_trong"] / _GB
        if ti_le < _DIA_TRONG_LOI[0] or od["con_trong"] < _DIA_TRONG_LOI[1]:
            them("loi", "Ổ đĩa", f"Ổ {od['o']} gần đầy — còn {gb:.1f} GB ({ti_le:.0%})")
        elif ti_le < _DIA_TRONG_CANH_BAO[0] or od["con_trong"] < _DIA_TRONG_CANH_BAO[1]:
            them("canh_bao", "Ổ đĩa", f"Ổ {od['o']} còn ít chỗ — {gb:.1f} GB ({ti_le:.0%})")
    wal = d["dia"]["wal"]
    if wal and wal > _WAL_CANH_BAO:
        them("canh_bao", "CSDL", f"File WAL phình to ({wal / 1024 ** 2:.0f} MB) — có kết nối giữ đọc quá lâu")

    bk = d["sao_luu"]
    if not bk.get("exists"):
        them("loi", "Sao lưu", "Chưa có bản sao lưu tự động nào")
    elif bk.get("tuoi_gio") is not None:
        if bk["tuoi_gio"] >= _BACKUP_LOI_GIO:
            them("loi", "Sao lưu", f"Sao lưu tự động đã ngừng {bk['tuoi_gio']:.0f} giờ (lần cuối {bk['time']})")
        elif bk["tuoi_gio"] >= _BACKUP_CANH_BAO_GIO:
            them("canh_bao", "Sao lưu", f"Sao lưu tự động trễ — lần cuối {bk['time']}")

    dh = d["dong_ho"]
    if dh.get("enabled") and not dh.get("error") and not dh.get("ok"):
        them("canh_bao", "Đồng hồ", f"Đồng hồ máy chủ lệch {dh['drift_seconds']} giây so với {dh['server']}")

    ram = d["may_chu"]["ram"]
    if ram and ram["phan_tram"] >= _RAM_CANH_BAO_PHAN_TRAM:
        them("canh_bao", "Máy chủ", f"RAM máy chủ đã dùng {ram['phan_tram']} %")

    nk = d["nhat_ky"]
    if nk["loi"]:
        them("canh_bao", "Nhật ký", f"{nk['loi']} lỗi trong 24 giờ qua")
    if not nk.get("day_du", True):
        them("canh_bao", "Nhật ký", f"Nhật ký đã xoay vòng hết — số đếm chỉ tính từ {nk['tu_luc']}, có thể thiếu")

    t = d["tai"] or {}
    if t.get("loop_chan_max_ms") is not None and t["loop_chan_max_ms"] >= _LOOP_CHAN_CANH_BAO_MS:
        them("canh_bao", "Hiệu năng", f"Backend bị đứng {t['loop_chan_max_ms']} ms liền trong 1 phút qua")
    if t.get("luong_cho"):
        them("canh_bao", "Hiệu năng", f"{t['luong_cho']} request đang xếp hàng chờ luồng xử lý")
    if t.get("csdl_xep_cong"):
        them("canh_bao", "Hiệu năng", f"{t['csdl_xep_cong']} request đang chờ kết nối CSDL")
    if t.get("hang_doi_nhat_ky", 0) >= t.get("hang_doi_nhat_ky_toi_da", 1) * _AUDIT_HANG_DOI_CANH_BAO:
        them("canh_bao", "Nhật ký", f"Hàng đợi ghi nhật ký tồn {t['hang_doi_nhat_ky']} dòng — CSDL ghi chậm")

    nd = d["nguoi_dung"]
    if (nd.get("dang_nhap_sai") or 0) >= _DANG_NHAP_SAI_CANH_BAO:
        them("canh_bao", "Đăng nhập", f"{nd['dang_nhap_sai']} lượt đăng nhập sai trong 24 giờ qua")

    ra.sort(key=lambda x: x["muc"] != "loi")
    return ra


def _tuoi_backup(bk: dict) -> dict:
    if bk.get("exists") and bk.get("time"):
        luc = datetime.strptime(bk["time"], "%H:%M %d/%m/%Y")
        bk = {**bk, "tuoi_gio": round((datetime.now() - luc).total_seconds() / 3600, 1)}
    bk.pop("path", None)        # đường dẫn tuyệt đối trên máy chủ — giao diện không cần
    return bk


@router.get("/overview")
async def overview(
    current: dict = Depends(require_feature("menu.monitor")),
    db: sqlite3.Connection = Depends(get_db),
):
    # so_lieu_tai() CÓ THỂ raise — hỏng một khối thì báo lỗi khối đó, không 500 cả màn
    try:
        tai = _tai_hien_tai()
    except Exception:
        _log.error("Giám sát: không đọc được số liệu tải", exc_info=True)
        tai = None
    # anyio.to_thread (bể 40 chung như endpoint `def`), KHÔNG asyncio.to_thread — xem DESIGN.md
    d = await anyio.to_thread.run_sync(_thu_thap_dong_bo, db, current)
    d["sao_luu"] = _tuoi_backup(d["sao_luu"])
    d["tai"] = tai
    canh_bao = danh_gia(d)
    d["canh_bao"] = canh_bao
    d["tong_the"] = ("loi" if any(c["muc"] == "loi" for c in canh_bao)
                     else "canh_bao" if canh_bao else "tot")
    d["luc"] = _vn_now().strftime("%Y-%m-%d %H:%M:%S")
    return d
