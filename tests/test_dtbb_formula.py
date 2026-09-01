"""Test công thức tính DTBB (backend/services/dtbb/calculator.py, reader.py).

Trọng tâm: công thức quy đổi tỷ giá bsrt(ngoại tệ)/ttbuyrt(USD) + fallback taxrt,
và lỗi thật đã bắt được khi viết module này — USD tự nhân với bsrt(USD)/ttbuyrt(USD)
(~1,0073) do thiếu nhánh riêng cho USD trong vòng lặp calculate(). Test này khoá lại
để không tái diễn nếu ai sửa lại calculate() sau này.
"""
import xlrd
import pytest

from backend.services.dtbb.calculator import (
    calculate, calculate_from_uploads, compute_native_groups, _rate_to_vnd, _rate_usd_to_vnd,
    _merge_9999_minus_9300,
)
from backend.services.dtbb.reader import (
    DtbbFileError, extract_report_date_and_branch, read_balance_file, read_tygia_file,
    BALANCE_HEADER,
)


# ── compute_native_groups ──────────────────────────────────────────────────────

def test_nhom_tai_khoan_group1_group2_tk413():
    """Mọi mã trong EXCL_423/EXCL_431 ĐỀU là thành viên của GROUP1 (thiết kế cố ý —
    đếm 1 lần ở group1 qua danh mục con chi tiết, rồi trừ ra khỏi phần dư 423/431
    tổng hợp để không đếm đôi cùng 1 số dư ở cả 2 nhóm)."""
    balances = {
        "401": 100.0,       # GROUP1 (không thuộc EXCL nào)
        "421202": 30.0,     # GROUP2_DIRECT
        "423": 1000.0, "423808": 200.0,  # 423808: vừa ở GROUP1, vừa ở EXCL_423
        "431": 500.0,       # không có mã con nào bị trừ — cộng nguyên vào group2
        "413": 77.0,
        "999999": 999.0,    # tài khoản ngoài danh mục — phải bị bỏ qua
    }
    g1, g2, tk413 = compute_native_groups(balances)
    assert g1 == 300.0  # 401(100) + 423808(200, đếm ở GROUP1)
    # GROUP2_DIRECT(30) + (423 - 423808 = 1000-200=800, KHÔNG đếm lại 423808) + (431-0=500)
    assert g2 == 30.0 + 800.0 + 500.0
    assert tk413 == 77.0


def test_tai_khoan_khong_co_trong_balance_mac_dinh_0():
    g1, g2, tk413 = compute_native_groups({})
    assert (g1, g2, tk413) == (0.0, 0.0, 0.0)


# ── _rate_to_vnd / _rate_usd_to_vnd — fallback taxrt ──────────────────────────

def test_rate_to_vnd_uu_tien_bsrt():
    assert _rate_to_vnd({"ttbuyrt": 100, "bsrt": 200, "taxrt": 300}) == 200

def test_rate_to_vnd_fallback_taxrt_khi_bsrt_0():
    assert _rate_to_vnd({"ttbuyrt": 100, "bsrt": 0, "taxrt": 300}) == 300

def test_rate_to_vnd_ca_hai_deu_0():
    assert _rate_to_vnd({"ttbuyrt": 100, "bsrt": 0, "taxrt": 0}) == 0

def test_rate_usd_to_vnd_uu_tien_ttbuyrt():
    assert _rate_usd_to_vnd({"ttbuyrt": 26110, "bsrt": 26300, "taxrt": 26300}) == 26110

def test_rate_usd_to_vnd_fallback_taxrt_khi_ttbuyrt_0():
    assert _rate_usd_to_vnd({"ttbuyrt": 0, "bsrt": 26300, "taxrt": 26300}) == 26300


# ── calculate() — công thức đầy đủ ─────────────────────────────────────────────

def _rates(ttbuyrt, bsrt, taxrt=0):
    return {"ttbuyrt": ttbuyrt, "bsrt": bsrt, "taxrt": taxrt}


