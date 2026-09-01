"""Chấm 459901 — không được ghi quá 1.048.576 dòng vào một sheet Excel.

Một file GL02 một ngày đã cho ~617.000 dòng nhóm "Lệnh Đi"; giao diện cho chọn
nhiều file và backend GỘP chúng lại, nên gộp 2 ngày là vượt trần định dạng XLSX.

Trước khi sửa: `_write_excel` cứ ghi thẳng qua dòng 1.048.576. Server báo "Hoàn
thành!", người dùng tải về file trăm MB rồi Excel từ chối mở — không có lỗi nào
ở cả hai đầu. `openpyxl` đọc file hỏng đó vẫn trót lọt nên phải đếm thẳng trong
`sheet1.xml`, không thể tin vào việc "đọc lại được là đạt".
"""
import re
import sys
import zipfile

import pandas as pd
import pytest

sys.path.insert(0, ".")

from backend.services import cham459901_service as sv


def _df(n: int) -> pd.DataFrame:
    """DataFrame n dòng đủ mọi cột đầu ra, giá trị không quan trọng."""
    return pd.DataFrame({
        c: ([1.0] * n if c in sv._NUM_COLS else [f"v{i}" for i in range(n)])
        for c in sv.OUTPUT_COLS
    })


def _so_dong_moi_sheet(path) -> dict:
    """{tên part: số dòng lớn nhất} đọc thẳng từ XML, không qua openpyxl."""
    ra = {}
    with zipfile.ZipFile(path) as z:
        for ten in z.namelist():
            if not re.match(r"xl/worksheets/sheet\d+\.xml$", ten):
                continue
            r = [int(x) for x in re.findall(rb'<row r="(\d+)"', z.read(ten))]
            ra[ten] = max(r) if r else 0
    return ra


def _ten_cac_sheet(path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return re.findall(rb'<sheet name="([^"]+)"', z.read("xl/workbook.xml"))


# ── Trần dòng ────────────────────────────────────────────────────────────────

def test_khong_sheet_nao_vuot_tran_cua_xlsx(tmp_path, monkeypatch):
    """Hạ trần xuống 100 để chạy nhanh — luật kiểm tra vẫn y nguyên."""
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(250), f, "Lệnh Đi", "27AE60")

    sheets = _so_dong_moi_sheet(f)
    assert len(sheets) == 3, f"250 dòng / 100 mỗi sheet phải ra 3 sheet, có {sheets}"
    for ten, dong_cuoi in sheets.items():
        # +3 = dòng tiêu đề gộp, dòng tên cột, dòng TỔNG CỘNG
        assert dong_cuoi <= 100 + 3, f"{ten} ghi tới dòng {dong_cuoi}, vượt trần"


def test_dung_bang_tran_thi_van_mot_sheet(tmp_path, monkeypatch):
    """Ranh giới: đúng _MAX_DATA_ROWS dòng thì KHÔNG được tách."""
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(100), f, "Lệnh Đi", "27AE60")
    assert len(_so_dong_moi_sheet(f)) == 1


def test_hon_tran_mot_dong_thi_tach_hai(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(101), f, "Lệnh Đi", "27AE60")
    assert len(_so_dong_moi_sheet(f)) == 2


def test_tran_that_dung_1048573(tmp_path):
    """Hằng số phải khớp giới hạn thật của định dạng, trừ 3 dòng khung."""
    assert sv._XLSX_MAX_ROWS == 1_048_576
    assert sv._MAX_DATA_ROWS == 1_048_573


# ── Không mất dữ liệu khi tách ───────────────────────────────────────────────

def test_tach_sheet_khong_lam_mat_dong_nao(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(250), f, "Lệnh Đi", "27AE60")

    # Mỗi sheet: dòng cuối - 3 = số dòng dữ liệu của sheet đó
    tong = sum(v - 3 for v in _so_dong_moi_sheet(f).values())
    assert tong == 250


