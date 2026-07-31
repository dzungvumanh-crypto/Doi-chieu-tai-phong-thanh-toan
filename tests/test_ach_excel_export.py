"""
Test lớp xuất Excel của pipeline ACH (`xuat_excel()`), tập trung vào phần mới
wiring Requirement C.1a (GW-thừa, `tim_nhom_gw_thua()`) vào 2 sheet Excel
GW_THUA_XAC_DINH / GW_CAN_DOI_CHIEU (xem Implementation-notes.html mục 41 và
pipeline.py::xuat_excel).

Không mock — ghi file .xlsx thật ra tmp_path rồi đọc lại bằng openpyxl, đúng
nguyên tắc "không mock I/O" của skill doi-chieu.
"""
import pandas as pd
import openpyxl

from backend.services.ach.pipeline import xuat_excel


def _synthetic_dfs():
    df_mis_di_khop = pd.DataFrame({'CHI_NHANH': ['0001'], 'SO_TIEN': [1_000_000]})
    df_npo_di_thua = pd.DataFrame({'CRAMOUNT': [500_000]})
    df_mis_di_thua = pd.DataFrame({'SO_TIEN': [200_000], 'LOAI_LENH_OSB': ['']})
    df_timeout     = pd.DataFrame({'SO_TIEN': [300_000]})
    df_mis_den_khop  = pd.DataFrame({'SO_TIEN': [400_000]})
    df_npo_den_thua  = pd.DataFrame({'DRAMOUNT': [100_000]})
    df_mis_den_thua  = pd.DataFrame({'SO_TIEN': [150_000], 'LOAI_LENH_OSB': ['']})
    df_gw_raw = pd.DataFrame({
        'BRCD': ['0001', '0002'], 'STTLMAMT': [1_000_000, 2_000_000],
        'MSGREF': ['REF1', 'REF2'], 'SessionId': ['16282', '16282'],
        'PrcFlg': ['Lệnh Hoàn thành', 'Lệnh Hoàn thành'],
        'KEY_GW': ['00011000000', '00022000000'],
    })

    # C.1a — GW thừa xác định chắc chắn (COUNT_MIS == 0 cho nhóm đó): toàn GW.
    df_gw_thua_xac_dinh = pd.DataFrame({
        'BRCD': ['0003'], 'STTLMAMT': [777_000], 'MSGREF': ['REF3'],
        'SessionId': ['16282'], 'PrcFlg': ['Lệnh Hoàn thành'],
        'KEY_GW': ['00037770000'], 'SOURCE': ['GW'], 'NHOM_CN_TIEN': ['00037770000'],
    })

    # C.1a — cần đối chiếu thủ công: trộn dòng GW + dòng MIS cùng nhóm.
    df_gw_can_doi_chieu = pd.DataFrame({
        'BRCD': ['0004', None], 'STTLMAMT': [888_000, None],
        'MSGREF': ['REF4', 'REF5'], 'SessionId': ['16282', None],
        'PrcFlg': ['Lệnh Hoàn thành', None],
        'KEY_GW': ['00048880000', None],
        'CHI_NHANH': [None, '0004'], 'SO_TIEN': [None, 888_000],
        'CN tiền Hub': [None, '00048880000'],
        'SOURCE': ['GW', 'MIS'], 'NHOM_CN_TIEN': ['00048880000', '00048880000'],
    })

    # Điểm 3 — điện đi huỷ trong ngày (2 dòng đối ứng) / khác ngày (1 dòng Cancel).
    df_dien_huy_trong_ngay = pd.DataFrame({
        'TRBRCD': ['1240', '1240'], 'CRAMOUNT': [3_000_000, -3_000_000],
        'TRTP': ['Normal', 'Cancel'],
    })
    df_dien_huy_khac_ngay = pd.DataFrame({
        'TRBRCD': ['1300'], 'CRAMOUNT': [-6_000_000], 'TRTP': ['Cancel'],
    })

    return dict(
        df_mis_di_khop=df_mis_di_khop, df_npo_di_thua=df_npo_di_thua,
        df_mis_di_thua=df_mis_di_thua, df_timeout=df_timeout,
        df_mis_den_khop=df_mis_den_khop, df_npo_den_thua=df_npo_den_thua,
        df_mis_den_thua=df_mis_den_thua, df_gw_raw=df_gw_raw,
        df_gw_thua_xac_dinh=df_gw_thua_xac_dinh,
        df_gw_can_doi_chieu=df_gw_can_doi_chieu,
        df_dien_huy_trong_ngay=df_dien_huy_trong_ngay,
        df_dien_huy_khac_ngay=df_dien_huy_khac_ngay,
    )


