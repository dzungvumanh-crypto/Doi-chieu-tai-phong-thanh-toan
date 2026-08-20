"""
Luật nghiệp vụ ca trực — dùng chung cho cả sinh tự động và sửa tay.

Hai tầng luật:
  CỨNG — đủ đúng số Lãnh đạo / trực chính / trực phụ đã khai báo ở tab Cài đặt.
          Vi phạm thì KHÔNG hình thành ca trực.
  MỀM  — ít nhất 1 người song phương trong (Lãnh đạo + trực chính), không xếp
          người đi dự án / vắng mặt. Vi phạm thì vẫn ghi nhận, chỉ cảnh báo.

Đặt riêng ở đây để engine (duty_scheduler_engine) và đường sửa tay
(duty_schedule_service) không thể lệch nhau về cách hiểu luật.
"""
import json
import sqlite3
from datetime import date, timedelta
from typing import List, Optional, Tuple

from backend.services.duty_staff_service import get_all_staff, get_absences

# Số người mặc định khi năm đó chưa có bản ghi cấu hình nào
_MAC_DINH = {
    "thuong":    {"ld": 1, "chinh": 2, "phu": 0},
    "quyet_toan": {"ld": 1, "chinh": 3, "phu": 2},
}

# Cùng bộ số trên nhưng khoá theo tên cột của duty_shift_config — đường ghi cấu
# hình dùng lại, để không sinh ra bộ mặc định thứ hai lệch với _MAC_DINH.
MAC_DINH_COT = {
    "ld_count":          _MAC_DINH["thuong"]["ld"],
    "nv_count":          _MAC_DINH["thuong"]["chinh"],
    "qt_ld_count":       _MAC_DINH["quyet_toan"]["ld"],
    "qt_nv_chinh_count": _MAC_DINH["quyet_toan"]["chinh"],
    "qt_nv_phu_count":   _MAC_DINH["quyet_toan"]["phu"],
}

# Thứ 6 và cut-off dùng chung cấu hình ca thường (quyết định của Business Owner)
_NHOM_CA = {
    "normal":          "thuong",
    "friday":          "thuong",
    "cutoff":          "thuong",
    "settlement_main": "quyet_toan",
    # Loại cũ, đã bị migration xoá sạch mỗi lần khởi động nên thực tế không còn
    # bản ghi nào. Giữ khoá ở đây để tra cứu không nổ nếu gặp dữ liệu sót.
    "settlement_sub":  "quyet_toan",
}


# ══════════════════════════════════════════════════════════════
# CẤU HÌNH SỐ NGƯỜI
# ══════════════════════════════════════════════════════════════

def get_cau_hinh_ca(db: sqlite3.Connection, year: int,
                    shift_type: str) -> Tuple[int, int, int]:
    """
    Số người bắt buộc của một loại ca: (số Lãnh đạo, số trực chính, số trực phụ).
    Một chỗ duy nhất dịch từ loại ca sang số người — engine và đường sửa tay
    cùng gọi hàm này nên không thể hiểu khác nhau.
    """
    nhom = _NHOM_CA.get(shift_type, "thuong")
    mac_dinh = _MAC_DINH[nhom]

    row = db.execute(
        "SELECT * FROM duty_shift_config WHERE year=?", (year,)
    ).fetchone()
    if not row:
        return mac_dinh["ld"], mac_dinh["chinh"], mac_dinh["phu"]

    cfg = dict(row)
    if nhom == "quyet_toan":
        return (cfg.get("qt_ld_count")       or mac_dinh["ld"],
                cfg.get("qt_nv_chinh_count") or mac_dinh["chinh"],
                cfg.get("qt_nv_phu_count")   if cfg.get("qt_nv_phu_count") is not None
                else mac_dinh["phu"])
    return (cfg.get("ld_count") or mac_dinh["ld"],
            cfg.get("nv_count") or mac_dinh["chinh"],
            0)


# ══════════════════════════════════════════════════════════════
# VAI SONG PHƯƠNG
# ══════════════════════════════════════════════════════════════

