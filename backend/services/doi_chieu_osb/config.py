"""Cấu hình module Đối chiếu OSB — GL02 (IPCAS) <-> OSB chi tiết hạch toán.

Nguồn: `OSB - Hà note chấm.docx` + `TH - Note chấm OSB.docx` (`G:\\NGOC HA\\OSB file chấm gửi a
Dũng\\`) + verify dữ liệu thật 3 ngày (01/07, 31/07, 04/04/2026, TK 519910) trước khi viết module
này — xem `docs/Implementation-notes.html`.
"""

# ─── Tài khoản trung gian OSB ──────────────────────────────────────────────────
# "customer" = giá trị cột CUSTOMER trên GL02 dùng để lọc đúng dòng của tài khoản này.
# 519910: verify ĐẦY ĐỦ bằng dữ liệu thật 3 ngày (01/07, 31/07, 04/04/2026) — khớp 100% với
# file "hà chấm" ở offset=0.
# 519908: CHƯA có dữ liệu thật xác nhận — suy từ `TH - Note chấm OSB.docx` (tài liệu dùng TK này
# làm ví dụ minh hoạ cách chấm, không kèm số liệu thật để verify). Nếu giá trị "customer" sai,
# hậu quả là bộ lọc GL02 rỗng hoàn toàn (không có dòng nào), hiện rõ trong log
# "[GL02] sau lọc ...: 0 dòng" — không sai âm thầm — nhưng CẦN verify bằng dữ liệu thật trước khi
# dùng TK này trong sản xuất.
TAI_KHOAN = {
    "519910": {"customer": "1000-000000001"},
    "519908": {"customer": "1000-000000001"},
}

# ─── Cột bắt buộc GL02 (CSV bên trong ZIP GL02_{ngày}_{chi_nhánh}.zip) ─────────
GL02_REQUIRED_COLS = {
    "TRDATE", "LOCAC", "CCY", "CUSTOMER", "REFERENCE", "REMARK", "DRAMOUNT", "CRAMOUNT",
}
# Toàn bộ cột gốc muốn giữ lại khi xuất file chênh lệch phía GL02 (đúng thứ tự file gốc, không
# gồm CRTDTM — không cần cho người đọc kết quả chênh lệch).
GL02_EXPORT_COLS = [
    "TRDATE", "TRBRCD", "USERID", "JOURSEQ", "DYTRSEQ", "LOCAC", "CCY", "BUSCD", "UNIT", "TRCD",
    "CUSTOMER", "TRTP", "REFERENCE", "REMARK", "DRAMOUNT", "CRAMOUNT",
]

# Toàn bộ cột gốc muốn giữ lại khi xuất file chênh lệch phía OSB (28 cột nguyên bản của file
# `DULIEUCHITIETHACHTOAN_*.xlsx`/`load_osb_file()`, đúng khuôn file "hà chấm" thủ công) — WHITELIST
# (không phải blacklist): `export.py::_osb_export_df()` chỉ giữ đúng các cột trong danh sách này,
# nên các cột NỘI BỘ module tự tính thêm (`SO_TIEN_NUM`, `KHOA_C`, `LOAI_GIAO_DICH`, ...) tự động
# KHÔNG lọt ra file mà không cần nhớ liệt kê từng cột nội bộ mới vào 1 blacklist riêng (đã dính lỗi
# thật: `LOAI_GIAO_DICH` thêm sau nhưng quên thêm vào blacklist, lọt ra file Excel — review code
# phát hiện trước khi mở PR).
OSB_EXPORT_COLS = [
    "STT", "Kênh", "Mã dịch vụ", "Dịch vụ", "Chiều giao dịch", "Mã giao dịch", "IPCAS Trace",
    "Mã giao dịch gốc", "Seq", "CN thực hiện", "CN hạch toán", "TK ghi nợ", "TK ghi có",
    "Tài khoản chuyên thu", "Tiền tệ", "Số tiền", "Số bút toán OSB", "Ref nợ", "Ref có",
    "Ngày giao dịch", "Ngày tổng hợp", "Ngày hạch toán", "Nội dung giao dịch", "Kiểu giao dịch",
    "Mã GL tổng OSB", "Mã hạch toán tổng IPCAS", "Trạng thái hạch toán tổng IPCAS", "Mã lỗi",
]

CCY_VND = "VND"
# Bước 1 (2 note gốc): loại các dòng REFERENCE=1000OSB khỏi GL02 trước khi tính chênh lệch —
# đây là chính điện quyết toán OSB hàng ngày, không phải giao dịch cần đối chiếu từng dòng.
REFERENCE_LOAI_TRU = "1000OSB"