def test_usd_khong_bi_tu_nhan_voi_ty_gia_cua_chinh_no():
    """Regression: bản vá trước bỏ sót nhánh riêng cho USD trong vòng lặp, khiến USD
    tự nhân với bsrt(USD)/ttbuyrt(USD) != 1 — phát hiện thật khi đối chiếu số liệu
    tay của kế toán (lệch ~0,73%, không phải sai số làm tròn)."""
    balances = [("USD", {"401": 1_000_000.0, "421202": 500_000.0})]
    tygia = {"USD": _rates(ttbuyrt=26110, bsrt=26300)}  # 2 cột khác nhau, cố ý
    r = calculate(balances, tygia, "2026-07-31", "9999")
    assert r.usd_duoi12 == 1_000_000.0   # cộng thẳng, KHÔNG nhân qua tỷ giá
    assert r.usd_tu12 == 500_000.0
    assert r.unconverted_ccy == []


def test_ngoai_te_dung_bsrt_chia_ttbuyrt_usd():
    balances = [
        ("USD", {"401": 0.0}),
        ("EUR", {"401": 10_000.0, "421202": 2_000.0}),
    ]
    tygia = {
        "USD": _rates(ttbuyrt=26110, bsrt=26300),
        "EUR": _rates(ttbuyrt=29632, bsrt=30228.5),
    }
    r = calculate(balances, tygia, "2026-07-31", "9999")
    expected_rate = 30228.5 / 26110
    assert r.usd_duoi12 == pytest.approx(10_000.0 * expected_rate)
    assert r.usd_tu12 == pytest.approx(2_000.0 * expected_rate)


def test_vnd_khong_quy_doi_gop_tk413_vao_duoi_12():
    balances = [("VND", {"401": 100.0, "421202": 50.0, "413": 7.0})]
    tygia = {"USD": _rates(ttbuyrt=26110, bsrt=26300)}
    r = calculate(balances, tygia, "2026-07-31", "9999")
    assert r.vnd_duoi12 == 107.0  # 100 + tk413(7), KHÔNG nhân tỷ giá
    assert r.vnd_tu12 == 50.0
    assert r.usd_duoi12 == 0.0


def test_ma_tien_khong_co_ty_gia_nao_bi_liet_vao_unconverted_khong_crash():
    """KHR nhiều kỳ thật có ttbuyrt=bsrt=taxrt=0 — không được chặn cả phép tính,
    chỉ bỏ qua đúng mã đó, các mã khác vẫn tính đúng."""
    balances = [
        ("USD", {"401": 0.0}),
        ("KHR", {"401": 1_000_000.0}),
        ("EUR", {"401": 5_000.0}),
    ]
    tygia = {
        "USD": _rates(ttbuyrt=26110, bsrt=26300),
        "KHR": _rates(ttbuyrt=0, bsrt=0, taxrt=0),
        "EUR": _rates(ttbuyrt=29632, bsrt=30228.5),
    }
    r = calculate(balances, tygia, "2026-07-31", "9999")
    assert r.unconverted_ccy == ["KHR"]
    assert r.usd_duoi12 == pytest.approx(5_000.0 * 30228.5 / 26110)  # chỉ EUR đóng góp
    # KHR vẫn có mặt trong details (rate=None) để FE biết có số dư nhưng chưa quy đổi
    khr_detail = next(d for d in r.details if d.ccy == "KHR")
    assert khr_detail.rate_to_vnd is None
    assert khr_detail.group1_native == 1_000_000.0


def test_khr_fallback_taxrt_khi_bsrt_0_nhung_taxrt_co_gia_tri():
    balances = [("USD", {"401": 0.0}), ("KHR", {"401": 1_000_000.0})]
    tygia = {
        "USD": _rates(ttbuyrt=26110, bsrt=26300),
        "KHR": _rates(ttbuyrt=0, bsrt=0, taxrt=6.5),
    }
    r = calculate(balances, tygia, "2026-07-31", "9999")
    assert r.unconverted_ccy == []
    assert r.usd_duoi12 == pytest.approx(1_000_000.0 * 6.5 / 26110)