def resolve_sp_role(leaders: List[dict], nv_chinh: List[dict],
                    nv_phu: Optional[List[dict]] = None
                    ) -> Tuple[Optional[dict], Optional[str]]:
    """
    Xác định ai giữ vai song phương trong ca.
    Trả (sp, sp_warning) — sp=None nghĩa là Lãnh đạo kiêm, hoặc không ai làm được.

    Luật: cần ÍT NHẤT 1 người biết song phương trong (Lãnh đạo + trực chính).

    `nv_phu` nhận vào nhưng CỐ Ý không dùng: người trực phụ về sớm hơn nên không
    giữ được vai song phương, và cũng không bị tính là dư. Giữ tham số để chỗ gọi
    truyền đủ thành phần ca, khỏi phải nhớ nhóm nào có ảnh hưởng nhóm nào không.

      leader_sp     Lãnh đạo kiêm song phương
      multi_sp      Lãnh đạo + trực chính có nhiều hơn 1 người biết song phương
                    (lãng phí nguồn lực)
      no_sp_chinh   Lãnh đạo và trực chính không có ai biết song phương
      None          Một nhân viên trực chính giữ vai, đúng 1 người trong ca
    """
    ld_la_sp   = [p for p in leaders if p.get("can_do_sp")]
    chinh_la_sp = [p for p in nv_chinh if p.get("can_do_sp")]

    # Từng cộng cả nhóm trực phụ vào đây. Hậu quả: ngày quyết toán nào có người
    # trực phụ biết song phương cũng bị báo "dư người song phương", dù nhóm trực
    # chính vẫn đúng một người — cảnh báo sai bật đều đặn thì thành quen mắt.
    tong_ca = len(ld_la_sp) + len(chinh_la_sp)
    du_sp_chinh = bool(ld_la_sp or chinh_la_sp)

    if not du_sp_chinh:
        return None, "no_sp_chinh"
    if tong_ca > 1:
        # Vẫn chỉ định người giữ vai để hiển thị, nhưng gắn cảnh báo dư
        return (chinh_la_sp[0] if chinh_la_sp and not ld_la_sp else None), "multi_sp"
    if ld_la_sp:
        return None, "leader_sp"
    return chinh_la_sp[0], None


# ══════════════════════════════════════════════════════════════
# CÔNG BẰNG THEO TUẦN / THÁNG
# ══════════════════════════════════════════════════════════════

def dem_ca_lanh_dao_trong_tuan(db: sqlite3.Connection, shift_date: str) -> dict:
    """
    Đếm số ca mỗi Lãnh đạo đã có trong tuần TRƯỚC ngày shift_date (không tính
    chính ca đang xét). Dùng chung cho engine sinh tự động và validate sửa tay
    để không thể hiểu khác nhau luật "Lãnh đạo tối đa 2 ca/tuần".
    """
    d = date.fromisoformat(shift_date)
    week_start = d - timedelta(days=d.weekday())
    if week_start >= d:
        return {}
    dem: dict = {}
    for r in db.execute(
        "SELECT leader_ids FROM duty_shifts WHERE shift_date >= ? AND shift_date < ? "
        "AND status IN ('confirmed','draft')",
        (week_start.isoformat(), shift_date)
    ):
        for sid in json.loads(r["leader_ids"] or "[]"):
            dem[sid] = dem.get(sid, 0) + 1
    return dem


def nguoi_da_truc_thu6_thang(db: sqlite3.Connection, shift_date: str) -> set:
    """
    Ai đã trực ca thứ 6 trong CÙNG THÁNG với shift_date rồi (không tính chính ca
    đang xét) — dùng để tránh xếp trực thứ 6 lần 2 trong tháng cho cùng một người.
    """
    thang = shift_date[:7]
    ids: set = set()
    for r in db.execute(
        "SELECT leader_ids, sp_id, nv_ids, nv_phu_ids FROM duty_shifts "
        "WHERE shift_type='friday' AND shift_date LIKE ? AND shift_date < ?",
        (f"{thang}-%", shift_date)
    ):
        if r["sp_id"]:
            ids.add(r["sp_id"])
        for cot in ("leader_ids", "nv_ids", "nv_phu_ids"):
            ids.update(json.loads(r[cot] or "[]"))
    return ids


# ══════════════════════════════════════════════════════════════
# KIỂM TRA THÀNH PHẦN CA
# ══════════════════════════════════════════════════════════════

def _ten(p: Optional[dict], sid: int) -> str:
    return p["full_name"] if p else f"id={sid}"


