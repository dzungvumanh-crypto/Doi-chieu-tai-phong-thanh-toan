"""Xếp loại lao động — Phòng Tổng hợp.

Một loại bản ghi (`xep_loai_lao_dong`), ba "loại" nghiệp vụ khác nhau nằm
chung bảng (`loai` — xem `backend/schemas/xep_loai.py`): xếp loại lao động,
kết quả phiếu tín nhiệm, xếp loại quý Cấp ủy. Cùng một mức quyền phẳng
(`xep_loai.manage`) — không có khái niệm "chủ sở hữu bản ghi", giống
`thi_dua.manage_*` / `hr.edit_all`: ai có mã quản lý thì sửa/xoá được mọi
bản ghi, đúng vai trò "Cán bộ Phòng Tổng hợp nhập thời điểm cuối năm, cuối quý"
trong yêu cầu — một người nhập thay cho cả đơn vị, không phải mỗi người tự
khai của mình.

`menu.xep_loai` là quyền xem/tra cứu; `xep_loai.export` gate hai route xuất Excel.
"""
import io
import sqlite3
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from openpyxl.styles import Alignment, Font, PatternFill
from urllib.parse import quote

from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.core.uploads import read_limited
from backend.database import _vn_now, get_db, write_audit
from backend.schemas.xep_loai import (
    KET_QUA_THEO_LOAI, KY_HOP_LE_THEO_LOAI, TEN_LOAI, XepLoaiIn, _fold, khop_ket_qua,
)

router = APIRouter(prefix="/api/xep-loai", tags=["xep-loai"])

_CHUA_XEP_PHONG = "Chưa xếp phòng"


def _download_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {"Content-Disposition": (f'attachment; filename="{fallback}"; '
                                    f"filename*=UTF-8''{quote(filename, safe='')}")}


def _staff_ton_tai(db, staff_id: int) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM user_tttt WHERE id = ? AND (is_deleted = 0 OR is_deleted IS NULL)",
        (staff_id,),
    ).fetchone())


def _trung_lap(db, staff_id: int, loai: str, nam: int, quy, exclude_id: int = None) -> bool:
    q = "SELECT 1 FROM xep_loai_lao_dong WHERE staff_id=? AND loai=? AND nam=? AND quy IS ?"
    params = [staff_id, loai, nam, quy]
    if exclude_id is not None:
        q += " AND id != ?"
        params.append(exclude_id)
    return bool(db.execute(q, params).fetchone())


_LOI_TRUNG_LAP = "Cán bộ này đã có xếp loại cho đúng kỳ này — sửa bản ghi cũ thay vì thêm mới"


# ── CRUD ────────────────────────────────────────────────────────────────────
@router.get("")
def list_xep_loai(
    staff_id: Optional[int] = Query(None),
    department_id: Optional[int] = Query(None),
    loai: Optional[str] = Query(None),
    ky: Optional[str] = Query(None),
    nam: Optional[int] = Query(None),
    quy: Optional[int] = Query(None),
    current: dict = Depends(require_feature("menu.xep_loai")),
    db: sqlite3.Connection = Depends(get_db),
):
    clauses, params = [], []
    if staff_id is not None:
        clauses.append("x.staff_id = ?")
        params.append(staff_id)
    if department_id is not None:
        clauses.append("u.department_id = ?")
        params.append(department_id)
    if loai is not None:
        clauses.append("x.loai = ?")
        params.append(loai)
    if ky is not None:
        clauses.append("x.ky = ?")
        params.append(ky)
    if nam is not None:
        clauses.append("x.nam = ?")
        params.append(nam)
    if quy is not None:
        clauses.append("x.quy = ?")
        params.append(quy)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        f"""SELECT x.id, x.staff_id, u.full_name AS staff_name, u.department_id,
                   COALESCE(d.name, ?) AS department_name,
                   x.loai, x.ky, x.nam, x.quy, x.ket_qua, x.ghi_chu,
                   x.created_at, x.updated_at
            FROM xep_loai_lao_dong x
            LEFT JOIN user_tttt u ON u.id = x.staff_id
            LEFT JOIN departments d ON d.id = u.department_id
            {where}
            ORDER BY x.nam DESC, x.quy DESC, u.full_name""",
        (_CHUA_XEP_PHONG, *params),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
