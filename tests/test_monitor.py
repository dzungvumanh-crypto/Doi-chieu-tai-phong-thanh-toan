"""Màn Giám sát hệ thống — /api/admin/monitor/overview.

Chạy: python -m pytest tests/test_monitor.py -v
"""
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import backend.api.logs as logs_api
import backend.api.monitor as mon
from backend.core.deps import get_current_staff
from backend.database import _vn_now, get_db
from backend.main import app
from tests.conftest import cap_quyen

_SCHEMA = """
CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, username TEXT);
CREATE TABLE user_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, is_active INTEGER);
CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
CREATE TABLE login_sessions (staff_id INTEGER PRIMARY KEY, ip_address TEXT, expires_at TEXT, session_key TEXT);
CREATE TABLE login_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, staff_id INTEGER,
                         ip_address TEXT, success INTEGER, detail TEXT, created_at DATETIME);
CREATE TABLE login_rate_limit (username TEXT PRIMARY KEY, attempt_count INTEGER, window_start TEXT, locked_until TEXT);
CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
                         target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT, created_at DATETIME);
"""


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO user_tttt (id, username) VALUES (2, 'cv')")
    conn.commit()

    # Không đụng máy thật: thư mục data, app.log, NTP, backup đều trỏ sang chỗ giả
    (tmp_path / "data" / "temp_ach").mkdir(parents=True)
    (tmp_path / "data" / "temp_ach" / "a.xlsx").write_bytes(b"x" * 1000)
    monkeypatch.setattr(mon, "BASE_DIR", tmp_path)
    monkeypatch.setattr(logs_api, "_LOG_PATH", str(tmp_path / "logs" / "app.log"))
    monkeypatch.setattr("backend.services.time_sync.check_drift",
                        lambda force=False: {"enabled": False, "ok": False, "error": None})
    monkeypatch.setattr("backend.services.backup_service.last_backup_info",
                        lambda: {"exists": True, "path": "D:/bi/mat", "time": datetime.now().strftime("%H:%M %d/%m/%Y"),
                                 "count": 3, "count_thu_cong": 0})
    monkeypatch.setattr(mon, "_cpu_phan_tram", lambda giay=0.3: 5.0)

    nguoi = {"id": 2, "role": "chuyen_vien", "username": "cv", "full_name": "CV"}

    def _db():
        yield conn
    app.dependency_overrides[get_current_staff] = lambda: nguoi
    app.dependency_overrides[get_db] = _db
    yield TestClient(app), conn
    app.dependency_overrides.clear()
    conn.close()


def test_khong_co_quyen_thi_403(ctx):
    client, _ = ctx
    assert client.get("/api/admin/monitor/overview").status_code == 403


def test_quyen_nhat_ky_khong_mo_duoc_giam_sat(ctx):
    # Tách mã có chủ đích — cấp menu.logs không kéo theo xem tải máy chủ
    client, conn = ctx
    cap_quyen(conn, 2, "menu.logs")
    assert client.get("/api/admin/monitor/overview").status_code == 403


def test_co_quyen_thi_du_khoi_va_dem_dung_24h(ctx):
    client, conn = ctx
    cap_quyen(conn, 2, "menu.monitor")
    gan = _vn_now() - timedelta(hours=1)
    cu = _vn_now() - timedelta(days=3)
    conn.executemany("INSERT INTO login_logs (username, success, created_at) VALUES (?,?,?)",
                     [("a", 1, gan), ("a", 0, gan), ("b", 0, gan), ("c", 0, cu)])
    conn.commit()

    r = client.get("/api/admin/monitor/overview")
    assert r.status_code == 200
    d = r.json()
    for khoa in ("may_chu", "tai", "csdl", "dia", "sao_luu", "dong_ho", "nhat_ky", "nguoi_dung", "canh_bao", "tong_the"):
        assert khoa in d, khoa
    assert d["nguoi_dung"]["dang_nhap_ok"] == 1
    assert d["nguoi_dung"]["dang_nhap_sai"] == 2          # dòng 3 ngày trước không tính
    assert d["csdl"]["ok"] is True
    assert d["dia"]["tam_chi_tiet"] == {"temp_ach": 1000}
    assert "path" not in d["sao_luu"]                      # không lộ đường dẫn tuyệt đối
    assert d["tong_the"] in ("tot", "canh_bao", "loi")


