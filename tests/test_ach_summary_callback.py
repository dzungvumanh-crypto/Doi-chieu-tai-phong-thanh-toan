"""Test `summary_callback` của `xuat_excel()` — dict số liệu nhóm nghiệp vụ ACH
thật, dùng để hiển thị "Kết quả tạm thời" ở trang cham_ach.py (nâng cấp UI
2026-08-21). Không mock — dựng DataFrame tổng hợp nhỏ, ghi Excel thật ra
tmp_path, đúng nguyên tắc "không mock I/O" của skill doi-chieu.

Tái dùng `_synthetic_dfs()` đã có ở test_ach_excel_export.py thay vì viết lại.
"""
import pandas as pd

from backend.services.ach.pipeline import xuat_excel
from tests.test_ach_excel_export import _synthetic_dfs


def _run_xuat_excel(tmp_path, dfs, **extra):
    calls: list[dict] = []
    output_path = str(tmp_path / 'doi_chieu_20260821.xlsx')
    xuat_excel(
        output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
        dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
        dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
        summary_callback=calls.append,
        **extra,
    )
    assert len(calls) == 1, 'summary_callback phải được gọi đúng 1 lần'
    return calls[0]


def test_summary_khop_va_thieu_khop_dung_so_luong_va_so_tien(tmp_path):
    dfs = _synthetic_dfs()
    summary = _run_xuat_excel(tmp_path, dfs)

    # Theo _synthetic_dfs(): df_mis_di_khop 1 dòng SO_TIEN=1_000_000, v.v.
    assert summary['khop_npo_di']       == 1
    assert summary['tien_khop_npo_di']  == 1_000_000
    assert summary['khop_npo_den']      == 1
    assert summary['tien_khop_npo_den'] == 400_000
    assert summary['timeout']           == 1
    assert summary['tien_timeout']      == 300_000

    # thua_di = NPO_đi thừa (CRAMOUNT=500_000) + MIS_đi thừa (SO_TIEN=200_000).
    assert summary['thua_di']      == 1 + 1
    assert summary['tien_thua_di'] == 500_000 + 200_000
    # thua_den = NPO_đến thừa (DRAMOUNT=100_000) + MIS_đến thừa (SO_TIEN=150_000).
    assert summary['thua_den']      == 1 + 1
    assert summary['tien_thua_den'] == 100_000 + 150_000


def test_summary_huy_trong_ngay_va_khac_ngay(tmp_path):
    dfs = _synthetic_dfs()
    summary = _run_xuat_excel(
        tmp_path, dfs,
        df_dien_huy_trong_ngay=dfs['df_dien_huy_trong_ngay'],
        df_dien_huy_khac_ngay=dfs['df_dien_huy_khac_ngay'],
    )

    # df_dien_huy_trong_ngay: 2 dòng CRAMOUNT [3_000_000, -3_000_000].
    assert summary['huy_trong_ngay']      == 2
    assert summary['tien_huy_trong_ngay'] == 0
    # df_dien_huy_khac_ngay: 1 dòng CRAMOUNT [-6_000_000].
    assert summary['huy_khac_ngay']      == 1
    assert summary['tien_huy_khac_ngay'] == -6_000_000


def test_summary_osb_khop_mac_dinh_0_khi_khong_co_file_qt(tmp_path):
    """Không truyền df_osb_di_khop/df_osb_den_khop (None mặc định, không có file
    QT) — summary vẫn trả về 0/0, không lỗi (None-safe qua _tong_tien)."""
    dfs = _synthetic_dfs()
    summary = _run_xuat_excel(tmp_path, dfs)

    assert summary['khop_osb_di']       == 0
    assert summary['tien_khop_osb_di']  == 0
    assert summary['khop_osb_den']      == 0
    assert summary['tien_khop_osb_den'] == 0


def test_summary_osb_khop_co_du_lieu(tmp_path):
    dfs = _synthetic_dfs()
    df_osb_di_khop  = pd.DataFrame({'SO_TIEN': [111_000, 222_000]})
    df_osb_den_khop = pd.DataFrame({'SO_TIEN': [333_000]})
    summary = _run_xuat_excel(
        tmp_path, dfs,
        df_osb_di_khop=df_osb_di_khop, df_osb_den_khop=df_osb_den_khop,
    )

    assert summary['khop_osb_di']       == 2
    assert summary['tien_khop_osb_di']  == 333_000
    assert summary['khop_osb_den']      == 1
    assert summary['tien_khop_osb_den'] == 333_000


def test_khong_truyen_summary_callback_van_chay_duoc(tmp_path):
    """summary_callback=None (mặc định) — xuat_excel() vẫn ghi file bình thường,
    không lỗi. Bảo đảm các test/caller cũ (không biết tham số mới) không bị vỡ."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260821.xlsx')

    xuat_excel(
        output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
        dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
        dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
    )

    import openpyxl
    wb = openpyxl.load_workbook(output_path)
    assert 'TONG_KET' in wb.sheetnames
