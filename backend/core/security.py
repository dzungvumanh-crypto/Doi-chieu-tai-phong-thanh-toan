"""JWT và password utilities"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from backend.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def _utcnow() -> datetime:
    """Giờ UTC dạng NAIVE — giống hệt datetime.utcnow() (bị đánh dấu bỏ từ 3.12).

    Cố ý KHÔNG trả về datetime có múi giờ: `exp` của JWT và các mốc giờ phiên
    đang so sánh/trừ với datetime naive ở nơi khác, trộn hai loại là TypeError.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = _utcnow() + (
        expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