def test_gw_thua_sheets_present(tmp_path):
    """2 sheet mới GW_THUA_XAC_DINH / GW_CAN_DOI_CHIEU phải xuất hiện trong Excel."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_gw_thua_xac_dinh=dfs['df_gw_thua_xac_dinh'],
               df_gw_can_doi_chieu=dfs['df_gw_can_doi_chieu'])

    wb = openpyxl.load_workbook(output_path)
    assert 'GW_THUA_XAC_DINH' in wb.sheetnames
    assert 'GW_CAN_DOI_CHIEU' in wb.sheetnames


def test_gw_thua_sheets_drop_internal_key_columns(tmp_path):
    """KEY_GW (và 'CN tiền Hub' ở sheet trộn) là cột khóa nội bộ, không xuất ra Excel."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_gw_thua_xac_dinh=dfs['df_gw_thua_xac_dinh'],
               df_gw_can_doi_chieu=dfs['df_gw_can_doi_chieu'])

    wb = openpyxl.load_workbook(output_path)
    header_xac_dinh = [c.value for c in next(wb['GW_THUA_XAC_DINH'].iter_rows(max_row=1))]
    header_can_doi  = [c.value for c in next(wb['GW_CAN_DOI_CHIEU'].iter_rows(max_row=1))]

    assert 'KEY_GW' not in header_xac_dinh
    assert 'KEY_GW' not in header_can_doi
    assert 'CN tiền Hub' not in header_can_doi
    # Cột nghiệp vụ vẫn còn đủ để đối chiếu tay.
    assert 'SOURCE' in header_xac_dinh and 'SOURCE' in header_can_doi
    assert 'NHOM_CN_TIEN' in header_can_doi


def test_tong_ket_reports_gw_thua_counts(tmp_path):
    """TONG_KET phải hiển thị đúng số dòng GW thừa xác định + cần đối chiếu thủ công."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_gw_thua_xac_dinh=dfs['df_gw_thua_xac_dinh'],
               df_gw_can_doi_chieu=dfs['df_gw_can_doi_chieu'])

    wb = openpyxl.load_workbook(output_path)
    ws = wb['TONG_KET']
    rows = {row[0].value: row[1].value for row in ws.iter_rows(min_row=2) if row[0].value}

    assert rows['GW thừa - xác định chắc chắn (C.1a)'] == len(dfs['df_gw_thua_xac_dinh'])
    assert rows['GW thừa - cần đối chiếu thủ công (C.1a)'] == len(dfs['df_gw_can_doi_chieu'])


def test_xuat_excel_khong_co_gw_thua_van_chay_duoc(tmp_path):
    """Khi không truyền df_gw_thua_xac_dinh/df_gw_can_doi_chieu (None mặc định) —
    Excel vẫn xuất được, sheet hiển thị '(Không có dữ liệu)', không lỗi."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'])

    wb = openpyxl.load_workbook(output_path)
    assert 'GW_THUA_XAC_DINH' in wb.sheetnames
    assert 'GW_CAN_DOI_CHIEU' in wb.sheetnames
    ws = wb['TONG_KET']
    rows = {row[0].value: row[1].value for row in ws.iter_rows(min_row=2) if row[0].value}
    assert rows['GW thừa - xác định chắc chắn (C.1a)'] == 0
    assert rows['GW thừa - cần đối chiếu thủ công (C.1a)'] == 0


# ── Điểm 3 (2026-07-31) — sheet DIEN_DI_HUY_TRONG_NGAY / DIEN_DI_HUY_KHAC_NGAY ──

def test_dien_huy_sheets_present(tmp_path):
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260731.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_dien_huy_trong_ngay=dfs['df_dien_huy_trong_ngay'],
               df_dien_huy_khac_ngay=dfs['df_dien_huy_khac_ngay'])

    wb = openpyxl.load_workbook(output_path)
    assert 'DIEN_DI_HUY_TRONG_NGAY' in wb.sheetnames
    assert 'DIEN_DI_HUY_KHAC_NGAY' in wb.sheetnames
    assert wb['DIEN_DI_HUY_TRONG_NGAY'].max_row == 3  # header + 2 dòng, KHÔNG có dòng tổng
    assert wb['DIEN_DI_HUY_KHAC_NGAY'].max_row == 3   # header + 1 dòng + 1 dòng TỔNG