def create_xep_loai(
    body: XepLoaiIn,
    current: dict = Depends(require_feature("xep_loai.manage")),
    db: sqlite3.Connection = Depends(get_db),
):
    if not _staff_ton_tai(db, body.staff_id):
        raise HTTPException(400, "Không tìm thấy cán bộ")
    if _trung_lap(db, body.staff_id, body.loai.value, body.nam, body.quy):
        raise HTTPException(400, _LOI_TRUNG_LAP)
    now = _vn_now()
    try:
        cur = db.execute(
            """INSERT INTO xep_loai_lao_dong
                   (staff_id, loai, ky, nam, quy, ket_qua, ghi_chu, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (body.staff_id, body.loai.value, body.ky.value, body.nam, body.quy, body.ket_qua,
             body.ghi_chu, current["id"], now, now),
        )
    except sqlite3.IntegrityError:
        # Hai request cùng lúc lọt qua _trung_lap() ở trên (check-then-act) —
        # UNIQUE index (ix_xep_loai_unique) là tuyến chặn cuối, không phải lỗi
        # hệ thống nên trả 400 như trên, không phải 500.
        raise HTTPException(400, _LOI_TRUNG_LAP)
    write_audit(db, current["id"], "xep_loai.create", "xep_loai_lao_dong", cur.lastrowid,
                f"staff={body.staff_id}, {TEN_LOAI[body.loai.value]} {body.nam}"
                f"{f'/Q{body.quy}' if body.quy else ''} — {body.ket_qua}")
    db.commit()
    return {"id": cur.lastrowid}


@router.put("/{item_id}")
def update_xep_loai(
    item_id: int,
    body: XepLoaiIn,
    current: dict = Depends(require_feature("xep_loai.manage")),
    db: sqlite3.Connection = Depends(get_db),
):
    if not db.execute("SELECT 1 FROM xep_loai_lao_dong WHERE id = ?", (item_id,)).fetchone():
        raise HTTPException(404, "Không tìm thấy bản ghi xếp loại")
    if not _staff_ton_tai(db, body.staff_id):
        raise HTTPException(400, "Không tìm thấy cán bộ")
    if _trung_lap(db, body.staff_id, body.loai.value, body.nam, body.quy, exclude_id=item_id):
        raise HTTPException(400, _LOI_TRUNG_LAP)
    try:
        db.execute(
            """UPDATE xep_loai_lao_dong SET staff_id=?, loai=?, ky=?, nam=?, quy=?, ket_qua=?,
                   ghi_chu=?, updated_at=?
               WHERE id=?""",
            (body.staff_id, body.loai.value, body.ky.value, body.nam, body.quy, body.ket_qua,
             body.ghi_chu, _vn_now(), item_id),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(400, _LOI_TRUNG_LAP)
    write_audit(db, current["id"], "xep_loai.update", "xep_loai_lao_dong", item_id,
                f"staff={body.staff_id}, {TEN_LOAI[body.loai.value]} {body.nam}"
                f"{f'/Q{body.quy}' if body.quy else ''} — {body.ket_qua}")
    db.commit()
    return {"ok": True}


@router.delete("/{item_id}")
def delete_xep_loai(
    item_id: int,
    current: dict = Depends(require_feature("xep_loai.manage")),
    db: sqlite3.Connection = Depends(get_db),
):
    if not db.execute("SELECT 1 FROM xep_loai_lao_dong WHERE id = ?", (item_id,)).fetchone():
        raise HTTPException(404, "Không tìm thấy bản ghi xếp loại")
    db.execute("DELETE FROM xep_loai_lao_dong WHERE id = ?", (item_id,))
    write_audit(db, current["id"], "xep_loai.delete", "xep_loai_lao_dong", item_id)
    db.commit()
    return {"ok": True}


# ── Nhập lô từ Excel ──────────────────────────────────────────────────────────
# Cán bộ Phòng Tổng hợp có thể đang theo dõi bằng Excel trước khi có màn hình
# này — cần đường nhập lô, không chỉ gõ tay từng dòng (yêu cầu người dùng).
# Dò cột theo TÊN tiêu đề (khuôn `thi_dua.py::_dinh_vi_cot`), không theo vị trí
# cột cố định. `dry_run=True` (mặc định) chỉ xem trước, không ghi DB.
def _dinh_vi_cot(ws, can_tim: dict, bat_buoc: set, max_row: int = 10):
    for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=max_row, values_only=True), 1):
        found = {}
        for ci, cell in enumerate(row):
            h = _fold(cell)
            if not h:
                continue
            for truong, cum_tu in can_tim.items():
                if truong in found:
                    continue
                if any(c in h for c in cum_tu):
                    found[truong] = ci
        if bat_buoc <= set(found):
            return ri, found
    return None, {}


_CAN_XEP_LOAI = {
    "ma_cb": ["ma can bo", "ma cb", "ma nhan vien"],
    "nam": ["nam"],
    "quy": ["quy"],
    "loai": ["loai xep loai"],
    "ket_qua": ["ket qua"],
    "ghi_chu": ["ghi chu"],
}
_BAT_BUOC_XEP_LOAI = {"ma_cb", "nam", "loai", "ket_qua"}


def _map_loai(v) -> Optional[str]:
    f = _fold(v)
    if "lao dong" in f:
        return "lao_dong"
    if "tin nhiem" in f:
        return "tin_nhiem"
    if "cap uy" in f:
        return "cap_uy"
    return None


def _doc_wb_xep_loai(content: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    ws = wb.active
    header_row, cot = _dinh_vi_cot(ws, _CAN_XEP_LOAI, _BAT_BUOC_XEP_LOAI)
    if header_row is None:
        wb.close()
        raise HTTPException(
            400, "Không tìm thấy đủ cột bắt buộc (Mã cán bộ, Năm, Loại xếp loại, Kết quả) "
                 "trong file. Hãy tải file mẫu và điền đúng tên cột.")
    items = []
    for ri, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
        def g(key):
            ci = cot.get(key)
            return row[ci] if ci is not None and ci < len(row) else None
        ma_cb = g("ma_cb")
        if not str(ma_cb or "").strip():
            continue
        if isinstance(ma_cb, float) and ma_cb.is_integer():
            ma_cb = int(ma_cb)
        items.append({"dong": ri, "ma_cb": ma_cb, "nam": g("nam"), "quy": g("quy"),
                      "loai": g("loai"), "ket_qua": g("ket_qua"), "ghi_chu": g("ghi_chu")})
    wb.close()
    return items


def _mau_workbook() -> bytes:
    cols = [("Mã cán bộ", 14), ("Họ và tên (chỉ để đối chiếu)", 26), ("Năm", 8),
            ("Quý (để trống nếu xếp theo năm)", 30), ("Loại xếp loại", 26),
            ("Kết quả", 34), ("Ghi chú", 30)]
    vi_du = ["NV001", "Nguyễn Văn A", 2026, "", "Lao động", "Hoàn thành tốt nhiệm vụ", ""]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mẫu nhập"
    fill = PatternFill("solid", fgColor="FEE2E2")
    for j, (ten, w) in enumerate(cols, start=1):
        c = ws.cell(row=1, column=j, value=ten)
        c.font, c.fill = Font(bold=True), fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = w
    for j, v in enumerate(vi_du, start=1):
        ws.cell(row=2, column=j, value=v)
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("Hướng dẫn")
    ws2.append(["Loại xếp loại", "Kỳ áp dụng", "Các mức Kết quả hợp lệ"])
    for b in ws2[1]:
        b.font = Font(bold=True)
    for loai, ten in TEN_LOAI.items():
        ky_txt = "/".join("Năm" if k == "nam" else "Quý" for k in sorted(KY_HOP_LE_THEO_LOAI[loai]))
        ws2.append([ten, ky_txt, " | ".join(KET_QUA_THEO_LOAI[loai])])
    for col, w in zip("ABC", (26, 16, 60)):
        ws2.column_dimensions[col].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/import-template")
def import_template(current: dict = Depends(require_feature("xep_loai.manage"))):
    noi_dung = _mau_workbook()
    return Response(content=noi_dung,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_download_headers("mau_xep_loai_lao_dong.xlsx"))


@router.post("/import")
async def import_xep_loai(
    file: UploadFile = File(...),
    dry_run: bool = Query(True),
    current: dict = Depends(require_feature("xep_loai.manage")),
    db: sqlite3.Connection = Depends(get_db),
):
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Chỉ nhận file Excel .xlsx/.xlsm")
    noi_dung = await read_limited(file, ten="File Excel xếp loại lao động")
    items = await run_heavy(_doc_wb_xep_loai, noi_dung)
    if not items:
        raise HTTPException(400, "Không đọc được dòng dữ liệu nào trong file")

    staff_by_code = {
        str(r["employee_code"] or "").strip(): r["id"]
        for r in db.execute(
            "SELECT id, employee_code FROM user_tttt WHERE is_deleted = 0 OR is_deleted IS NULL")
    }
    da_co = {
        (r["staff_id"], r["loai"], r["nam"], r["quy"])
        for r in db.execute("SELECT staff_id, loai, nam, quy FROM xep_loai_lao_dong")
    }
    loi, them = [], 0
    now = _vn_now()
    for it in items:
        ma_cb = str(it["ma_cb"]).strip()
        staff_id = staff_by_code.get(ma_cb)
        if staff_id is None:
            loi.append({"dong": it["dong"], "ly_do": f"Không khớp mã cán bộ: '{ma_cb}'"})
            continue
        loai = _map_loai(it["loai"])
        if loai is None:
            loi.append({"dong": it["dong"],
                        "ly_do": f"Loại xếp loại không hợp lệ: '{it['loai']}' "
                                 "(cần Lao động/Tín nhiệm/Cấp ủy)"})
            continue
        try:
            nam_i = int(it["nam"])
        except (TypeError, ValueError):
            loi.append({"dong": it["dong"], "ly_do": f"Năm không hợp lệ: '{it['nam']}'"})
            continue
        if not (2000 <= nam_i <= 2100):
            loi.append({"dong": it["dong"], "ly_do": f"Năm không hợp lệ: {nam_i}"})
            continue
        quy_raw = it["quy"]
        quy_i = None
        if str(quy_raw or "").strip():
            try:
                quy_i = int(quy_raw)
            except (TypeError, ValueError):
                loi.append({"dong": it["dong"], "ly_do": f"Quý không hợp lệ: '{quy_raw}'"})
                continue
            if not (1 <= quy_i <= 4):
                loi.append({"dong": it["dong"], "ly_do": f"Quý không hợp lệ: {quy_i}"})
                continue
        ky = "quy" if quy_i is not None else "nam"
        if ky not in KY_HOP_LE_THEO_LOAI[loai]:
            loi.append({"dong": it["dong"],
                        "ly_do": f"{TEN_LOAI[loai]} không áp dụng theo "
                                 f"{'quý' if ky == 'quy' else 'năm'}"})
            continue
        ket_qua = khop_ket_qua(loai, it["ket_qua"])
        if ket_qua is None:
            loi.append({"dong": it["dong"],
                        "ly_do": f"Kết quả không hợp lệ cho {TEN_LOAI[loai]}: '{it['ket_qua']}' "
                                 f"— cần là một trong: {', '.join(KET_QUA_THEO_LOAI[loai])}"})
            continue
        khoa = (staff_id, loai, nam_i, quy_i)
        if khoa in da_co:
            loi.append({"dong": it["dong"],
                        "ly_do": "Cán bộ này đã có xếp loại cho đúng kỳ này (trùng với bản ghi "
                                 "đã có hoặc dòng khác trong cùng file)"})
            continue
        if not dry_run:
            try:
                db.execute(
                    """INSERT INTO xep_loai_lao_dong
                           (staff_id, loai, ky, nam, quy, ket_qua, ghi_chu, created_by,
                            created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (staff_id, loai, ky, nam_i, quy_i, ket_qua,
                     str(it["ghi_chu"] or "").strip() or None, current["id"], now, now),
                )
            except sqlite3.IntegrityError:
                loi.append({"dong": it["dong"], "ly_do": _LOI_TRUNG_LAP})
                continue
        da_co.add(khoa)
        them += 1

    if not dry_run and them:
        write_audit(db, current["id"], "xep_loai.import", "xep_loai_lao_dong", None,
                    f"{file.filename}: thêm {them}, lỗi {len(loi)}")
        db.commit()
    return {"tong_dong": len(items), "da_them": them, "loi": loi}


# ── Tra cứu, thống kê ─────────────────────────────────────────────────────────
# Logic tách khỏi route (`_tong_hop_data`/`_ca_nhan_data`) để route xem
# (`menu.xep_loai`) và route xuất Excel (`xep_loai.export`) dùng chung, mỗi
# route tự kiểm đúng mã quyền của mình — khuôn `thi_dua.py::_tong_hop_rows`.
def _tong_hop_data(db: sqlite3.Connection, loai: str, nam: int, ky: str,
                   quy: Optional[int]) -> dict:
    if loai not in KET_QUA_THEO_LOAI:
        raise HTTPException(400, f"Loại xếp loại không hợp lệ: '{loai}'")
    if ky not in KY_HOP_LE_THEO_LOAI[loai]:
        raise HTTPException(400, f"{TEN_LOAI[loai]} không áp dụng theo "
                                  f"{'quý' if ky == 'quy' else 'năm'}")
    if ky == "quy" and quy is None:
        raise HTTPException(400, "Cần chọn quý")
    # Chốt lại quy=None khi ky="nam" — nếu không, caller lỡ gửi kèm quy (vd
    # ky=nam&quy=3) thì SQL vẫn lọc đúng (điều kiện dưới tự bỏ qua) nhưng dict
    # trả về và tiêu đề Excel ở export_tong_hop() lại in nhầm "QUÝ 3" cho một
    # báo cáo thực chất là theo năm — chuẩn hoá một lần ở đây để cả response
    # lẫn file xuất ra không bao giờ lệch nhau.
    quy = quy if ky == "quy" else None

    rows = db.execute(
        """SELECT COALESCE(d.name, ?) AS department_name, x.ket_qua, COUNT(*) AS so_luong
           FROM xep_loai_lao_dong x
           LEFT JOIN user_tttt u ON u.id = x.staff_id
           LEFT JOIN departments d ON d.id = u.department_id
           WHERE x.loai = ? AND x.nam = ? AND x.ky = ? AND x.quy IS ?
           GROUP BY department_name, x.ket_qua""",
        (_CHUA_XEP_PHONG, loai, nam, ky, quy),
    ).fetchall()

    categories = KET_QUA_THEO_LOAI[loai]
    theo_phong: dict[str, dict[str, int]] = {}
    tong: dict[str, int] = {c: 0 for c in categories}
    for r in rows:
        d = theo_phong.setdefault(r["department_name"], {c: 0 for c in categories})
        d[r["ket_qua"]] = r["so_luong"]
        tong[r["ket_qua"]] = tong.get(r["ket_qua"], 0) + r["so_luong"]

    out_rows = [
        {"department_name": ten, "counts": counts, "total": sum(counts.values())}
        for ten, counts in sorted(theo_phong.items())
    ]
    return {
        "loai": loai, "nam": nam, "ky": ky, "quy": quy,
        "categories": categories, "rows": out_rows,
        "tong": {"counts": tong, "total": sum(tong.values())},
    }


def _ca_nhan_data(db: sqlite3.Connection, staff_id: int, loai: str,
                  den_nam: Optional[int]) -> dict:
    if loai not in KET_QUA_THEO_LOAI:
        raise HTTPException(400, f"Loại xếp loại không hợp lệ: '{loai}'")
    if "nam" not in KY_HOP_LE_THEO_LOAI[loai]:
        # cap_uy chỉ tồn tại ở ky='quy' — không chặn ở đây thì câu SQL bên dưới
        # (lọc ky='nam') luôn trả 0 dòng, và cả 5 năm hiện "Chưa có dữ liệu" dù
        # dữ liệu quý vẫn có thật — trông y hệt "cán bộ chưa từng được xếp loại".
        raise HTTPException(
            400, f"{TEN_LOAI[loai]} chỉ xếp theo quý — dùng bảng tổng hợp theo quý "
                 "thay vì tra cứu nhiều năm liên tiếp")
    staff = db.execute(
        "SELECT full_name FROM user_tttt WHERE id = ? AND (is_deleted = 0 OR is_deleted IS NULL)",
        (staff_id,),
    ).fetchone()
    if not staff:
        raise HTTPException(400, "Không tìm thấy cán bộ")

    den = den_nam or _vn_now().year
    tu = den - 4
    rows = db.execute(
        """SELECT nam, ket_qua, ghi_chu FROM xep_loai_lao_dong
           WHERE staff_id = ? AND loai = ? AND ky = 'nam' AND nam BETWEEN ? AND ?""",
        (staff_id, loai, tu, den),
    ).fetchall()
    theo_nam = {r["nam"]: dict(r) for r in rows}
    nam_theo_thu_tu = [
        {"nam": y, "ket_qua": (theo_nam.get(y) or {}).get("ket_qua"),
         "ghi_chu": (theo_nam.get(y) or {}).get("ghi_chu")}
        for y in range(tu, den + 1)
    ]
    return {"staff_id": staff_id, "staff_name": staff["full_name"], "loai": loai,
            "tu_nam": tu, "den_nam": den, "nam_theo_thu_tu": nam_theo_thu_tu}


@router.get("/stats/tong-hop")
def stats_tong_hop(
    loai: str = Query("lao_dong"),
    nam: int = Query(...),
    ky: str = Query("nam"),
    quy: Optional[int] = Query(None),
    current: dict = Depends(require_feature("menu.xep_loai")),
    db: sqlite3.Connection = Depends(get_db),
):
    return _tong_hop_data(db, loai, nam, ky, quy)


@router.get("/stats/ca-nhan")
def stats_ca_nhan(
    staff_id: int = Query(...),
    loai: str = Query("lao_dong"),
    den_nam: Optional[int] = Query(None),
    current: dict = Depends(require_feature("menu.xep_loai")),
    db: sqlite3.Connection = Depends(get_db),
):
    return _ca_nhan_data(db, staff_id, loai, den_nam)


# ── Xuất Excel ────────────────────────────────────────────────────────────────
def _wb_tong_hop(data: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tổng hợp"
    cot = ["Trung tâm / Phòng", *data["categories"], "Tổng"]
    tieu_de = (f"TỔNG HỢP {TEN_LOAI[data['loai']].upper()} NĂM {data['nam']}"
               + (f" — QUÝ {data['quy']}" if data["quy"] else ""))
    ws.cell(row=1, column=1, value=tieu_de).font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cot))
    fill = PatternFill("solid", fgColor="FEE2E2")
    for j, nhan in enumerate(cot, start=1):
        c = ws.cell(row=3, column=j, value=nhan)
        c.font, c.fill = Font(bold=True), fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.column_dimensions["A"].width = 28
    for j in range(2, len(cot) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = 20
    r = 4
    for row in data["rows"]:
        ws.cell(row=r, column=1, value=row["department_name"])
        for j, c in enumerate(data["categories"], start=2):
            ws.cell(row=r, column=j, value=row["counts"].get(c, 0))
        ws.cell(row=r, column=len(cot), value=row["total"])
        r += 1
    ws.cell(row=r, column=1, value="TỔNG CỘNG").font = Font(bold=True)
    for j, c in enumerate(data["categories"], start=2):
        ws.cell(row=r, column=j, value=data["tong"]["counts"].get(c, 0)).font = Font(bold=True)
    ws.cell(row=r, column=len(cot), value=data["tong"]["total"]).font = Font(bold=True)
    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/export/tong-hop")
async def export_tong_hop(
    loai: str = Query("lao_dong"),
    nam: int = Query(...),
    ky: str = Query("nam"),
    quy: Optional[int] = Query(None),
    current: dict = Depends(require_feature("xep_loai.export")),
    db: sqlite3.Connection = Depends(get_db),
):
    data = _tong_hop_data(db, loai, nam, ky, quy)
    noi_dung = await run_heavy(_wb_tong_hop, data)
    write_audit(db, current["id"], "xep_loai.export_tong_hop", "xep_loai_lao_dong", None,
                f"loai={loai}, nam={nam}, ky={ky}, quy={data['quy']}")
    db.commit()
    ten_file = f"tong_hop_xep_loai_{loai}_{nam}" + (f"_q{data['quy']}" if data["quy"] else "") + ".xlsx"
    return Response(content=noi_dung,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_download_headers(ten_file))


def _wb_ca_nhan(data: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tra cứu"
    tieu_de = f"{TEN_LOAI[data['loai']].upper()} — {data['staff_name']} ({data['tu_nam']}-{data['den_nam']})"
    ws.cell(row=1, column=1, value=tieu_de).font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3)
    fill = PatternFill("solid", fgColor="FEE2E2")
    for j, nhan in enumerate(["Năm", "Kết quả", "Ghi chú"], start=1):
        c = ws.cell(row=3, column=j, value=nhan)
        c.font, c.fill = Font(bold=True), fill
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 34
    for i, r in enumerate(data["nam_theo_thu_tu"], start=4):
        ws.cell(row=i, column=1, value=r["nam"])
        ws.cell(row=i, column=2, value=r["ket_qua"] or "Chưa có dữ liệu")
        ws.cell(row=i, column=3, value=r["ghi_chu"] or "")
    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/export/ca-nhan")
async def export_ca_nhan(
    staff_id: int = Query(...),
    loai: str = Query("lao_dong"),
    den_nam: Optional[int] = Query(None),
    current: dict = Depends(require_feature("xep_loai.export")),
    db: sqlite3.Connection = Depends(get_db),
):
    data = _ca_nhan_data(db, staff_id, loai, den_nam)
    noi_dung = await run_heavy(_wb_ca_nhan, data)
    write_audit(db, current["id"], "xep_loai.export_ca_nhan", "xep_loai_lao_dong", None,
                f"staff_id={staff_id}, loai={loai}")
    db.commit()
    ten_file = f"xep_loai_{data['staff_name']}_{data['tu_nam']}-{data['den_nam']}.xlsx"
    return Response(content=noi_dung,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_download_headers(ten_file))
