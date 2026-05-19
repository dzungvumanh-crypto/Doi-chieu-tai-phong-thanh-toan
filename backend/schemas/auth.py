from typing import Optional
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    force: bool = False  # override active session on another IP

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff_id: int
    full_name: str
    role: str
    department_id: Optional[int] = None
    must_change_password: bool = False

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

class AdminPasswordReset(BaseModel):
    staff_id: int
    new_password: str
