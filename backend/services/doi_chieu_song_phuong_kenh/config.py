"""Cấu hình module Đối chiếu Song phương — Kênh↔Hub chiều ĐẾN.

Nguồn: tài liệu `đối chiếu kênh hub Song phương.docx` (Business Owner cung cấp 2026-08-22) +
kiểm chứng dữ liệu thật 21-23/08/2026 (2 vòng khảo sát read-only). Quyết định nghiệp vụ chốt
2026-08-25 — xem `docs/TU-DIEN-LENH-THANH-TOAN.md` mục 4.5 (cần viết lại theo thiết kế này).

Khác với module Phân loại dữ liệu (`doi_chieu_song_phuong_service.py`, đọc IPCAS/GL02) — module
này đọc 2 nguồn hoàn toàn khác: HUB (`doichieugd_*.zip`, export riêng cho đối chiếu song phương)
và KÊNH (Excel do ngân hàng đối tác gửi).
"""

# ─── Định tuyến file HUB theo mã ngân hàng ─────────────────────────────────────
# Số trong tên file `doichieugd_YYYYMMDD__NN_DEN_9999_N.zip` LÀ MÃ NGÂN HÀNG, KHÔNG
# phải 2 nguồn của cùng luồng (đã sửa giả định sai ở vòng khảo sát 1 — lúc đó tưởng
# "05"/"06" là 2 nguồn gộp chung). Mở rộng 201/311 sau chỉ cần thêm dòng vào đây.
HUB_FILE_CODE: dict[str, str] = {
    "201": "04",
    "202": "05",
    "203": "06",
    "311": "07",
}

# ─── Cột HUB (doichieugd_*.zip → CSV, 14 cột) ──────────────────────────────────
HUB_COLS = [
    "NGAY_GIAO_DICH", "CHI_NHANH", "REFHUB", "MSGREF", "MSGSEQ", "TXID",
    "KENH_THANH_TOAN", "TRANG_THAI_LENH", "SO_TIEN", "TRACE", "SESSION",
    "LOAI_LENH_OSB", "NH_GUI", "NOI_DUNG",
]
HUB_REQUIRED_COLS = {"MSGREF", "TXID", "KENH_THANH_TOAN", "TRANG_THAI_LENH", "SO_TIEN"}
HUB_AMOUNT_COL = "SO_TIEN"

# ─── Cột kênh (Excel đối tác NH, 5 cột) ────────────────────────────────────────
KENH_COLS = ["STT", "Ngày GD", "Giờ truyền nhận", "MtId/MsgId", "Số tiền"]
KENH_KEY_COL = "MtId/MsgId"
KENH_AMOUNT_COL = "Số tiền"

# ─── Nhận diện ngân hàng qua nội dung MtId/MsgId (chỉ SP REALTIME) ─────────────
# Nguồn: lyxink.txt (Business Owner, 2026-08-25) — 10 ký tự đầu MtId/MsgId là mã cố
# định theo NH, verify 100% trên dữ liệu thật 202/203 (xem TU-DIEN mục 4.5). Dùng để
# guard: phát hiện file kênh SPRT bị đặt/copy nhầm NH (đã xảy ra thật ở ngày 24.8 với
# 1 file hỏng — đây là lớp bảo vệ khác, cho trường hợp file lành nhưng sai NH).
# KHÔNG áp dụng cho SPT — khoá SPT là số tuần tự 16 chữ số, không có cấu trúc prefix
# theo NH quan sát được. 201/311 chưa verify (chưa có dữ liệu kênh SPRT thật).
KENH_MTID_PREFIX: dict[str, str] = {
    "201": "0200970415",
    "202": "0200970488",
    "203": "0200970436",
    "311": "0200970422",
}

# ─── Loại song phương ───────────────────────────────────────────────────────────
# SPRT = Song Phương Real Time (khoá MSGREF), SPT = Song Phương Thường (khoá TXID).
LOAI_KHOA_HUB = {"SPRT": "MSGREF", "SPT": "TXID"}
LOAI_KENH_THANH_TOAN = {"SPRT": "SP REALTIME", "SPT": "SP THUONG"}

