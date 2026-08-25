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
from backend.services.doi_soat_citad.parsers import _parse_so_tien


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
