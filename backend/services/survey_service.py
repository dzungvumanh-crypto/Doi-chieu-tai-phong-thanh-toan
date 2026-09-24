"""Khảo sát — logic dùng chung cho API khảo sát và khối "Công việc chờ xử lý".

Tách khỏi backend/api/surveys.py vì dashboard.py cũng cần đúng bộ lọc "khảo sát
chưa trả lời": viết SQL hai nơi thì số trên sidebar và danh sách chi tiết sẽ lệch
nhau ngay lần sửa đầu tiên (cùng lý do với _leave_filter trong dashboard.py).
"""
import json
import sqlite3
from collections import Counter

from backend.database import _vn_now
from backend.schemas.surveys import CHOICE_TYPES, chuan_hoa_thoi_diem


def now_str() -> str:
    """Giờ VN dạng 19 ký tự — CÙNG khuôn với cột start_at/deadline để so chuỗi."""
    return _vn_now().strftime("%Y-%m-%d %H:%M:%S")


# ── Trạng thái ────────────────────────────────────────────────────────────────
# `surveys.status` chỉ lưu ý định của người tạo (draft / published / closed).
# "Chưa tới giờ mở" và "đã quá hạn" SUY RA từ thời gian, không lưu: lưu thì cần
# một tác vụ nền đúng giờ đi đổi trạng thái, máy chủ tắt đúng lúc đó là khảo sát
# nằm "đang mở" mãi dù đã quá hạn.
def trang_thai(s, now: str | None = None) -> str:
    now = now or now_str()
    if s["status"] == "draft":
        return "draft"
    if s["status"] == "closed":
        return "closed"
    if s["start_at"] and now < s["start_at"]:
        return "scheduled"
    if s["deadline"] and now > s["deadline"]:
        return "expired"
    return "open"


def pending_filter(staff_id: int, now: str | None = None) -> tuple[str, list]:
    """Khảo sát đang MỞ mà người này có tên nhận nhưng chưa trả lời.

    Dùng với `FROM survey_recipients r JOIN surveys s ON s.id = r.survey_id`.
    Điều kiện thời gian phải khớp đúng trang_thai() == 'open'.
    """
    now = now or now_str()
    return (
        "r.staff_id = ? AND s.status = 'published' "
        "AND (s.start_at IS NULL OR s.start_at <= ?) "
        "AND (s.deadline IS NULL OR s.deadline >= ?) "
        "AND NOT EXISTS (SELECT 1 FROM survey_responses x "
        "                 WHERE x.survey_id = s.id AND x.staff_id = r.staff_id)",
        [staff_id, now, now],
    )


# ── Người nhận ────────────────────────────────────────────────────────────────
def dong_bo_nguoi_nhan(db: sqlite3.Connection, survey_id: int) -> tuple[int, int]:
    """Chốt danh sách người nhận = thành viên đang hoạt động của các nhóm đích.

    Chốt (snapshot) chứ không tra nhóm lúc chạy: nhóm user trước hết là nhóm
    PHÂN QUYỀN — admin rút ai đó khỏi nhóm để bớt quyền mà khảo sát cũng biến mất
    theo, mẫu số thống kê co lại lặng lẽ. Gọi lại hàm này khi người tạo đổi nhóm
    đích hoặc phát hành lại.

    Người đã trả lời nhưng không còn thuộc nhóm nào vẫn GIỮ tên: câu trả lời của
    họ đã nằm trong thống kê, xoá tên khỏi mẫu số thì tỷ lệ vượt 100%.
    Trả (số thêm, số bớt).
    """
    target = {
        r["id"] for r in db.execute(
            """SELECT DISTINCT u.id
                 FROM survey_target_groups tg
                 JOIN group_members gm ON gm.group_id = tg.group_id
                 JOIN user_tttt u ON u.id = gm.staff_id
                WHERE tg.survey_id = ? AND u.is_active = 1 AND IFNULL(u.is_deleted, 0) = 0""",
            (survey_id,),
        ).fetchall()
    }
    current = {r["staff_id"] for r in db.execute(
        "SELECT staff_id FROM survey_recipients WHERE survey_id = ?", (survey_id,)).fetchall()}
    answered = {r["staff_id"] for r in db.execute(
        "SELECT staff_id FROM survey_responses WHERE survey_id = ?", (survey_id,)).fetchall()}

    add = target - current
    drop = current - target - answered
    now = now_str()
    db.executemany(
        "INSERT INTO survey_recipients (survey_id, staff_id, added_at) VALUES (?,?,?)",
        [(survey_id, sid, now) for sid in add],
    )
    db.executemany(
        "DELETE FROM survey_recipients WHERE survey_id = ? AND staff_id = ?",
        [(survey_id, sid) for sid in drop],
    )
    return len(add), len(drop)


