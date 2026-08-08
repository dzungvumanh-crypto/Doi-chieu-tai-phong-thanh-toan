"""
Luật nghiệp vụ ca trực — dùng chung cho cả sinh tự động và sửa tay.

Hai tầng luật:
  CỨNG — đúng 1 Lãnh đạo + 2 nhân viên. Vi phạm thì KHÔNG hình thành ca trực.
  MỀM  — đúng 1 người song phương, không xếp người đi dự án / vắng mặt.
          Vi phạm thì vẫn ghi nhận, chỉ cảnh báo.

Đặt riêng ở đây để engine (duty_scheduler_engine) và đường sửa tay
(duty_schedule_service) không thể lệch nhau về cách hiểu luật.
"""
import sqlite3
from typing import List, Optional, Tuple

from backend.services.duty_staff_service import get_all_staff, get_absent_staff_ids

SHIFT_MEMBER_COUNT = 2   # số nhân viên đi cùng Lãnh đạo trong 1 ca


# ══════════════════════════════════════════════════════════════
# VAI SONG PHƯƠNG
# ══════════════════════════════════════════════════════════════

def resolve_sp_role(leader: Optional[dict],
                    nvs: List[dict]) -> Tuple[Optional[dict], Optional[str]]:
    """
    Xác định ai giữ vai song phương trong ca.
    Trả (sp, sp_warning) — sp=None nghĩa là Lãnh đạo kiêm, hoặc cả ca không ai làm được.

      leader_sp  Lãnh đạo kiêm song phương (đúng 1 người — bình thường)
      multi_sp   Ca có nhiều hơn 1 người làm được song phương
      no_sp      Ca không có ai làm được song phương
      None       Một nhân viên giữ vai, đúng 1 người — bình thường
    """
    ld_la_sp = bool(leader and leader.get("can_do_sp"))
    nv_la_sp = [p for p in nvs if p.get("can_do_sp")]
    tong_sp  = (1 if ld_la_sp else 0) + len(nv_la_sp)

    if tong_sp == 0:
        return None, "no_sp"
    if ld_la_sp:
        return None, ("multi_sp" if tong_sp > 1 else "leader_sp")
    return nv_la_sp[0], ("multi_sp" if tong_sp > 1 else None)


# ══════════════════════════════════════════════════════════════
# KIỂM TRA THÀNH PHẦN CA
# ══════════════════════════════════════════════════════════════

def validate_shift_members(db: sqlite3.Connection, shift_date: str,
                           leader_id: Optional[int],
                           nv_ids: List[int]) -> Tuple[List[str], List[str], dict]:
    """
    Kiểm tra thành phần một ca trực.
    Trả (loi_cung, canh_bao, nguoi) — `nguoi` là dict {id: bản ghi nhân sự}
    để caller khỏi truy vấn lại.

    Có phần tử trong `loi_cung` → không được hình thành ca trực.
    `canh_bao` chỉ để hiển thị, không chặn.
    """
    nhan_su = {p["id"]: p for p in get_all_staff(db)}
    loi_cung: List[str] = []
    canh_bao: List[str] = []

    # ── Luật cứng: đúng 1 Lãnh đạo ──
    leader = nhan_su.get(leader_id) if leader_id else None
    if leader_id is None:
        loi_cung.append("Ca trực phải có 1 Lãnh đạo.")
    elif leader is None:
        loi_cung.append("Lãnh đạo được chọn không thuộc Phòng Thanh toán hoặc đã nghỉ việc.")
    elif leader["duty_role"] != "LD":
        loi_cung.append(f"{leader['full_name']} không phải Lãnh đạo — không thể xếp vào vị trí này.")

    # ── Luật cứng: đúng 2 nhân viên, không trùng nhau ──
    if len(nv_ids) != SHIFT_MEMBER_COUNT:
        loi_cung.append(f"Ca trực phải có đúng {SHIFT_MEMBER_COUNT} nhân viên "
                        f"(đang chọn {len(nv_ids)}).")
    if len(set(nv_ids)) != len(nv_ids):
        loi_cung.append("Không thể xếp cùng một người vào hai vị trí nhân viên.")
    if leader_id is not None and leader_id in nv_ids:
        loi_cung.append("Lãnh đạo không thể đồng thời là nhân viên trong cùng ca.")

    nvs: List[dict] = []
    for nid in nv_ids:
        p = nhan_su.get(nid)
        if p is None:
            loi_cung.append(f"Nhân viên id={nid} không thuộc Phòng Thanh toán hoặc đã nghỉ việc.")
            continue
        if p["duty_role"] != "NV":
            loi_cung.append(f"{p['full_name']} là Lãnh đạo — không thể xếp vào vị trí nhân viên.")
        nvs.append(p)

    if loi_cung:
        return loi_cung, canh_bao, nhan_su

    # ── Luật mềm ──
    vang_mat = get_absent_staff_ids(db, shift_date)
    for p in ([leader] if leader else []) + nvs:
        if p["is_on_project"]:
            canh_bao.append(f"{p['full_name']} đang đi dự án.")
        if p["id"] in vang_mat:
            canh_bao.append(f"{p['full_name']} đã khai vắng mặt ngày {shift_date}.")

    _, sp_warning = resolve_sp_role(leader, nvs)
    if sp_warning == "no_sp":
        canh_bao.append("Ca không có ai xử lý song phương.")
    elif sp_warning == "multi_sp":
        canh_bao.append("Ca có nhiều hơn 1 người xử lý song phương.")

    return loi_cung, canh_bao, nhan_su
