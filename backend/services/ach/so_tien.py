"""Đọc cột số tiền từ file ngoài (QT, MIS thừa T-2) thành int64.

Vì sao phải có riêng module này: `pd.to_numeric()` KHÔNG an toàn cho tiền định
dạng Việt Nam. '180.000' (180 nghìn đồng) parse ra 180.0 rất "hợp lệ", rồi
`.astype('int64')` cắt còn 180 — sai 1000 lần mà không báo lỗi, không NaN, không
dấu hiệu nào. Khóa đối chiếu có chứa số tiền sẽ lệch toàn bộ.

Luật (Business Owner chốt 2026-08-10 cho QT, 2026-08-11 cho MIS thừa T-2,
2026-08-21 bổ sung dấu phẩy):

- Số tiền là **số nguyên**, dấu chấm LUÔN là ngăn nghìn, không bao giờ là thập phân.
- VND luôn là số nguyên, không có phần thập phân — nên dấu phẩy ('180,000') cũng
  an toàn để coi là ngăn nghìn giống hệt dấu chấm, không có rủi ro nhầm với kiểu
  thập phân châu Âu (khác USD/EUR, nơi dấu phẩy có thể là thập phân).
- Luật gắn theo **NỘI DUNG ô**, KHÔNG theo đuôi file. Cùng một hàm dùng cho cả
  `.csv` lẫn `.xlsx` — vì người chấm hay mở `.csv` bằng Excel rồi lưu lại, dấu
  chấm đi theo sang `.xlsx`; luật gắn theo đuôi file sẽ hỏng im lặng đúng lúc đó.
- Mẫu lạ (VD '1.5') → **raise**, không đoán là 15 hay 1,5.
- Ô trống hoặc NaN (chưa hạch toán — VD dòng GL02 ghi Có thường bỏ trống cột
  Nợ) → coi là 0, KHÔNG raise. Giữ đúng hành vi `to_numeric(errors='coerce').
  fillna(0)` mà module này thay thế — module chỉ siết mẫu lạ có nội dung, chưa
  từng có ý định siết ô trống.
- Ô chỉ chứa dấu `-` → **VẪN raise** (KHÔNG thêm vào ô trống/0). Business Owner
  xác nhận 2026-08-31: `-` là bút toán đảo/huỷ hoặc điều chỉnh — có ý nghĩa
  nghiệp vụ thật, không phải "chưa hạch toán". Coi ngầm là 0 sẽ làm biến mất
  một giao dịch thật khỏi khoá đối chiếu mà không ai biết. Nếu sau này cần xử
  lý riêng dòng `-`, đó là quyết định ở TẦNG GỌI (phân loại/tách riêng bút toán
  đảo trước khi tới `doc_so_tien()`), không phải nới luật ở module này.
"""
import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

_RE_SO_THUAN        = re.compile(r'^-?\d+$')            # 180000
_RE_NGAN_NGHIN      = re.compile(r'^-?\d{1,3}(\.\d{3})+$')  # 180.000
_RE_NGAN_NGHIN_PHAY = re.compile(r'^-?\d{1,3}(,\d{3})+$')   # 180,000
_RE_DUOI_THAP_PHAN_0 = re.compile(r'^(-?\d+)\.0{1,2}$')     # "1000000.0"/"0.00" -> "1000000"/"0"
                                                              # CHỈ 1-2 số 0: đúng 3 số 0 ('.000') trùng
                                                              # cú pháp ngăn-nghìn hợp lệ ('180.000' = 180
                                                              # nghìn) — không được đụng, sẽ tái phát lỗi
                                                              # "sai 1000 lần, im lặng" đang cần chặn.
_O_TRONG             = {'', 'nan', 'None'}                  # rỗng / NaN sau astype(str)


class LoiDinhDangSoTien(ValueError):
    """Cột số tiền có (các) giá trị không đúng định dạng số nguyên VN.

    Tách khỏi ValueError trần để phân biệt được với ValueError nghiệp vụ khác
    (VD lỗi file xác nhận MIS_đi ở ach_service.py) — hai loại cần xử lý khác
    nhau khi pipeline đang chạy lại sau checkpoint."""


def _chuan_hoa_chuoi(sr: pd.Series) -> pd.Series:
    """Chuẩn hoá Series thành chuỗi trước khi validate regex.

    Bẫy thực nghiệm 2026-08-27: cột dtype float64 do pandas tự nâng kiểu
    (thường vì có NaN xen kẽ trong cột vốn toàn số nguyên, đọc từ Excel không
    ép dtype=str) khiến `.astype(str)` sinh đuôi '.0' (VD "1000000.0"), không
    khớp cả 3 mẫu số nguyên/ngăn-nghìn ở trên — hàm raise NHẦM dù input hợp lệ.
    Review PR#69 (khanhbq693): Excel định dạng tiền 2 số lẻ ('0.00',
    '150000.00') cũng gặp y hệt — mở rộng bỏ đuôi ĐÚNG 1 hoặc 2 số 0, KHÔNG mở
    rộng tới 3 số 0 trở lên: '180.000' (đúng 3 số 0) là ngăn-nghìn hợp lệ (180
    nghìn) theo _RE_NGAN_NGHIN, bỏ nhầm đuôi đó sẽ cắt về 180 — tái phát chính
    lỗi "sai 1000 lần, im lặng" mà module này được viết ra để chặn. Giá trị có
    phần thập phân khác 0 (VD "1000000.5", "1000000.50") không khớp, vẫn rơi
    vào nhánh raise/log như cũ (VND không có phần thập phân, phải báo lỗi)."""
    s = sr.astype(str).str.strip()
    return s.str.replace(_RE_DUOI_THAP_PHAN_0, r'\1', regex=True)


def doc_so_tien(sr: pd.Series, nguon: str, ten_cot: str = 'số tiền') -> pd.Series:
    """Trả về Series int64. `nguon`/`ten_cot` chỉ dùng cho thông báo lỗi/log."""
    # NaN/None bắt TRƯỚC khi ép chuỗi: với dtype 'str' (pandas >= 2.x, PDEP-14),
    # `.astype(str)` giữ nguyên NA thay vì đổi thành chuỗi 'nan' như dtype object
    # cũ — so khớp chuỗi sau khi ép kiểu bỏ sót ca này.
    trong_nan = sr.isna()
    s = _chuan_hoa_chuoi(sr)

    # ── Ô trống/NaN = chưa hạch toán → 0, không phải mẫu lạ ──
    trong = trong_nan | s.isin(_O_TRONG)
    if trong.any():
        logger.warning(
            "Cột %s (%s) có %d ô trống, coi là 0.", ten_cot, nguon, int(trong.sum())
        )
        s = s.mask(trong, '0')

    # ── Validate mẫu TRƯỚC, bỏ dấu ngăn nghìn SAU ──
    hop_le = (
        s.str.fullmatch(_RE_SO_THUAN)
        | s.str.fullmatch(_RE_NGAN_NGHIN)
        | s.str.fullmatch(_RE_NGAN_NGHIN_PHAY)
    )
    if not hop_le.all():
        la = sorted(set(s[~hop_le]))
        raise LoiDinhDangSoTien(
            f"Cột {ten_cot} có {int((~hop_le).sum()):,} giá trị không đúng định dạng số "
            f"nguyên (chấp nhận '180000', '180.000' hoặc '180,000'): {la[:5]} — {nguon}"
        )

    cleaned = s.str.replace('.', '', regex=False).str.replace(',', '', regex=False)
    return pd.to_numeric(cleaned).astype('int64')
