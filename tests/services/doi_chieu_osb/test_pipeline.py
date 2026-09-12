"""Test module `doi_chieu_osb` — fixture DataFrame tự tạo (KHÔNG dùng đường dẫn `G:\\...` cố định,
máy khác không có ổ đó). Cover: 1 cặp khớp đúng, 1 dòng chênh lệch Nợ, 1 dòng chênh lệch Có, 1 cặp
Hủy hợp lệ, 1 REMARK < 7 ký tự — và đặc biệt 2 lỗi đã phát hiện bằng dữ liệu thật trước khi viết
module này (xem `docs/Implementation-notes.html`):
  1) chiều cột OSB "TK ghi nợ"/"TK ghi có" phải CÙNG TÊN với case (Nợ<->ghi Nợ, Có<->ghi Có).
  2) dedupe OSB phải theo TOÀN BỘ CỘT, không theo riêng "Mã giao dịch" (phá vỡ cặp Hủy hợp lệ).
"""
import io

import pandas as pd
import pytest

from backend.services.doi_chieu_osb import load_gl02, load_osb, match, pipeline

MA_TK = "519910"
KHACH_HANG = "1000-000000001"
NGAY = "20260701"


def _gl02_row(remark, dramount="0", cramount="0", reference="1000API0000000123"):
    return {
        "TRDATE": NGAY, "TRBRCD": "1000", "USERID": "1000OSB", "JOURSEQ": "1", "DYTRSEQ": "1",
        "LOCAC": MA_TK, "CCY": "VND", "BUSCD": "GL", "UNIT": "ST", "TRCD": "  ",
        "CUSTOMER": KHACH_HANG, "TRTP": "Normal", "REFERENCE": reference, "REMARK": remark,
        "DRAMOUNT": dramount, "CRAMOUNT": cramount, "CRTDTM": "20260701 00:00:00",
    }


def _osb_row(ma_gd, ipcas_trace, so_tien, tk_no, tk_co, cn="1000 - Tru so chinh"):
    return {
        "STT": "1", "Kênh": "AgribankPlus", "Mã dịch vụ": "LCN", "Dịch vụ": "LCN",
        "Chiều giao dịch": "IPCAS -> OSB", "Mã giao dịch": ma_gd, "IPCAS Trace": ipcas_trace,
        "Mã giao dịch gốc": ma_gd, "Seq": "1", "CN thực hiện": cn, "CN hạch toán": cn,
        "TK ghi nợ": tk_no, "TK ghi có": tk_co, "Tài khoản chuyên thu": "123", "Tiền tệ": "VND",
        "Số tiền": so_tien, "Số bút toán OSB": "1", "Ref nợ": "0", "Ref có": "0",
        "Ngày giao dịch": "01/07/2026", "Ngày tổng hợp": "01/07/2026",
        "Ngày hạch toán": "01/07/2026", "Nội dung giao dịch": "test", "Kiểu giao dịch": "Normal",
        "Mã GL tổng OSB": "1", "Mã hạch toán tổng IPCAS": "1",
        "Trạng thái hạch toán tổng IPCAS": "Thành công", "Mã lỗi": "02",
    }


