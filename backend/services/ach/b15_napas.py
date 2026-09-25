"""Mục 6/7 (bổ sung 11.09.2026 + 14.09.2026) — đối chiếu với báo cáo Napas
(BC.03 dạng PDF + CSV chi tiết ISS/BEN), độc lập với luồng GL02/MIS/GW chính.

Bước 0 (14.09.2026) — cấu trúc dòng "Tổng" của BC.03 được ĐO trên dữ liệu thật 3
ngày (04.09/05.09/06.09.2026, `G:\\NGUYEN TAC DOI CHIEU ACH\\04-06.09\\`) bằng
`pypdfium2`, KHÔNG đoán theo mắt. Dòng bắt đầu bằng "Tổng " (phân biệt với nhãn
cột "Tổng phí"/"Tổng cộng" — không có số theo sau) luôn trích được ĐÚNG 18 số theo
thứ tự cố định, giống nhau cả 3 ngày:

    [0]=SL Ghi nợ        [1]=Giá trị Ghi nợ   [2]=Phí DV TCNL (Ghi nợ)
    [3]=Phí chia sẻ TCNL (Ghi nợ)              [4]=Phí DV TCPL (Ghi nợ, =0 trong mẫu)
    [5]=Phí chia sẻ TCPL (Ghi nợ, =0)          [6]=Tổng phí Ghi nợ (=[2]+[3]+[4]+[5])
    [7]=Tổng cộng Ghi nợ (=[1]+[6])            [8]=SL Ghi có
    [9]=Giá trị Ghi có   [10..14]=phí Ghi có (=0 trong mẫu)
    [15]=Tổng cộng Ghi có (=[9]+tổng [10..14]) [16]=Napas hưởng phí   [17]=Tổng phí

VD thật ngày 04.09.2026 (đối chiếu với số Business Owner đọc trực tiếp từ bản
render PDF TRƯỚC khi viết code trích số này):
    [0]=533,896  [1]=3,081,559,142,449  [8]=569,337  [9]=3,593,883,470,596
    → khớp đúng SL/Giá trị Ghi nợ + Ghi có đã biết trước, và tự kiểm chứng
      [1]+[6] = 3,081,559,142,449 + 95,125,646 = 3,081,654,268,095 = [7]  ✓

Ghi nợ = chiều ĐI, Ghi có = chiều ĐẾN (Business Owner xác nhận). "Ghi nợ" ở đây là
nhãn cột báo cáo Napas, KHÔNG liên quan CRAMOUNT/DRAMOUNT của GL02 (b2_xu_ly_gl02.py)
— hai hệ tọa độ khác nhau, đừng nhầm lẫn khi đọc code.

CSV chi tiết ISS (chiều đi)/BEN (chiều đến): cột '001' phân biệt dòng giao dịch
thật ('002') với dòng trailer/checksum cuối file ('003' — MsgId rỗng, không phải
giao dịch). Đã xác minh trên dữ liệu thật 04.09 VÀ 05.09: lọc '001'=='002' cho ra
ĐÚNG số dòng bằng SL Ghi nợ/Ghi có đọc từ PDF cùng ngày (VD ISS 04.09: 533,896
dòng '002' = đúng SL Ghi nợ PDF; BEN 04.09: 569,337 dòng '002' = đúng SL Ghi có
PDF) — không lọc sẽ lẫn 1 dòng trailer NaN vào đối chiếu, hiện thành 1 "Napas thừa"
giả không có ý nghĩa nghiệp vụ.

Đối chiếu MsgId (Napas CSV) với MSGREF (GW) tái dùng `_doi_chieu()` (đối chiếu
theo count, vectorized) từ b5_doi_chieu_di.py — KHÔNG viết thuật toán khớp mới.
"""
import os
import re

import pandas as pd
import pypdfium2 as pdfium

from .b5_doi_chieu_di import _doi_chieu

_RE_DONG_TONG = re.compile(r'^Tổng\s+\d')
_SO_LUONG_SO_KY_VONG = 18  # đo được trên 3 ngày dữ liệu thật, xem docstring module


