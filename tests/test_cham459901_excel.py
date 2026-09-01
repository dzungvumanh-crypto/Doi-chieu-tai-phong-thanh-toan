r"""Chấm 459901 — nhận thêm file Excel bên cạnh ZIP.

Điểm cốt lõi cần canh:
  * Excel và ZIP gộp chung được — cặp Cancel/Normal nằm ở hai nguồn khác nhau
    vẫn phải khớp thành Lệnh Hủy;
  * ô số trong Excel không được biến thành "459901.0" — lệch một ký tự là bộ
    lọc TK 459901 loại sạch mọi dòng, kết quả 0 dòng mà KHÔNG có lỗi nào;
  * sheet thiếu cột phải báo lỗi, không được lặng lẽ bỏ qua.

Chạy: .venv\Scripts\python.exe -m pytest tests/test_cham459901_excel.py -v
"""

import io
import time

import openpyxl
import pytest
import pyzipper

from backend.services import cham459901_service as svc

_MK = "matkhau-test-459901"

_COLS = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
         'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
         'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']


def _dong(**ghi_de) -> dict:
    d = {c: '' for c in _COLS}
    d.update({
        'TRDATE': '20260801', 'TRBRCD': '001', 'USERID': 'u1', 'JOURSEQ': '1',
        'DYTRSEQ': '9', 'LOCAC': svc.FILTER_LOCAC, 'CCY': svc.FILTER_CCY,
        'CUSTOMER': svc.FILTER_CUSTOMER, 'TRTP': 'Normal', 'REFERENCE': 'R1',
        'REMARK': 'ghi chu', 'DRAMOUNT': '100', 'CRAMOUNT': '0',
        'CRTDTM': '20260801120000',
    })
    d.update(ghi_de)
    return d


def _xlsx(rows: list[dict], cols: list[str] | None = None,
          dong_thua: int = 0, so_thuc: bool = False) -> bytes:
    """Dựng 1 workbook 1 sheet. `dong_thua` = số dòng tiêu đề báo cáo chèn lên trên."""
    cols = cols or _COLS
    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(dong_thua):
        ws.append([f'BAO CAO GL02 - dong thua {i + 1}'])
    ws.append(cols)
    for r in rows:
        # so_thuc=True: ghi các ô mã số dưới dạng SỐ, đúng như khi người dùng
        # mở CSV bằng Excel rồi lưu lại — Excel tự nuốt số 0 đứng đầu và đổi
        # kiểu ô. Đây là đường dễ sinh "459901.0" nhất.
        ws.append([
            int(r[c]) if so_thuc and c in ('LOCAC', 'DYTRSEQ') and str(r[c]).isdigit()
            else r[c]
            for c in cols
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip(rows: list[dict], ten_csv: str = 'gl02.csv') -> bytes:
    csv = ','.join(_COLS) + '\n' + '\n'.join(
        ','.join(str(r[c]) for c in _COLS) for r in rows
    )
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_MK.encode())
        zf.writestr(ten_csv, csv.encode('utf-8-sig'))
    return buf.getvalue()


# `process_files()` nhận ĐƯỜNG DẪN file đã nằm trên máy chủ, không nhận bytes —
# API ghi thẳng từng khối xuống `data/temp_cham459901/upload_<token>/` rồi mới
# gọi xử lý. Helper này dựng đúng cảnh đó: đổ bytes ra file rồi đưa đường dẫn.
_thu_muc = None      # đặt bởi fixture _moi_truong


def _tep(ten: str, data: bytes):
    """(tên người dùng chọn, đường dẫn trên đĩa) — đúng dạng process_files() nhận."""
    p = _thu_muc / ten
    p.write_bytes(data)
    return ten, p


@pytest.fixture(autouse=True)
def _moi_truong(tmp_path, monkeypatch):
    global _thu_muc
    monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', _MK)
    monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path / 'temp_cham459901')
    _thu_muc = tmp_path / 'upload'
    _thu_muc.mkdir()
    svc._progress.clear()
    yield
    svc._progress.clear()


# ── Service ───────────────────────────────────────────────────────────────────

def test_excel_chay_duoc_nhu_zip():
    r = svc.process_files([_tep('gl02.xlsx', _xlsx([_dong()]))])
    assert r['total_rows'] == 1
    assert r['huy_rows'] + r['di_rows'] + r['khac_rows'] == 1
    assert r['filtered_rows'] == 0        # không dòng nào bị lọc oan


