from pydantic import BaseModel, ConfigDict


class DepartmentOut(BaseModel):
    id: int
    code: str
    name: str
    is_source: bool
    is_active: bool
    model_config = ConfigDict(from_attributes=True)