def _doc_full_text_pdf(pdf_path: str) -> str:
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        parts = []
        for i in range(len(pdf)):
            page = pdf[i]
            tp = page.get_textpage()
            try:
                parts.append(tp.get_text_range())
            finally:
                tp.close()
            page.close()
        return '\n'.join(parts)
    finally:
        pdf.close()


def doc_pdf_napas(pdf_path: str) -> dict:
    """Mục 6 (bổ sung 11.09.2026) — trích Tổng SL/Giá trị Ghi nợ (chiều đi) và Ghi
    có (chiều đến) từ báo cáo Napas BC.03. Trả về dict
    {'n_di': int, 's_di': int, 'n_den': int, 's_den': int}. Raise ValueError với
    thông báo rõ ràng nếu không tìm thấy đúng 1 dòng 'Tổng', số lượng số trích
    được khác 18 (cấu trúc đã đổi), hoặc đẳng thức tự kiểm chứng sai lệch — không
    được âm thầm trả số sai."""
    full_text = _doc_full_text_pdf(pdf_path)

    dong_tong = [
        line for line in full_text.splitlines()
        if _RE_DONG_TONG.match(line.strip())
    ]
    if not dong_tong:
        raise ValueError(
            f"[B15][Mục 6] Không tìm thấy dòng 'Tổng <số>' trong báo cáo Napas: "
            f"{pdf_path} — cấu trúc PDF có thể đã đổi, KHÔNG đoán tiếp."
        )
    if len(dong_tong) > 1:
        raise ValueError(
            f"[B15][Mục 6] Tìm thấy {len(dong_tong)} dòng 'Tổng <số>' trong {pdf_path} "
            f"— không rõ dòng nào là dòng tổng thật, cần người kiểm tra: {dong_tong}"
        )

    nums_raw = re.findall(r'\d[\d,]*', dong_tong[0].strip())
    nums = [int(n.replace(',', '')) for n in nums_raw]
    if len(nums) != _SO_LUONG_SO_KY_VONG:
        raise ValueError(
            f"[B15][Mục 6] Dòng 'Tổng' trong {pdf_path} có {len(nums)} số, kỳ vọng "
            f"{_SO_LUONG_SO_KY_VONG} (đo được trên dữ liệu thật 04-06.09.2026) — cấu "
            f"trúc báo cáo đã đổi, KHÔNG tin index cố định nữa: {dong_tong[0]!r}"
        )

    n_di, s_di           = nums[0], nums[1]
    tong_phi_no, tong_cong_no = nums[6], nums[7]
    n_den, s_den          = nums[8], nums[9]

    # Tự kiểm chứng an toàn — Giá trị Ghi nợ + Tổng phí Ghi nợ phải = Tổng cộng Ghi
    # nợ (đúng cho cả 3 ngày kiểm tra thật). Sai lệch nghĩa là index đã lệch khỏi
    # cấu trúc đo được — KHÔNG được tin mù số vừa trích, raise ngay.
    if s_di + tong_phi_no != tong_cong_no:
        raise ValueError(
            f"[B15][Mục 6] Tự kiểm chứng thất bại trong {pdf_path}: Giá trị Ghi nợ "
            f"({s_di:,}) + Tổng phí Ghi nợ ({tong_phi_no:,}) = {s_di + tong_phi_no:,} "
            f"!= Tổng cộng Ghi nợ ({tong_cong_no:,}) — index có thể đã lệch khỏi cấu "
            f"trúc đo được, KHÔNG tin số vừa trích."
        )

    return {'n_di': n_di, 's_di': s_di, 'n_den': n_den, 's_den': s_den}