def test_quet_log_chi_dem_24h_va_bo_dong_noi(tmp_path):
    now = datetime.now()
    f = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
    p = tmp_path / "app.log"
    p.write_text("\n".join([
        f"{f(now - timedelta(days=2))} ERROR    x — lỗi cũ",
        f"{f(now - timedelta(hours=2))} ERROR    backend.api — hỏng rồi",
        "Traceback (most recent call last):",
        "  ERROR giả nằm trong traceback",
        f"{f(now - timedelta(hours=1))} WARNING  slow.request — Request chậm: GET /api/x",
        f"{f(now - timedelta(minutes=5))} WARNING  audit — cảnh báo khác",
        f"{f(now)} INFO     x — thông tin",
    ]) + "\n", encoding="utf-8")
    r = mon._quet_log([p], now - timedelta(hours=24))
    assert (r["loi"], r["canh_bao"], r["request_cham"]) == (1, 2, 1)
    assert r["loi_gan"][0]["nguon"] == "backend.api" and r["loi_gan"][0]["msg"] == "hỏng rồi"


def test_file_log_xoay_vong_trong_cua_so_thi_doc_them_ban_cu(tmp_path):
    now = datetime.now()
    moi, cu = tmp_path / "app.log", tmp_path / "app.log.1"
    moi.write_text(f"{(now - timedelta(hours=1)):%Y-%m-%d %H:%M:%S} INFO     x — a\n", encoding="utf-8")
    cu.write_text("", encoding="utf-8")
    assert mon._file_log(moi, now - timedelta(hours=24)) == [moi, cu]
    assert mon._file_log(moi, now - timedelta(minutes=5)) == [moi]


def _tot() -> dict:
    return {
        "csdl": {"ok": True},
        "dia": {"o_dia": {"tong": 500 * mon._GB, "con_trong": 300 * mon._GB, "o": "D:"}, "wal": 0},
        "sao_luu": {"exists": True, "tuoi_gio": 3, "time": "x"},
        "dong_ho": {"enabled": True, "ok": True, "error": None},
        "may_chu": {"ram": {"phan_tram": 40}},
        "nhat_ky": {"loi": 0},
        "tai": {"loop_chan_max_ms": 20, "luong_cho": 0, "csdl_xep_cong": 0,
                "hang_doi_nhat_ky": 0, "hang_doi_nhat_ky_toi_da": 2000},
        "nguoi_dung": {"dang_nhap_sai": 0},
    }


def test_danh_gia_binh_thuong_thi_khong_canh_bao():
    assert mon.danh_gia(_tot()) == []


def test_danh_gia_o_day_va_backup_ngung_la_loi_dung_dau():
    d = _tot()
    d["nhat_ky"]["loi"] = 3
    d["dia"]["o_dia"]["con_trong"] = 1 * mon._GB
    d["sao_luu"]["tuoi_gio"] = 60
    ra = mon.danh_gia(d)
    assert [c["muc"] for c in ra] == ["loi", "loi", "canh_bao"]
    assert {c["nhom"] for c in ra} == {"Ổ đĩa", "Sao lưu", "Nhật ký"}


def test_noi_dung_dong_loi_chi_cho_nguoi_co_menu_logs(ctx, tmp_path):
    # Số đếm ai có menu.monitor cũng thấy; NỘI DUNG dòng lỗi là nhật ký — cần menu.logs
    client, conn = ctx
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text(
        f"{datetime.now():%Y-%m-%d %H:%M:%S} ERROR    x — dữ liệu nhạy cảm\n", encoding="utf-8")
    cap_quyen(conn, 2, "menu.monitor")
    nk = client.get("/api/admin/monitor/overview").json()["nhat_ky"]
    assert nk["loi"] == 1 and nk["loi_gan"] == [] and nk["xem_noi_dung"] is False
    cap_quyen(conn, 2, "menu.logs")
    nk = client.get("/api/admin/monitor/overview").json()["nhat_ky"]
    assert nk["loi_gan"][0]["msg"] == "dữ liệu nhạy cảm"


def test_doi_chieu_khong_lo_job_id(ctx, monkeypatch):
    client, conn = ctx
    cap_quyen(conn, 2, "menu.monitor")
    monkeypatch.setattr("backend.core.phien_doi_chieu.dang_chay", lambda: [
        {"module": "ach", "ten_module": "ACH", "job_id": "bi-mat", "task_token": "t", "status": "running", "tuoi_giay": 5}])
    (j,) = client.get("/api/admin/monitor/overview").json()["tai"]["doi_chieu"]
    assert j == {"module": "ach", "ten_module": "ACH", "status": "running", "tuoi_giay": 5}


def test_so_lieu_tai_hong_thi_bao_loi_khong_500(ctx, monkeypatch):
    client, conn = ctx
    cap_quyen(conn, 2, "menu.monitor")

    def vo(tu):
        raise RuntimeError("hỏng")
    monkeypatch.setattr("backend.core.slow_request.so_lieu_tai", vo)
    d = client.get("/api/admin/monitor/overview").json()
    assert d["tai"] is None and d["tong_the"] == "loi"


