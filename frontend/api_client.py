"""HTTP client kết nối tới FastAPI backend — token lưu per-user qua app.storage.user"""
import os
import httpx
from typing import Optional, Any, Dict
from nicegui import app
from dotenv import load_dotenv

load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


class SessionExpiredError(Exception):
    """Raised khi backend trả 401 — session đã hết hạn hoặc đã logout."""
    pass


class ViolationError(Exception):
    """Raised khi server trả 422 với danh sách user có name_5 ≠ 0."""
    def __init__(self, message: str, violations: list):
        super().__init__(message)
        self.violations = violations  # [{"user_code", "name_5", "system"}]

# Persistent client — tái dùng TCP connection, tránh overhead kết nối mỗi request
_client = httpx.Client(timeout=httpx.Timeout(10.0))
_download_client = httpx.Client(timeout=httpx.Timeout(60.0))


def set_token(token: str, user: dict):
    app.storage.user["token"] = token
    app.storage.user["user_data"] = user


def get_current_user() -> Optional[Dict]:
    return app.storage.user.get("user_data")


def clear_auth():
    app.storage.user.pop("token", None)
    app.storage.user.pop("user_data", None)
    app.storage.user.pop("features", None)


def load_my_features() -> None:
    """Gọi sau login. Lưu features vào app.storage.user['features'].
    features=None → admin (all-access). features=[] → không có nhóm nào.
    """
    try:
        result = get("/api/auth/my-features")
        app.storage.user["features"] = result.get("features")  # None hoặc list[str]
    except Exception:
        app.storage.user["features"] = []  # safe fallback


def has_feature(code: str) -> bool:
    """Kiểm tra user có feature code này không.
    Admin (features=None) → True cho mọi code.
    """
    user = get_current_user()
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    features = app.storage.user.get("features")
    if features is None:
        # Chưa load hoặc admin — check role thêm lần nữa
        return user.get("role") == "admin"
    return code in features


def get_all_features() -> list:
    """GET /api/groups/features/all — danh sách feature definitions theo nhóm."""
    return get("/api/groups/features/all")


def login(username: str, password: str, client_ip: str = None, force: bool = False) -> Any:
    """Login without an existing token. Passes real browser IP via X-Client-IP."""
    headers = {"Content-Type": "application/json"}
    if client_ip:
        headers["X-Client-IP"] = client_ip
    try:
        r = _client.post(
            f"{BACKEND_URL}/api/auth/login",
            headers=headers,
            json={"username": username, "password": password, "force": force},
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise Exception(_parse_error(e))
    except Exception as e:
        raise Exception(str(e))


def logout_session() -> None:
    """Notify backend to clear the session. Ignores errors (token may already be invalid)."""
    try:
        _client.post(
            f"{BACKEND_URL}/api/auth/logout",
            headers=_headers(),
            json={},
        )
    except Exception:
        pass


def _headers():
    h = {"Content-Type": "application/json"}
    token = app.storage.user.get("token")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _parse_error(e: "httpx.HTTPStatusError") -> str:
    try:
        body = e.response.json()
    except Exception:
        return str(e)
    detail = body.get("detail", "")
    if isinstance(detail, list):
        parts = []
        for err in detail:
            loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query")]
            msg = err.get("msg", "")
            parts.append(f"{'.'.join(loc)}: {msg}" if loc else msg)
        return "; ".join(parts) or str(e)
    return str(detail) or str(e)


def _raise_http_error(e: httpx.HTTPStatusError):
    if e.response.status_code == 401:
        clear_auth()
        raise SessionExpiredError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
    if e.response.status_code == 422:
        try:
            detail = e.response.json().get("detail", "")
            if isinstance(detail, dict) and "violations" in detail:
                raise ViolationError(detail.get("message", "Vi phạm dữ liệu"), detail["violations"])
        except ViolationError:
            raise
        except Exception:
            pass
    raise Exception(_parse_error(e))


def get(path: str, params: dict = None) -> Any:
    try:
        r = _client.get(f"{BACKEND_URL}{path}", headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        _raise_http_error(e)
    except Exception as e:
        raise Exception(str(e))


def post(path: str, data: dict = None) -> Any:
    try:
        r = _client.post(f"{BACKEND_URL}{path}", headers=_headers(), json=data)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        _raise_http_error(e)
    except Exception as e:
        raise Exception(str(e))


def put(path: str, data: dict = None) -> Any:
    try:
        r = _client.put(f"{BACKEND_URL}{path}", headers=_headers(), json=data)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        _raise_http_error(e)
    except Exception as e:
        raise Exception(str(e))


def patch(path: str, data: dict = None) -> Any:
    try:
        r = _client.patch(f"{BACKEND_URL}{path}", headers=_headers(), json=data)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {}
    except httpx.HTTPStatusError as e:
        _raise_http_error(e)
    except Exception as e:
        raise Exception(str(e))


def delete(path: str) -> Any:
    try:
        r = _client.delete(f"{BACKEND_URL}{path}", headers=_headers())
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {}
    except httpx.HTTPStatusError as e:
        _raise_http_error(e)
    except Exception as e:
        raise Exception(str(e))


def post_upload_bytes(path: str, files: dict) -> bytes:
    """Multipart POST, nhận bytes response (ZIP, Excel…). Dùng cho generate-dept-zip."""
    try:
        h = {k: v for k, v in _headers().items() if k != "Content-Type"}
        r = _download_client.post(f"{BACKEND_URL}{path}", headers=h, files=files)
        r.raise_for_status()
        return r.content
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            clear_auth()
            raise SessionExpiredError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
        try:
            body = e.response.json()
            detail = body.get("detail", "")
            if isinstance(detail, dict):
                if "violations" in detail:
                    raise ViolationError(
                        detail.get("message", "Vi phạm dữ liệu"),
                        detail["violations"],
                    )
                raise Exception(detail.get("message", str(detail)))
            raise Exception(str(detail) or e.response.text)
        except (SessionExpiredError, ViolationError):
            raise
        except Exception as inner:
            raise Exception(str(inner))
    except Exception as e:
        raise Exception(str(e))


def post_upload(path: str, files: dict, data: dict = None) -> Any:
    """Gửi multipart/form-data (file upload). files = {'field': (name, bytes, mime)}"""
    try:
        h = {k: v for k, v in _headers().items() if k != "Content-Type"}
        r = _download_client.post(f"{BACKEND_URL}{path}", headers=h, files=files, data=data or {})
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        _raise_http_error(e)
    except Exception as e:
        raise Exception(str(e))


def post_download(path: str, data: dict = None) -> bytes:
    """POST với JSON body, nhận bytes (Excel/Word)."""
    try:
        r = _download_client.post(f"{BACKEND_URL}{path}", headers=_headers(), json=data or {})
        r.raise_for_status()
        return r.content
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            clear_auth()
            raise SessionExpiredError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
        raise Exception(e.response.text)
    except Exception as e:
        raise Exception(str(e))


def download(path: str, params: dict = None) -> bytes:
    """Download file (docx, xlsx, etc.)"""
    try:
        r = _download_client.get(f"{BACKEND_URL}{path}", headers=_headers(), params=params)
        r.raise_for_status()
        return r.content
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            clear_auth()
            raise SessionExpiredError("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
        raise Exception(e.response.text)
    except Exception as e:
        raise Exception(str(e))
