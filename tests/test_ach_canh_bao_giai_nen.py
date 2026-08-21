"""Cảnh báo khi phải giải nén bằng cách dự phòng (pyzipper) phải tới được MÀN HÌNH
người vận hành, không chỉ nằm trong logs/backend.log.

Bối cảnh (19/08/2026): một lượt chạy đứng ở "[B4] Đọc MIS_DI từ 2 ZIP..." rồi mất
kết nối. Nhánh dự phòng nạp trọn CSV vào bộ nhớ (đo được: `dtype=str` phình ~7 lần
kích thước file) nên rất có thể là thủ phạm — nhưng người bấm nút không có cách nào
biết mình đã rơi vào nhánh đó, vì mọi dòng chẩn đoán đều đi qua `print()`.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_ach_canh_bao_giai_nen.py -v
"""
import pandas as pd
import pytest

from backend.services.ach import b2_xu_ly_gl02, b4_xu_ly_mis_di, b6_xu_ly_mis_den

# (module, tên bước) — ba bước đọc ZIP đều có cùng nhánh dự phòng
BUOC_DOC_ZIP = [
    (b2_xu_ly_gl02, 'B2'),
    (b4_xu_ly_mis_di, 'B4'),
    (b6_xu_ly_mis_den, 'B6'),
]


def _goi_doc_zip(mod, log):
    """B2 nhận (zip_path, log_callback); B4/B6 nhận (zip_path, session_filter, log)."""
    if mod is b2_xu_ly_gl02:
        return mod._doc_zip('khong_ton_tai.zip', log)
    return mod._doc_zip('khong_ton_tai.zip', None, log)


@pytest.mark.parametrize('mod,buoc', BUOC_DOC_ZIP)
def test_khong_co_7zip_thi_canh_bao_ra_log_cua_job(mod, buoc, monkeypatch):
    monkeypatch.setattr(mod, '_find_zip_tool', lambda: None)
    monkeypatch.setattr(mod, '_doc_zip_pyzipper',
                        lambda *a, **kw: pd.DataFrame())

    dong = []
    _goi_doc_zip(mod, dong.append)

    assert any('CẢNH BÁO' in d and 'không cài 7-Zip' in d for d in dong), dong
    assert any('bộ nhớ' in d for d in dong), (
        'Cảnh báo phải nói rõ hậu quả (ăn bộ nhớ), không chỉ báo "dùng pyzipper" '
        f'— người vận hành không biết pyzipper là gì. Nhận được: {dong}'
    )


@pytest.mark.parametrize('mod,buoc', BUOC_DOC_ZIP)
def test_cong_cu_giai_nen_loi_thi_canh_bao_kem_ly_do(mod, buoc, monkeypatch):
    monkeypatch.setattr(mod, '_find_zip_tool', lambda: ('C:/7z.exe', '7z'))

    def _no(*a, **kw):
        raise RuntimeError('o dia day')

    monkeypatch.setattr(mod, '_doc_zip_tool', _no)
    monkeypatch.setattr(mod, '_doc_zip_pyzipper', lambda *a, **kw: pd.DataFrame())

    dong = []
    _goi_doc_zip(mod, dong.append)

    assert any('o dia day' in d for d in dong), (
        f'Lý do công cụ giải nén thất bại phải hiện ra, nếu không mọi lần lui về '
        f'nhánh dự phòng đều trông giống nhau. Nhận được: {dong}'
    )
    assert any('CẢNH BÁO' in d for d in dong), dong


@pytest.mark.parametrize('mod,buoc', BUOC_DOC_ZIP)
def test_khong_co_log_callback_thi_khong_no(mod, buoc, monkeypatch):
    """Pipeline gọi được với log_callback=None (mặc định) — nhánh cảnh báo không
    được giả định lúc nào cũng có nơi để ghi."""
    monkeypatch.setattr(mod, '_find_zip_tool', lambda: None)
    monkeypatch.setattr(mod, '_doc_zip_pyzipper', lambda *a, **kw: pd.DataFrame())

    mod._doc_zip('khong_ton_tai.zip')
