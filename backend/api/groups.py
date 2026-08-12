"""API quản lý nhóm user và phân quyền chức năng."""
import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.database import get_db, _vn_now
from backend.core.deps import require_admin, get_current_staff
from backend.core.features import FEATURES, FEATURE_GROUPS

router = APIRouter(prefix="/api/groups", tags=["groups"])


# ── Schemas ───────────────────────────────────────────────────────────────────
class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class MemberAdd(BaseModel):
    staff_id: int


class FeaturesUpdate(BaseModel):
    codes: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_group_or_404(db: sqlite3.Connection, group_id: int) -> dict:
    row = db.execute("SELECT * FROM user_groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy nhóm")
    return dict(row)


# ── Group CRUD ────────────────────────────────────────────────────────────────
@router.get("")
def list_groups(db: sqlite3.Connection = Depends(get_db), _=Depends(require_admin)):
    rows = db.execute("""
        SELECT g.id, g.name, g.description, g.is_active, g.created_at,
               COUNT(DISTINCT gm.staff_id) AS member_count
        FROM user_groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id
        GROUP BY g.id
        ORDER BY g.name
    """).fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
def create_group(
    body: GroupCreate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    existing = db.execute("SELECT id FROM user_groups WHERE name = ?", (body.name,)).fetchone()
    if existing:
        raise HTTPException(400, "Tên nhóm đã tồn tại")
    cur = db.execute(
        "INSERT INTO user_groups (name, description, is_active, created_at) VALUES (?,?,?,?)",
        (body.name, body.description, int(body.is_active), _vn_now()),
    )
    db.commit()
    return _get_group_or_404(db, cur.lastrowid)


@router.put("/{group_id}")
def update_group(
    group_id: int,
    body: GroupUpdate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    fields, vals = [], []
    if body.name is not None:
        existing = db.execute(
            "SELECT id FROM user_groups WHERE name = ? AND id != ?", (body.name, group_id)
        ).fetchone()
        if existing:
            raise HTTPException(400, "Tên nhóm đã tồn tại")
        fields.append("name = ?"); vals.append(body.name)
    if body.description is not None:
        fields.append("description = ?"); vals.append(body.description)
    if body.is_active is not None:
        fields.append("is_active = ?"); vals.append(int(body.is_active))
    if fields:
        vals.append(group_id)
        db.execute(f"UPDATE user_groups SET {', '.join(fields)} WHERE id = ?", vals)
        db.commit()
    return _get_group_or_404(db, group_id)


@router.delete("/{group_id}", status_code=204)
def delete_group(
    group_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    db.execute("DELETE FROM user_groups WHERE id = ?", (group_id,))
    db.commit()


# ── Members ───────────────────────────────────────────────────────────────────
@router.get("/{group_id}/members")
def list_members(
    group_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    rows = db.execute("""
        SELECT u.id, u.full_name, u.role, u.employee_code,
               d.name AS department_name
        FROM group_members gm
        JOIN user_tttt u ON u.id = gm.staff_id
        LEFT JOIN departments d ON d.id = u.department_id
        WHERE gm.group_id = ?
        ORDER BY u.full_name
    """, (group_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/{group_id}/members", status_code=201)
def add_member(
    group_id: int,
    body: MemberAdd,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    staff = db.execute(
        "SELECT id FROM user_tttt WHERE id = ? AND is_active = 1 AND is_deleted = 0",
        (body.staff_id,),
    ).fetchone()
    if not staff:
        raise HTTPException(404, "Không tìm thấy nhân viên")
    existing = db.execute(
        "SELECT 1 FROM group_members WHERE group_id = ? AND staff_id = ?",
        (group_id, body.staff_id),
    ).fetchone()
    if existing:
        raise HTTPException(400, "Nhân viên đã là thành viên của nhóm này")
    db.execute(
        "INSERT INTO group_members (group_id, staff_id) VALUES (?,?)",
        (group_id, body.staff_id),
    )
    db.commit()
    return {"message": "Đã thêm thành viên"}


@router.delete("/{group_id}/members/{staff_id}", status_code=204)
def remove_member(
    group_id: int,
    staff_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    db.execute(
        "DELETE FROM group_members WHERE group_id = ? AND staff_id = ?",
        (group_id, staff_id),
    )
    db.commit()


# ── Features ──────────────────────────────────────────────────────────────────
@router.get("/{group_id}/features")
def get_group_features(
    group_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    rows = db.execute(
        "SELECT feature_code FROM group_features WHERE group_id = ?", (group_id,)
    ).fetchall()
    return {"codes": [r["feature_code"] for r in rows]}


@router.put("/{group_id}/features")
def update_group_features(
    group_id: int,
    body: FeaturesUpdate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_admin),
):
    _get_group_or_404(db, group_id)
    # Chỉ giữ lại codes hợp lệ (có trong FEATURES dict)
    valid_codes = [c for c in body.codes if c in FEATURES]
    db.execute("DELETE FROM group_features WHERE group_id = ?", (group_id,))
    for code in valid_codes:
        db.execute(
            "INSERT OR IGNORE INTO group_features (group_id, feature_code) VALUES (?,?)",
            (group_id, code),
        )
    db.commit()
    return {"codes": valid_codes}


# ── Feature definitions ───────────────────────────────────────────────────────
def _menu_payload(m: dict) -> dict | None:
    """Menu + action kèm nhãn. None nếu mã không còn trong FEATURES."""
    code = m["code"]
    if code not in FEATURES:
        return None
    return {
        "code": code,
        # Bỏ hậu tố " (menu)" trong label để UI hiển thị gọn hơn
        "label": FEATURES[code].replace(" (menu)", ""),
        "actions": [
            {"code": a, "label": FEATURES[a]}
            for a in m["actions"]
            if a in FEATURES
        ],
    }


@router.get("/features/all")
def get_all_features(_=Depends(get_current_staff)):
    """Cấu trúc màn phân quyền — dùng cho UI.

    Hai loại phần tử, phân biệt bằng "kind" (xem FEATURE_GROUPS):
      kind="group" → {"dept", "icon", "sections": [{"label", "menus"}]}
      kind="menu"  → {"code", "label", "icon", "actions"}
    Nhóm/section rỗng bị loại bỏ — không dựng thẻ trống.
    """
    result = []
    for node in FEATURE_GROUPS:
        if node["kind"] == "menu":
            payload = _menu_payload(node)
            if payload:
                result.append({"kind": "menu", "icon": node["icon"], **payload})
            continue

        sections = []
        for sec in node["sections"]:
            menus = [p for p in (_menu_payload(m) for m in sec["menus"]) if p]
            if menus:
                sections.append({"label": sec["label"], "menus": menus})
        if sections:
            result.append({
                "kind":     "group",
                "dept":     node["dept"],
                "icon":     node["icon"],
                "sections": sections,
            })
    return result