# ─── Trạng thái đương nhiên một phía (hub-only hợp lệ, KHÔNG cảnh báo) ─────────
# Xác nhận bằng dữ liệu thật: 100% (277/277) dòng "chỉ-hub" 3 ngày mẫu đều là RJCT
# (lệnh bị từ chối không gửi tiếp sang kênh). Mọi trạng thái khác lọt vào "chỉ-hub"
# là tín hiệu cảnh báo cần điều tra, không mặc định coi là bình thường.
EXPECTED_ONE_SIDED_STATUSES = {"RJCT"}

# ─── Đơn vị đối chiếu ────────────────────────────────────────────────────────
# NH 203 và 311 KHÔNG có nghiệp vụ SPT — xác nhận trực tiếp từ chủ dự án (2026-08-25),
# cho CẢ 2 chiều (đến lẫn đi), khớp dữ liệu thật: không có file `kenh SPT ... 311 ...`
# trong bộ dữ liệu 201/311 cung cấp 2026-08-27 (thư mục `TRANG/`), dù bộ này CÓ đủ
# SPRT lẫn SPT cho NH 201. ĐÍNH CHÍNH so với ghi chú cũ ở đây ("SPT chỉ áp dụng NH
# 202") — nhận định đó dựa trên lúc chỉ mới có dữ liệu 202/203, ngoại suy quá rộng
# sang cả 201/311. Dữ liệu thật `kenh SPT den 201 24.8.xlsx` (15.781 dòng, cấu trúc
# đúng `KENH_COLS`) xác nhận 201 CÓ nghiệp vụ SPT — chỉ 203/311 là không có.
#
# Nếu sau này thấy file `kênh đến SPT 203.xlsx`/`kênh đến SPT 311.xlsx` xuất hiện,
# đó là bất thường cần hỏi lại, không phải "dữ liệu đã bổ sung, thêm đơn vị".
#
# Quyết định 2026-08-26 (chủ dự án): báo cáo KHÔNG hiển thị dòng SPT cho ngân hàng
# không có nghiệp vụ này (trước đó có dòng "N/A" tường minh qua `FULL_MATRIX_NOTE`,
# nay bỏ hẳn — đỡ rối bảng). `build_bang1_rows()` lặp qua đúng các đơn vị trong
# `RECONCILE_UNITS` — không còn ma trận N/A riêng.
RECONCILE_UNITS: list[dict] = [
    {"ma_nh": "201", "loai": "SPRT"},
    {"ma_nh": "201", "loai": "SPT"},
    {"ma_nh": "202", "loai": "SPRT"},
    {"ma_nh": "202", "loai": "SPT"},
    {"ma_nh": "203", "loai": "SPRT"},
    {"ma_nh": "311", "loai": "SPRT"},
]

# ─── Chiều — đợt này chỉ ĐẾN, chừa chỗ tham số hoá cho ĐI (chưa code logic ĐI) ──
CHIEU_DA_HO_TRO = ("DEN",)

# ─── Đối chiếu chi tiết chiều ĐẾN (Bước 1/2, tài liệu v3 27/08/2026) ───────────
# Thay hẳn thiết kế "Bảng 3" cũ (tổng hợp theo TRANG_THAI_LENH, duyệt Phase 9) — v3 yêu cầu gắn
# cột trạng thái vào TỪNG DÒNG của chính file kênh/hub gốc, xem process.py::classify_kenh_hub_den.
COT_TRANG_THAI_TAI_HUB = "TRẠNG THÁI TẠI HUB"   # thêm vào file kênh (Bước 1)
COT_TRANG_THAI_KENH = "TRẠNG THÁI KÊNH"          # thêm vào file hub (Bước 2)

NHAN_KENH_THUA = "KÊNH THỪA"                                          # Bước 1.2
NHAN_TRACE_HUY = "GD có trace hủy"                                    # Bước 2.1
NHAN_CHUYEN_TIEP = "GD chuyển tiếp"                                   # Bước 2.2
NHAN_TU_CHOI_KENH_KHONG_TC = "GD Đã từ chối-kênh không thành công"    # Bước 2.3
NHAN_KENH_THANH_CONG = "KÊNH THÀNH CÔNG"                              # Bước 2.4
NHAN_HUB_THUA = "HUB THỪA"                                            # Bước 2.5