def test_du_lieu_dung_thu_tu_giua_cac_sheet(tmp_path, monkeypatch):
    """Sheet 2 phải bắt đầu đúng ở dòng kế tiếp của sheet 1, không lặp không nhảy."""
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(150), f, "Lệnh Đi", "27AE60")

    with zipfile.ZipFile(f) as z:
        s1 = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        s2 = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
    assert "<t>v0</t>" in s1 and "<t>v99</t>" in s1
    assert "<t>v100</t>" in s2 and "<t>v149</t>" in s2
    assert "<t>v100</t>" not in s1, "dòng 101 bị ghi lặp ở cả hai sheet"


# ── Cấu trúc file vẫn hợp lệ ─────────────────────────────────────────────────

def test_excel_van_doc_duoc_sau_khi_tach(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(250), f, "Lệnh Đi", "27AE60")

    wb = openpyxl.load_workbook(f, read_only=True)
    assert len(wb.sheetnames) == 3
    wb.close()


def test_ten_sheet_khong_qua_31_ky_tu(tmp_path, monkeypatch):
    """Excel từ chối tên sheet dài hơn 31 ký tự."""
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "x.xlsx"
    sv._write_excel(_df(250), f, "Chuyển chi nhánh dài lê thê quá mức", "8E44AD")
    for ten in _ten_cac_sheet(f):
        assert len(ten.decode("utf-8")) <= 31


def test_mot_phan_thi_giu_nguyen_ten_sheet_cu(tmp_path):
    """Trường hợp thường gặp không được đổi gì so với trước."""
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(10), f, "Lệnh Đi", "27AE60")
    assert _ten_cac_sheet(f) == ["Lệnh Đi".encode("utf-8")]


def test_bucket_rong_van_ra_dung_mot_sheet(tmp_path):
    """0 dòng: trước đây ra 1 sheet rỗng, phải giữ nguyên như vậy."""
    f = tmp_path / "ht1000.xlsx"
    sv._write_excel(_df(0), f, "1000 Hoàn trả", "2980B9")
    assert len(_so_dong_moi_sheet(f)) == 1


# ── Tổng tiền ────────────────────────────────────────────────────────────────

def _tong_cua_sheet(path, sheet: str) -> list[float]:
    """Các ô số trên dòng TỔNG CỘNG (style s="5") của một sheet."""
    with zipfile.ZipFile(path) as z:
        xml = z.read(f"xl/worksheets/{sheet}").decode("utf-8")
    dong = re.search(r"<row r=\"\d+\">((?:(?!</row>).)*TỔNG CỘNG.*?)</row>", xml)
    assert dong, f"{sheet} không có dòng TỔNG CỘNG"
    return [float(v) for v in re.findall(r's="5"><v>([\d.]+)</v>', dong.group(1))]


def test_tong_cong_moi_sheet_la_tong_cua_sheet_do(tmp_path, monkeypatch):
    """Dòng TỔNG CỘNG ở cuối mỗi sheet phải là tổng CỦA PHẦN ĐÓ — nếu ghi tổng cả
    nhóm vào từng sheet thì cộng ba sheet lại ra gấp ba, kế toán không đối được."""
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(250), f, "Lệnh Đi", "27AE60")   # mỗi dòng DRAMOUNT=CRAMOUNT=1.0

    assert _tong_cua_sheet(f, "sheet1.xml") == [100.0, 100.0]
    assert _tong_cua_sheet(f, "sheet2.xml") == [100.0, 100.0]
    assert _tong_cua_sheet(f, "sheet3.xml") == [50.0, 50.0]   # phần cuối chỉ 50 dòng

    cong_lai = sum(_tong_cua_sheet(f, f"sheet{k}.xml")[0] for k in (1, 2, 3))
    assert cong_lai == 250.0, "cộng tổng các sheet phải ra đúng tổng cả nhóm"


def test_tieu_de_noi_ro_phan_may_tren_may(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "_MAX_DATA_ROWS", 100)
    f = tmp_path / "di.xlsx"
    sv._write_excel(_df(250), f, "Lệnh Đi", "27AE60")
    with zipfile.ZipFile(f) as z:
        s2 = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
    assert "phần 2/3" in s2
    assert "101" in s2 and "200" in s2, "phải ghi rõ khoảng dòng của phần này"
