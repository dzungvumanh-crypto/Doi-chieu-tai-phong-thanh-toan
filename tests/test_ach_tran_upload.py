"""Hai cửa ải chặn trước khi nhận file ACH: trần dung lượng và "một phiên một lúc".

Vì sao đáng một file test riêng: khi trần ACH >= trần middleware thì
BodySizeLimitMiddleware chặn TRƯỚC, trả 413 rồi đóng kết nối lúc client còn
đang gửi. Client không đọc nổi cái 413 đó — nó chỉ thấy socket đứt và báo
"[WinError 10054] An existing connection was forcibly closed by the remote
host". Log máy chủ ghi 413, người dùng nhìn thấy lỗi Windows: hai bên nói hai
chuyện khác nhau, mất cả buổi mới lần ra (26/08/2026).

Cửa ải thứ hai ra đời cùng ngày, từ quan sát của người vận hành: lỗi thường
xảy ra khi phiên cũ CHƯA CHẠY XONG đã upload bộ file phiên mới. Hai pipeline
pandas cùng ôm vài trăm MB thì backend hết RAM và chết ngay giữa lúc nhận file
— cũng ra đúng một thông báo "[WinError 10054]" như trên, nhưng nguyên nhân
khác hẳn nên phải chặn bằng một cửa khác.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_ach_tran_upload.py -v
"""

import time

import pytest

from backend.api.ach import _MAX_UPLOAD
from backend.services import ach_service
from backend.core.uploads import MAX_REQUEST_BYTES


def test_tran_ach_nho_hon_tran_than_request():
    assert _MAX_UPLOAD < MAX_REQUEST_BYTES, (
        'Trần ACH phải nhỏ hơn trần thân request, nếu không middleware chặn trước '
        'và người dùng chỉ nhận được lỗi socket khó hiểu.'
    )


def test_validate_tra_ve_tran_de_frontend_chan_som(admin_client):
    """Frontend dựa vào `max_total_mb` để chặn trước khi gửi — thiếu field này là
    quay lại cảnh gửi hết vài trăm MB rồi mới đứt."""
    r = admin_client.post('/api/ach/validate', json={'filenames': ['GL02_x.zip']})
    assert r.status_code == 200
    assert r.json()['max_total_mb'] == _MAX_UPLOAD // (1024 * 1024) > 0


# ── Một phiên tại một thời điểm ──────────────────────────────────────────────

# `_jobs` được fixture autouse trong conftest dọn trước/sau mỗi test.

def test_dang_chay_bao_dung_job_dang_chiem_may_chu(admin_client):
    """Frontend hỏi endpoint này TRƯỚC khi gửi file — trả sai là nó gửi bừa."""
    assert admin_client.get('/api/ach/dang-chay').json()['job'] is None

    job_id, job = ach_service._new_job()
    job['status'] = 'running'
    res = admin_client.get('/api/ach/dang-chay').json()['job']
    assert res['job_id'] == job_id and res['status'] == 'running'

    # Job đã xong thì không chiếm máy chủ nữa — không được chặn lượt sau.
    job['status'] = 'done'
    assert admin_client.get('/api/ach/dang-chay').json()['job'] is None


@pytest.mark.parametrize('trang_thai', ['pending', 'running', 'awaiting_confirmation'])
def test_start_tu_choi_khi_dang_co_phien_khac(admin_client, trang_thai):
    """Chốt chặn thật nằm ở backend: F5 mất state, hay người khác bấm chạy, thì
    frontend không biết gì — chỉ backend biết."""
    job_id, job = ach_service._new_job()
    job['status'] = trang_thai

    r = admin_client.post(
        '/api/ach/start',
        files=[('files', ('GL02_x.zip', b'noi dung gia', 'application/octet-stream'))],
        data={'ngay_doi_chieu': '', 'bo_qua_checkpoint': 'false'},
    )
    assert r.status_code == 409
    detail = r.json()['detail']
    assert detail['job']['job_id'] == job_id
    assert job_id in detail['message']
    # Không được đẻ thêm job nào khi đã từ chối.
    assert len(ach_service._jobs) == 1


# ── "Dừng" phải dừng THẬT, và không được khoá chết tính năng ─────────────────

def test_gui_lenh_dung_chua_lam_may_chu_ranh_ngay(admin_client):
    """Nghe ngược đời nhưng đúng: bấm Dừng chỉ ĐẶT CỜ. Thread vẫn ôm nguyên dữ liệu
    cho tới khi nó ngó tới cờ ở ranh giới bước kế tiếp và tự kết thúc.

    Đây là lý do frontend phải chờ máy chủ báo rảnh rồi mới cho chạy phiên mới —
    tin vào "đã bấm Dừng rồi" là quay lại đúng cảnh hai bộ dữ liệu cùng trong RAM."""
    job_id, job = ach_service._new_job()
    job['status'] = 'running'

    assert admin_client.post(f'/api/ach/cancel/{job_id}').status_code == 200
    assert job['cancel_event'].is_set()
    assert admin_client.get('/api/ach/dang-chay').json()['job']['job_id'] == job_id

    # Chỉ khi thread thật sự kết thúc (_run đặt 'cancelled') máy chủ mới rảnh.
    job['status'] = 'cancelled'
    assert admin_client.get('/api/ach/dang-chay').json()['job'] is None


def test_dung_o_buoc_cho_xac_nhan_thi_ranh_ngay(admin_client):
    """Không có thread nào đang chạy → dừng là rảnh tức thì."""
    job_id, job = ach_service._new_job()
    job['status'] = 'awaiting_confirmation'

    assert admin_client.post(f'/api/ach/cancel/{job_id}').status_code == 200
    assert admin_client.get('/api/ach/dang-chay').json()['job'] is None


def test_phien_bo_do_qua_han_khong_khoa_chet_tinh_nang(admin_client):
    """Người dùng đóng trình duyệt lúc đang chờ xác nhận rồi đi mất: không ai dọn
    job đó (`_cleanup_old_jobs()` chỉ chạy ở finally của một job KHÁC). Quá hạn thì
    phải tự hết hiệu lực, nếu không cả tính năng khoá chết tới khi restart backend."""
    _, job = ach_service._new_job()
    job['status'] = 'awaiting_confirmation'
    job['_ts'] = time.time() - ach_service.CLEANUP_TTL - 1

    assert admin_client.get('/api/ach/dang-chay').json()['job'] is None
