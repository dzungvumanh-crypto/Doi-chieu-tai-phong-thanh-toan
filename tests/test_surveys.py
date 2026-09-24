"""Khảo sát — người nhận, hạn chót, kiểm tra câu trả lời, thống kê, việc chờ xử lý."""
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import _vn_now, get_db
from backend.db.migrations import _create_tables
from backend.main import app
from tests.conftest import cap_quyen


def _dt(**kw) -> str:
    return (_vn_now() + timedelta(**kw)).strftime("%Y-%m-%d %H:%M")


@pytest.fixture
def sv(tmp_path):
    """DB SQLite thật (file tạm): khảo sát dùng FK CASCADE + JOIN nhóm user."""
    db_file = tmp_path / "sv.db"
    _create_tables(str(db_file))
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Cột này chỉ thêm qua schema_migrations, _create_tables không có — DB thật luôn có.
    conn.execute("ALTER TABLE user_tttt ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
    conn.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, username, pwd_hash, is_active)
           VALUES (?,?,?,?,?,'x',?)""",
        [(1, "A1", "Người tạo", "chuyen_vien", "u1", 1),
         (2, "A2", "Người Hai", "chuyen_vien", "u2", 1),
         (3, "A3", "Người Ba", "chuyen_vien", "u3", 1),
         (4, "A4", "Người Nghỉ", "chuyen_vien", "u4", 0)],
    )
    # Nhóm đích: 2, 3 và một người đã nghỉ việc (không được nhận)
    conn.execute("INSERT INTO user_groups (id, name, is_active) VALUES (10, 'Nhóm KS', 1)")
    conn.executemany("INSERT INTO group_members (group_id, staff_id) VALUES (10, ?)", [(2,), (3,), (4,)])
    conn.commit()
    cap_quyen(conn, 1, "menu.surveys", "surveys.create")

    who = {"id": 1, "role": "chuyen_vien", "username": "u1", "full_name": "Người tạo"}

    def _db():
        yield conn

    app.dependency_overrides[get_current_staff] = lambda: dict(who)
    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    client.db = conn
    client.who = who
    yield client
    app.dependency_overrides.clear()
    conn.close()


def _as(client, sid: int, role="chuyen_vien"):
    client.who.update(id=sid, role=role)


_QS = [
    {"qtype": "single", "title": "Hài lòng không?", "required": True, "options": ["Có", "Không"]},
    {"qtype": "multi", "title": "Chọn món", "options": ["Phở", "Bún", "Cơm"]},
    {"qtype": "scale", "title": "Chấm điểm", "scale_min": 1, "scale_max": 5},
    {"qtype": "paragraph", "title": "Góp ý"},
]


def _tao(client, **over) -> int:
    body = {"title": "KS thử", "deadline": _dt(days=3), "group_ids": [10], "questions": _QS}
    body.update(over)
    r = client.post("/api/surveys", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _phat_hanh(client, **over) -> int:
    sid = _tao(client, **over)
    r = client.post(f"/api/surveys/{sid}/publish")
    assert r.status_code == 200, r.text
    return sid


def _qids(client, sid):
    return [r["id"] for r in client.db.execute(
        "SELECT id FROM survey_questions WHERE survey_id = ? ORDER BY order_no", (sid,))]


def _nop(client, sid, values):
    ans = [{"question_id": q, "value": v} for q, v in zip(_qids(client, sid), values)]
    return client.post(f"/api/surveys/{sid}/responses", json={"answers": ans})


# ── Soạn & phát hành ──────────────────────────────────────────────────────────
def test_lua_chon_trung_hoac_thieu_bi_chan(sv):
    bad = [{"qtype": "single", "title": "X", "options": ["A", "a"]}]
    assert sv.post("/api/surveys", json={"title": "T", "questions": bad}).status_code == 422
    bad = [{"qtype": "dropdown", "title": "X", "options": ["A", "  "]}]
    assert sv.post("/api/surveys", json={"title": "T", "questions": bad}).status_code == 422


def test_phat_hanh_chot_nguoi_nhan_bo_nguoi_nghi_viec(sv):
    sid = _phat_hanh(sv)
    rec = {r["staff_id"] for r in sv.db.execute(
        "SELECT staff_id FROM survey_recipients WHERE survey_id = ?", (sid,))}
    assert rec == {2, 3}


def test_phat_hanh_thieu_dieu_kien(sv):
    sid = _tao(sv, group_ids=[])
    assert sv.post(f"/api/surveys/{sid}/publish").status_code == 400
    sid = _tao(sv, questions=[])
    assert sv.post(f"/api/surveys/{sid}/publish").status_code == 400
    sid = _tao(sv, deadline=_dt(minutes=-5))
    assert sv.post(f"/api/surveys/{sid}/publish").status_code == 400


def test_nguoi_khong_phai_chu_khong_sua_duoc(sv):
    sid = _tao(sv)
    cap_quyen(sv.db, 2, "menu.surveys", "surveys.create")
    _as(sv, 2)
    body = {"title": "Đổi", "questions": _QS, "group_ids": [10]}
    assert sv.put(f"/api/surveys/{sid}", json=body).status_code == 403
    assert sv.get(f"/api/surveys/{sid}/results").status_code == 403


# ── Trả lời ───────────────────────────────────────────────────────────────────
def test_tra_loi_khong_can_ma_quyen_chi_can_co_ten(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)                                   # người 2 KHÔNG có mã quyền nào
    assert _nop(sv, sid, [0, [0, 2], 4, "Tốt"]).status_code == 200
    _as(sv, 1)                                   # người tạo không có tên nhận
    assert _nop(sv, sid, [0, [], None, ""]).status_code == 403


def test_kiem_tra_gia_tri_tra_loi(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)
    assert _nop(sv, sid, [None, [], None, ""]).status_code == 400       # thiếu câu bắt buộc
    assert _nop(sv, sid, [5, [], None, ""]).status_code == 400          # lựa chọn không có
    assert _nop(sv, sid, [0, [9], None, ""]).status_code == 400
    assert _nop(sv, sid, [0, [], 6, ""]).status_code == 400             # ngoài thang
    assert _nop(sv, sid, [True, [], None, ""]).status_code == 400       # bool không phải số


def test_khong_nop_lai_tru_khi_cho_sua(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)
    assert _nop(sv, sid, [0, [], None, ""]).status_code == 200
    assert _nop(sv, sid, [1, [], None, ""]).status_code == 409

    _as(sv, 1)
    sid2 = _phat_hanh(sv, allow_edit=True)
    _as(sv, 2)
    assert _nop(sv, sid2, [0, [], None, ""]).status_code == 200
    assert _nop(sv, sid2, [1, [], None, ""]).status_code == 200
    n = sv.db.execute("SELECT COUNT(*) c FROM survey_responses WHERE survey_id = ?", (sid2,)).fetchone()["c"]
    assert n == 1


def test_qua_han_va_chua_toi_gio(sv):
    sid = _phat_hanh(sv)
    sv.db.execute("UPDATE surveys SET deadline = ? WHERE id = ?",
                  ((_vn_now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"), sid))
    sv.db.commit()
    _as(sv, 2)
    assert _nop(sv, sid, [0, [], None, ""]).status_code == 409

    _as(sv, 1)
    sid2 = _phat_hanh(sv, start_at=_dt(days=1))
    _as(sv, 2)
    r = _nop(sv, sid2, [0, [], None, ""])
    assert r.status_code == 409 and "chưa tới giờ" in r.json()["detail"]


def test_khoa_cau_hoi_khi_da_co_tra_loi(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)
    _nop(sv, sid, [0, [], None, ""])
    _as(sv, 1)
    doi = [dict(_QS[0], options=["Có", "Không", "Tuỳ"])] + _QS[1:]
    r = sv.put(f"/api/surveys/{sid}", json={"title": "KS", "deadline": _dt(days=3),
                                           "group_ids": [10], "questions": doi})
    assert r.status_code == 409
    # Giữ nguyên câu hỏi, chỉ đổi tên + gia hạn + mô tả câu → được, và mô tả phải được ghi
    giu = [dict(_QS[0], description="Chọn một ý")] + _QS[1:]
    r = sv.put(f"/api/surveys/{sid}", json={"title": "KS mới", "deadline": _dt(days=5),
                                           "group_ids": [10], "questions": giu})
    assert r.status_code == 200, r.text
    mo_ta = sv.db.execute("SELECT description FROM survey_questions WHERE survey_id = ? AND order_no = 1",
                          (sid,)).fetchone()["description"]
    assert mo_ta == "Chọn một ý"


def test_doi_nhom_giu_nguoi_da_tra_loi(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)
    _nop(sv, sid, [0, [], None, ""])
    _as(sv, 1)
    sv.db.execute("INSERT INTO user_groups (id, name, is_active) VALUES (99, 'Nhóm khác', 1)")
    sv.db.execute("INSERT INTO group_members (group_id, staff_id) VALUES (99, 1)")
    sv.db.commit()
    r = sv.put(f"/api/surveys/{sid}", json={"title": "KS", "deadline": _dt(days=3),
                                           "group_ids": [99], "questions": _QS})
    assert r.status_code == 200, r.text
    rec = {x["staff_id"] for x in sv.db.execute(
        "SELECT staff_id FROM survey_recipients WHERE survey_id = ?", (sid,))}
    # 2 đã trả lời → giữ; 3 chưa trả lời → bỏ; 1 thuộc nhóm mới → thêm
    assert rec == {1, 2}


# ── Thống kê ──────────────────────────────────────────────────────────────────
def test_thong_ke_va_an_danh(sv):
    sid = _phat_hanh(sv, is_anonymous=True)
    _as(sv, 2)
    _nop(sv, sid, [0, [0, 1], 5, "Rất tốt"])
    _as(sv, 3)
    _nop(sv, sid, [1, [0], 3, ""])
    _as(sv, 1)
    res = sv.get(f"/api/surveys/{sid}/results").json()
    assert res["recipient_count"] == 2 and res["response_rate"] == 100.0
    single, multi, scale, text = res["stats"]
    assert [o["count"] for o in single["options"]] == [1, 1]
    assert [o["count"] for o in multi["options"]] == [2, 1, 0]
    assert multi["options"][0]["pct"] == 100.0            # % trên số người trả lời câu
    assert scale["average"] == 4.0
    assert text["texts"] == [{"text": "Rất tốt", "staff_name": None}]
    assert all(r["staff_name"] is None and r["submitted_at"] is None for r in res["rows"])
    assert all(r["submitted_at"] is None for r in res["recipients"])

    x = sv.get(f"/api/surveys/{sid}/export")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_an_danh_xep_theo_noi_dung_khong_theo_thu_tu_nop(sv):
    # Thứ tự nộp tra được từ Nhật ký hệ thống — dòng ẩn danh không được mang theo nó.
    # 5 lượt khác nhau đúng ở câu văn bản, nộp theo thứ tự NGƯỢC chữ cái. Cần đủ nhiều
    # dòng: với 2 dòng, phép trộn cũ random.Random(sid) tình cờ ra đúng thứ tự và test
    # xanh cả trên mã lỗi (đã thử 11/09/2026).
    sv.db.executemany(
        """INSERT INTO user_tttt (id, employee_code, full_name, role, username, pwd_hash, is_active)
           VALUES (?,?,?,'chuyen_vien',?,'x',1)""",
        [(i, f"A{i}", f"Người {i}", f"u{i}") for i in (5, 6, 7)])
    sv.db.executemany("INSERT INTO group_members (group_id, staff_id) VALUES (10, ?)", [(5,), (6,), (7,)])
    sv.db.commit()
    sid = _phat_hanh(sv, is_anonymous=True)
    chu = ["Eee", "Ddd", "Ccc", "Bbb", "Aaa"]
    for staff, txt in zip((2, 3, 5, 6, 7), chu):
        _as(sv, staff)
        assert _nop(sv, sid, [0, [], None, txt]).status_code == 200
    _as(sv, 1)
    res = sv.get(f"/api/surveys/{sid}/results").json()
    assert [r["answers"][3] for r in res["rows"]] == sorted(chu)
    assert [t["text"] for t in res["stats"][3]["texts"]] == sorted(chu)


def test_khong_tat_an_danh_sau_phat_hanh(sv):
    body = {"title": "KS", "deadline": _dt(days=3), "group_ids": [10], "questions": _QS}
    # Bản nháp: bật/tắt tự do
    sid = _tao(sv, is_anonymous=True)
    assert sv.put(f"/api/surveys/{sid}", json=dict(body, is_anonymous=False)).status_code == 200
    # Đã phát hành ẩn danh: tắt → 409 (khoá ở giao diện chưa đủ, gọi thẳng API vẫn tới đây)
    sid = _phat_hanh(sv, is_anonymous=True)
    r = sv.put(f"/api/surveys/{sid}", json=dict(body, is_anonymous=False))
    assert r.status_code == 409, r.text
    assert sv.db.execute("SELECT is_anonymous FROM surveys WHERE id = ?", (sid,)).fetchone()[0] == 1
    # Chiều ngược lại (bật ẩn danh sau phát hành) chỉ giấu bớt — được
    sid = _phat_hanh(sv)
    assert sv.put(f"/api/surveys/{sid}", json=dict(body, is_anonymous=True)).status_code == 200


def test_bat_an_danh_khi_da_co_tra_loi_bi_chan(sv):
    # Chủ đã xem các bài có tên; bật ẩn danh rồi người nộp sau tưởng mình ẩn danh —
    # trừ các bài đã biết là ra bài của họ.
    body = {"title": "KS", "deadline": _dt(days=3), "group_ids": [10], "questions": _QS}
    sid = _phat_hanh(sv)
    _as(sv, 2)
    _nop(sv, sid, [0, [], None, ""])
    _as(sv, 1)
    assert sv.put(f"/api/surveys/{sid}", json=dict(body, is_anonymous=True)).status_code == 409


def test_nop_bang_id_cau_hoi_cu_bi_409_khong_luu_bai_rong(sv):
    # Người nhận mở biểu mẫu, chủ bấm Lưu (chưa ai trả lời → câu hỏi ghi lại, id mới),
    # người nhận bấm Gửi với id cũ. Bản đầu: 200 + một bài 0 câu trả lời.
    # Toàn câu KHÔNG bắt buộc: có câu bắt buộc thì mã cũ trả 400 ("thiếu câu bắt buộc")
    # và test đỏ vì lý do khác lỗi thật.
    tuy_y = [dict(q, required=False) for q in _QS]
    sid = _phat_hanh(sv, questions=tuy_y)
    cu = _qids(sv, sid)
    r = sv.put(f"/api/surveys/{sid}", json={"title": "KS", "deadline": _dt(days=3),
                                           "group_ids": [10], "questions": tuy_y})
    assert r.status_code == 200 and _qids(sv, sid) != cu
    _as(sv, 2)
    ans = [{"question_id": q, "value": v} for q, v in zip(cu, [0, [], None, "x"])]
    r = sv.post(f"/api/surveys/{sid}/responses", json={"answers": ans})
    assert r.status_code == 409, r.text
    assert sv.db.execute("SELECT COUNT(*) FROM survey_responses WHERE survey_id = ?", (sid,)).fetchone()[0] == 0


def _ket_noi_thu_hai(sv) -> sqlite3.Connection:
    """Kết nối riêng tới cùng file DB tạm — mô phỏng request khác chạy xen giữa."""
    c2 = sqlite3.connect(sv.db.execute("PRAGMA database_list").fetchone()["file"])
    c2.execute("PRAGMA foreign_keys=ON")
    return c2


def test_dua_chu_sua_cau_hoi_giua_luc_nop_khong_bao_da_ghi_nhan(sv, monkeypatch):
    # Nộp đọc câu hỏi (id cũ) xong thì chủ ghi lại câu hỏi và commit → ghi câu trả lời vỡ
    # FK. Bản đầu coi mọi IntegrityError là "bấm Gửi hai lần" → báo "đã ghi nhận" với 0 bài.
    import backend.api.surveys as mod
    sid = _phat_hanh(sv, questions=[dict(q, required=False) for q in _QS])
    that = mod.svc.doc_cau_hoi

    def doc_roi_bi_sua(db, s_id):
        out = that(db, s_id)
        c2 = _ket_noi_thu_hai(sv)
        c2.execute("DELETE FROM survey_questions WHERE survey_id = ?", (s_id,))
        c2.execute("INSERT INTO survey_questions (survey_id, order_no, qtype, title, options) "
                   "VALUES (?, 1, 'short_text', 'Mới', '[]')", (s_id,))
        c2.commit()
        c2.close()
        return out

    cu = _qids(sv, sid)
    monkeypatch.setattr(mod.svc, "doc_cau_hoi", doc_roi_bi_sua)
    _as(sv, 2)
    ans = [{"question_id": q, "value": v} for q, v in zip(cu, [0, [1], 4, "abc"])]
    r = sv.post(f"/api/surveys/{sid}/responses", json={"answers": ans})
    assert r.status_code == 409 and "tải lại trang rồi trả lời lại" in r.json()["detail"]
    assert sv.db.execute("SELECT COUNT(*) FROM survey_responses WHERE survey_id = ?", (sid,)).fetchone()[0] == 0


def test_dua_bai_nop_chen_giua_luc_put_dem_va_xoa_cau_hoi(sv, monkeypatch):
    # PUT đếm "chưa ai trả lời" (ngoài giao dịch), rồi một bài commit từ kết nối khác, rồi
    # PUT xoá câu hỏi → câu trả lời của bài đó mất theo FK CASCADE. Phải 409 + giữ nguyên.
    import backend.api.surveys as mod
    sid = _phat_hanh(sv)
    cu = _qids(sv, sid)
    that, lan = mod._so_tra_loi, {"n": 0}

    def dem(db, s_id):
        lan["n"] += 1
        v = that(db, s_id)
        if lan["n"] == 1:
            c2 = _ket_noi_thu_hai(sv)
            rid = c2.execute("INSERT INTO survey_responses (survey_id, staff_id, submitted_at) "
                             "VALUES (?, 2, '2026-09-11 10:00:00')", (s_id,)).lastrowid
            c2.execute("INSERT INTO survey_answers VALUES (?, ?, '0')", (rid, cu[0]))
            c2.commit()
            c2.close()
        return v

    monkeypatch.setattr(mod, "_so_tra_loi", dem)
    r = sv.put(f"/api/surveys/{sid}", json={"title": "Đổi tên", "deadline": _dt(days=3),
                                           "group_ids": [10], "questions": _QS})
    assert r.status_code == 409, r.text
    assert sv.db.execute("SELECT COUNT(*) FROM survey_answers").fetchone()[0] == 1
    assert _qids(sv, sid) == cu
    assert sv.db.execute("SELECT title FROM surveys WHERE id = ?", (sid,)).fetchone()[0] == "KS thử"


def test_view_all_khong_xem_ban_nhap_nguoi_khac(sv):
    sid = _tao(sv)                                         # bản nháp của người 1
    cap_quyen(sv.db, 3, "menu.surveys", "surveys.view_all")
    _as(sv, 3)
    assert sv.get(f"/api/surveys/{sid}").status_code == 404
    assert sv.get("/api/surveys/manage?scope=all").json() == []


def test_xuat_excel_an_danh_khong_co_ten(sv):
    import io
    import openpyxl
    sid = _phat_hanh(sv, is_anonymous=True)
    _as(sv, 2)
    _nop(sv, sid, [0, [], None, "Góp ý kín"])
    _as(sv, 1)
    wb = openpyxl.load_workbook(io.BytesIO(sv.get(f"/api/surveys/{sid}/export").content))
    o = {str(c.value) for ws in (wb["Tổng hợp"], wb["Câu trả lời"]) for row in ws.iter_rows() for c in row}
    assert "Góp ý kín" in o and "Người Hai" not in o


def test_nhat_ky_khong_chua_noi_dung_tra_loi(sv, monkeypatch):
    # Hai đường vào audit_logs, canh cả hai:
    # - AuditMiddleware ghi CẢ BODY qua audit_queue (kết nối riêng tới DB thật, không phải
    #   DB tạm của test) → canh bằng cách chặn enqueue: /api/surveys phải không đi qua nó.
    # - write_audit() trong route → đọc thẳng audit_logs của DB tạm.
    from backend.core import audit_queue
    goi = []
    monkeypatch.setattr(audit_queue, "enqueue", lambda *a, **kw: goi.append((a, kw)))
    sid = _phat_hanh(sv, is_anonymous=True)
    _as(sv, 2)
    _nop(sv, sid, [0, [], None, "Nội dung bí mật"])
    assert goi == []
    logs = [dict(r) for r in sv.db.execute("SELECT action, detail FROM audit_logs")]
    assert any(r["action"] == "survey.submit" for r in logs)
    assert not any("bí mật" in (r["detail"] or "") for r in logs)


def test_xem_tat_ca_can_ma_view_all(sv):
    sid = _phat_hanh(sv)
    cap_quyen(sv.db, 3, "menu.surveys")
    _as(sv, 3)
    assert sv.get(f"/api/surveys/{sid}/results").status_code == 403
    assert sv.get("/api/surveys/manage?scope=all").status_code == 403
    cap_quyen(sv.db, 3, "surveys.view_all")
    assert sv.get(f"/api/surveys/{sid}/results").status_code == 200
    assert len(sv.get("/api/surveys/manage?scope=all").json()) == 1


# ── Công việc chờ xử lý ───────────────────────────────────────────────────────
def test_viec_cho_xu_ly(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)
    c = sv.get("/api/dashboard/pending-counts").json()
    assert c["surveys"] == 1
    items = sv.get("/api/dashboard/pending-items").json()["surveys"]
    assert [i["id"] for i in items] == [sid]
    _nop(sv, sid, [0, [], None, ""])
    assert sv.get("/api/dashboard/pending-counts").json()["surveys"] == 0

    _as(sv, 3)
    sv.post(f"/api/surveys/{sid}/close")               # 3 không phải chủ → 403, vẫn chờ
    assert sv.get("/api/dashboard/pending-counts").json()["surveys"] == 1
    _as(sv, 1)
    assert sv.post(f"/api/surveys/{sid}/close").status_code == 200
    _as(sv, 3)
    assert sv.get("/api/dashboard/pending-counts").json()["surveys"] == 0


def test_xoa_khao_sat_xoa_theo_tra_loi(sv):
    sid = _phat_hanh(sv)
    _as(sv, 2)
    _nop(sv, sid, [0, [], None, ""])
    _as(sv, 1)
    assert sv.delete(f"/api/surveys/{sid}").json()["deleted_responses"] == 1
    for t in ("survey_questions", "survey_recipients", "survey_responses", "survey_answers"):
        assert sv.db.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] == 0