def doc_napas_csv(path: str, log_callback=None) -> pd.DataFrame:
    """Mục 7 (bổ sung 14.09.2026) — đọc CSV Napas chi tiết (ISS hoặc BEN), sep=';',
    dtype=str, encoding utf-8-sig. Lọc bỏ dòng trailer/checksum cuối file (cột
    '001'=='003', MsgId rỗng — không phải giao dịch, xem docstring module) khi có
    cột '001'. Bóc dấu nháy đơn đầu MsgId nếu có (phòng thủ)."""
    _log = log_callback or print
    df = pd.read_csv(path, sep=';', dtype=str, encoding='utf-8-sig')

    if '001' in df.columns:
        n_truoc = len(df)
        df = df[df['001'] == '002'].copy()
        n_bo = n_truoc - len(df)
        if n_bo:
            _log(f"[B15][Mục 7] {os.path.basename(path)}: bỏ {n_bo} dòng trailer/checksum "
                 f"(cột '001' != '002'), giữ {len(df):,} dòng giao dịch thật.")

    if 'MsgId' not in df.columns:
        raise ValueError(f"[B15][Mục 7] File CSV Napas thiếu cột 'MsgId': {path}")

    # Bẫy thực nghiệm 14.09.2026 — dữ liệu thật BEN 04.09 có 2 dòng giao dịch thật
    # (cột '001'=='002') nhưng MsgId RỖNG (lỗi dữ liệu nguồn, không phải trailer).
    # Ô rỗng trong CSV đọc bằng dtype=str vẫn ra NaN (float), KHÔNG phải chuỗi rỗng.
    # `.astype(str)` trên NaN cho ra chuỗi literal 'nan' (không phải NA nữa) — nên
    # `fillna('')` phải chạy TRƯỚC `.astype(str)`, không phải sau (đã tự đo, khác
    # với so_tien.py::_chuan_hoa_chuoi ở cột số tiền). Nếu để NA lọt vào
    # _doi_chieu(), groupby() mặc định dropna=True khiến cc (cumcount) của các dòng
    # đó là NaN → so sánh `NaN < 0` VÀ `NaN >= 0` đều ra False → dòng biến mất khỏi
    # CẢ df_khop LẪN df_napas_thua, không có lỗi nào báo (đã đo được: BEN 04.09 mất
    # đúng 2 dòng theo cách này trước khi sửa thứ tự fillna). '' không bao giờ
    # trùng MSGREF thật bên GW nên các dòng này rơi đúng vào "Napas thừa".
    n_msgid_rong = df['MsgId'].isna().sum()
    if n_msgid_rong:
        _log(f"[B15][Mục 7] {os.path.basename(path)}: {n_msgid_rong} dòng giao dịch "
             f"thật có MsgId RỖNG (lỗi dữ liệu nguồn) — giữ lại, sẽ hiện ở Napas thừa "
             f"vì không thể khớp MSGREF nào.")
    df['MsgId'] = df['MsgId'].fillna('').astype(str).str.strip().str.lstrip("'")

    return df.reset_index(drop=True)


def doi_chieu_napas_gw(df_napas_csv: pd.DataFrame, df_gw: pd.DataFrame, gw_key_col: str,
                       log_callback=None):
    """Mục 7 — đối chiếu MsgId (Napas CSV chi tiết) với cột khoá trên GW
    (`gw_key_col` — 'MSGREF' cho cả 2 chiều, nhưng `df_gw` khác nhau tuỳ chiều: GW
    đi thô (đầu ra `xu_ly_gw()`, b3_xu_ly_gw.py) cho chiều đi, GW đến (đầu ra Mục 4,
    b13_xu_ly_gw_den.py) cho chiều đến). Tái dùng `_doi_chieu()` (đối chiếu theo
    count, vectorized) từ b5_doi_chieu_di.py — KHÔNG viết thuật toán khớp mới.

    Trả về (df_khop, df_napas_thua, df_gw_thua):
    - df_khop        — phía Napas CSV của các dòng khớp đúng (giữ nguyên cột chi
                        tiết Napas — cùng quy ước với doi_chieu_gw_den() trả về
                        phía nhiều thông tin hơn).
    - df_napas_thua   — dòng Napas CSV không có MSGREF tương ứng bên GW.
    - df_gw_thua      — dòng GW không có MsgId tương ứng bên Napas CSV.
    """
    _log = log_callback or print
    gw_khop, napas_khop, gw_thua, napas_thua = _doi_chieu(
        df_gw, gw_key_col, df_napas_csv, 'MsgId', 'B15-NAPAS', log_callback,
    )
    _log(f'[B15][Mục 7] Khớp: {len(napas_khop):,} | Napas thừa: {len(napas_thua):,} | '
         f'GW thừa: {len(gw_thua):,}')
    return (
        napas_khop.reset_index(drop=True),
        napas_thua.reset_index(drop=True),
        gw_thua.reset_index(drop=True),
    )
