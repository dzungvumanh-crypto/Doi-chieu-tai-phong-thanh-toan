# -*- coding: utf-8 -*-
"""
test_doi_soat_citad_parsers.py
--------------------------------
Khoá lại `_parse_so_tien()` — bug thật phát hiện 25/08/2026 (Phòng Thanh
toán tự phát hiện qua xoá thử 1 dòng trong Excel): mở CSV IPCAS trong Excel
để xoá 1 dòng rồi lưu lại, Excel tự đổi số tiền ĐỦ LỚN (nhóm "cao"/IH)
sang định dạng khoa học ("5.53722E+11") khi lưu CSV — cách đọc cũ (xoá mọi
ký tự không phải chữ số) ghép chữ số còn lại thành số SAI HẲN
("55372211" thay vì 553722000000, đuôi "11" chính là số mũ "E+11").

Sửa lần đầu cũng có 1 bug: bắt theo BẤT KỲ dấu chấm nào (không riêng
khoa học) — vỡ ngay với số tiền CITAD dùng dấu chấm làm phân cách hàng
nghìn kiểu Việt Nam ("790.840" đồng bị hiểu nhầm thành số thập phân
790,84 rồi làm tròn ra 791). Test dưới đây khoá cả 2 lần sửa.
"""
from backend.services.doi_soat_citad import parsers
from backend.services.doi_soat_citad.parsers import _parse_ipcas_text, _parse_so_tien

_IPCAS_HEADER = (
    "NGAY_GIAO_DICH,CHI_NHANH,REFHUB,MSGREF,MSGSEQ,TXID,KENH_THANH_TOAN,"
    "TRANG_THAI_LENH,SO_TIEN,TRACE,SE_TRACE,SESSION,LOAI_LENH_OSB,NH_NHAN,"
    "MA_GIAO_DICH,NOI_DUNG,NGAY_KENH_TRA"
)


def _ipcas_di_row(msgref, trang_thai, so_tien=7000000):
    return (
        f"15/09/2026,4305,'260915200000004898256358,'{msgref},'LFO621328610,"
        f"'4305HUB181742,CITAD THAP,{trang_thai},{so_tien},203762902,203825784,,,"
        f"NH Quan doi Ha Noi,4305SMF2609150000005,\"VO XUAN LICH\",15/09/2026 14:21:02"
    )


def test_so_tien_thuong_co_dau_phay():
    assert _parse_so_tien("553,722,000,000") == 553722000000
    assert _parse_so_tien("790840500000") == 790840500000


def test_so_tien_khoa_hoc_ipcas_excel_doi_sang():
    """Bug thật 25/08/2026 — Excel tự đổi số tiền lớn sang dạng khoa học
    khi lưu lại CSV IPCAS. Đúng ca thật: '5.53722E+11' phải ra 553.722 tỷ,
    không phải '55372211' (đuôi 11 = số mũ E+11 bị ghép nhầm vào)."""
    assert _parse_so_tien("5.53722E+11") == 553722000000
    assert _parse_so_tien("7.90841e+11") == 790841000000


def test_so_tien_dau_cham_phan_cach_hang_nghin_kieu_viet_nam():
    """Regression thật của chính lần sửa đầu tiên (tự phát hiện ngay khi
    kiểm lại): số tiền CITAD dùng dấu CHẤM làm phân cách hàng nghìn kiểu
    Việt Nam, không phải số thập phân. Bắt nhầm theo dấu chấm sẽ hiểu
    "790.840" (790.840 đồng) thành số thập phân 790,84 rồi làm tròn ra
    791 — sai gấp cả nghìn lần. Chỉ được bắt theo dấu hiệu khoa học thật
    ('E'/'e'), không bắt theo dấu chấm nói chung."""
    assert _parse_so_tien("790.840") == 790840
    assert _parse_so_tien("252.121.572") == 252121572
    assert _parse_so_tien("1.000") == 1000


def test_so_tien_rong_hoac_khong_hop_le():
    assert _parse_so_tien("") == 0
    assert _parse_so_tien(None) == 0
    assert _parse_so_tien("0") == 0
    assert _parse_so_tien("   ") == 0


def test_ipcas_di_errc_khong_con_bi_loc_mat():
    """Bug thật (PR lịch sử 44, 15/09/2026, người dùng tự phát hiện + xác
    nhận nghiệp vụ 16/09/2026): lệnh Đi msgref '11418711' bị "hạch toán huỷ
    lỗi" (ERRC) tại IPCAS đúng lúc file được xuất — sau đó xử lý thủ công
    lại thành công, nhưng KEEP_DI trước đây không có ERRC nên dòng bị `continue`
    ngay lúc đọc file, không bao giờ tới được reconcile.py để so khớp — lệnh
    CITAD tương ứng rơi thành "Chỉ CITAD" giả dù IPCAS THẬT SỰ có bản ghi.
    Giờ phải được GIỮ LẠI (không tự động coi là khớp — reconcile.py sẽ tự
    xếp vào 'lech_trang_thai' vì ERRC không nằm trong VALID_DI)."""
    text = _IPCAS_HEADER + "\n" + _ipcas_di_row("11418711", "ERRC", so_tien=7000000)
    rows = _parse_ipcas_text(text, "HQTTTHA1_doichieugd_20260915__03_DI_9999_N.csv", "15/09/2026")
    assert len(rows) == 1
    assert rows[0]["msgref"] == "11418711"
    assert rows[0]["trang_thai"] == "ERRC"
    assert rows[0]["so_tien"] == 7000000


