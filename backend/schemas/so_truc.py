"""Schemas Sổ trực cuối ngày — Phòng Thanh toán.

Luồng: draft -> pending_gdv_confirm -> pending_ksv -> approved | rejected.
Xem docstring đầy đủ ở backend/services/so_truc_service.py.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SaveDraftIn(BaseModel):
    gdv1_id: Optional[int] = None
    gdv2_id: Optional[int] = None
    ghi_chu: str = ""


class ForwardKsvIn(BaseModel):
    gdv1_id: Optional[int] = None
    gdv2_id: Optional[int] = None
    ghi_chu: str = ""
    ksv_id: int


class RejectIn(BaseModel):
    reason: str


class SoTrucOut(BaseModel):
    truc_date: str
    gdv1_name: str
    gdv2_name: str
    ghi_chu: str
    status: str
    initiated_by: Optional[int] = None
    initiated_by_name: Optional[str] = None
    initiated_at: Optional[str] = None
    ksv_id: Optional[int] = None
    ksv_name: Optional[str] = None
    confirmed_by: Optional[int] = None
    confirmed_by_name: Optional[str] = None
    confirmed_at: Optional[str] = None
    ksv_decided_by: Optional[int] = None
    ksv_decided_by_name: Optional[str] = None
    ksv_decided_at: Optional[str] = None
    reject_reason: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class KsvCandidateOut(BaseModel):
    id: int
    full_name: str
