"""Khoảng ngày bật trang trí Quốc khánh 2-9."""
from datetime import date
import frontend.le_29 as le_29


def test_bat_dung_khoang():
    assert not le_29.dang_dip_le(date(2026, 8, 24))
    assert le_29.dang_dip_le(date(2026, 8, 25))
    assert le_29.dang_dip_le(date(2026, 9, 2))
    assert le_29.dang_dip_le(date(2026, 9, 3))
    assert not le_29.dang_dip_le(date(2026, 9, 4))


def test_khong_phu_thuoc_nam():
    # Không viết cứng năm → sang năm tự bật lại, không phải deploy để gỡ
    assert le_29.dang_dip_le(date(2031, 9, 1))
    assert not le_29.dang_dip_le(date(2031, 12, 25))


def test_so_nam_va_cau_chuc():
    assert le_29.so_nam(date(2026, 9, 2)) == 81
    d1, d2 = le_29.hai_dong(date(2026, 9, 2))
    # Số năm và cả 4 mốc ngày đều tính từ 1945 — không có số cứng nào phải nhớ sửa
    assert "81 NĂM CÁCH MẠNG THÁNG TÁM" in d1
    assert "19/8/1945 - 19/8/2026" in d1
    assert "QUỐC KHÁNH" in d2 and "2/9/1945 - 2/9/2026" in d2
    assert le_29.cau_chuc(date(2026, 9, 2)) == f"{d1} {d2}"


def test_hai_dong_du_ngan_de_khong_tran():
    # Mỗi dòng phải vừa vùng nội dung (~1078px ở màn 1366 trừ sidebar 256px).
    # Chữ hoa ~0.62em: 14px → ~8.7px/ký tự. Chặn ở 100 ký tự cho một dòng.
    for dong in le_29.hai_dong(date(2026, 9, 2)):
        assert len(dong) <= 100, f"dòng dài {len(dong)} ký tự sẽ tràn dải trang chủ"
