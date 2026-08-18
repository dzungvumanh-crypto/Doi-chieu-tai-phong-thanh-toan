"""Dọn thư mục kết quả tạm theo lịch — ACH, Chấm 459901, Đối chiếu song phương.

Ba service đó đều tự dọn rác của mình, nhưng chỉ dọn KHI CÓ NGƯỜI DÙNG TÍNH
NĂNG: `_cleanup_old_results()` nằm ngay đầu `process_zip()`, `_cleanup_old_jobs()`
nằm trong `finally` của một lượt chạy. Nghỉ dùng một tháng thì kết quả của tháng
trước nằm nguyên trên đĩa — mà đây là file Excel/CSV của cả ngày giao dịch, không
phải vài KB.

Đúng bài học đã rút ở `log_cleanup_service`: việc dọn dẹp phải chạy nền theo
lịch, không được treo vào đường đi của request. Module này chỉ gọi lại đúng các
hàm dọn sẵn có của từng service — không tự đi xoá thư mục, để mỗi service vẫn là
nơi duy nhất quyết định cái gì của mình là quá hạn.
"""
import logging
import threading

_log = logging.getLogger(__name__)

_INTERVAL_HOURS = 6

# Ref timer toàn cục để có thể hủy khi test
_timer: threading.Timer | None = None


def run_cleanup() -> None:
    """Gọi hàm dọn của từng service. Một service lỗi không được chặn service kia."""
    from backend.services import ach_service, cham459901_service
    from backend.services import doi_chieu_song_phuong_service as sp

    for ten, ham in (
        ("ACH", ach_service._cleanup_old_jobs),
        ("Chấm 459901", cham459901_service._cleanup_old_results),
        ("Đối chiếu song phương", sp._cleanup_old_results),
    ):
        try:
            ham()
        except Exception as exc:
            _log.error("Dọn thư mục tạm %s thất bại: %s", ten, exc, exc_info=True)


def _schedule_next():
    global _timer
    _timer = threading.Timer(_INTERVAL_HOURS * 3600, lambda: (_schedule_next(), run_cleanup()))
    _timer.daemon = True
    _timer.start()


def start_scheduler():
    """Gọi khi khởi động app: dọn ngay (nền) + lặp lại mỗi _INTERVAL_HOURS giờ."""
    threading.Thread(target=run_cleanup, daemon=True, name="temp-cleanup-init").start()
    _schedule_next()


def stop_scheduler():
    global _timer
    if _timer:
        _timer.cancel()
        _timer = None