def test_dien_huy_khac_ngay_co_dong_tong(tmp_path):
    """Sheet DIEN_DI_HUY_KHAC_NGAY phải kèm dòng TỔNG (số món + số tiền) cuối
    sheet — đúng yêu cầu PR gốc, khác DIEN_DI_HUY_TRONG_NGAY."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260731.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_dien_huy_khac_ngay=dfs['df_dien_huy_khac_ngay'])

    wb = openpyxl.load_workbook(output_path)
    ws = wb['DIEN_DI_HUY_KHAC_NGAY']
    dong_tong = [c.value for c in ws[3]]
    assert dong_tong[0] == 'TỔNG: 1 món'
    assert dong_tong[1] == '-6,000,000 VND'


def test_tong_ket_tach_dien_huy_khoi_npo_di_thua(tmp_path):
    """TONG_KET phải hiển thị đúng số dòng huỷ trong ngày/khác ngày, và Tổng NPO_DI
    phải cộng đủ cả 2 khoản huỷ (bảo toàn số học)."""
    dfs = _synthetic_dfs()
    output_path = str(tmp_path / 'doi_chieu_20260731.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_dien_huy_trong_ngay=dfs['df_dien_huy_trong_ngay'],
               df_dien_huy_khac_ngay=dfs['df_dien_huy_khac_ngay'])

    wb = openpyxl.load_workbook(output_path)
    ws = wb['TONG_KET']
    rows = {row[0].value: row[1].value for row in ws.iter_rows(min_row=2) if row[0].value}

    assert rows['  Điện đi huỷ trong ngày (đã tách khỏi NPO_DI thừa)'] == 2
    assert rows['  Điện đi huỷ khác ngày (đã tách khỏi NPO_DI thừa)'] == 1
    # NPO_DI thừa (1 dòng, CRAMOUNT=500_000 từ _synthetic_dfs) + 2 huỷ trong ngày
    # + 1 huỷ khác ngày = 4, cộng thêm 0 dòng khớp (không truyền n_di_khop thật ở
    # test này, df_mis_di_khop chỉ có cột CHI_NHANH/SO_TIEN không phải MSGREF khớp
    # đúng nghĩa) — kiểm tra đúng phép cộng của Tổng NPO_DI theo giá trị hiện có.
    n_di_khop = len(dfs['df_mis_di_khop'])
    n_npo_di_thua = len(dfs['df_npo_di_thua'])
    n_huy_trong_ngay = len(dfs['df_dien_huy_trong_ngay'])
    n_huy_khac_ngay = len(dfs['df_dien_huy_khac_ngay'])
    assert rows['Tổng NPO_DI (cần đối)'] == n_di_khop + n_npo_di_thua + n_huy_trong_ngay + n_huy_khac_ngay


# ── Điểm 4 (2026-07-31) — cột GHI_CHU_T2 trên NPO_DI_THUA/NPO_DEN_THUA ─────────

def test_ghi_chu_t2_xuat_hien_tren_npo_di_thua_va_npo_den_thua(tmp_path):
    dfs = _synthetic_dfs()
    dfs['df_npo_di_thua']  = dfs['df_npo_di_thua'].assign(GHI_CHU_T2=['Hạch toán lệnh ngày T-2'])
    dfs['df_npo_den_thua'] = dfs['df_npo_den_thua'].assign(GHI_CHU_T2=[''])
    output_path = str(tmp_path / 'doi_chieu_20260731.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'])

    wb = openpyxl.load_workbook(output_path)
    header_di  = [c.value for c in next(wb['NPO_DI_THUA'].iter_rows(max_row=1))]
    header_den = [c.value for c in next(wb['NPO_DEN_THUA'].iter_rows(max_row=1))]
    assert 'GHI_CHU_T2' in header_di
    assert 'GHI_CHU_T2' in header_den

    di_col = header_di.index('GHI_CHU_T2') + 1
    assert wb['NPO_DI_THUA'].cell(row=2, column=di_col).value == 'Hạch toán lệnh ngày T-2'


def test_ghi_chu_t2_khong_xuat_hien_tren_sheet_huy_diem_3(tmp_path):
    """GHI_CHU_T2 chỉ có ý nghĩa trên NPO_DI_THUA/NPO_DEN_THUA — 2 sheet huỷ của
    Điểm 3 không nên bị ảnh hưởng bởi wiring cột mới của Điểm 4."""
    dfs = _synthetic_dfs()
    dfs['df_npo_di_thua'] = dfs['df_npo_di_thua'].assign(GHI_CHU_T2=[''])
    output_path = str(tmp_path / 'doi_chieu_20260731.xlsx')

    xuat_excel(output_path, '16282', dfs['df_mis_di_khop'], dfs['df_npo_di_thua'],
               dfs['df_mis_di_thua'], dfs['df_timeout'], dfs['df_mis_den_khop'],
               dfs['df_npo_den_thua'], dfs['df_mis_den_thua'], dfs['df_gw_raw'],
               df_dien_huy_trong_ngay=dfs['df_dien_huy_trong_ngay'],
               df_dien_huy_khac_ngay=dfs['df_dien_huy_khac_ngay'])

    wb = openpyxl.load_workbook(output_path)
    header_trong_ngay = [c.value for c in next(wb['DIEN_DI_HUY_TRONG_NGAY'].iter_rows(max_row=1))]
    header_khac_ngay  = [c.value for c in next(wb['DIEN_DI_HUY_KHAC_NGAY'].iter_rows(max_row=1))]
    assert 'GHI_CHU_T2' not in header_trong_ngay
    assert 'GHI_CHU_T2' not in header_khac_ngay