@pytest.fixture
def gl02_df():
    """5 dòng GL02: 1 khớp Có, 1 khớp Nợ, 1 chênh lệch Có, 1 chênh lệch Nợ, 1 REMARK ngắn."""
    rows = [
        # Khớp OK — Có: SO_TRACE="111111", DRAMOUNT=100000, CRAMOUNT=0
        _gl02_row("[111111] khop co", dramount="100000", cramount="0"),
        # Khớp OK — Nợ: SO_TRACE="222222", CRAMOUNT=200000, DRAMOUNT=0
        _gl02_row("[222222] khop no", dramount="0", cramount="200000"),
        # Chênh lệch Có: SO_TRACE="333333", DRAMOUNT=300000, không có OSB tương ứng
        _gl02_row("[333333] le co", dramount="300000", cramount="0"),
        # Chênh lệch Nợ: SO_TRACE="444444", CRAMOUNT=400000, không có OSB tương ứng
        _gl02_row("[444444] le no", dramount="0", cramount="400000"),
        # REMARK ngắn (< 7 ký tự) — rủi ro khoá rỗng, DRAMOUNT!=0 nhưng không kỳ vọng khớp
        _gl02_row("LCN", dramount="50000", cramount="0"),
        # Loại theo REFERENCE=1000OSB — không được lọt vào subset nào
        _gl02_row("[555555] loai ref", dramount="999999", cramount="0", reference="1000OSB"),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def osb_df():
    """OSB gồm: 1 dòng khớp Có (TK ghi có=519910), 1 dòng khớp Nợ (TK ghi nợ=519910), 1 cặp Hủy
    hợp lệ (cùng Mã giao dịch, số tiền trái dấu, IPCAS Trace khác nhau, TK ghi có=519910)."""
    rows = [
        # Khớp Có: TK ghi có = 519910 (Chênh lệch Có lọc theo "TK ghi có")
        _osb_row("GD001", "111111", "100.000", tk_no="519101", tk_co=MA_TK),
        # Khớp Nợ: TK ghi nợ = 519910 (Chênh lệch Nợ lọc theo "TK ghi nợ")
        _osb_row("GD002", "222222", "200.000", tk_no=MA_TK, tk_co="519101"),
        # Cặp Hủy hợp lệ, thuộc phía "TK ghi có"=519910 (Chênh lệch Có) — PHẢI bị loại khỏi subset
        _osb_row("GD003", "999999", "50.000", tk_no="519101", tk_co=MA_TK),
        _osb_row("GD003", "", "-50.000", tk_no="519101", tk_co=MA_TK),
    ]
    return pd.DataFrame(rows)


# ─── Test dedupe: KHÔNG được theo riêng "Mã giao dịch" ─────────────────────────

def test_read_osb_files_khong_pha_cap_huy(tmp_path, osb_df, monkeypatch):
    """Nếu dedupe theo riêng 'Mã giao dịch', cặp Hủy (GD003 x2) sẽ bị rút còn 1 dòng — sai. Dedupe
    toàn cột phải giữ nguyên cả 4 dòng vì không có dòng nào giống hệt dòng khác."""
    # Giả lập read_osb_files() nội bộ: gọi thẳng logic dedupe bằng cách nối chính osb_df 2 lần vào
    # 1 "danh sách file" ảo — mô phỏng việc gộp 2 file OSB thật của 1 ngày.
    monkeypatch.setattr(load_osb, "load_osb_file", lambda p: osb_df if p == "f1" else osb_df.iloc[0:0])
    full = load_osb.read_osb_files(["f1", "f2"])
    # 4 dòng gốc của osb_df phải còn nguyên (f2 rỗng nên không thêm gì, không mất gì).
    assert len(full) == len(osb_df)


def test_process_osb_danh_dau_huy_dung(osb_df):
    df, n_over2 = load_osb.process_osb(osb_df)
    assert n_over2 == 0
    huy_rows = df[df["Mã giao dịch"] == "GD003"]
    assert len(huy_rows) == 2
    assert (huy_rows["LOAI_GIAO_DICH"] == "Hủy").all()
    # 2 dòng còn lại (GD001, GD002) KHÔNG bị đánh dấu Hủy.
    khong_huy = df[df["Mã giao dịch"] != "GD003"]
    assert (khong_huy["LOAI_GIAO_DICH"] == "").all()


def test_dedupe_theo_ma_giao_dich_se_pha_cap_huy_neu_lam_sai(osb_df):
    """Chứng minh CỤ THỂ vì sao KHÔNG được dedupe theo 'Mã giao dịch': làm vậy sẽ chỉ còn 1 dòng
    GD003 thay vì 2, khiến nhóm không còn đủ ≥2 dòng để nhận diện Hủy."""
    sai = osb_df.drop_duplicates(subset=["Mã giao dịch"], keep="first")
    assert len(sai[sai["Mã giao dịch"] == "GD003"]) == 1  # bị phá — đúng là bug đã tìm thấy
    dung = osb_df.drop_duplicates()
    assert len(dung[dung["Mã giao dịch"] == "GD003"]) == 2  # dedupe toàn cột giữ nguyên


# ─── Test chiều "TK ghi nợ"/"TK ghi có" phải CÙNG TÊN với case ─────────────────

def test_chieu_tk_ghi_no_co_cung_ten_khong_cheo(gl02_df, osb_df):
    """Case 'Chênh lệch Nợ' phải lọc OSB theo 'TK ghi nợ' (không phải 'TK ghi có'); case
    'Chênh lệch Có' phải lọc theo 'TK ghi có'. Đảo ngược (như hiểu nhầm ban đầu từ note Hà bị lỗi
    copy-paste) sẽ làm dòng khớp Nợ/Có ở trên KHÔNG khớp được nữa."""
    osb_df2, _ = load_osb.process_osb(osb_df)
    # Đúng: case Có lọc "TK ghi có" == MA_TK -> phải thấy đúng dòng GD001 (khớp) + cặp Hủy GD003
    # (bị loại vì Hủy) -> subset chỉ còn GD001.
    co_sub = osb_df2[(osb_df2["TK ghi có"] == MA_TK) & (osb_df2["LOAI_GIAO_DICH"] != "Hủy")]
    assert set(co_sub["Mã giao dịch"]) == {"GD001"}
    # Đúng: case Nợ lọc "TK ghi nợ" == MA_TK -> chỉ GD002.
    no_sub = osb_df2[(osb_df2["TK ghi nợ"] == MA_TK) & (osb_df2["LOAI_GIAO_DICH"] != "Hủy")]
    assert set(no_sub["Mã giao dịch"]) == {"GD002"}


# ─── Test end-to-end (pipeline) bằng file tạm trong tmp_path ───────────────────

def test_pipeline_end_to_end(tmp_path, monkeypatch, gl02_df, osb_df):
    """Chạy trọn `chay_doi_chieu_osb` bằng cách monkeypatch tầng đọc I/O (zip GL02, file OSB) —
    không cần zip/xlsx thật, chỉ cần đúng shape DataFrame để test toàn bộ logic match+export."""
    monkeypatch.setattr(load_gl02, "_doc_zip", lambda zip_path, log_callback=None: gl02_df.copy())
    monkeypatch.setattr(load_osb, "load_osb_file", lambda p: osb_df if p == "osb1" else osb_df.iloc[0:0])

    ket_qua = pipeline.chay_doi_chieu_osb("dummy.zip", ["osb1", "osb2"], MA_TK, NGAY)

    assert ket_qua["ma_tk"] == MA_TK
    assert ket_qua["ngay"] == NGAY

    # Chênh lệch Có: 2 dòng GL02 — dòng cố ý lệch ("[333333] le co") VÀ dòng REMARK ngắn ("LCN",
    # DRAMOUNT=50000 cũng không có OSB tương ứng nên tự nhiên rơi vào chênh lệch, đúng như mong
    # đợi cho 1 REMARK < 7 ký tự). 0 dòng OSB (không có OSB thừa mẫu này).
    assert len(ket_qua["co"]["gl02"]) == 2
    assert set(ket_qua["co"]["gl02"]["REMARK"]) == {"[333333] le co", "LCN"}
    assert len(ket_qua["co"]["osb"]) == 0

    # Chênh lệch Nợ: đúng 1 dòng GL02 (SO_TRACE="444444").
    assert len(ket_qua["no"]["gl02"]) == 1
    assert ket_qua["no"]["gl02"]["REMARK"].iloc[0] == "[444444] le no"
    assert len(ket_qua["no"]["osb"]) == 0

    # Cảnh báo REMARK ngắn: đúng 1 dòng ("LCN", 3 ký tự).
    assert ket_qua["canh_bao"]["remark_ngan"] == 1
    assert ket_qua["canh_bao"]["nhom_huy_qua_2"] == 0

    # ZIP kết quả xuất ra được, không rỗng.
    assert isinstance(ket_qua["zip_bytes"], bytes)
    assert len(ket_qua["zip_bytes"]) > 0


def test_khoa_a_b_dung_cong_thuc(gl02_df):
    df, n_short = load_gl02_process(gl02_df)
    assert n_short == 1
    # Dòng "khop co": SO_TRACE = REMARK[1:7] = "111111", DRAMOUNT=100000 -> Khoá A = "111111100000"
    row = df[df["REMARK"] == "[111111] khop co"].iloc[0]
    assert row["SO_TRACE"] == "111111"
    assert row["KHOA_CHENH_LECH_CO"] == "111111100000"


def load_gl02_process(gl02_df):
    """Helper: chạy đúng phần xử lý (không I/O) của `read_gl02_zip()` bằng cách monkeypatch
    `_doc_zip()` qua gọi trực tiếp hàm nội bộ — tránh phải tạo ZIP thật cho 1 test đơn giản."""
    from backend.services.doi_chieu_osb import load_gl02 as m

    original = m._doc_zip
    m._doc_zip = lambda zip_path, log_callback=None: gl02_df.copy()
    try:
        df, n_short = m.read_gl02_zip("dummy.zip", MA_TK, NGAY)
    finally:
        m._doc_zip = original
    return df, n_short


# ─── Ca biên: xuất file KHÔNG lọt cột nội bộ (review code trước PR) ────────────

def test_export_khong_lot_cot_noi_bo(gl02_df, osb_df, monkeypatch):
    """`export.py::_osb_export_df()` phải dùng WHITELIST — 3 cột nội bộ ('SO_TIEN_NUM', 'KHOA_C',
    'LOAI_GIAO_DICH') KHÔNG được lọt ra file Excel dù có mặt trong DataFrame trước khi xuất."""
    monkeypatch.setattr(load_gl02, "_doc_zip", lambda zip_path, log_callback=None: gl02_df.copy())
    monkeypatch.setattr(load_osb, "load_osb_file",
                         lambda p: osb_df if p == "osb1" else osb_df.iloc[0:0])

    ket_qua = pipeline.chay_doi_chieu_osb("dummy.zip", ["osb1", "osb2"], MA_TK, NGAY)

    import zipfile
    with zipfile.ZipFile(io.BytesIO(ket_qua["zip_bytes"])) as zf:
        for name in zf.namelist():
            if not name.endswith("_OSB.xlsx"):
                continue
            df = pd.read_excel(io.BytesIO(zf.read(name)))
            for cot_noi_bo in ("SO_TIEN_NUM", "KHOA_C", "LOAI_GIAO_DICH"):
                assert cot_noi_bo not in df.columns, f"{name} lọt cột nội bộ {cot_noi_bo}"
        for name in zf.namelist():
            if not name.endswith("_GL02.xlsx"):
                continue
            df = pd.read_excel(io.BytesIO(zf.read(name)))
            for cot_noi_bo in ("DRAMOUNT_NUM", "CRAMOUNT_NUM", "KHOA_CHENH_LECH_CO",
                               "KHOA_CHENH_LECH_NO"):
                assert cot_noi_bo not in df.columns, f"{name} lọt cột nội bộ {cot_noi_bo}"


# ─── Ca biên: REMARK rỗng hoàn toàn ─────────────────────────────────────────────

def test_remark_rong_khong_crash():
    """REMARK = '' (rỗng thật, khác 'LCN' ngắn) không được làm crash pipeline — Số trace ra rỗng
    (`''[1:7] == ''`, slice Python không bao giờ ném lỗi kể cả chuỗi rỗng/ngắn hơn chỉ số)."""
    df = pd.DataFrame([_gl02_row("", dramount="70000", cramount="0")])
    result, n_short = load_gl02_process(df)
    assert len(result) == 1
    assert result["SO_TRACE"].iloc[0] == ""
    assert result["KHOA_CHENH_LECH_CO"].iloc[0] == "70000"  # "" + "70000"
    assert n_short == 1  # len("") = 0 < 7


def test_remark_rong_co_the_khop_nham_neu_trung_tien_hanh_vi_hien_tai(monkeypatch):
    """QUYẾT ĐỊNH: đây là rủi ro khoá rỗng ĐÃ BIẾT (mục B, lượt phản biện thiết kế) — module CHỈ
    log cảnh báo (`n_remark_ngan`), KHÔNG thêm rào chắn loại khoá rỗng khỏi tập khớp. Lý do không
    chặn: một REMARK rỗng/ngắn là dữ liệu thật hợp lệ (không phải lỗi định dạng) — tự loại nó khỏi
    so khớp sẽ khiến 1 giao dịch thật luôn bị báo "chênh lệch" dù có mặt đúng ở cả 2 phía, sai theo
    hướng ngược lại. Test này xác nhận CỤ THỂ hành vi hiện tại: 1 dòng GL02 REMARK rỗng + 1 dòng
    OSB IPCAS Trace rỗng, TRÙNG số tiền -> bị coi là khớp (không xuất hiện trong "chênh lệch") dù
    trong thực tế đây có thể là 2 giao dịch khác nhau tình cờ cùng thiếu trace + cùng số tiền."""
    gl02 = pd.DataFrame([_gl02_row("", dramount="80000", cramount="0")])
    osb = pd.DataFrame([_osb_row("GDX", "", "80.000", tk_no="519101", tk_co=MA_TK)])

    monkeypatch.setattr(load_gl02, "_doc_zip", lambda zip_path, log_callback=None: gl02.copy())
    monkeypatch.setattr(load_osb, "load_osb_file",
                         lambda p: osb if p == "osb1" else osb.iloc[0:0])

    ket_qua = pipeline.chay_doi_chieu_osb("dummy.zip", ["osb1", "osb2"], MA_TK, NGAY)

    # Hành vi HIỆN TẠI: 2 dòng khoá rỗng+cùng tiền bị coi là khớp -> 0 dòng "chênh lệch Có".
    assert len(ket_qua["co"]["gl02"]) == 0
    assert len(ket_qua["co"]["osb"]) == 0
    assert ket_qua["canh_bao"]["remark_ngan"] == 1


# ─── Ca biên: ô tiền để trống (rỗng/NaN) ────────────────────────────────────────

def test_dramount_cramount_trong_khong_crash():
    """DRAMOUNT/CRAMOUNT để trống (chuỗi rỗng) -> `doc_so_tien()` coi là 0 (hành vi ĐÃ CÓ sẵn của
    hàm dùng chung `backend/services/ach/so_tien.py`, module này không tự bịa quy tắc riêng)."""
    df = pd.DataFrame([_gl02_row("[123456] trong tien", dramount="", cramount="")])
    result, _ = load_gl02_process(df)
    assert result["DRAMOUNT_NUM"].iloc[0] == 0
    assert result["CRAMOUNT_NUM"].iloc[0] == 0
    # DRAMOUNT=0 và CRAMOUNT=0 -> dòng này không lọt vào subset của case Nợ lẫn Có (cả 2 đều lọc
    # theo != 0) khi chạy qua pipeline — không kiểm ở đây (đã cover ở test end-to-end khác).


def test_so_tien_osb_trong_khong_crash():
    """Cột 'Số tiền' OSB để trống -> `doc_so_tien()` coi là 0, không crash `process_osb()`."""
    df = pd.DataFrame([_osb_row("GDY", "654321", "", tk_no="519101", tk_co=MA_TK)])
    result, n_over2 = load_osb.process_osb(df)
    assert n_over2 == 0
    assert result["SO_TIEN_NUM"].iloc[0] == 0
    assert result["KHOA_C"].iloc[0] == "654321" + "0"


# ─── Ca biên: GL02/OSB 0 dòng sau khi lọc ───────────────────────────────────────

def test_pipeline_gl02_va_osb_0_dong_sau_loc(monkeypatch):
    """GL02 0 dòng sau lọc (VD tài khoản không tồn tại trong file — LOCAC không khớp `ma_tk` ở
    dòng nào) VÀ OSB 0 dòng (file trống) -> `chay_doi_chieu_osb()` phải chạy hết, trả kết quả rỗng
    hợp lệ, KHÔNG crash. Đây là nhánh `if len(gl02_df) == 0 or len(osb_df) == 0` trong
    `match.py::khop_case()` — trước đây CHƯA có test nào gọi tới thật qua pipeline end-to-end."""
    gl02_khong_khop = pd.DataFrame([
        _gl02_row("[999999] khong khop tk", dramount="10000", cramount="0"),
    ])
    gl02_khong_khop["LOCAC"] = "000000"  # KHÔNG khớp MA_TK -> bị lọc sạch ở read_gl02_zip()
    osb_rong = pd.DataFrame(columns=list(_osb_row("x", "x", "0", "519101", MA_TK).keys()))

    monkeypatch.setattr(load_gl02, "_doc_zip",
                         lambda zip_path, log_callback=None: gl02_khong_khop.copy())
    monkeypatch.setattr(load_osb, "load_osb_file", lambda p: osb_rong.copy())

    ket_qua = pipeline.chay_doi_chieu_osb("dummy.zip", ["osb1", "osb2"], MA_TK, NGAY)

    assert len(ket_qua["no"]["gl02"]) == 0
    assert len(ket_qua["no"]["osb"]) == 0
    assert len(ket_qua["co"]["gl02"]) == 0
    assert len(ket_qua["co"]["osb"]) == 0
    assert ket_qua["canh_bao"]["nhom_huy_qua_2"] == 0
    assert isinstance(ket_qua["zip_bytes"], bytes)
    assert len(ket_qua["zip_bytes"]) > 0