def test_o_kieu_so_khong_bien_thanh_459901_cham_0():
    """LOCAC ghi dạng số mà đọc ra '459901.0' thì bộ lọc loại sạch, im lặng."""
    r = svc.process_files([_tep('so.xlsx', _xlsx([_dong()], so_thuc=True))])
    assert r['filtered_rows'] == 0
    assert r['total_rows'] == 1


def test_gop_excel_voi_zip_bat_duoc_lenh_huy_nam_o_hai_nguon():
    z = _zip([_dong(TRTP='Normal', DRAMOUNT='100', CRAMOUNT='0')])
    x = _xlsx([_dong(TRTP='Cancel', DRAMOUNT='0', CRAMOUNT='100')])

    assert svc.process_files([_tep('a.zip', z)])['huy_rows'] == 0
    assert svc.process_files([_tep('b.xlsx', x)])['huy_rows'] == 0

    r = svc.process_files([_tep('a.zip', z), _tep('b.xlsx', x)])
    assert r['huy_rows'] == 2
    assert r['n_files'] == 2


def test_bo_qua_dong_tieu_de_bao_cao_o_tren_cung():
    r = svc.process_files([_tep('co_tieu_de.xlsx', _xlsx([_dong()], dong_thua=3))])
    assert r['total_rows'] == 1


def test_sheet_thieu_cot_bao_ro_ten_file_va_ten_sheet():
    thieu = _xlsx([_dong()], cols=['TRDATE', 'LOCAC', 'CUSTOMER'])
    with pytest.raises(svc.InputError, match=r"thieu\.xlsx.*sheet.*thiếu cột bắt buộc"):
        svc.process_files([_tep('day_du.xlsx', _xlsx([_dong()])), _tep('thieu.xlsx', thieu)])


def test_sai_han_loai_file_bao_khac_voi_thieu_vai_cot():
    """File chuyển tiền đi (cột tiếng Việt) không được báo "thiếu cột bắt buộc".

    Thiếu SẠCH 6 cột = cầm nhầm bảng. Báo "thiếu cột" thì người vận hành đi tìm
    cột trong một file vốn không bao giờ có.
    """
    khac = _xlsx([{'Ngày giao dịch': '01/08/2026', 'Số tiền': '100',
                   'Nội dung': 'CK'}],
                 cols=['Ngày giao dịch', 'Số tiền', 'Nội dung'])
    with pytest.raises(svc.InputError, match=r"không phải dữ liệu GL02.*Ngày giao dịch"):
        svc.process_files([_tep('chuyen_tien_di.xlsx', khac)])


def test_khoi_tieu_de_bao_cao_dai_van_do_ra_dong_tieu_de():
    """Bản người dùng tự lưu có thể có hơn 10 dòng tiêu đề báo cáo ở trên cùng."""
    r = svc.process_files([_tep('tieu_de_dai.xlsx', _xlsx([_dong()], dong_thua=15))])
    assert r['total_rows'] == 1


def test_file_hong_bao_loi_kem_ten_file():
    with pytest.raises(svc.InputError, match=r"hong\.xlsx"):
        svc.process_files([_tep('hong.xlsx', b'khong phai excel')])


def test_duoi_la_bi_chan():
    with pytest.raises(svc.InputError, match=r"la\.txt.*chỉ nhận"):
        svc.process_files([_tep('la.txt', b'x')])


def test_excel_nam_trong_zip_cung_doc_duoc():
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_MK.encode())
        zf.writestr('gl02.xlsx', _xlsx([_dong()]))
    assert svc.process_files([_tep('trong_zip.zip', buf.getvalue())])['total_rows'] == 1


# ── API ───────────────────────────────────────────────────────────────────────

_MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _cho_xong(client, token, giay=20):
    het = time.time() + giay
    while time.time() < het:
        prog = client.get(f'/api/cham459901/progress/{token}').json()
        if prog['done']:
            return prog
        time.sleep(0.1)
    pytest.fail('Xử lý không kết thúc trong thời gian chờ')


def test_api_nhan_excel(admin_client):
    r = admin_client.post('/api/cham459901/process', files=[
        ('files', ('gl02.xlsx', _xlsx([_dong()]), _MIME_XLSX)),
    ])
    assert r.status_code == 200, r.text
    prog = _cho_xong(admin_client, r.json()['task_token'])
    assert prog['error'] is None, prog['error']
    assert prog['result']['total_rows'] == 1


def test_api_chan_duoi_la_ngay_tu_dau(admin_client):
    r = admin_client.post('/api/cham459901/process', files=[
        ('files', ('bao_cao.pdf', b'%PDF-1.4', 'application/pdf')),
    ])
    assert r.status_code == 400
    assert 'chỉ nhận' in r.json()['detail']
