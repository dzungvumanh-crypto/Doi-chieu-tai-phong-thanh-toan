"""Schemas cho Khảo sát (biểu mẫu kiểu Google Forms)."""
import unicodedata
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Loại câu hỏi — khoá ngắn lưu trong DB, nhãn tiếng Việt nằm ở frontend.
QTYPES = ("short_text", "paragraph", "single", "multi", "dropdown", "scale", "date")
CHOICE_TYPES = ("single", "multi", "dropdown")

_MAX_QUESTIONS = 200
_MAX_OPTIONS = 50


def _clean(v: Optional[str]) -> Optional[str]:
    """NFC + strip; chuỗi rỗng → None."""
    if v is None:
        return None
    v = unicodedata.normalize("NFC", str(v)).strip()
    return v or None


def chuan_hoa_thoi_diem(v: Optional[str]) -> Optional[str]:
    """'2026-09-20T17:00' / '2026-09-20 17:00[:00]' → '2026-09-20 17:00:00'.

    Lưu dạng chuỗi CỐ ĐỊNH 19 ký tự để so sánh thẳng bằng chuỗi trong SQL
    (`s.deadline >= ?`). Để sqlite3 tự đổi datetime thì có lúc kèm micro giây,
    có lúc không — so chuỗi giữa hai dạng đó cho kết quả sai ở đúng giây chót.
    """
    v = _clean(v)
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("T", " "))
    except ValueError:
        raise ValueError(f"Thời điểm không hợp lệ: '{v}' (cần YYYY-MM-DD HH:MM)")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── Định nghĩa câu hỏi ────────────────────────────────────────────────────────
class QuestionIn(BaseModel):
    qtype: str = Field(pattern="^(" + "|".join(QTYPES) + ")$")
    title: str
    description: Optional[str] = None
    required: bool = False
    options: list[str] = []
    scale_min: int = Field(1, ge=0, le=1)
    scale_max: int = Field(5, ge=2, le=10)
    scale_min_label: Optional[str] = None
    scale_max_label: Optional[str] = None

    @field_validator("title")
    @classmethod
    def _need_title(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Câu hỏi không được để trống nội dung")
        return v

    @field_validator("description", "scale_min_label", "scale_max_label")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @model_validator(mode="after")
    def _check_options(self):
        if self.qtype in CHOICE_TYPES:
            opts = [o for o in (_clean(x) for x in self.options) if o]
            if len(opts) < 2:
                raise ValueError(f"Câu «{self.title}»: cần ít nhất 2 lựa chọn")
            if len(opts) > _MAX_OPTIONS:
                raise ValueError(f"Câu «{self.title}»: tối đa {_MAX_OPTIONS} lựa chọn")
            # Trùng lựa chọn làm thống kê tách một ý thành hai cột — chặn luôn.
            if len({o.casefold() for o in opts}) != len(opts):
                raise ValueError(f"Câu «{self.title}»: có lựa chọn bị trùng")
            self.options = opts
        else:
            self.options = []
        return self


class SurveyIn(BaseModel):
    title: str
    description: Optional[str] = None
    is_anonymous: bool = False
    allow_edit: bool = False
    start_at: Optional[str] = None
    deadline: Optional[str] = None
    group_ids: list[int] = []
    questions: list[QuestionIn] = Field([], max_length=_MAX_QUESTIONS)

    @field_validator("title")
    @classmethod
    def _need_title(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Tên khảo sát không được để trống")
        return v

    @field_validator("description")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @field_validator("start_at", "deadline")
    @classmethod
    def _dt(cls, v):
        return chuan_hoa_thoi_diem(v)

    @model_validator(mode="after")
    def _order(self):
        if self.start_at and self.deadline and self.start_at >= self.deadline:
            raise ValueError("Thời điểm bắt đầu phải trước hạn chót")
        self.group_ids = sorted(set(self.group_ids))
        return self


# ── Trả lời ───────────────────────────────────────────────────────────────────
class AnswerIn(BaseModel):
    """`value` theo loại câu: chuỗi (văn bản / ngày), số thứ tự lựa chọn (0-based),
    danh sách số thứ tự (nhiều lựa chọn), hoặc số điểm (thang đo). Kiểm kỹ ở
    backend/services/survey_service.py::kiem_tra_tra_loi()."""
    question_id: int
    value: Any = None


class ResponseIn(BaseModel):
    answers: list[AnswerIn] = []