def validate_shift_members(db: sqlite3.Connection, shift_date: str, shift_type: str,
                           leader_ids: List[int], nv_chinh_ids: List[int],
                           nv_phu_ids: Optional[List[int]] = None
                           ) -> Tuple[List[str], List[str], dict]:
    """
    Kiểm tra thành phần một ca trực theo số người đã khai báo.
    Trả (loi_cung, canh_bao, nguoi) — `nguoi` là dict {id: bản ghi nhân sự}
    để caller khỏi truy vấn lại.

    Có phần tử trong `loi_cung` → không được hình thành ca trực.
    `canh_bao` chỉ để hiển thị, không chặn.
    """
    nv_phu_ids = nv_phu_ids or []
    year = int(shift_date[:4])
    so_ld, so_chinh, so_phu = get_cau_hinh_ca(db, year, shift_type)

    nhan_su = {p["id"]: p for p in get_all_staff(db)}
    loi_cung: List[str] = []
    canh_bao: List[str] = []

    # ── Luật cứng: đủ đúng số người từng vị trí ──
    for ten_vi_tri, ids, can_co in (("Lãnh đạo", leader_ids, so_ld),
                                    ("nhân viên trực chính", nv_chinh_ids, so_chinh),
                                    ("nhân viên trực phụ", nv_phu_ids, so_phu)):
        if len(ids) != can_co:
            loi_cung.append(f"Ca trực phải có đúng {can_co} {ten_vi_tri} "
                            f"(đang chọn {len(ids)}).")

    # ── Luật cứng: không ai giữ hai chỗ trong cùng ca ──
    tat_ca = list(leader_ids) + list(nv_chinh_ids) + list(nv_phu_ids)
    if len(set(tat_ca)) != len(tat_ca):
        loi_cung.append("Không thể xếp cùng một người vào hai vị trí trong một ca.")

    # ── Luật cứng: đúng vai ──
    leaders, nv_chinh, nv_phu = [], [], []
    for sid in leader_ids:
        p = nhan_su.get(sid)
        if p is None:
            loi_cung.append(f"Lãnh đạo {_ten(p, sid)} không thuộc Phòng Thanh toán "
                            f"hoặc đã nghỉ việc.")
        elif p["duty_role"] != "LD":
            loi_cung.append(f"{p['full_name']} không phải Lãnh đạo — không thể xếp "
                            f"vào vị trí này.")
        else:
            leaders.append(p)

    for nhom_ids, nhom_ra, nhan in ((nv_chinh_ids, nv_chinh, "trực chính"),
                                    (nv_phu_ids, nv_phu, "trực phụ")):
        for sid in nhom_ids:
            p = nhan_su.get(sid)
            if p is None:
                loi_cung.append(f"Nhân viên id={sid} không thuộc Phòng Thanh toán "
                                f"hoặc đã nghỉ việc.")
            elif p["duty_role"] != "NV":
                loi_cung.append(f"{p['full_name']} là Lãnh đạo — không thể xếp vào "
                                f"vị trí nhân viên {nhan}.")
            else:
                nhom_ra.append(p)

    if loi_cung:
        return loi_cung, canh_bao, nhan_su

    # ── Luật mềm ──
    vang_mat = get_absences(db, shift_date)
    for p in leaders + nv_chinh + nv_phu:
        if p["is_on_project"]:
            canh_bao.append(f"{p['full_name']} đang đi dự án.")
        if p["id"] in vang_mat:
            canh_bao.append(f"{p['full_name']} {vang_mat[p['id']]} ngày {shift_date}.")

    _, sp_warning = resolve_sp_role(leaders, nv_chinh, nv_phu)
    if sp_warning == "no_sp_chinh":
        canh_bao.append("Lãnh đạo và nhóm trực chính không có ai xử lý song phương.")
    elif sp_warning == "multi_sp":
        canh_bao.append("Ca có nhiều hơn 1 người xử lý song phương.")

    so_ca_ld_tuan = dem_ca_lanh_dao_trong_tuan(db, shift_date)
    for p in leaders:
        if so_ca_ld_tuan.get(p["id"], 0) >= 2:
            canh_bao.append(f"{p['full_name']} đã trực {so_ca_ld_tuan[p['id']]} ca trong "
                            f"tuần này — vượt tối đa 2 ca/tuần cho Lãnh đạo.")

    if shift_type == "friday":
        da_truc_t6 = nguoi_da_truc_thu6_thang(db, shift_date)
        for p in leaders + nv_chinh + nv_phu:
            if p["id"] in da_truc_t6:
                canh_bao.append(f"{p['full_name']} đã trực thứ 6 trong tháng này rồi.")

    return loi_cung, canh_bao, nhan_su
