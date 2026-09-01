r"""File tải lên phải nằm trên đĩa TRƯỚC khi xử lý — 459901 và Đối chiếu song phương.

Vì sao đáng một file test riêng: cả hai tính năng từng nhận `bytes` và ôm trọn
file trong RAM suốt thời gian xử lý. Đổi sang đường dẫn là một thay đổi dễ bị
"sửa ngược" lúc refactor sau này — chỉ cần một chỗ gọi `zf.read()` thay
`zf.open()`, hoặc một chỗ `await read_limited()` mọc lại, là RAM quay về như cũ
mà **không có test nào đỏ và kết quả vẫn đúng y hệt**.

Đo được (27/08/2026): CSV 114 MB nằm trong ZIP, đọc bằng `zf.read()` đỉnh 256 MB,
đọc bằng `zf.open()` đỉnh 0,1 MB — cùng 900.000 dòng.

Chạy: .venv\Scripts\python.exe -m pytest tests/test_upload_ghi_ra_dia.py -v
"""

import io
import time
from pathlib import Path

import pyzipper
import pytest

from backend.services import cham459901_service as svc459
from backend.services import doi_chieu_song_phuong_service as svcsp

_MK = "matkhau-test-upload"

_COLS = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
         'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
         'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']


@pytest.fixture(autouse=True)
def _moi_truong(tmp_path, monkeypatch):
    monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', _MK)
    monkeypatch.setattr(svc459, 'TEMP_DIR', tmp_path / 'temp_cham459901')
    monkeypatch.setattr(svcsp, 'TEMP_DIR', tmp_path / 'temp_song_phuong')
    svc459._progress.clear()
    svcsp._progress.clear()
    yield
    svc459._progress.clear()
    svcsp._progress.clear()


def _zip459() -> bytes:
    d = {c: '' for c in _COLS}
    d.update({'TRDATE': '20260801', 'TRBRCD': '001', 'DYTRSEQ': '9',
              'LOCAC': svc459.FILTER_LOCAC, 'CCY': svc459.FILTER_CCY,
              'CUSTOMER': svc459.FILTER_CUSTOMER, 'TRTP': 'Normal',
              'REFERENCE': 'R1', 'DRAMOUNT': '100', 'CRAMOUNT': '0'})
    csv = ','.join(_COLS) + '\n' + ','.join(str(d[c]) for c in _COLS)
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_MK.encode())
        zf.writestr('gl02.csv', csv.encode('utf-8-sig'))
    return buf.getvalue()


def _cho_xong(client, url: str, token: str) -> dict:
    for _ in range(150):
        p = client.get(f"{url}/{token}").json()
        if p['done']:
            return p
        time.sleep(0.05)
    pytest.fail("chạy quá lâu, không xong")


# ── Chấm 459901 ──────────────────────────────────────────────────────────────

def test_459901_file_nam_tren_dia_dung_noi_dung_roi_moi_xu_ly(admin_client):
    """Byte của client phải xuống đĩa nguyên vẹn — đây là cả mục đích của thay đổi."""
    z = _zip459()
    r = admin_client.post('/api/cham459901/process',
                          files=[('files', ('gl02.zip', io.BytesIO(z), 'application/zip'))])
    assert r.status_code == 200
    token = r.json()['task_token']

    tren_dia = list((svc459.TEMP_DIR / f"upload_{token}").iterdir())
    assert [p.name for p in tren_dia] == ['gl02.zip']
    assert tren_dia[0].read_bytes() == z

    ket_qua = _cho_xong(admin_client, '/api/cham459901/progress', token)
    assert ket_qua['error'] is None
    assert ket_qua['result']['total_rows'] == 1


def test_459901_upload_hong_khong_de_lai_thu_muc_va_entry_ma(admin_client, monkeypatch):
    """Quên dọn ở đường lỗi thì mỗi lần upload hỏng để lại một thư mục và một
    lượt 'đang khởi tạo' không bao giờ chạy tới — không ai xoá được nữa."""
    monkeypatch.setattr('backend.core.uploads.MAX_REQUEST_BYTES', 10)
    monkeypatch.setattr('backend.api.cham459901.MAX_REQUEST_BYTES', 10)

    r = admin_client.post('/api/cham459901/process',
                          files=[('files', ('to.zip', io.BytesIO(b'x' * 500), 'application/zip'))])
    assert r.status_code == 413
    assert not list(svc459.TEMP_DIR.iterdir())
    assert svc459._progress == {}