def test_usd_hoan_toan_khong_co_ty_gia_thi_raise():
    """Khác KHR (mã tiền phụ) — nếu chính USD (đơn vị đích) không có tỷ giá nào,
    không còn cơ sở quy đổi bất kỳ mã tiền nào khác, phải chặn cứng."""
    balances = [("EUR", {"401": 100.0})]
    tygia = {"USD": _rates(ttbuyrt=0, bsrt=0, taxrt=0), "EUR": _rates(ttbuyrt=29632, bsrt=30228.5)}
    with pytest.raises(DtbbFileError, match="tỷ giá USD"):
        calculate(balances, tygia, "2026-07-31", "9999")


def test_hai_file_cung_ma_tien_bi_chan():
    balances = [("USD", {"401": 1.0}), ("USD", {"401": 2.0})]
    tygia = {"USD": _rates(ttbuyrt=26110, bsrt=26300)}
    with pytest.raises(DtbbFileError, match="2 file"):
        calculate(balances, tygia, "2026-07-31", "9999")


# ── extract_report_date_and_branch — tách mã chi nhánh từ tên file ────────────

def test_tach_chi_nhanh_co_prefix():
    d, b = extract_report_date_and_branch("1200USD20260720.XLS", "USD")
    assert d == "2026-07-20"
    assert b == "1200"


def test_tach_chi_nhanh_khong_co_prefix_mac_dinh_9999():
    d, b = extract_report_date_and_branch("USD20260731.XLS", "USD")
    assert d == "2026-07-31"
    assert b == "9999"


def test_tach_chi_nhanh_khong_khop_ma_tien_bao_loi():
    with pytest.raises(DtbbFileError):
        extract_report_date_and_branch("1200EUR20260720.XLS", "USD")  # ccy thật là USD, tên file lại EUR


# ── _merge_9999_minus_9300 — chi nhánh 9999 trừ đi chi nhánh 9300 ─────────────
# Nghiệp vụ xác nhận 2026-08-27: file cân đối không mã (9999) upload CHUNG 1 lượt
# với file cùng mã tiền có tiền tố 9300 → số 9999 thật = 9999 - 9300, trừ ĐÚNG THEO
# TỪNG DÒNG tài khoản (Acctcd), không phải trừ tổng cuối cùng.

def _entry(ccy, balances, branch_code, filename=None):
    return (ccy, balances, "2026-07-31", branch_code, filename or f"{branch_code}{ccy}.XLS")


def test_tru_9300_dung_theo_tung_dong_tai_khoan():
    entries = [
        _entry("USD", {"401": 1000.0, "421202": 500.0}, "9999"),
        _entry("USD", {"401": 200.0, "421202": 100.0}, "9300"),
    ]
    merged, netted = _merge_9999_minus_9300(entries)
    assert netted == ["USD"]
    assert dict(merged) == {"USD": {"401": 800.0, "421202": 400.0}}


def test_tai_khoan_chi_co_o_9300_ra_am_sau_khi_tru():
    """Tài khoản '421202' chỉ có ở file 9300 (không có ở 9999) — coi phía 9999 = 0,
    kết quả dòng đó thành số ÂM. Đây là hệ quả đúng của phép trừ theo dòng."""
    entries = [
        _entry("EUR", {"401": 100.0}, "9999"),
        _entry("EUR", {"401": 30.0, "421202": 50.0}, "9300"),
    ]
    merged, netted = _merge_9999_minus_9300(entries)
    balances = dict(merged)["EUR"]
    assert balances["401"] == 70.0
    assert balances["421202"] == -50.0


def test_ma_tien_chi_co_9999_khong_bi_tru():
    entries = [
        _entry("USD", {"401": 1000.0}, "9999"),
        _entry("JPY", {"401": 500.0}, "9999"),  # không có JPY ở 9300
        _entry("USD", {"401": 100.0}, "9300"),
    ]
    merged, netted = _merge_9999_minus_9300(entries)
    d = dict(merged)
    assert d["JPY"] == {"401": 500.0}  # giữ nguyên, không trừ
    assert netted == ["USD"]  # chỉ USD bị trừ, JPY không có mặt trong danh sách


