"""SWIFT recon — đối chiếu điện SAA ↔ Quản lý điện, phần nặng chạy ở tiến trình riêng.

Trước 18/09/2026 module này không có test nào. File dựng dữ liệu mẫu đúng định dạng thật
(SAA: SpreadsheetML XML; Quản lý điện: bảng HTML) và đi qua MỌI endpoint — cả khi chạy
trong luồng (mặc định conftest) lẫn tiến trình con thật (`tien_trinh_that`).

`chup_ket_qua()` gom kết quả mọi endpoint về dạng so sánh được (JSON + giá trị từng ô
Excel) — dùng để đối chiếu bản trước/sau khi tách tiến trình, không chỉ để assert.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_swift_recon_tach.py -v
"""
import contextlib
import inspect
import io
import logging
import sqlite3
from xml.sax.saxutils import escape

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.db import migrations
from backend.database import get_db
from backend.main import app

_SS = "urn:schemas-microsoft-com:office:spreadsheet"
_COT_SAA = ["Correspondent", "Identifier", "Reference", "MUR", "I/O", "Reception Info",
            "Mesg Creation", "Netw. Status"]


# ── Dựng file mẫu ──

def _saa_xml(dong: list[dict]) -> bytes:
    def _hang(gia_tri):
        o = "".join(f'<Cell><Data ss:Type="String">{escape(str(v))}</Data></Cell>' for v in gia_tri)
        return f"<Row>{o}</Row>"
    than = [_hang(["Report Header"]), _hang(_COT_SAA)]
    than += [_hang([d.get(c, "") for c in _COT_SAA]) for d in dong]
    than.append(_hang(["Report Footer"]))
    return (
        f'<?xml version="1.0"?><Workbook xmlns="{_SS}" xmlns:ss="{_SS}">'
        f'<Worksheet ss:Name="Report"><Table>{"".join(than)}</Table></Worksheet></Workbook>'
    ).encode("utf-8")


def _ql_html(cot: list[str], dong: list[list[str]]) -> bytes:
    dau = "".join(f"<th>{c}</th>" for c in cot)
    than = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in d) + "</tr>" for d in dong)
    return f"<html><body><table><tr>{dau}</tr>{than}</table></body></html>".encode("utf-8")


def _saa_den() -> bytes:
    # Khoá = 6 ký tự cuối Reception Info. Dòng I/O = "I" bị lọc (không phải điện đến).
    d = [("fin.103", "RI000001"), ("fin.103", "RI000002"), ("fin.950", "RI000003"),
         ("pacs.008.001.08", "RI000004")]
    dong = [{"Correspondent": "BKVN", "Identifier": t, "Reference": f"REF{i}", "MUR": "",
             "I/O": "O", "Reception Info": ri, "Mesg Creation": f"2026/09/18 08:0{i}:00"}
            for i, (t, ri) in enumerate(d)]
    dong.append({"Identifier": "fin.103", "I/O": "I", "Reception Info": "RI000099",
                 "Mesg Creation": "2026/09/18 09:00:00"})
    return _saa_xml(dong)


def _ql_den() -> bytes:
    cot = ["Msg Key", "Msg Type", "Brcd", "SaSeq", "Create Date"]
    return _ql_html(cot, [
        ["K1", "103", "1000", "SQ000001", "2026-09-18 08:00:00.000+0700"],
        ["K2", "103", "1000", "SQ000002", "2026-09-18 08:01:00.000+0700"],
        ["K3", "950", "1000", "SQ000003", "2026-09-18 08:02:00.000+0700"],
        ["K9", "202", "1000", "SQ000009", "2026-09-18 08:09:00.000+0700"],
    ])


def _ql_di() -> bytes:
    # Khoá = Brcd(4) + 12 ký tự cuối Msg Key. Dòng thứ 3 khớp khoá nhưng NAK.
    cot = ["Msg Key", "Msg Type", "Brcd", "Create Date", "ACK/NAK"]
    return _ql_html(cot, [
        ["ABCDEF000001", "103", "1000", "2026-09-18 10:00:00", "ACK"],
        ["ABCDEF000002", "202", "1000", "2026-09-18 10:01:00", "ACK"],
        ["ABCDEF000003", "103", "1000", "2026-09-18 10:02:00", "NAK"],
        ["ABCDEF000008", "103", "2000", "2026-09-18 10:08:00", "ACK"],
    ])