def test_file_log_doc_qua_nhieu_ban_xoay_toi_khi_phu_moc(tmp_path):
    now = datetime.now()
    ghi = lambda ten, gio: (tmp_path / ten).write_text(  # noqa: E731
        f"{(now - timedelta(hours=gio)):%Y-%m-%d %H:%M:%S} INFO     x — a\n", encoding="utf-8")
    ghi("app.log", 1)
    ghi("app.log.1", 5)
    ghi("app.log.2", 30)        # bắt đầu trước mốc 24 h → dừng ở đây
    ghi("app.log.3", 60)
    ds = mon._file_log(tmp_path / "app.log", now - timedelta(hours=24))
    assert [p.name for p in ds] == ["app.log", "app.log.1", "app.log.2"]


def test_log_xoay_het_thi_bao_khong_day_du():
    d = _tot()
    d["nhat_ky"].update(day_du=False, tu_luc="2026-09-22 10:00:00")
    (c,) = mon.danh_gia(d)
    assert c["nhom"] == "Nhật ký" and "có thể thiếu" in c["noi_dung"]


def test_khong_doc_duoc_o_dia_thi_canh_bao():
    d = _tot()
    d["dia"]["o_dia"] = None
    assert [c["nhom"] for c in mon.danh_gia(d)] == ["Ổ đĩa"]


# ── Số liệu cho biểu đồ ──
def test_theo_gio_du_24_o_ke_ca_gio_khong_co_ban_ghi(tmp_path):
    # Thiếu ô là trục thời gian co lại: hai cột cách nhau 6 tiếng trông như liền nhau
    den = datetime(2026, 9, 24, 10, 30)
    p = tmp_path / "app.log"
    p.write_text("\n".join([
        f"{den - timedelta(hours=1):%Y-%m-%d %H:%M:%S} ERROR    x — a",
        f"{den - timedelta(hours=1):%Y-%m-%d %H:%M:%S} WARNING  x — b",
        f"{den - timedelta(hours=6):%Y-%m-%d %H:%M:%S} ERROR    x — c",
    ]) + "\n", encoding="utf-8")
    tg = mon._quet_log([p], den - timedelta(hours=24), den)["theo_gio"]
    assert len(tg) == 24
    assert [o["gio"] for o in tg][-3:] == ["08", "09", "10"]     # cũ → mới, kết ở giờ hiện tại
    assert tg[-2] == {"gio": "09", "loi": 1, "canh_bao": 1}
    assert tg[-7]["loi"] == 1 and tg[-1] == {"gio": "10", "loi": 0, "canh_bao": 0}


def test_dang_nhap_theo_gio_tach_dung_va_sai(ctx):
    client, conn = ctx
    cap_quyen(conn, 2, "menu.monitor")
    gio_nay = _vn_now().replace(minute=5, second=0, microsecond=0)
    conn.executemany("INSERT INTO login_logs (username, success, created_at) VALUES (?,?,?)",
                     [("a", 1, gio_nay), ("b", 0, gio_nay), ("c", 0, gio_nay),
                      ("d", 1, gio_nay - timedelta(days=2))])       # ngoài 24h
    conn.commit()
    tg = client.get("/api/admin/monitor/overview").json()["nguoi_dung"]["theo_gio"]
    assert len(tg) == 24 and tg[-1] == {"gio": gio_nay.strftime("%H"), "ok": 1, "sai": 2}
    assert sum(o["ok"] + o["sai"] for o in tg) == 3


def test_thanh_phan_dia_cong_du_phan_da_dung(ctx):
    client, conn = ctx
    cap_quyen(conn, 2, "menu.monitor")
    dia = client.get("/api/admin/monitor/overview").json()["dia"]
    biet = sum(dia[k] or 0 for k in ("csdl", "wal", "sao_luu", "nhat_ky", "tam"))
    assert dia["khac"] >= 0
    assert biet + dia["khac"] == dia["da_dung"]                     # cột xếp chồng khớp phần đã dùng
    assert dia["da_dung"] + dia["o_dia"]["con_trong"] == dia["o_dia"]["tong"]


def test_chuoi_tre_lay_dinh_tung_o_va_tra_none_khi_khong_do():
    import time as _t
    from backend.core import slow_request as sr

    assert sr.chuoi_tre() is None                                   # chưa bật bộ đo
    sr._task_do_tre = object()                                      # giả "đang đo"
    try:
        now = _t.monotonic()
        sr._mau_tre.clear()
        sr._mau_tre.extend([(now - 1, 0.5), (now - 2, 0.02), (now - 7, 0.3)])
        s = sr.chuoi_tre(cua_so_giay=10, buoc_giay=5)
        assert [o["giay_truoc"] for o in s] == [5, 0]               # cũ → mới
        assert s[-1]["ms"] == round((0.5 - sr._NEN_GIAY) * 1000)    # ĐỈNH, không phải trung bình
        assert s[0]["ms"] == round((0.3 - sr._NEN_GIAY) * 1000)
    finally:
        sr._task_do_tre = None
        sr._mau_tre.clear()
