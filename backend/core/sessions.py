"""In-memory session store — tracks which IP each staff member is logged in from."""
from datetime import datetime, timedelta
from threading import Lock

_sessions: dict = {}  # staff_id (int) -> {"ip": str, "expires_at": datetime}
_lock = Lock()


def set_session(staff_id: int, ip: str, ttl_hours: int = 8) -> None:
    with _lock:
        _sessions[staff_id] = {
            "ip": ip,
            "expires_at": datetime.utcnow() + timedelta(hours=ttl_hours),
        }


def get_session_ip(staff_id: int) -> str | None:
    """Return the IP of the active session, or None if expired/absent."""
    with _lock:
        s = _sessions.get(staff_id)
        if not s:
            return None
        if datetime.utcnow() > s["expires_at"]:
            del _sessions[staff_id]
            return None
        return s["ip"]


def clear_session(staff_id: int) -> None:
    with _lock:
        _sessions.pop(staff_id, None)