def test_ma_tien_chi_co_9300_khong_co_9999_bao_loi():
    entries = [
        _entry("USD", {"401": 1000.0}, "9999"),
        _entry("GBP", {"401": 50.0}, "9300"),  # không có GBP ở 9999 — không có gì để trừ vào
    ]
    with pytest.raises(DtbbFileError, match="9300"):
        _merge_9999_minus_9300(entries)


def test_trung_ma_tien_cung_chi_nhanh_bao_loi():
    entries = [
        _entry("USD", {"401": 1000.0}, "9999", "a.XLS"),
        _entry("USD", {"401": 999.0}, "9999", "b.XLS"),
    ]
    with pytest.raises(DtbbFileError, match="2 file"):
        _merge_9999_minus_9300(entries)


def test_calculate_full_pipeline_voi_ket_qua_da_tru_9300():
    """Ghép _merge_9999_minus_9300 + calculate() — mô phỏng đúng đường đi thật của
    calculate_from_uploads() khi gặp cặp chi nhánh {9999, 9300}."""
    entries = [
        _entry("USD", {"401": 1_000_000.0}, "9999"),
        _entry("USD", {"401": 200_000.0}, "9300"),
        _entry("EUR", {"401": 10_000.0}, "9999"),  # không có EUR ở 9300 — giữ nguyên
    ]
    merged, netted = _merge_9999_minus_9300(entries)
    tygia = {
        "USD": {"ttbuyrt": 26110, "bsrt": 26300, "taxrt": 0},
        "EUR": {"ttbuyrt": 29632, "bsrt": 30228.5, "taxrt": 0},
    }
    r = calculate(merged, tygia, "2026-07-31", "9999")
    assert r.netted_9300_ccy == []  # calculate() không tự set field này — do calculate_from_uploads gán
    assert r.usd_duoi12 == 800_000.0 + 10_000.0 * 30228.5 / 26110  # USD đã trừ 9300 + EUR quy đổi nguyên


def test_tach_chi_nhanh_thieu_ngay_bao_loi():
    with pytest.raises(DtbbFileError):
        extract_report_date_and_branch("USD.XLS", "USD")


# ── read_balance_file / read_tygia_file — giả lập xlrd, không cần file .XLS thật ─

class _FakeSheet:
    def __init__(self, rows):
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = len(rows[0]) if rows else 0

    def cell_value(self, r, c):
        return self._rows[r][c]


class _FakeWorkbook:
    def __init__(self, rows, datemode=0):
        self._sheet = _FakeSheet(rows)
        self.datemode = datemode

    def sheet_by_index(self, i):
        return self._sheet


def _fake_open_workbook(rows):
    return lambda file_contents=None, **kw: _FakeWorkbook(rows)


def test_read_balance_file_chuan_hoa_ccy_thuong_thanh_hoa(monkeypatch):
    """File nguồn ghi mã tiền thường ('vnd') vẫn phải khớp so sánh case-sensitive
    'VND' ở calculator.py — .upper() phải chạy đúng."""
    row_data = [0] * len(BALANCE_HEADER)
    col_ccy, col_code, col_cr = (BALANCE_HEADER.index(c) for c in ("ccy", "Acctcd", "afterbal_cr"))
    row_data[col_ccy], row_data[col_code], row_data[col_cr] = "vnd", "401", 1_000_000.0
    rows = [BALANCE_HEADER, row_data]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    ccy, balances = read_balance_file(b"", "VND20260715.XLS")
    assert ccy == "VND"
    assert balances["401"] == 1_000_000.0


