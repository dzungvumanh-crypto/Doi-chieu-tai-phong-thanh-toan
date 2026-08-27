"""Ôn tập trắc nghiệm — đọc file Excel, sinh đề, chấm điểm, xếp hạng."""
import io
import json
import sqlite3

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.db.migrations import _create_tables
from backend.main import app

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Câu hỏi", "Đáp án 1", "Đáp án 2", "Đáp án 3", "Đáp án 4", "Đáp án đúng"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_GOOD = [
    ["Thủ đô nước ta là gì?", "Hà Nội", "Huế", "Đà Nẵng", "Cần Thơ", 1],
    ["Câu chỉ có 3 lựa chọn", "A", "B", "C", None, 3],
    ["Một cộng một bằng mấy?", "1", "2", "3", "4", 2],
]


@pytest.fixture
def quiz_client(tmp_path):
    """TestClient + DB SQLite thật (file tạm) — quiz dùng executemany, JOIN nhiều
    bảng và FK CASCADE nên DB rỗng trong RAM của conftest không đủ."""
    db_file = tmp_path / "quiz.db"
    _create_tables(str(db_file))
    # check_same_thread=False: endpoint `def` của FastAPI chạy trong threadpool,
    # khác luồng với luồng dựng fixture (backend/database.py cũng mở như vậy).
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, username, pwd_hash)
           VALUES (?,?,?,?,?,'x')""",
        [(1, "A1", "Người Một", "admin", "u1"), (2, "A2", "Người Hai", "chuyen_vien", "u2")],
    )
    conn.commit()

    current = {"id": 1, "role": StaffRole.ADMIN, "username": "u1", "full_name": "Người Một"}
    def _db():
        # Phải là HÀM SINH: lambda trả về iterator thì FastAPI coi là giá trị
        # thường và tiêm nguyên cái iterator vào tham số `db`.
        yield conn

    app.dependency_overrides[get_current_staff] = lambda: current
    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    client.db = conn                       # test tự đổi dữ liệu / kiểm tra trực tiếp
    client.actor = current                 # đổi người đăng nhập giữa chừng
    yield client
    app.dependency_overrides.clear()
    conn.close()


def _upload(client, rows=None, name="Bộ thử"):
    return client.post(
        f"/api/quiz/sets/upload?name={name}",
        files={"file": ("bo.xlsx", _xlsx(_GOOD if rows is None else rows), _XLSX)},
    )


# ── Đọc file Excel ────────────────────────────────────────────────────────────
def test_nhap_file_dung_khuon(quiz_client):
    r = _upload(quiz_client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 3 and body["skipped"] == 0

    qs = quiz_client.db.execute(
        "SELECT * FROM quiz_questions ORDER BY order_no").fetchall()
    assert [q["correct_no"] for q in qs] == [1, 3, 2]
    assert qs[1]["opt4"] is None            # câu 3 lựa chọn giữ nguyên ô trống


def test_dong_hong_bi_bo_qua_con_lai_van_nhap(quiz_client):
    rows = [
        ["Câu tốt", "A", "B", "C", "D", 2],
        ["Thiếu đáp án đúng", "A", "B", "C", "D", ""],
        ["Đáp án đúng trỏ vào ô trống", "A", "B", None, None, 3],
        ["Chỉ có 1 đáp án", "A", None, None, None, 1],
        ["", "A", "B", None, None, 1],
        ["Câu tốt thứ hai", "A", "B", None, None, 1],
    ]
    body = _upload(quiz_client, rows).json()
    assert body["imported"] == 2
    assert body["skipped"] == 4
    # Thông báo phải chỉ đúng số dòng trong file (kể cả dòng tiêu đề) để người
    # nhập mở Excel là thấy ngay chỗ sai.
    assert any("Dòng 3" in e for e in body["errors"])
    assert any("Dòng 4" in e for e in body["errors"])


def test_file_khong_co_dong_nao_dung_thi_tu_choi(quiz_client):
    r = _upload(quiz_client, [["Chỉ có 1 đáp án", "A", None, None, None, 1]])
    assert r.status_code == 400
    assert quiz_client.db.execute("SELECT COUNT(*) c FROM quiz_sets").fetchone()["c"] == 0


def test_chan_tai_len_trung_ten_va_trung_noi_dung(quiz_client):
    assert _upload(quiz_client, name="Bộ A").status_code == 200
    assert _upload(quiz_client, name="Bộ A").status_code == 409          # trùng tên
    r = _upload(quiz_client, name="Bộ B")
    assert r.status_code == 409                                          # trùng nội dung
    assert "Bộ A" in r.json()["detail"]


def test_trung_noi_dung_van_bat_duoc_du_file_khac_byte(quiz_client):
    """Cùng bộ câu hỏi, hai file Excel khác nhau từng byte — vẫn phải nhận ra.

    Mỗi lần openpyxl lưu là một dấu thời gian mới trong `docProps/core.xml`,
    và người dùng thật thì mở file ra xem rồi bấm lưu. Băm byte của file sẽ
    trượt hết những ca đó, nên vân tay lấy từ nội dung câu hỏi đã đọc.
    """
    def _files(blob):
        return {"file": ("bo.xlsx", blob, _XLSX)}

    goc = _xlsx(_GOOD)
    them_cot = _xlsx([r + [None] for r in _GOOD])   # thêm cột trống ở cuối
    assert goc != them_cot                          # khác byte thật sự
    assert quiz_client.post(
        "/api/quiz/sets/upload?name=Bộ A", files=_files(goc)).status_code == 200
    r = quiz_client.post("/api/quiz/sets/upload?name=Bộ B", files=_files(them_cot))
    assert r.status_code == 409, r.text
    assert "Bộ A" in r.json()["detail"]


# ── Sinh đề ───────────────────────────────────────────────────────────────────
def test_gioi_han_so_cau_va_giu_nguyen_khi_de_0(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]

    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id,
        "settings": {"mode": "exam", "num_questions": 2},
    }).json()
    assert att["total_questions"] == 2 and len(att["questions"]) == 2

    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"num_questions": 0},
    }).json()
    assert att["total_questions"] == 3

    # Xin nhiều hơn số câu có thật → lấy hết, KHÔNG lặp lại câu
    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"num_questions": 50},
    }).json()
    ids = [q["question_id"] for q in att["questions"]]
    assert len(ids) == 3 and len(set(ids)) == 3


def test_khong_tron_thi_giu_dung_thu_tu_goc(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id,
        "settings": {"shuffle_questions": False, "shuffle_options": False},
    }).json()
    assert [q["content"] for q in att["questions"]] == [r[0] for r in _GOOD]
    assert [o["no"] for o in att["questions"][0]["options"]] == [1, 2, 3, 4]
    assert [o["no"] for o in att["questions"][1]["options"]] == [1, 2, 3]   # câu 3 lựa chọn


def test_tron_dap_an_giu_nguyen_so_thu_tu_goc(quiz_client):
    """Trộn chỉ đổi CHỖ HIỂN THỊ; `no` vẫn là số gốc nên chấm điểm không lệch."""
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"shuffle_options": True},
    }).json()
    for q in att["questions"]:
        goc = {o["no"]: o["text"] for o in q["options"]}
        row = quiz_client.db.execute(
            "SELECT * FROM quiz_questions WHERE id = ?", (q["question_id"],)).fetchone()
        for no, text in goc.items():
            assert row[f"opt{no}"] == text


def test_che_do_thi_thu_khong_lo_dap_an_truoc_khi_nop(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    exam = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"mode": "exam"}}).json()
    assert all(q["correct_no"] is None for q in exam["questions"])

    practice = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"mode": "practice"}}).json()
    assert all(q["correct_no"] is not None for q in practice["questions"])


# ── Chấm điểm ─────────────────────────────────────────────────────────────────
def _dap_an_dung(client, item) -> int:
    return client.db.execute(
        """SELECT q.correct_no FROM quiz_attempt_items i
             JOIN quiz_questions q ON q.id = i.question_id WHERE i.id = ?""",
        (item["item_id"],),
    ).fetchone()["correct_no"]


def test_cham_diem_bang_dap_an_trong_db_khong_tin_client(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"mode": "exam"}}).json()
    qs = att["questions"]

    # Câu 1 đúng, câu 2 chọn sai, câu 3 bỏ trống (không gửi lên)
    dung = _dap_an_dung(quiz_client, qs[0])
    sai = next(o["no"] for o in qs[1]["options"] if o["no"] != _dap_an_dung(quiz_client, qs[1]))
    res = quiz_client.post(f"/api/quiz/attempts/{att['id']}/submit", json={
        "answers": [
            {"item_id": qs[0]["item_id"], "chosen_no": dung, "time_ms": 1500},
            {"item_id": qs[1]["item_id"], "chosen_no": sai, "time_ms": 2500},
        ],
        "duration_ms": 9000,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["correct_count"], body["wrong_count"], body["skipped_count"]) == (1, 1, 1)
    assert body["score"] == pytest.approx(33.3)
    assert len(body["review"]) == 3


def test_khong_nop_duoc_hai_lan(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts",
                           json={"set_id": set_id, "settings": {}}).json()
    assert quiz_client.post(
        f"/api/quiz/attempts/{att['id']}/submit", json={"answers": []}).status_code == 200
    assert quiz_client.post(
        f"/api/quiz/attempts/{att['id']}/submit", json={"answers": []}).status_code == 409


def test_khong_xem_duoc_bai_cua_nguoi_khac(quiz_client):
    """Chủ sở hữu bài chặn ở cả /attempts và /submit — kể cả admin.

    Chỉ /result mới mở cho admin (hỗ trợ tra soát), vì tới lúc đó bài đã nộp.
    """
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts",
                           json={"set_id": set_id, "settings": {}}).json()
    quiz_client.db.execute("UPDATE quiz_attempts SET staff_id = 2 WHERE id = ?", (att["id"],))
    quiz_client.db.commit()
    assert quiz_client.get(f"/api/quiz/attempts/{att['id']}").status_code == 403
    assert quiz_client.post(
        f"/api/quiz/attempts/{att['id']}/submit", json={"answers": []}).status_code == 403


def test_item_cua_luot_khac_bi_bo_qua(quiz_client):
    """Gửi item_id của bài khác không được cộng điểm sang bài này."""
    set_id = _upload(quiz_client).json()["set_id"]
    a1 = quiz_client.post("/api/quiz/attempts",
                          json={"set_id": set_id, "settings": {}}).json()
    a2 = quiz_client.post("/api/quiz/attempts",
                          json={"set_id": set_id, "settings": {}}).json()
    lac = a2["questions"][0]
    res = quiz_client.post(f"/api/quiz/attempts/{a1['id']}/submit", json={
        "answers": [{"item_id": lac["item_id"],
                     "chosen_no": _dap_an_dung(quiz_client, lac), "time_ms": 100}],
    }).json()
    assert res["correct_count"] == 0
    assert res["skipped_count"] == 3


# ── Xếp hạng & lịch sử ────────────────────────────────────────────────────────
def _lam_bai(client, set_id, so_cau_dung: int, duration_ms: int, mode="exam"):
    att = client.post("/api/quiz/attempts",
                      json={"set_id": set_id, "settings": {"mode": mode}}).json()
    answers = []
    for i, q in enumerate(att["questions"]):
        dung = _dap_an_dung(client, q)
        chon = dung if i < so_cau_dung else next(
            o["no"] for o in q["options"] if o["no"] != dung)
        answers.append({"item_id": q["item_id"], "chosen_no": chon, "time_ms": 100})
    return client.post(f"/api/quiz/attempts/{att['id']}/submit",
                       json={"answers": answers, "duration_ms": duration_ms}).json()


def test_xep_hang_lay_luot_tot_nhat_moi_nguoi(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    _lam_bai(quiz_client, set_id, 1, 5000)
    _lam_bai(quiz_client, set_id, 3, 4000)          # lượt tốt nhất của Người Một
    # Giữ vai admin: `require_feature` cho admin đi thẳng, khỏi phải dựng
    # user_groups/group_features chỉ để đổi người làm bài.
    quiz_client.actor.update(id=2, full_name="Người Hai")
    _lam_bai(quiz_client, set_id, 3, 9000)          # cùng điểm nhưng chậm hơn

    bxh = quiz_client.get(f"/api/quiz/sets/{set_id}/leaderboard").json()
    assert len(bxh) == 2
    assert [r["staff_name"] for r in bxh] == ["Người Một", "Người Hai"]
    assert bxh[0]["score"] == 100.0


def test_xep_hang_bo_qua_bai_on_tap(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    _lam_bai(quiz_client, set_id, 3, 1000, mode="practice")
    assert quiz_client.get(f"/api/quiz/sets/{set_id}/leaderboard").json() == []


def test_danh_sach_bo_kem_diem_tot_nhat_cua_toi(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    _lam_bai(quiz_client, set_id, 2, 3000)
    s = quiz_client.get("/api/quiz/sets").json()[0]
    assert s["question_count"] == 3
    assert s["my_attempts"] == 1
    assert s["my_best_score"] == pytest.approx(66.7)
    assert s["created_by_name"] == "Người Một"


def test_xoa_bo_keo_theo_cau_hoi_va_luot_lam_bai(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    _lam_bai(quiz_client, set_id, 3, 1000)
    r = quiz_client.delete(f"/api/quiz/sets/{set_id}")
    assert r.status_code == 200 and r.json()["deleted_attempts"] == 1
    for bang in ("quiz_questions", "quiz_attempts", "quiz_attempt_items"):
        assert quiz_client.db.execute(f"SELECT COUNT(*) c FROM {bang}").fetchone()["c"] == 0


def test_nap_lai_de_dang_lam_do_giu_nguyen_thu_tu(quiz_client):
    """F5 giữa bài: đề phải y hệt, không sinh lại thứ tự mới."""
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id, "settings": {"shuffle_questions": True, "shuffle_options": True},
    }).json()
    lai = quiz_client.get(f"/api/quiz/attempts/{att['id']}").json()
    assert [q["question_id"] for q in lai["questions"]] == \
           [q["question_id"] for q in att["questions"]]
    assert [[o["no"] for o in q["options"]] for q in lai["questions"]] == \
           [[o["no"] for o in q["options"]] for q in att["questions"]]
    assert lai["settings"]["shuffle_options"] is True


def test_thong_so_luu_kem_luot_lam_bai(quiz_client):
    set_id = _upload(quiz_client).json()["set_id"]
    att = quiz_client.post("/api/quiz/attempts", json={
        "set_id": set_id,
        "settings": {"mode": "exam", "seconds_per_question": 30, "total_minutes": 10,
                     "instant_feedback": False},
    }).json()
    luu = json.loads(quiz_client.db.execute(
        "SELECT settings FROM quiz_attempts WHERE id = ?", (att["id"],)).fetchone()["settings"])
    assert luu["seconds_per_question"] == 30
    assert luu["total_minutes"] == 10
    assert luu["instant_feedback"] is False
