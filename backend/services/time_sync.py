"""Kiểm tra lệch giờ đồng hồ máy chủ so với nguồn thời gian chuẩn (NTP).

Chỉ CẢNH BÁO, không tự sửa giờ máy — đồng bộ giờ là việc của OS/domain
(Windows Time / NTP), không thuộc tầng ứng dụng. App chỉ so đồng hồ máy với
một máy chủ NTP và báo nếu lệch quá ngưỡng, phục vụ độ tin cậy của nhật ký.

Dùng raw socket UDP (RFC 5905) — không thêm thư viện. Mọi lỗi (mạng nội bộ
cô lập chặn NTP, timeout...) được nuốt và trả về ok=False + error, không raise.
"""
import socket
import struct
import time
import logging

from backend.core.config import settings

_log = logging.getLogger("time_sync")

# NTP epoch (1900-01-01) → Unix epoch (1970-01-01)
_NTP_UNIX_DELTA = 2208988800


def _ntp_unix_time(server: str, timeout: float) -> float:
    """Lấy thời gian Unix (UTC epoch) từ máy chủ NTP. Raise nếu không kết nối được."""
    packet = b"\x1b" + 47 * b"\0"     # LI=0, VN=3, Mode=3 (client)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(48)
    finally:
        sock.close()
    if len(data) < 44:
        raise ValueError("Gói NTP trả về không hợp lệ")
    # Transmit Timestamp — 4 byte giây, bắt đầu ở offset 40
    secs = struct.unpack("!I", data[40:44])[0]
    return secs - _NTP_UNIX_DELTA


def check_drift() -> dict:
    """So đồng hồ máy với NTP. Trả về dict mô tả kết quả, không bao giờ raise."""
    if not settings.NTP_ENABLED:
        return {"ok": False, "enabled": False, "server": settings.NTP_SERVER,
                "drift_seconds": None, "threshold": settings.NTP_DRIFT_THRESHOLD_SEC,
                "error": "Đã tắt kiểm tra NTP (NTP_ENABLED=false)"}
    try:
        ntp = _ntp_unix_time(settings.NTP_SERVER, settings.NTP_TIMEOUT_SEC)
        drift = round(time.time() - ntp, 2)   # dương = đồng hồ máy nhanh hơn chuẩn
        within = abs(drift) <= settings.NTP_DRIFT_THRESHOLD_SEC
        return {"ok": within, "enabled": True, "server": settings.NTP_SERVER,
                "drift_seconds": drift, "threshold": settings.NTP_DRIFT_THRESHOLD_SEC,
                "error": None}
    except Exception as e:
        return {"ok": False, "enabled": True, "server": settings.NTP_SERVER,
                "drift_seconds": None, "threshold": settings.NTP_DRIFT_THRESHOLD_SEC,
                "error": f"Không truy cập được NTP: {e}"}


def check_drift_and_log() -> dict:
    """Chạy check_drift + ghi log phù hợp (dùng khi khởi động)."""
    r = check_drift()
    if not r["enabled"]:
        return r
    if r["error"]:
        _log.info("Bỏ qua kiểm tra lệch giờ: %s", r["error"])
    elif not r["ok"]:
        _log.warning(
            "Đồng hồ máy chủ lệch %.2fs so với NTP %s (ngưỡng %ss) — nhật ký có thể sai giờ",
            r["drift_seconds"], r["server"], r["threshold"],
        )
    else:
        _log.info("Đồng hồ máy chủ khớp NTP %s (lệch %.2fs)", r["server"], r["drift_seconds"])
    return r
