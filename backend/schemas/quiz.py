"""Schemas cho Ôn tập trắc nghiệm (Quizz)."""
import unicodedata
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _clean(v: Optional[str]) -> Optional[str]:
    """NFC + strip; chuỗi rỗng → None (cùng lý do với ttqt_branches._clean)."""
    if v is None:
        return None
    v = unicodedata.normalize("NFC", str(v)).strip()
    return v or None


# ── Bộ câu hỏi ────────────────────────────────────────────────────────────────
class QuizSetOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    source_file: Optional[str] = None
    question_count: int
    created_by_name: Optional[str] = None
    created_at: Optional[str] = None
    my_attempts: int = 0
    my_best_score: Optional[float] = None
    # Bài đang làm dở của CHÍNH người gọi (mỗi người mỗi bộ nhiều nhất một bài)
    resume_attempt_id: Optional[int] = None
    resume_answered: int = 0
    resume_total: int = 0
    resume_saved_at: Optional[str] = None


class QuizSetUpdate(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _need_name(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Tên bộ câu hỏi không được để trống")
        return v

    @field_validator("description")
    @classmethod
    def _opt(cls, v):
        return _clean(v)


class ImportResult(BaseModel):
    set_id: int
    name: str
    imported: int
    skipped: int
    errors: list[str] = []


# ── Cài đặt & lượt làm bài ────────────────────────────────────────────────────
class AttemptSettings(BaseModel):
    """Thông số thi thử. num_questions=0 nghĩa là lấy hết bộ.

    seconds_per_question / total_minutes = 0 nghĩa là không giới hạn — dùng 0
    thay cho None để một giá trị duy nhất diễn đạt "tắt", khỏi phải phân biệt
    None với 0 ở cả frontend lẫn backend.
    """
    mode: str = Field("practice", pattern="^(practice|exam)$")
    num_questions: int = Field(0, ge=0, le=1000)
    shuffle_questions: bool = True
    shuffle_options: bool = True
    seconds_per_question: int = Field(0, ge=0, le=3600)
    total_minutes: int = Field(0, ge=0, le=600)
    instant_feedback: bool = True


class AttemptCreate(BaseModel):
    set_id: int
    settings: AttemptSettings = AttemptSettings()


class QuestionOut(BaseModel):
    """Một câu trong đề đã sinh.

    `options` đã trộn sẵn; `no` của mỗi lựa chọn là số thứ tự GỐC trong DB nên
    chấm điểm không phụ thuộc thứ tự hiển thị. `correct_no` chỉ có ở chế độ ôn
    tập (xem docstring _questions_of_attempt trong backend/api/quiz.py).
    """
    item_id: int
    question_id: int
    order_no: int
    content: str
    options: list[dict]
    correct_no: Optional[int] = None
    chosen_no: Optional[int] = None


class AttemptOut(BaseModel):
    id: int
    set_id: int
    set_name: str
    mode: str
    status: str
    settings: AttemptSettings
    total_questions: int
    # Chỗ người làm đang đứng, để lần vào sau nối tiếp đúng câu đó
    current_idx: int = 0
    elapsed_ms: int = 0
    started_at: Optional[str] = None
    questions: list[QuestionOut] = []


class AnswerIn(BaseModel):
    item_id: int
    chosen_no: Optional[int] = Field(None, ge=1, le=4)
    time_ms: int = Field(0, ge=0)


class AttemptSubmit(BaseModel):
    answers: list[AnswerIn] = []
    duration_ms: int = Field(0, ge=0)


class ProgressIn(BaseModel):
    """Một lần lưu tiến độ giữa chừng.

    `answers` chỉ mang phần THAY ĐỔI kể từ lần lưu trước, không phải cả bài —
    bài 550 câu mà lần nào cũng gửi hết thì mỗi câu trả lời kéo theo ~20 KB.
    """
    answers: list[AnswerIn] = []
    current_idx: int = Field(0, ge=0)
    elapsed_ms: int = Field(0, ge=0)


class ResumeRow(BaseModel):
    """Một bài đang làm dở, dùng cho nút *Làm tiếp*."""
    id: int
    set_id: int
    set_name: str
    mode: str
    total_questions: int
    answered: int
    current_idx: int
    elapsed_ms: int
    started_at: Optional[str] = None
    saved_at: Optional[str] = None


class ReviewItem(BaseModel):
    order_no: int
    content: str
    options: list[dict]
    chosen_no: Optional[int] = None
    correct_no: int
    is_correct: bool
    time_ms: Optional[int] = None


class AttemptResult(BaseModel):
    id: int
    set_id: int
    set_name: str
    mode: str
    total_questions: int
    correct_count: int
    wrong_count: int
    skipped_count: int
    score: float
    duration_ms: int
    finished_at: Optional[str] = None
    review: list[ReviewItem] = []


class AttemptRow(BaseModel):
    """Một dòng trong lịch sử / bảng xếp hạng."""
    id: int
    set_id: int
    set_name: str
    staff_name: Optional[str] = None
    mode: str
    total_questions: int
    correct_count: Optional[int] = None
    score: Optional[float] = None
    duration_ms: Optional[int] = None
    finished_at: Optional[str] = None