def test_read_balance_file_acctcd_dang_so_khong_bi_mat_dong():
    """Excel lưu Acctcd dạng số (xlrd trả float 401.0) — phải quy về '401', không phải
    '401.0' (chuỗi này sẽ không khớp danh mục tài khoản hardcode, dòng bị bỏ sót âm thầm)."""
    row_data = [0] * len(BALANCE_HEADER)
    col_ccy, col_code, col_cr = (BALANCE_HEADER.index(c) for c in ("ccy", "Acctcd", "afterbal_cr"))
    row_data[col_ccy], row_data[col_code], row_data[col_cr] = "USD", 401.0, 500.0
    rows = [BALANCE_HEADER, row_data]

    import backend.services.dtbb.reader as reader_mod
    orig = reader_mod.xlrd.open_workbook
    reader_mod.xlrd.open_workbook = _fake_open_workbook(rows)
    try:
        ccy, balances = read_balance_file(b"", "USD20260715.XLS")
    finally:
        reader_mod.xlrd.open_workbook = orig
    assert "401" in balances
    assert "401.0" not in balances


def test_read_balance_file_o_loi_dinh_dang_bao_dtbbfileerror_ro_rang(monkeypatch):
    """Ô số dư không parse được thành số (vd lỗi công thức Excel) phải báo DtbbFileError
    rõ ràng (tên file/dòng/cột) — không được lọt thành ValueError/500 thô."""
    row_data = [0] * len(BALANCE_HEADER)
    col_ccy, col_code, col_cr = (BALANCE_HEADER.index(c) for c in ("ccy", "Acctcd", "afterbal_cr"))
    row_data[col_ccy], row_data[col_code], row_data[col_cr] = "USD", "401", "#N/A"
    rows = [BALANCE_HEADER, row_data]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    with pytest.raises(DtbbFileError, match="USD20260715.XLS"):
        read_balance_file(b"", "USD20260715.XLS")


def test_read_tygia_file_chuan_hoa_ccy_thuong_thanh_hoa(monkeypatch):
    header = ["ccycd", "ttbuyrt", "bsrt", "taxrt", "rgstdt"]
    rgstdt_serial = xlrd.xldate.xldate_from_date_tuple((2026, 7, 15), 0)
    rows = [header, ["usd", 25400.0, 25450.0, 25300.0, rgstdt_serial]]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    rates, report_date = read_tygia_file(b"", "TIGIA.XLS")
    assert "USD" in rates
    assert report_date == "2026-07-15"


def test_read_tygia_file_ty_gia_loi_bao_dtbbfileerror(monkeypatch):
    header = ["ccycd", "ttbuyrt", "bsrt", "taxrt", "rgstdt"]
    rgstdt_serial = xlrd.xldate.xldate_from_date_tuple((2026, 7, 15), 0)
    rows = [header, ["USD", "lỗi", 25450.0, 25300.0, rgstdt_serial]]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    with pytest.raises(DtbbFileError, match="TIGIA.XLS"):
        read_tygia_file(b"", "TIGIA.XLS")


# ── DtbbFileError.filenames — FE dùng để tô đỏ đúng file lỗi ────────────────────

def test_dtbbfileerror_filenames_tu_extract_report_date():
    with pytest.raises(DtbbFileError) as exc_info:
        extract_report_date_and_branch("1200EUR20260715.XLS", "USD")  # ccy không khớp
    assert exc_info.value.filenames == ["1200EUR20260715.XLS"]


def test_dtbbfileerror_filenames_tu_read_balance_file(monkeypatch):
    rows = [["sai", "tieu", "de"], ["a", "b", "c"]]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))
    with pytest.raises(DtbbFileError) as exc_info:
        read_balance_file(b"", "USD20260715.XLS")
    assert exc_info.value.filenames == ["USD20260715.XLS"]


def test_dtbbfileerror_filenames_tu_tru_9300_trung_ma_tien():
    balance_entries = [
        ("USD", {"401": 100.0}, "2026-07-15", "9999", "USD20260715.XLS"),
        ("USD", {"401": 50.0}, "2026-07-15", "9999", "USD20260715_v2.XLS"),
    ]
    with pytest.raises(DtbbFileError) as exc_info:
        _merge_9999_minus_9300(balance_entries)
    assert set(exc_info.value.filenames) == {"USD20260715.XLS", "USD20260715_v2.XLS"}