# ── Câu hỏi ───────────────────────────────────────────────────────────────────
def doc_cau_hoi(db: sqlite3.Connection, survey_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM survey_questions WHERE survey_id = ? ORDER BY order_no", (survey_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["required"] = bool(d["required"])
        d["options"] = json.loads(d["options"] or "[]")
        out.append(d)
    return out


def dau_van_tay_cau_hoi(questions: list[dict]) -> str:
    """Chuỗi đại diện PHẦN ẢNH HƯỞNG TỚI THỐNG KÊ của bộ câu hỏi.

    Dùng để nhận ra người tạo có đổi câu hỏi hay không khi đã có câu trả lời.
    Câu trả lời lựa chọn lưu theo SỐ THỨ TỰ lựa chọn — đổi/chèn một lựa chọn là
    mọi câu trả lời cũ trỏ sai sang ý khác. Sửa lỗi chính tả ở tiêu đề thì vô
    hại, nhưng phân biệt "sửa chính tả" với "đổi nghĩa" không làm được bằng máy,
    nên khoá cả.
    """
    keys = ("qtype", "title", "required", "options", "scale_min", "scale_max")
    return json.dumps([[q.get(k) for k in keys] for q in questions], ensure_ascii=False)


# ── Kiểm tra câu trả lời ──────────────────────────────────────────────────────
def _la_rong(v) -> bool:
    return v is None or v == "" or v == []


def kiem_tra_tra_loi(questions: list[dict], answers: dict[int, object]) -> dict[int, object]:
    """{question_id: value thô} → {question_id: value đã chuẩn hoá}. Sai → ValueError.

    Không tin client ở bất cứ điểm nào: số thứ tự lựa chọn phải nằm trong danh
    sách thật, điểm thang đo phải trong khoảng, câu bắt buộc phải có. Câu hỏi
    không thuộc khảo sát này bị bỏ qua (không lưu).
    """
    out: dict[int, object] = {}
    for q in questions:
        qid, qt, v = q["id"], q["qtype"], answers.get(q["id"])
        if isinstance(v, str):
            v = v.strip()
        if _la_rong(v):
            if q["required"]:
                raise ValueError(f"Câu «{q['title']}» là câu bắt buộc")
            continue

        n_opt = len(q["options"])
        if qt in ("short_text", "paragraph"):
            v = str(v)
            if len(v) > 10000:
                raise ValueError(f"Câu «{q['title']}»: câu trả lời quá dài")
        elif qt in ("single", "dropdown"):
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < n_opt:
                raise ValueError(f"Câu «{q['title']}»: lựa chọn không hợp lệ")
        elif qt == "multi":
            if not isinstance(v, list) or not all(
                isinstance(x, int) and not isinstance(x, bool) and 0 <= x < n_opt for x in v
            ):
                raise ValueError(f"Câu «{q['title']}»: lựa chọn không hợp lệ")
            v = sorted(set(v))
        elif qt == "scale":
            if not isinstance(v, int) or isinstance(v, bool) or not q["scale_min"] <= v <= q["scale_max"]:
                raise ValueError(f"Câu «{q['title']}»: điểm phải từ {q['scale_min']} đến {q['scale_max']}")
        elif qt == "date":
            try:
                v = chuan_hoa_thoi_diem(str(v))[:10]
            except ValueError:
                raise ValueError(f"Câu «{q['title']}»: ngày không hợp lệ")
        out[qid] = v
    return out


def hien_thi(q: dict, v) -> str:
    """Giá trị đã lưu → chữ đọc được (bảng từng câu trả lời, file Excel)."""
    if _la_rong(v):
        return ""
    qt = q["qtype"]
    if qt in ("single", "dropdown"):
        return q["options"][v] if 0 <= v < len(q["options"]) else f"#{v}"
    if qt == "multi":
        return "; ".join(q["options"][i] for i in v if 0 <= i < len(q["options"]))
    if qt == "date":
        y, m, d = str(v).split("-")
        return f"{d}/{m}/{y}"
    return str(v)


# ── Tổng hợp kết quả ──────────────────────────────────────────────────────────
def tong_hop(db: sqlite3.Connection, survey: dict) -> dict:
    """Thống kê theo câu + bảng từng câu trả lời + tiến độ người nhận."""
    sid = survey["id"]
    anon = bool(survey["is_anonymous"])
    questions = doc_cau_hoi(db, sid)

    responses = db.execute(
        """SELECT x.id, x.staff_id, x.submitted_at, x.updated_at,
                  u.full_name AS staff_name, d.name AS dept_name
             FROM survey_responses x
             LEFT JOIN user_tttt u ON u.id = x.staff_id
             LEFT JOIN departments d ON d.id = u.department_id
            WHERE x.survey_id = ?
            ORDER BY x.submitted_at, x.id""",
        (sid,),
    ).fetchall()
    ans: dict[int, dict[int, object]] = {}
    for a in db.execute(
        """SELECT a.response_id, a.question_id, a.value FROM survey_answers a
             JOIN survey_responses x ON x.id = a.response_id WHERE x.survey_id = ?""",
        (sid,),
    ).fetchall():
        ans.setdefault(a["response_id"], {})[a["question_id"]] = json.loads(a["value"])

    # Ẩn danh: không tên, không giờ nộp, và KHÔNG giữ thứ tự nộp — thứ tự nộp đặt cạnh
    # danh sách "ai đã trả lời" là ghép lại được ai viết gì. Xếp theo NỘI DUNG câu trả
    # lời: thứ tự chỉ phụ thuộc chính câu trả lời, ổn định giữa các lần mở trang.
    # KHÔNG trộn bằng random.Random(sid) (bản đầu làm vậy): hạt giống là id khảo sát ai
    # cũng biết, còn thứ tự nộp tra được trong Nhật ký hệ thống (survey.submit ghi người
    # + giờ) — người có menu.logs + surveys.view_all đảo lại được phép trộn.
    resp_list = list(responses)
    if anon:
        resp_list.sort(key=lambda r: json.dumps(
            [ans.get(r["id"], {}).get(q["id"]) for q in questions], ensure_ascii=False))

    stats = []
    for q in questions:
        vals = [ans.get(r["id"], {}).get(q["id"]) for r in resp_list]
        given = [v for v in vals if not _la_rong(v)]
        item = {"question_id": q["id"], "qtype": q["qtype"], "title": q["title"],
                "answered": len(given), "total": len(resp_list)}
        if q["qtype"] in CHOICE_TYPES:
            cnt = Counter()
            for v in given:
                cnt.update(v if isinstance(v, list) else [v])
            # % trên SỐ NGƯỜI trả lời câu này (câu nhiều lựa chọn có thể cộng > 100%).
            base = len(given) or 1
            item["options"] = [
                {"label": o, "count": cnt.get(i, 0), "pct": round(cnt.get(i, 0) * 100 / base, 1)}
                for i, o in enumerate(q["options"])
            ]
        elif q["qtype"] == "scale":
            cnt = Counter(given)
            base = len(given) or 1
            item["options"] = [
                {"label": str(p), "count": cnt.get(p, 0), "pct": round(cnt.get(p, 0) * 100 / base, 1)}
                for p in range(q["scale_min"], q["scale_max"] + 1)
            ]
            item["average"] = round(sum(given) / len(given), 2) if given else None
            item["scale_min_label"] = q["scale_min_label"]
            item["scale_max_label"] = q["scale_max_label"]
        elif q["qtype"] == "date":
            cnt = Counter(given)
            item["options"] = [
                {"label": hien_thi(q, dv), "count": c, "pct": round(c * 100 / len(given), 1)}
                for dv, c in sorted(cnt.items())
            ]
        else:
            item["texts"] = [
                {"text": v, "staff_name": None if anon else r["staff_name"]}
                for r, v in zip(resp_list, vals) if not _la_rong(v)
            ]
        stats.append(item)

    rows = [
        {
            "staff_name": None if anon else r["staff_name"],
            "dept_name": None if anon else r["dept_name"],
            "submitted_at": None if anon else r["submitted_at"],
            "updated_at": None if anon else r["updated_at"],
            "answers": [hien_thi(q, ans.get(r["id"], {}).get(q["id"])) for q in questions],
        }
        for r in resp_list
    ]

    done_at = {r["staff_id"]: r["submitted_at"] for r in responses}
    recipients = [
        {
            "staff_name": r["full_name"], "dept_name": r["dept_name"],
            "responded": r["staff_id"] in done_at,
            "submitted_at": None if anon else done_at.get(r["staff_id"]),
        }
        for r in db.execute(
            """SELECT r.staff_id, u.full_name, d.name AS dept_name
                 FROM survey_recipients r
                 JOIN user_tttt u ON u.id = r.staff_id
                 LEFT JOIN departments d ON d.id = u.department_id
                WHERE r.survey_id = ?
                ORDER BY d.name, u.full_name""",
            (sid,),
        ).fetchall()
    ]
    n_rec = len(recipients)
    n_done = sum(1 for r in recipients if r["responded"])
    return {
        "survey": survey,
        "questions": [{"id": q["id"], "title": q["title"], "qtype": q["qtype"]} for q in questions],
        "recipient_count": n_rec,
        "response_count": len(resp_list),
        "responded_recipients": n_done,
        "response_rate": round(n_done * 100 / n_rec, 1) if n_rec else 0.0,
        "stats": stats,
        "rows": rows,
        "recipients": recipients,
    }