def test_ipcas_di_trang_thai_la_khong_nam_trong_keep_di_van_bi_loc():
    """Trạng thái hoàn toàn xa lạ (không phải ERRC vừa thêm, cũng không phải
    1 trong các mã đã xác nhận nghiệp vụ trước đó) vẫn phải bị lọc như cũ —
    chỉ thêm đúng ERRC, không nới lỏng bộ lọc rộng hơn ngoài ý định."""
    text = _IPCAS_HEADER + "\n" + _ipcas_di_row("99999999", "MA_LA_HOAN_TOAN", so_tien=1000)
    rows = _parse_ipcas_text(text, "HQTTTHA1_doichieugd_20260915__03_DI_9999_N.csv", "15/09/2026")
    assert rows == []


class _FakeWs:
    """Worksheet giả, đủ interface cell_value()/nrows/ncols giống
    _XlrdWs/_OpenpyxlWs trong parsers.py — dùng để test _extract_bank_group()
    không cần dựng file .xls thật."""

    def __init__(self, rows):
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = max((len(r) for r in rows), default=0)

    def cell_value(self, row, col):
        try:
            v = self._rows[row][col]
        except IndexError:
            return ''
        return v if v is not None else ''


def test_extract_bank_group_nhan_dien_dong_nhom():
    """Bug thật xác nhận dữ liệu 15/09/2026 (txid=10008309): file CITAD
    chiều Đến có dòng "tiêu đề nhóm ngân hàng gửi" dạng "<mã> - <tên>" xen
    kẽ với các khối giao dịch — parsers.py trước đây bỏ qua hoàn toàn."""
    ws = _FakeWs([['', '', '01203003 - Ngân hàng TMCP ABC', '', '', '']])
    assert parsers._extract_bank_group(ws, 0, 2) == '203003'


def test_extract_bank_group_ma_o_cot_lech():
    """Mã ngân hàng có thể nằm lệch 1 cột so với i_so_gd tuỳ dòng — xác
    nhận thực tế qua nhiều file mẫu."""
    ws = _FakeWs([['', "79204017 - NH Quan doi", '', '', '', '']])
    assert parsers._extract_bank_group(ws, 0, 2) == '204017'


def test_extract_bank_group_khong_nham_dong_giao_dich_thuong():
    ws = _FakeWs([['', '', '10008309', '', 'Chuyển có giá trị thấp', '']])
    assert parsers._extract_bank_group(ws, 0, 2) is None


def test_extract_bank_group_khong_nham_dong_tong_so_tien():
    # dong tong dang "<ma> - <so tien>" — khong co chu cai sau dau gach,
    # KHONG duoc nham thanh dong nhom (_RE_BANK_GROUP doi ky tu sau "-"
    # phai la chu, khong phai chu so).
    ws = _FakeWs([['', '', '01203003 - 500,000,000', '', '', '']])
    assert parsers._extract_bank_group(ws, 0, 2) is None


def test_nh_gui_ke_thua_qua_sheet_moi():
    """Test tích hợp — khoá lại đúng bug thật 16/09/2026 (txid=10009779,
    dòng 2 triệu): khi Crystal Reports chia 1 nhóm ngân hàng qua nhiều
    sheet, dòng ĐẦU TIÊN của sheet mới (chưa gặp dòng tiêu đề ngân hàng
    nào) vẫn phải mang đúng mã ngân hàng còn dang dở từ sheet TRƯỚC —
    không được coi là "chưa xác định" (rỗng). Gọi thẳng `_parse_sheet()`
    2 lần với CHUNG 1 `nh_gui_ref`, đúng cách `parse_citad_xls()` làm khi
    xử lý nhiều sheet trong 1 file — không cần dựng file .xls thật."""
    chieu_ref, cong_ref, ngay_ref, loai_tien_ref = [None], [None], [None], [None]
    nh_gui_ref = ['']

    # Sheet 0: header "...chuyển tiền đến..." để chieu='den', 1 dòng nhóm
    # ngân hàng (203002) rồi 1 giao dịch, KẾT THÚC sheet mà KHÔNG có dòng
    # nhóm nào khác sau đó (mô phỏng đúng "nhóm bị cắt ngang giữa sheet").
    ws0 = _FakeWs([
        ['', 'BÁO CÁO CHUYỂN TIỀN ĐẾN', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],
        ['', '', '203002 - Ngân hàng ABC', '', '', '', '', '', '', '', '', '', '', '', '', '', ''],
        ['', '', '10000001', '', '', 'Chuyển có giá trị thấp', '', '', '', '', '', '', '', '', '', '500.000', ''],
    ])
    rows0 = parsers._parse_sheet(ws0, 'test.xls', True, chieu_ref, cong_ref, ngay_ref,
                                  loai_tien_ref, nh_gui_ref)
    assert len(rows0) == 1
    assert rows0[0]['nh_gui'] == '203002'
    assert nh_gui_ref[0] == '203002'  # da ghi lai dung trang thai cuoi

    # Sheet 1: KHÔNG có dòng tiêu đề ngân hàng nào — dòng giao dịch đầu
    # tiên phải kế thừa đúng '203002' từ nh_gui_ref, không phải rỗng.
    ws1 = _FakeWs([
        ['', '', '10000002', '', '', 'Chuyển có giá trị thấp', '', '', '', '', '', '', '', '', '', '750.000', ''],
    ])
    rows1 = parsers._parse_sheet(ws1, 'test.xls', False, chieu_ref, cong_ref, ngay_ref,
                                  loai_tien_ref, nh_gui_ref)
    assert len(rows1) == 1
    assert rows1[0]['nh_gui'] == '203002'