def test_dtbbfileerror_khong_co_filename_cu_the_thi_rong():
    """Lỗi không gắn với 1 file cụ thể (vd chưa upload đủ loại file) — filenames rỗng,
    không phải lỗi/crash, FE chỉ đơn giản không tô đỏ file nào."""
    err = DtbbFileError("Chưa upload file tỷ giá")
    assert err.filenames == []


# ── PR #67 rà soát vòng Người 1 — fix reader.py: cộng dồn Acctcd trùng,
# chặn trộn mã tiền, rgstdt sai định dạng không văng 500 thô ───────────────────

def test_read_balance_file_trung_acctcd_cong_don_khong_ghi_de():
    """File GLCB41/CĐ1000 'Sub Branch, Including 1056' tách 1 tài khoản thành nhiều
    dòng theo subunit — số dư thật = tổng các dòng, không phải dòng cuối cùng."""
    row_data = [0] * len(BALANCE_HEADER)
    col_ccy, col_code, col_cr = (BALANCE_HEADER.index(c) for c in ("ccy", "Acctcd", "afterbal_cr"))
    r1 = list(row_data); r1[col_ccy], r1[col_code], r1[col_cr] = "USD", "401", 100.0
    r2 = list(row_data); r2[col_ccy], r2[col_code], r2[col_cr] = "USD", "401", 250.0
    rows = [BALANCE_HEADER, r1, r2]

    import backend.services.dtbb.reader as reader_mod
    orig = reader_mod.xlrd.open_workbook
    reader_mod.xlrd.open_workbook = _fake_open_workbook(rows)
    try:
        ccy, balances = read_balance_file(b"", "USD20260715.XLS")
    finally:
        reader_mod.xlrd.open_workbook = orig
    assert ccy == "USD"
    assert balances["401"] == 350.0


def test_read_balance_file_tron_2_ma_tien_bao_loi(monkeypatch):
    row_data = [0] * len(BALANCE_HEADER)
    col_ccy, col_code, col_cr = (BALANCE_HEADER.index(c) for c in ("ccy", "Acctcd", "afterbal_cr"))
    r1 = list(row_data); r1[col_ccy], r1[col_code], r1[col_cr] = "USD", "401", 100.0
    r2 = list(row_data); r2[col_ccy], r2[col_code], r2[col_cr] = "EUR", "402", 50.0
    rows = [BALANCE_HEADER, r1, r2]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    with pytest.raises(DtbbFileError, match="nhiều mã tiền") as exc_info:
        read_balance_file(b"", "USD20260715.XLS")
    assert exc_info.value.filenames == ["USD20260715.XLS"]


def test_read_tygia_file_rgstdt_chuoi_bao_loi_khong_crash_500(monkeypatch):
    """rgstdt là chuỗi (không phải serial Excel) — trước đây xlrd.xldate_as_tuple()
    ném TypeError thô, lọt thành lỗi 500. Giờ phải bắt được thành DtbbFileError."""
    header = ["ccycd", "ttbuyrt", "bsrt", "taxrt", "rgstdt"]
    rows = [header, ["USD", 25400.0, 25450.0, 25300.0, "không phải ngày"]]
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    with pytest.raises(DtbbFileError, match="TIGIA.XLS") as exc_info:
        read_tygia_file(b"", "TIGIA.XLS")
    assert exc_info.value.filenames == ["TIGIA.XLS"]


