"""Test nhận diện lệnh OSB dùng chung (D1) — khóa lại đúng giá trị đã verify trên
dữ liệu thật (chữ 'O' chiều đi, số '1' chiều đến), để Điểm 2/Điểm 4 sau này dùng
đúng, không cắm nhầm giá trị lần nữa.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_osb_common.py -v
"""

import pandas as pd

from backend.services.ach.osb_common import la_lenh_osb_di, la_lenh_osb_den


class TestLaLenhOsbDi:
    def test_chu_o_la_osb(self):
        df = pd.DataFrame({'LOAI_LENH_OSB': ['O', 'O ', ' O']})
        assert la_lenh_osb_di(df).all()

    def test_rong_khong_phai_osb(self):
        df = pd.DataFrame({'LOAI_LENH_OSB': ['', '  ', None]})
        assert not la_lenh_osb_di(df).any()

    def test_so_0_khong_phai_osb(self):
        """Đúng theo dữ liệu thật đã verify — chiều đi là chữ 'O', KHÔNG phải số 0
        như mô tả nghiệp vụ gốc."""
        df = pd.DataFrame({'LOAI_LENH_OSB': ['0']})
        assert not la_lenh_osb_di(df).any()

    def test_so_1_khong_phai_osb_di(self):
        """Số 1 là giá trị OSB của chiều ĐẾN, không phải chiều đi."""
        df = pd.DataFrame({'LOAI_LENH_OSB': ['1']})
        assert not la_lenh_osb_di(df).any()


class TestLaLenhOsbDen:
    def test_so_1_la_osb(self):
        df = pd.DataFrame({'LOAI_LENH_OSB': ['1', '1 ', ' 1']})
        assert la_lenh_osb_den(df).all()

    def test_rong_khong_phai_osb(self):
        df = pd.DataFrame({'LOAI_LENH_OSB': ['', '  ', None]})
        assert not la_lenh_osb_den(df).any()

    def test_chu_o_khong_phai_osb_den(self):
        """Chữ 'O' là giá trị OSB của chiều ĐI, không phải chiều đến."""
        df = pd.DataFrame({'LOAI_LENH_OSB': ['O']})
        assert not la_lenh_osb_den(df).any()
