from pydantic import BaseModel


class DepartmentOut(BaseModel):
    id: int
    code: str
    name: str
    is_source: bool
    is_active: bool
    class Config: from_attributes = True
