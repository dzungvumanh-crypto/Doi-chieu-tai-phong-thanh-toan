r"""Chấm 459901 — chọn NHIỀU file ZIP trong một lượt.

Điểm cốt lõi cần canh: nhiều file được GỘP rồi mới phân loại. Cặp Cancel/Normal
của một lệnh hủy có thể nằm ở hai file khác nhau (GL02 xuất theo ngày); chạy
tách từng file thì cả hai vế rơi nhầm vào "Lệnh Khác" mà không có lỗi nào.

Chạy: .venv\Scripts\python.exe -m pytest tests/test_cham459901_nhieu_zip.py -v
"""

import io
import time

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
    """Mật khẩu ZIP giả + thư mục kết quả nằm trong tmp_path (test tự dọn)."""
    global _thu_muc
    monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', _MK)
    monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path / 'temp_cham459901')
    _thu_muc = tmp_path / 'upload'
    _thu_muc.mkdir()
    svc._progress.clear()
    yield
    svc._progress.clear()


# ── Service ───────────────────────────────────────────────────────────────────

def test_gop_nhieu_zip_moi_bat_duoc_lenh_huy_nam_o_hai_file():
    a = _zip([_dong(TRTP='Normal', DRAMOUNT='100', CRAMOUNT='0')])
    b = _zip([_dong(TRTP='Cancel', DRAMOUNT='0', CRAMOUNT='100'),
              _dong(TRTP='Normal', REFERENCE='R2', REMARK='le loi',
                    DRAMOUNT='50', CRAMOUNT='0')])

    # Từng file một: không file nào có đủ cả hai vế → không có lệnh hủy nào
    assert svc.process_files([_tep('a.zip', a)])['huy_rows'] == 0
    assert svc.process_files([_tep('b.zip', b)])['huy_rows'] == 0

    # Gộp một lượt: cặp Cancel/Normal khớp key → 2 dòng vào Lệnh Hủy
    r = svc.process_files([_tep('a.zip', a), _tep('b.zip', b)])
    assert r['huy_rows'] == 2
    assert r['n_files'] == 2
    assert r['total_rows'] == 3


def test_loi_kem_ten_file_de_biet_bo_file_nao_ra():
    tot = _zip([_dong()])
    with pytest.raises(svc.InputError, match=r"hong\.zip"):
        svc.process_files([_tep('tot.zip', tot), _tep('hong.zip', b'khong phai zip')])


def test_zip_khong_co_csv_bao_dung_ten_file():
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w') as zf:
        zf.writestr('doc.txt', b'x')
    with pytest.raises(svc.InputError, match=r"rong\.zip.*\.csv"):
        svc.process_files([_tep('rong.zip', buf.getvalue())])


def test_thieu_cot_o_mot_file_bi_bat_thay_vi_thanh_o_rong():
    """Gộp trước rồi mới kiểm cột thì file thiếu cột chỉ thành ô rỗng — lọt lưới."""
    csv = 'TRDATE,LOCAC,CUSTOMER\n20260801,459901,1000-000007709'
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_MK.encode())
        zf.writestr('thieu.csv', csv.encode('utf-8-sig'))
    thieu = buf.getvalue()

    with pytest.raises(svc.InputError, match=r"thieu\.zip.*thiếu cột bắt buộc"):
        svc.process_files([_tep('day_du.zip', _zip([_dong()])), _tep('thieu.zip', thieu)])


# ── API ───────────────────────────────────────────────────────────────────────

def _cho_xong(client, token, giay=20):
    het = time.time() + giay
    while time.time() < het:
        prog = client.get(f'/api/cham459901/progress/{token}').json()
        if prog['done']:
            return prog
        time.sleep(0.1)
    pytest.fail('Xử lý không kết thúc trong thời gian chờ')


def test_api_nhan_nhieu_file_trong_mot_lan_goi(admin_client):
    a = _zip([_dong(TRTP='Normal')])
    b = _zip([_dong(TRTP='Cancel', DRAMOUNT='0', CRAMOUNT='100')])
    r = admin_client.post('/api/cham459901/process', files=[
        ('files', ('a.zip', a, 'application/zip')),
        ('files', ('b.zip', b, 'application/zip')),
    ])
    assert r.status_code == 200, r.text

    prog = _cho_xong(admin_client, r.json()['task_token'])
    assert prog['error'] is None, prog['error']
    assert prog['result']['n_files'] == 2
    assert prog['result']['huy_rows'] == 2


def test_api_chan_chon_trung_mot_file_hai_lan(admin_client):
    z = _zip([_dong()])
    r = admin_client.post('/api/cham459901/process', files=[
        ('files', ('a.zip', z, 'application/zip')),
        ('files', ('a.zip', z, 'application/zip')),
    ])
    assert r.status_code == 400
    assert 'hai lần' in r.json()['detail']


def test_api_van_chay_voi_dung_mot_file(admin_client):
    r = admin_client.post('/api/cham459901/process', files=[
        ('files', ('a.zip', _zip([_dong()]), 'application/zip')),
    ])
    assert r.status_code == 200, r.text
    prog = _cho_xong(admin_client, r.json()['task_token'])
    assert prog['error'] is None, prog['error']
    assert prog['result']['n_files'] == 1