def _saa_di() -> bytes:
    # Chỉ cần MỘT bên báo Ack là khớp (reconcile._ack_ok) → cặp 000003 phải cả hai bên
    # cùng không Ack mới thành MATCHED_NOT_ACK
    d = [("fin.103", "1000ABCDEF000001", "Network Ack"), ("fin.202", "1000ABCDEF000002", "Network Ack"),
         ("fin.103", "1000ABCDEF000003", "Network Nak"), ("fin.199", "3000ABCDEF000007", "Network Ack")]
    return _saa_xml([{"Identifier": t, "MUR": m, "I/O": "I", "Netw. Status": s,
                      "Mesg Creation": f"2026/09/18 10:0{i}:00"} for i, (t, m, s) in enumerate(d)])


_XLS = "application/vnd.ms-excel"


def _tep(ten_truong: str, du_lieu: bytes, ten_tep: str):
    return (ten_truong, (ten_tep, du_lieu, _XLS))


# ── CSDL có bảng lịch sử + client ──

@contextlib.contextmanager
def _client_moi():
    """TestClient admin + CSDL trong RAM mới tinh có bảng lịch sử — mỗi lượt id lịch sử
    bắt đầu lại từ 1 nên kết quả hai lượt so thẳng được."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, full_name TEXT)")
    conn.execute("INSERT INTO user_tttt VALUES (1, 'Test Admin')")
    nguon = inspect.getsource(migrations)
    i = nguon.index("CREATE TABLE IF NOT EXISTS swift_recon_history")
    conn.execute(nguon[i:nguon.index('"""', i)])

    def _db():
        yield conn

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 1, "role": "admin", "username": "t", "full_name": "Test Admin"}
    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        conn.close()


@pytest.fixture
def swift_client():
    with _client_moi() as client:
        yield client


# ── Gom kết quả mọi endpoint về dạng so sánh được ──

def _o_excel(noi_dung: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(noi_dung))
    return {ws.title: [[c for c in hang] for hang in ws.iter_rows(values_only=True)]
            for ws in wb.worksheets}


def chup_ket_qua(client) -> dict:
    ra = {}

    def _ok(r):
        assert r.status_code == 200, (r.status_code, r.text[:300])
        return r

    ra["preview_saa_den"] = _ok(client.post("/api/swift-recon/parse-preview",
        files=[_tep("file", _saa_den(), "saa.xls")], data={"source": "SAA_DEN"})).json()
    ra["preview_sai_dinh_dang"] = client.post("/api/swift-recon/parse-preview",
        files=[_tep("file", _ql_den(), "ql.xls")], data={"source": "SAA_DEN"}).status_code

    ra["den"] = _ok(client.post("/api/swift-recon/reconcile-den", files=[
        _tep("saa_files", _saa_den(), "saa_den.xls"), _tep("ql_files", _ql_den(), "ql_den.xls")])).json()
    ra["di"] = _ok(client.post("/api/swift-recon/reconcile-di", files=[
        _tep("ql_files", _ql_di(), "ql_di.xls"), _tep("saa_files", _saa_di(), "saa_di.xls")])).json()

    ca_hai = [_tep("saa_den", _saa_den(), "a.xls"), _tep("ql_den", _ql_den(), "b.xls"),
              _tep("ql_di", _ql_di(), "c.xls"), _tep("saa_di", _saa_di(), "d.xls")]
    chi_den = ca_hai[:2]
    for ten, url, tep in (("xuat_tong_hop", "export-summary", ca_hai),
                          ("xuat_chi_tiet", "export-diff", ca_hai),
                          ("xuat_mau_tong_hop", "export-summary-template", chi_den),
                          ("xuat_mau_chi_tiet", "export-diff-template", chi_den)):
        ra[ten] = _o_excel(_ok(client.post(f"/api/swift-recon/{url}", files=tep)).content)
    ra["xuat_thieu_du_lieu"] = client.post("/api/swift-recon/export-summary",
        files=[_tep("saa_den", _saa_den(), "a.xls")]).status_code

    ra["xuat_loc"] = _o_excel(_ok(client.post("/api/swift-recon/export-filtered", json={
        "records": ra["den"]["records"][:2], "columns": ["_key", "_status"],
        "filename": "loc.xlsx"})).content)

    ra["lich_su"] = [{k: v for k, v in h.items() if k != "recon_date"}
                     for h in _ok(client.get("/api/swift-recon/history")).json()]
    for hid in (1, 2):
        chi_tiet = _ok(client.get(f"/api/swift-recon/history/{hid}")).json()
        ra[f"lich_su_{hid}"] = {k: v for k, v in chi_tiet.items() if k not in ("recon_date", "created_at")}
        for side in ("a", "b"):
            ra[f"lich_su_{hid}_tho_{side}"] = _o_excel(_ok(client.get(
                f"/api/swift-recon/history/{hid}/export-raw", params={"side": side})).content)
        ra[f"lich_su_{hid}_tong_hop"] = _o_excel(_ok(client.get(
            f"/api/swift-recon/history/{hid}/export-summary")).content)
        ra[f"lich_su_{hid}_chi_tiet"] = _o_excel(_ok(client.get(
            f"/api/swift-recon/history/{hid}/export-diff")).content)
    ra["lich_su_khong_co"] = client.get("/api/swift-recon/history/99/export-diff").status_code
    return ra