# ─── Số trace GL02 ──────────────────────────────────────────────────────────────
# "Số trace" = REMARK[SO_TRACE_START:SO_TRACE_END] (slice Python, 0-indexed) = ký tự thứ 2 đến
# thứ 7 (1-indexed), tức 6 ký tự. ⚠️ Note gốc (`OSB - Hà note chấm.docx`) viết "ký tự thứ 2 đến
# ký tự thứ 6" (5 ký tự) — ĐÃ VERIFY SAI 1 KÝ TỰ bằng dữ liệu thật (4 dòng mẫu từ 3 ngày khác
# nhau, khớp đúng "trace, tiền" trong file hà chấm chỉ khi dùng công thức 6 ký tự [1:7], không
# phải 5 ký tự [1:6]). Áp dụng CƠ HỌC bất kể REMARK có định dạng "[123456] ..." hay không (REMARK
# ngắn/khác định dạng thì Số trace chỉ là 1 chuỗi ký tự bất kỳ — không có ý nghĩa số trace thật,
# nhưng vẫn tính cơ học đúng công thức, không có nhánh đặc biệt).
SO_TRACE_START = 1
SO_TRACE_END = 7

# ─── Cột bắt buộc OSB (bổ sung, ngoài {"CN thực hiện", "Mã giao dịch", "Ngày hạch toán"} đã được
# `doi_chieu_song_phuong_core.load_osb.load_osb_file()` kiểm tra sẵn) ──────────
OSB_REQUIRED_COLS_BO_SUNG = {"IPCAS Trace", "TK ghi nợ", "TK ghi có", "Số tiền"}

# ─── Nhãn 2 case chênh lệch ─────────────────────────────────────────────────────
NHAN_CHENH_LECH_NO = "Chênh lệch Nợ"
NHAN_CHENH_LECH_CO = "Chênh lệch Có"

# QUAN TRỌNG — chiều cột OSB dùng cho mỗi case, ĐÃ VERIFY BẰNG DỮ LIỆU THẬT (3 ngày, TK 519910):
# case "Nợ" lọc OSB theo cột "TK ghi nợ" == mã tài khoản; case "Có" lọc theo "TK ghi có" == mã tài
# khoản (CÙNG TÊN case/cột, KHÔNG chéo).
#
# `OSB - Hà note chấm.docx` (đọc bằng python-docx, không suy đoán) có LỖI COPY-PASTE: đoạn hướng
# dẫn "Xác định các giao dịch chênh lệch nợ 519910" VÀ đoạn "...chênh lệch có 519910" đều viết
# giống hệt nhau "tại cột TK ghi nợ: chỉ lấy các dòng giao dịch có giá trị=519910" — tức bản thân
# note Hà không phân biệt được 2 case (khả năng cao là copy đoạn Nợ sang rồi quên sửa "ghi nợ"
# thành "ghi có" ở đoạn Có).
# `TH - Note chấm OSB.docx` viết RÕ RÀNG, không mơ hồ: "Chênh lệch Nợ - File OSB: chỉ lấy dữ liệu
# tại cột TK ghi Nợ", "Chênh lệch Có - File OSB: chỉ lấy dữ liệu tại cột TK ghi Có" — đúng công
# thức "cùng tên" ở trên.
# Verify độc lập bằng chính dữ liệu: 2 file `DULIEUCHITIETHACHTOAN_*.xlsx` cấp mỗi ngày luôn tách
# sẵn — 1 file 100% dòng "TK ghi nợ"=<TK trung gian>, file kia 100% dòng "TK ghi có"=<TK trung
# gian> (verify cả 3 ngày 01/07, 31/07, 04/04/2026). File "hà chấm" case "Có" luôn chứa dòng
# "TK ghi có"=<TK trung gian> — khớp đúng công thức "cùng tên".
# Test thực tế (spike, không đưa vào sản xuất): dùng công thức "cùng tên" khớp 100% (0 thừa/0
# thiếu) so với hà chấm cả 3 ngày; công thức "chéo" (như hiểu ban đầu từ note Hà bị lỗi) làm case
# Có ngày 01/07 bung ra 393 dòng "chênh lệch" giả thay vì 5 dòng thật.
COT_OSB_THEO_CASE = {
    NHAN_CHENH_LECH_NO: "TK ghi nợ",
    NHAN_CHENH_LECH_CO: "TK ghi có",
}
# Khoá A/B tương ứng phía GL02 cho mỗi case (xem load_gl02.py).
KHOA_GL02_THEO_CASE = {
    NHAN_CHENH_LECH_NO: "KHOA_CHENH_LECH_NO",   # SoTrace + CRAMOUNT (CRAMOUNT != 0)
    NHAN_CHENH_LECH_CO: "KHOA_CHENH_LECH_CO",   # SoTrace + DRAMOUNT (DRAMOUNT != 0)
}
