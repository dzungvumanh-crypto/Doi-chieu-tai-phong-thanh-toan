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
"""
import re

import pandas as pd

_RE_SO_THUAN        = re.compile(r'^-?\d+$')            # 180000
_RE_NGAN_NGHIN      = re.compile(r'^-?\d{1,3}(\.\d{3})+$')  # 180.000
_RE_NGAN_NGHIN_PHAY = re.compile(r'^-?\d{1,3}(,\d{3})+$')   # 180,000
_RE_DUOI_THAP_PHAN_0 = re.compile(r'^(-?\d+)\.0$')          # "1000000.0" -> "1000000"


def _chuan_hoa_chuoi(sr: pd.Series) -> pd.Series:
    """Chuẩn hoá Series thành chuỗi trước khi validate regex.

    Bẫy thực nghiệm 2026-08-27: cột dtype float64 do pandas tự nâng kiểu
    (thường vì có NaN xen kẽ trong cột vốn toàn số nguyên, đọc từ Excel không
    ép dtype=str) khiến `.astype(str)` sinh đuôi '.0' (VD "1000000.0"), không
    khớp cả 3 mẫu số nguyên/ngăn-nghìn ở trên — hàm raise NHẦM dù input hợp lệ.
    Chỉ bỏ đuôi khi phần thập phân đúng bằng 0; giá trị có phần thập phân khác
    0 (VD "1000000.5") không khớp, vẫn rơi vào nhánh raise/log như cũ (VND
    không có phần thập phân, phải báo lỗi)."""
    s = sr.astype(str).str.strip()
    return s.str.replace(_RE_DUOI_THAP_PHAN_0, r'\1', regex=True)


def doc_so_tien(sr: pd.Series, nguon: str, ten_cot: str = 'số tiền') -> pd.Series:
    """Trả về Series int64. `nguon`/`ten_cot` chỉ dùng cho thông báo lỗi."""
    s = _chuan_hoa_chuoi(sr)

    # ── Validate mẫu TRƯỚC, bỏ dấu ngăn nghìn SAU ──
    hop_le = (
        s.str.fullmatch(_RE_SO_THUAN)
        | s.str.fullmatch(_RE_NGAN_NGHIN)
        | s.str.fullmatch(_RE_NGAN_NGHIN_PHAY)
    )
    if not hop_le.all():
        la = sorted(set(s[~hop_le]))
        raise ValueError(
            f"Cột {ten_cot} có {int((~hop_le).sum()):,} giá trị không đúng định dạng số "
            f"nguyên (chấp nhận '180000', '180.000' hoặc '180,000'): {la[:5]} — {nguon}"
        )

    cleaned = s.str.replace('.', '', regex=False).str.replace(',', '', regex=False)
    return pd.to_numeric(cleaned).astype('int64')


def doc_so_tien_mem(sr: pd.Series, nguon: str, ten_cot: str = 'số tiền', log=None) -> pd.Series:
    """Biến thể KHÔNG raise của doc_so_tien() — dùng khi cột là thành phần
    khóa đối chiếu trên DataFrame hiển thị nguyên vẹn cho người chấm tay (VD
    AMOUNT/CRAMOUNT của ILO1000), nơi giữ nguyên SỐ DÒNG là bắt buộc (drop
    dòng sẽ làm lệch index/mất dòng khỏi sheet xuất — khác với lọc dữ liệu
    thô ở tầng load_*()). Dòng không khớp mẫu số nguyên hợp lệ ('180000',
    '180.000' hoặc '180,000' ngăn nghìn) → gán 0 (an toàn, không đoán) + log
    cảnh báo, thay vì raise cứng làm gián đoạn cả ngày đang chấm."""
    s = _chuan_hoa_chuoi(sr)
    hop_le = (
        s.str.fullmatch(_RE_SO_THUAN)
        | s.str.fullmatch(_RE_NGAN_NGHIN)
        | s.str.fullmatch(_RE_NGAN_NGHIN_PHAY)
    )
    if not hop_le.all() and log:
        n_bad = int((~hop_le).sum())
        mau = sorted(set(s[~hop_le]))[:5]
        log(f"[WARN] Cột {ten_cot} ({nguon}) có {n_bad:,} giá trị không đúng "
            f"định dạng số nguyên, gán 0 + cần kiểm tra tay: {mau}")
    cleaned = s.where(hop_le, '0').str.replace('.', '', regex=False).str.replace(',', '', regex=False)
    return pd.to_numeric(cleaned, errors='coerce').fillna(0).astype('int64')