# ── Test ──

def _kiem(kq: dict) -> None:
    assert kq["preview_saa_den"] == {"filename": "saa.xls", "rows": 4}   # dòng I/O=I bị lọc
    assert kq["preview_sai_dinh_dang"] == 422
    den, di = kq["den"], kq["di"]
    assert (den["total_a"], den["total_b"], den["total_matched"], den["total_diff"]) == (4, 4, 3, 2)
    assert den["history_saved"] and di["history_saved"], (den["history_error"], di["history_error"])
    # Điện đi: 3 cặp khớp khoá nhưng 1 cặp cả hai bên không Ack → chỉ 2 MATCHED
    assert (di["total_a"], di["total_b"], di["total_matched"]) == (4, 4, 2)
    assert [r["_status"] for r in di["records"]].count("MATCHED_NOT_ACK") == 1
    assert len(kq["xuat_chi_tiet"]["DI_KHOPKHOA_CHUA_ACK"]) == 2   # tiêu đề + 1 cặp
    assert kq["xuat_thieu_du_lieu"] == 400
    assert kq["lich_su_khong_co"] == 404
    assert [h["recon_type"] for h in kq["lich_su"]] == ["di", "den"]
    assert "TỔNG" in str(kq["xuat_tong_hop"])
    assert kq["xuat_loc"]["BanGhiDangLoc"][0] == ["_key", "_status"]


def test_xuat_tu_ban_ghi_nho_khong_mo_tien_trinh(swift_client, monkeypatch, caplog):
    # Mở tiến trình ~0,85 s mà ghi 2 dòng Excel 0,06 s — dưới ngưỡng phải chạy tại chỗ
    monkeypatch.delenv("DOI_CHIEU_TIEN_TRINH", raising=False)
    ban_ghi = [{"_key": "000001", "_status": "MATCHED"}]
    with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
        r = swift_client.post("/api/swift-recon/export-filtered",
                              json={"records": ban_ghi, "columns": ["_key"], "filename": "x.xlsx"})
    assert r.status_code == 200
    assert not any("tiến trình riêng" in x.getMessage() for x in caplog.records)


def test_moi_endpoint_chay_trong_luong(swift_client):
    _kiem(chup_ket_qua(swift_client))


def test_moi_endpoint_chay_tien_trinh_rieng_cung_ket_qua(monkeypatch, caplog):
    # Cùng dữ liệu, cùng CSDL mới: chạy trong luồng rồi chạy tiến trình con thật — mọi JSON
    # và từng ô Excel phải trùng. Đo 18/09/2026: cũng trùng với bản TRƯỚC khi tách (mốc chụp
    # từ mã cũ, 22 mục, 12 file Excel).
    from backend.api import swift_recon as api
    with _client_moi() as client:
        kq_luong = chup_ket_qua(client)
    monkeypatch.delenv("DOI_CHIEU_TIEN_TRINH", raising=False)
    # Ngưỡng 0: cả các lệnh xuất từ bản ghi nhỏ cũng tách — thử đủ mọi hàm của tach.py qua
    # ranh giới tiến trình (ngưỡng là logic phía cha nên vá được)
    monkeypatch.setattr(api, "_NGUONG_TACH_DONG", 0)
    with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
        with _client_moi() as client:
            kq_tach = chup_ket_qua(client)
    # 2 đối chiếu + 4 xuất từ file + 1 bản ghi lọc + 2 lịch sử × 4 lệnh xuất; đọc thử KHÔNG tách
    assert sum("tiến trình riêng" in r.getMessage() for r in caplog.records) == 15
    _kiem(kq_tach)
    assert kq_tach == kq_luong
