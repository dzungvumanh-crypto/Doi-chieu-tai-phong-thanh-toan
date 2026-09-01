"""Mốc thời gian dùng chung cho việc dọn file tạm — mỗi ngày một lần lúc 23h.

Chính sách (chốt 27/08/2026, thay cho TTL 2–4 giờ trước đó): file người dùng
tải lên và kết quả sinh ra **sống hết ngày làm việc**, tới 23h thì xoá sạch. Ai
chạy lúc 8h sáng vẫn tải lại được kết quả lúc 4h chiều — thứ mà TTL 2 giờ cũ
lấy mất, và không ai đoán được vì sao file "tự biến mất".

Cả lịch dọn lẫn từng service đều quy về ĐÚNG MỘT con số ở đây: `moc_don_gan_nhat()`
trả về mốc 23h **gần nhất đã trôi qua**. Xoá "mọi thứ cũ hơn mốc đó" cho ra hành
vi đúng ở cả hai tình huống, không cần phân nhánh:

  * lúc 23:00:05 hôm nay  → mốc = 23:00 hôm nay  → xoá sạch mọi thứ trong ngày;
  * lúc backend khởi động 9h sáng → mốc = 23:00 hôm qua → dọn rác còn sót của
    hôm qua, KHÔNG đụng vào file người ta vừa tải lên sáng nay.

Vì thế các hàm `_cleanup_old_*()` vẫn được gọi ngay trong đường đi của request
(đầu `process_zip()`, `finally` của pipeline ACH) mà không còn nguy hiểm: chúng
không bao giờ xoá được file của phiên đang chạy cùng ngày.

Dùng giờ **local của máy chủ** (`time.time()` / `datetime.fromtimestamp`), không
dùng `_vn_now()`: vế còn lại của phép so sánh là `st_mtime` của file — đồng hồ
hệ thống. Trộn UTC+7 vào đây là so hai đồng hồ khác nhau, lệch đúng 7 tiếng.
`_vn_now()` là quy ước cho timestamp ghi vào DB, không phải cho mtime.
"""
import time
from datetime import datetime, timedelta

GIO_DON = 23   # 23h hằng ngày, giờ máy chủ


def moc_don_gan_nhat(bay_gio: float | None = None) -> float:
    """Epoch của mốc GIO_DON:00 gần nhất ĐÃ trôi qua."""
    now = datetime.fromtimestamp(time.time() if bay_gio is None else bay_gio)
    moc = now.replace(hour=GIO_DON, minute=0, second=0, microsecond=0)
    if moc > now:
        moc -= timedelta(days=1)
    return moc.timestamp()


def giay_toi_moc_ke_tiep(bay_gio: float | None = None) -> float:
    """Số giây từ giờ tới mốc GIO_DON:00 kế tiếp (luôn > 0)."""
    now = time.time() if bay_gio is None else bay_gio
    return moc_don_gan_nhat(now) + 24 * 3600 - now
