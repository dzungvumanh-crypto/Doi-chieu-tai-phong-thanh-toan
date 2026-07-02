"""Hằng số cấu hình cho pipeline Chấm ILO1000."""

# ── Tên cột sau khi chuẩn hóa (dùng trong toàn pipeline) ─────────────────────
HUB_COL_SO_GD      = 'Số giao dịch'
HUB_COL_SO_REF     = 'Số Ref Hub'
HUB_COL_STC        = 'STC'
HUB_COL_TRACE      = 'Trace'
HUB_COL_SO_TIEN    = 'Số tiền thực chuyển'
HUB_COL_TRANG_THAI = 'Trạng thái'
HUB_COL_NGAY_GIO   = 'Ngày giờ kênh trả'
HUB_COL_NOI_DUNG   = 'Nội dung chuyển tiền'

HUB_COLS_KEEP = [
    HUB_COL_SO_GD, HUB_COL_SO_REF, HUB_COL_STC, HUB_COL_TRACE,
    HUB_COL_SO_TIEN, HUB_COL_TRANG_THAI, HUB_COL_NGAY_GIO, HUB_COL_NOI_DUNG,
]

# Map tên cột thực tế trong file pHub → tên chuẩn của pipeline
# (pHub XLSX có title row ở row 0, header ở row 1)
HUB_COL_RENAME = {
    'Số giao dịch':      HUB_COL_SO_GD,
    'Số Ref Hub':        HUB_COL_SO_REF,
    'Số thành công':     HUB_COL_STC,      # STC
    'Số Trace 1':        HUB_COL_TRACE,    # Trace (col gốc từ pHub)
    'Số tiền thực chuyển': HUB_COL_SO_TIEN,
    'Trạng thái':        HUB_COL_TRANG_THAI,
    'Ngày giờ kênh trả': HUB_COL_NGAY_GIO,
    'Nội dung chuyển tiền': HUB_COL_NOI_DUNG,
}

# ── Tên cột CITAD (UUID CSVs) ─────────────────────────────────────────────────
CITAD_HEADER = ['ID', 'SERIAL_NO', 'RELATION_NO', 'O_CI_ID', 'R_CI_ID',
                'TRX_DATE', 'CI_CODE', 'CI_NAME', 'AMOUNT', 'TRX_STATUS', 'TELLERID']
CITAD_COLS_KEEP = ['SERIAL_NO', 'RELATION_NO', 'TRX_DATE', 'AMOUNT', 'TRX_STATUS']

# ── Tên cột GL02 / Core ───────────────────────────────────────────────────────
CORE_HEADER = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC',
               'CCY', 'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP',
               'REFERENCE', 'REMARK', 'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']

# ── Tên cột EICP (old XLS) ───────────────────────────────────────────────────
EICP_COL_BRCD   = 'BRCD'
EICP_COL_MSGKEY = 'MSGKEY'
EICP_COL_TRSEQ  = 'TRSEQ'

# ── TTL cleanup ───────────────────────────────────────────────────────────────
CLEANUP_TTL = 4 * 3600  # 4 giờ

# ── Giới hạn upload ───────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 1_000 * 1024 * 1024  # 1 GB
