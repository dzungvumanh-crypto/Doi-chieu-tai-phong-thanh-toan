"""Schema dùng chung cho các module chạy pipeline nền qua job/token (ACH, ILO1000...) —
chế độ "chọn thư mục server" thay vì upload file."""
from pydantic import BaseModel


class FolderRequest(BaseModel):
    folder_path: str
