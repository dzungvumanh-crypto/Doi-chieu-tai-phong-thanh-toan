"""Phân biệt "máy chủ không trả lời" với "máy chủ trả lời rằng hỏng".

Trang Chấm đối chiếu ACH dựa vào phân biệt này để quyết định hai việc ngược nhau:

  - im lặng (hết giờ chờ, đứt kết nối) → job RẤT CÓ THỂ VẪN ĐANG CHẠY, phải giữ
    nút Dừng và CHẶN lượt chạy mới, nếu không sẽ có hai pipeline song song
    (đúng sự cố 19/08/2026: lần 1 mất liên lạc, lần 2 không phản hồi);
  - trả lời 404 "job đã hết hạn" → câu trả lời dứt khoát, dừng thử lại ngay và
    cho chạy lượt mới.

Chỗ dễ vỡ: `get()` để nguyên kiểu lỗi httpx, còn `post()/put()/patch()` lại gói
mọi thứ thành `Exception` thường. Ai đó "dọn cho đồng bộ" bằng cách thêm
`except Exception` vào `get()` sẽ làm `la_loi_mang()` luôn trả False — bảo vệ ở
trên lặng lẽ đảo ngược, không test nào đỏ. Test này canh đúng chỗ đó.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_ach_mat_lien_lac.py -v
"""
import httpx
import pytest

import frontend.api_client as api


@pytest.mark.parametrize('loi', [
    httpx.ReadTimeout('timed out'),      # đúng lỗi thấy trên màn hình 19/08/2026
    httpx.ConnectTimeout('timed out'),
    httpx.ConnectError('connection refused'),
    httpx.RemoteProtocolError('server disconnected'),
])
def test_may_chu_khong_tra_loi_la_loi_mang(loi):
    assert api.la_loi_mang(loi) is True


@pytest.mark.parametrize('loi', [
    Exception('Job không tồn tại hoặc đã hết hạn.'),   # 404 sau khi get() gói lại
    api.SessionExpiredError('Phiên đăng nhập đã hết hạn.'),
    ValueError('lỗi lập trình'),
])
def test_may_chu_co_tra_loi_thi_khong_phai_loi_mang(loi):
    assert api.la_loi_mang(loi) is False


def test_get_khong_duoc_nuot_kieu_loi_cua_httpx(monkeypatch):
    """Chốt chặn thật: gọi `api.get()` với máy chủ hết giờ chờ thì kiểu lỗi httpx
    phải còn nguyên khi ra tới nơi gọi."""
    def _het_gio(*a, **kw):
        raise httpx.ReadTimeout('timed out')

    monkeypatch.setattr(api._client, 'get', _het_gio)
    monkeypatch.setattr(api, '_headers', lambda: {})

    with pytest.raises(Exception) as e:
        api.get('/api/ach/poll/abc')

    assert api.la_loi_mang(e.value), (
        'api.get() đã nuốt mất kiểu lỗi httpx — trang ACH sẽ tưởng máy chủ đã trả '
        'lời dứt khoát và cho chạy lượt thứ hai chồng lên lượt đang chạy.'
    )