def test_459901_bao_loi_bang_TEN_NGUOI_DUNG_CHON(admin_client):
    """Tên trên đĩa đã qua `safe_filename()` nên có thể khác tên người dùng thấy.
    Báo lỗi bằng tên đã cắt là bắt họ đi tìm một file không tồn tại."""
    r = admin_client.post(
        '/api/cham459901/process',
        files=[('files', ('bao cáo tháng 8.zip', io.BytesIO(b'khong phai zip'), 'application/zip'))])
    token = r.json()['task_token']
    ket_qua = _cho_xong(admin_client, '/api/cham459901/progress', token)
    assert 'bao cáo tháng 8.zip' in ket_qua['error']


# ── Đối chiếu song phương ────────────────────────────────────────────────────

def _zip_sp(so_dong: int = 3) -> bytes:
    cust = next(iter(svcsp.BANK_MAP))
    mau = {c: '' for c in svcsp.COLS}
    if 'CUSTOMER' in mau:
        mau['CUSTOMER'] = cust
    dong = ','.join(str(mau[c]) for c in svcsp.COLS)
    csv = ','.join(svcsp.COLS) + '\r\n' + '\r\n'.join([dong] * so_dong) + '\r\n'
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_MK.encode())
        zf.writestr('data.csv', csv.encode('utf-8-sig'))
    return buf.getvalue()


def test_song_phuong_file_nam_tren_dia_roi_moi_dinh_tuyen(admin_client):
    z = _zip_sp(3)
    r = admin_client.post('/api/doi_chieu_song_phuong/process',
                          files=[('file', ('sp.zip', io.BytesIO(z), 'application/zip'))])
    assert r.status_code == 200
    token = r.json()['task_token']

    tren_dia = list((svcsp.TEMP_DIR / f"upload_{token}").iterdir())
    assert [p.name for p in tren_dia] == ['sp.zip']
    assert tren_dia[0].read_bytes() == z

    ket_qua = _cho_xong(admin_client, '/api/doi_chieu_song_phuong/progress', token)
    assert ket_qua['error'] is None
    assert ket_qua['result']['total_rows'] == 3


def test_song_phuong_file_khong_phai_zip_van_bao_dung_loi(admin_client):
    """Cửa magic bytes nay đọc 4 byte đầu TỪ FILE thay vì từ bytes trong RAM.
    Đọc hụt chỗ này thì người chọn nhầm file PDF sẽ nhận lỗi giải nén khó hiểu."""
    r = admin_client.post('/api/doi_chieu_song_phuong/process',
                          files=[('file', ('gia.zip', io.BytesIO(b'%PDF-1.4 xin chao'),
                                           'application/zip'))])
    token = r.json()['task_token']
    ket_qua = _cho_xong(admin_client, '/api/doi_chieu_song_phuong/progress', token)
    assert 'không phải định dạng ZIP' in ket_qua['error']


# ── CSV bên trong ZIP phải đọc theo luồng ────────────────────────────────────

@pytest.fixture
def cam_doc_ca_file(monkeypatch):
    """Làm `zf.read()` nổ tung. Code đọc CSV theo luồng (`zf.open()`) chạy qua bình
    thường; code nạp cả file giải nén vào RAM sẽ hỏng ngay — chứ không âm thầm tốn
    bộ nhớ như trước, vì kết quả trả ra vẫn đúng y hệt trong cả hai trường hợp."""
    def cam(self, *a, **k):
        raise AssertionError(
            "zf.read() nạp cả file giải nén vào RAM (đo được 256 MB cho một CSV "
            "114 MB) — dùng zf.open() để đọc theo luồng."
        )
    monkeypatch.setattr(pyzipper.AESZipFile, "read", cam)


def test_song_phuong_doc_csv_trong_zip_theo_luong(admin_client, cam_doc_ca_file):
    """`_route_file()` chỉ đi tuần tự từng dòng nên không bao giờ cần nhìn lại
    dòng đã qua — `zf.open()` là đủ."""
    r = admin_client.post('/api/doi_chieu_song_phuong/process',
                          files=[('file', ('sp.zip', io.BytesIO(_zip_sp(3)), 'application/zip'))])
    ket_qua = _cho_xong(admin_client, '/api/doi_chieu_song_phuong/progress',
                        r.json()['task_token'])
    assert ket_qua['error'] is None
    assert ket_qua['result']['total_rows'] == 3


def test_459901_doc_csv_trong_zip_theo_luong(admin_client, cam_doc_ca_file):
    """Cùng lý do. Workbook Excel bên trong ZIP thì vẫn phải qua `zf.read()`
    (calamine đọc nhảy vị trí) — test này chỉ đi nhánh CSV."""
    r = admin_client.post('/api/cham459901/process',
                          files=[('files', ('gl02.zip', io.BytesIO(_zip459()), 'application/zip'))])
    ket_qua = _cho_xong(admin_client, '/api/cham459901/progress', r.json()['task_token'])
    assert ket_qua['error'] is None
    assert ket_qua['result']['total_rows'] == 1
