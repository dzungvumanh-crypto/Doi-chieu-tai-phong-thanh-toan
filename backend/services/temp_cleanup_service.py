"""Dọn thư mục file tạm theo lịch — 23h hằng ngày.

Năm tính năng có file nằm trên đĩa: ACH, Chấm 459901, Đối chiếu song phương,
Đối soát CITAD, Chuẩn hoá văn bản. Cả bốn đều tự dọn rác của mình, nhưng chỉ dọn KHI CÓ NGƯỜI DÙNG
TÍNH NĂNG: `_cleanup_old_results()` nằm ngay đầu `process_zip()`,
`_cleanup_old_jobs()` nằm trong `finally` của một lượt chạy. Nghỉ dùng một tháng
thì kết quả của tháng trước nằm nguyên trên đĩa — mà đây là file Excel/CSV của cả
ngày giao dịch, không phải vài KB.

Đúng bài học đã rút ở `log_cleanup_service`: việc dọn dẹp phải chạy nền theo
lịch, không được treo vào đường đi của request. Module này chỉ gọi lại đúng các
hàm dọn sẵn có của từng service — không tự đi xoá thư mục, để mỗi service vẫn là
nơi duy nhất quyết định cái gì của mình là quá hạn.

## Vì sao 23h chứ không phải "mỗi 6 giờ"

Chu kỳ 6 giờ + TTL 2–4 giờ của từng service khiến file biến mất giữa giờ làm:
chạy ACH lúc 8h sáng, chiều quay lại tải báo cáo thì không còn gì, không thông
báo. Chính sách mới (27/08/2026): file sống hết ngày làm việc, 23h xoá sạch.

Mốc chung nằm ở `backend/core/don_dep.py`. Điểm mấu chốt: mọi hàm dọn đều lấy
"mốc 23h **gần nhất đã trôi qua**" làm ranh giới, nên chúng an toàn ở mọi thời
điểm được gọi — kể cả giữa request, kể cả ngay lúc backend vừa bật lúc 9h sáng
(khi đó ranh giới là 23h **hôm qua**, rác cũ bị dọn còn file sáng nay còn
nguyên).

## Vì sao không hẹn thẳng một `Timer` 24 tiếng

`threading.Timer` đếm theo thời gian trôi của tiến trình. Máy chủ ngủ/ngừng vài
tiếng là mốc trôi theo, càng ngày càng lệch khỏi 23h. Ở đây timer chỉ được đặt
tối đa `_TICK_TOI_DA` giây một lần và **giờ dọn thì tính lại từ đồng hồ** mỗi
lần thức dậy: sát 23h thì hẹn đúng số giây còn lại, xa thì ngủ 30 phút rồi kiểm
tra lại. Bỏ lỡ một mốc (máy tắt qua đêm) cũng không mất: lần thức đầu tiên sau
đó thấy `moc > _moc_da_don` là dọn bù ngay.
"""
import logging
import threading

from backend.core.don_dep import giay_toi_moc_ke_tiep, moc_don_gan_nhat

_log = logging.getLogger(__name__)

_TICK_TOI_DA = 30 * 60          # không ngủ liền một mạch quá 30 phút

# Ref timer toàn cục để có thể hủy khi test
_timer: threading.Timer | None = None
# Mốc 23h gần nhất ĐÃ dọn — chặn dọn lại nhiều lần trong cùng một mốc
_moc_da_don: float = 0.0


def run_cleanup(cutoff: float | None = None) -> None:
    """Gọi hàm dọn của từng service. Một service lỗi không được chặn service kia."""
    from backend.services import ach_service, cham459901_service
    from backend.services import doi_chieu_song_phuong_service as sp
    from backend.services.doi_soat_citad import temp_files as citad_tmp
    from backend.api import vb_format as vb_format_api

    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff
    for ten, ham in (
        ("ACH", ach_service._cleanup_old_jobs),
        ("Chấm 459901", cham459901_service._cleanup_old_results),
        ("Đối chiếu song phương", sp._cleanup_old_results),
        ("Đối soát CITAD", citad_tmp._cleanup_old_results),
        ("Chuẩn hoá văn bản", vb_format_api._don_file_cu),
    ):
        try:
            ham(cutoff)
        except Exception as exc:
            _log.error("Dọn thư mục tạm %s thất bại: %s", ten, exc, exc_info=True)


def _tick():
    """Tới mốc 23h mới thì dọn, rồi hẹn lần thức tiếp theo."""
    global _moc_da_don
    try:
        moc = moc_don_gan_nhat()
        if moc > _moc_da_don:
            _moc_da_don = moc
            run_cleanup(moc)
    finally:
        _schedule_next()


def _schedule_next():
    global _timer
    _timer = threading.Timer(min(giay_toi_moc_ke_tiep() + 1, _TICK_TOI_DA), _tick)
    _timer.daemon = True
    _timer.start()


def start_scheduler():
    """Gọi khi khởi động app: dọn rác của những ngày trước (nền) rồi canh 23h."""
    threading.Thread(target=_tick, daemon=True, name="temp-cleanup-init").start()


def stop_scheduler():
    global _timer
    if _timer:
        _timer.cancel()
        _timer = None