def test_read_tygia_file_rgstdt_so_qua_lon_bao_loi_khong_crash_500(monkeypatch):
    """rgstdt là số nhưng vượt phạm vi ngày Excel hợp lệ (vd nhập nhầm YYYYMMDD thô
    thay vì serial) — xlrd.XLDateError, không phải TypeError. Cả 2 dạng lỗi đều phải
    được bắt (xem except (TypeError, ValueError, xlrd.XLDateError) trong reader.py)."""
    header = ["ccycd", "ttbuyrt", "bsrt", "taxrt", "rgstdt"]
    rows = [header, ["USD", 25400.0, 25450.0, 25300.0, 20260731]]  # YYYYMMDD thô, không phải serial
    monkeypatch.setattr("backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook(rows))

    with pytest.raises(DtbbFileError, match="TIGIA.XLS"):
        read_tygia_file(b"", "TIGIA.XLS")


# ── PR #67 rà soát vòng Người 1 — fix calculator.py: filenames khi trùng mã tiền
# ở nhánh 1 chi nhánh, file_count đếm đúng số file gốc (không phải số mã tiền sau
# gộp 9999-9300) ────────────────────────────────────────────────────────────────

def _fake_open_workbook_multi(content_map):
    def _open(file_contents=None, **kw):
        return _FakeWorkbook(content_map[file_contents])
    return _open


def _balance_rows(ccy, code, cr):
    row_data = [0] * len(BALANCE_HEADER)
    col_ccy, col_code, col_cr = (BALANCE_HEADER.index(c) for c in ("ccy", "Acctcd", "afterbal_cr"))
    row_data[col_ccy], row_data[col_code], row_data[col_cr] = ccy, code, cr
    return [BALANCE_HEADER, row_data]


def _tygia_rows(entries, date_tuple):
    # Header thật có cả 'ccyseq' (sniff_file_type dò cột này) lẫn 'ccycd' (read_tygia_file
    # đọc cột này) — 2 cột khác nhau trong file thật, không phải lỗi gõ.
    header = ["ccyseq", "ccycd", "ttbuyrt", "bsrt", "taxrt", "rgstdt"]
    serial = xlrd.xldate.xldate_from_date_tuple(date_tuple, 0)
    rows = [header]
    for i, (ccy, ttbuyrt, bsrt) in enumerate(entries):
        rows.append([i, ccy, ttbuyrt, bsrt, 0, serial if i == 0 else 0])
    return rows


def test_calculate_from_uploads_1_chi_nhanh_trung_ma_tien_bao_loi_kem_filenames(monkeypatch):
    content_map = {
        b"A": _balance_rows("USD", "401", 100.0),
        b"B": _balance_rows("USD", "402", 50.0),
        b"T": _tygia_rows([("USD", 26110, 26300)], (2026, 7, 31)),
    }
    monkeypatch.setattr(
        "backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook_multi(content_map)
    )
    files = [
        ("USD20260731.XLS", b"A"),
        ("usd20260731.XLS", b"B"),  # tên khác (thường/hoa), cùng chi nhánh 9999 mặc định
        ("TIGIA.XLS", b"T"),
    ]
    with pytest.raises(DtbbFileError, match="2 file") as exc_info:
        calculate_from_uploads(files)
    assert set(exc_info.value.filenames) == {"USD20260731.XLS", "usd20260731.XLS"}


def test_calculate_from_uploads_file_count_dem_dung_khi_co_gop_9300(monkeypatch):
    """4 file gốc (2 file USD 9999+9300 gộp thành 1 mã tiền, 1 file EUR riêng, 1 file
    tỷ giá) — file_count phải là 4 (tổng file THẬT SỰ upload), không phải 2 (số mã
    tiền post-merge: USD gộp + EUR)."""
    content_map = {
        b"U9999": _balance_rows("USD", "401", 1000.0),
        b"U9300": _balance_rows("USD", "401", 200.0),
        b"E9999": _balance_rows("EUR", "401", 500.0),
        b"T": _tygia_rows([("USD", 26110, 26300), ("EUR", 29632, 30228.5)], (2026, 7, 31)),
    }
    monkeypatch.setattr(
        "backend.services.dtbb.reader.xlrd.open_workbook", _fake_open_workbook_multi(content_map)
    )
    files = [
        ("USD20260731.XLS", b"U9999"),
        ("9300USD20260731.XLS", b"U9300"),
        ("EUR20260731.XLS", b"E9999"),
        ("TIGIA.XLS", b"T"),
    ]
    result = calculate_from_uploads(files)
    assert result.file_count == 4
    assert result.netted_9300_ccy == ["USD"]
