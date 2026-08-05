"""Reverse-proxy /api/* — chuyển tiếp sang backend nội bộ qua đúng cổng frontend.

Một số máy chủ production chỉ mở tường lửa cổng FRONTEND (NiceGUI) ra máy
trạm, không mở cổng BACKEND (FastAPI) — ví dụ Extension CITAD chạy trên máy
trạm chỉ gọi được đúng 1 link chính thức (cổng frontend). Route ở đây cho
tiến trình frontend tự làm proxy sang backend chạy cùng máy (BACKEND_URL,
xem frontend/api_client.py) — máy trạm/Extension không cần biết cổng backend.
"""
import httpx
from nicegui import app
from starlette.requests import Request
from starlette.responses import Response

from frontend.api_client import BACKEND_URL

# Header hop-by-hop — không forward, để tầng ASGI/httpx tự tính lại đúng.
_HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding", "keep-alive"}

_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def _proxy_api(full_path: str, request: Request) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    # Backend thấy request này tới từ tiến trình frontend (localhost) — mất
    # IP thật của máy trạm/Extension nếu không gắn thêm. X-Client-IP là cơ
    # chế đã có sẵn cho đúng tình huống này (xem frontend/api_client.py,
    # backend/core/audit_queue.py::_real_ip) — GHI ĐÈ chứ không giữ giá trị
    # client tự gửi lên, để không ai giả mạo được IP trong audit_logs.
    headers["X-Client-IP"] = request.client.host if request.client else ""
    body = await request.body()

    upstream = await _client.request(
        request.method,
        f"{BACKEND_URL}/api/{full_path}",
        # request.query_params là multi-dict (1 key có thể lặp nhiều lần) —
        # truyền thẳng object này cho httpx sẽ bị hiểu như dict thường, MẤT
        # các giá trị trùng key, chỉ giữ lại giá trị cuối. multi_items() giữ
        # đúng toàn bộ cặp key-value kể cả key lặp lại (đã kiểm chứng qua test).
        params=list(request.query_params.multi_items()),
        headers=headers,
        content=body,
    )

    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
    )
