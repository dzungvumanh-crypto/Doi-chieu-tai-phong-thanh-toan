"""Mọi cửa đối chiếu nặng chạy pipeline ở TIẾN TRÌNH RIÊNG (card 150 Implementation-notes).

Hai lớp canh:
  1. Tĩnh — service nào khai `dang_ky_nguon()` (tức là cửa đối chiếu nặng) mà không gọi
     `chay_tach()` thì đỏ. Module đối chiếu mới chép khuôn cũ là chạy lại trong luồng web,
     tranh GIL với mọi request mà không ai biết.
  2. Chạy thật từng module qua tiến trình con với đầu vào hỏng/rỗng — không cần dữ liệu
     ngân hàng mà vẫn đi qua đủ đường ống: log, tiến độ, lỗi mang về đúng kiểu.

Test ở đây KHÔNG được vá biến toàn cục của module (TEMP_DIR...): tiến trình con không
thấy bản vá, sẽ ghi vào `data/temp_*` thật. Chỉ truyền đường dẫn tường minh.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_doi_chieu_chay_tien_trinh_rieng.py -v
"""
import ast
import logging
from pathlib import Path

import pytest

_GOC = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _bat_tien_trinh(tien_trinh_that):
    pass  # conftest mặc định chạy trong luồng


def _thay_tach(caplog) -> bool:
    return any("tiến trình riêng" in r.getMessage() for r in caplog.records)


# ── 1. Lưới canh tĩnh ──

def _cac_loi_goi(cay: ast.AST) -> set[str]:
    # Lời gọi THẬT — so chuỗi thì một docstring nhắc "chay_tach()" cũng đủ cho test xanh
    return {
        n.func.id if isinstance(n.func, ast.Name) else n.func.attr
        for n in ast.walk(cay)
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
    }


def test_moi_cua_doi_chieu_deu_chay_tach():
    thieu = []
    for f in sorted((_GOC / "backend" / "services").rglob("*.py")):
        goi = _cac_loi_goi(ast.parse(f.read_text(encoding="utf-8")))
        if "dang_ky_nguon" in goi and "chay_tach" not in goi:
            thieu.append(str(f.relative_to(_GOC)))
    assert not thieu, (
        f"Cửa đối chiếu nặng chưa chạy tách tiến trình: {thieu}. Gọi pipeline qua "
        f"backend/core/tien_trinh_doi_chieu.py::chay_tach() — xem DESIGN.md."
    )


def test_api_khong_dung_asyncio_to_thread():
    # to_thread chạy trên bể luồng mặc định của event loop, NGOÀI giới hạn MAX_HEAVY
    # (concurrency.py) — DTBB từng vậy tới 18/09/2026. Việc nặng: `await run_heavy(...)`; rất nặng: thêm `chay_tach`.
    vi_pham = []
    for f in sorted((_GOC / "backend" / "api").rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "to_thread"):
                vi_pham.append(f"{f.relative_to(_GOC)}:{n.lineno}")
    assert not vi_pham, f"Dùng run_heavy() thay cho asyncio.to_thread: {vi_pham}"


def test_api_swift_khong_tu_lam_viec_nang():
    # Đọc file / đối chiếu / sinh Excel của SWIFT phải ở backend/services/swift_recon/tach.py
    # (chạy qua chay_tach). Viết thẳng ở API là quay lại giữ GIL trong tiến trình web.
    f = _GOC / "backend" / "api" / "swift_recon.py"
    cay = ast.parse(f.read_text(encoding="utf-8"))
    cam = {"reconcile", "exporters", "template_exporters", "pandas", "openpyxl"}
    nap = {a.name.split(".")[-1] for n in ast.walk(cay) if isinstance(n, (ast.Import, ast.ImportFrom))
           for a in n.names} | {n.module.split(".")[-1] for n in ast.walk(cay)
                                if isinstance(n, ast.ImportFrom) and n.module}
    assert not (nap & cam), f"API SWIFT import thư viện/module nặng: {nap & cam}"
    dung_parsers = {n.attr for n in ast.walk(cay)
                    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "parsers"}
    assert dung_parsers <= {"UnknownFileFormat"}, f"API SWIFT tự parse file: {dung_parsers}"

    # Gọi thẳng tach.<hàm>(...) là việc nặng quay về tiến trình web — mọi tham chiếu phải là
    # ĐỐI SỐ của chay_tach / _xuat_tu_ban_ghi / _xuat_tu_tep (trực tiếp
    # hoặc qua run_heavy). Ngoại lệ cố ý: xem_truoc (việc nhỏ).
    cha = {id(con): n for n in ast.walk(cay) for con in ast.iter_child_nodes(n)}
    tach_ra = {"chay_tach", "_xuat_tu_ban_ghi", "_xuat_tu_tep"}

    def _ten(x):
        return x.id if isinstance(x, ast.Name) else None

    goi_thang = []
    for n in ast.walk(cay):
        if not (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "tach"):
            continue
        if n.attr in ("Tep", "xem_truoc"):
            continue
        p = cha.get(id(n))
        # run_heavy(tach.x, ...) chạy thẳng trong luồng → không tính; phải là
        # run_heavy(<hàm tách>, tach.x, ...) hoặc <hàm tách>(tach.x, ...)
        la_doi_so = isinstance(p, ast.Call) and n in p.args and (
            _ten(p.func) in tach_ra
            or (_ten(p.func) == "run_heavy" and p.args and _ten(p.args[0]) in tach_ra))
        if not la_doi_so:
            goi_thang.append(f"tach.{n.attr} dòng {n.lineno}")
    assert not goi_thang, f"API SWIFT gọi thẳng việc nặng, không qua chay_tach: {goi_thang}"


# ── 2. Chạy thật từng module ──

def test_ach(tmp_path, caplog):
    from backend.services import ach_service as svc
    job_id, input_dir = svc.tao_job()
    job = svc.get_job(job_id)
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc._run(job_id, str(input_dir), job["output_dir"], "15/07/2026")
        assert job["status"] == "error"
        assert "file PDF" in job["error"]                   # FileNotFoundError từ con
        assert "Ngày đối chiếu: 15/07/2026" in job["logs"]  # log của pipeline về tới job
        assert _thay_tach(caplog)
    finally:
        svc.bo_job(job_id)


@pytest.mark.parametrize("ten_mod", [
    "doi_chieu_song_phuong_kenh_core_service",
    "doi_chieu_song_phuong_kenh_core_di_service",
])
def test_song_phuong_den_di(ten_mod, caplog):
    import importlib
    svc = importlib.import_module(f"backend.services.{ten_mod}")
    job_id, input_dir = svc.tao_job("20260715", "201")
    job = svc.get_job(job_id)
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc._run(job_id, str(input_dir), job["ngay"], job["ma_nh"], job["output_dir"])
        assert job["status"] == "error", job["error"]
        assert job["stage"] == 2                    # stage_callback từ con về tới job
        trang_thai = job["ket_qua"]["trang_thai"]   # ket_qua điền trong con, ghi lại ở cha
        assert all(v and v["trang_thai"] == "chua_doi_chieu" for v in trang_thai.values()), trang_thai
        assert _thay_tach(caplog)
    finally:
        svc.bo_job(job_id)


def test_cham459901(tmp_path, caplog):
    from backend.services import cham459901_service as svc
    hong = tmp_path / "GL02_hong.zip"
    hong.write_bytes(b"khong phai zip")
    token = svc.init_progress()
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc.run_process([("GL02_hong.zip", hong)], token)
        p = svc.get_progress(token)
        assert p["done"] and p["error"] and not p["cancelled"]
        # InputError mang về đúng kiểu → thông báo thẳng cho người dùng, không phải
        # "Lỗi xử lý — xem log server" của nhánh lỗi hệ thống
        assert p["msg"] == p["error"]
        assert p["pct"] >= 5                        # tiến độ từ con về tới _progress của cha
        assert _thay_tach(caplog)
    finally:
        svc.bo_luot(token)


def test_cham459901_dung_toi_duoc_tien_trinh_con(tmp_path):
    # Nút Dừng: Event của cha → Event liên tiến trình → _set_prog trong con ném _Cancelled
    # → về cha đúng kiểu → "Đã dừng". Sai một khâu là lượt chạy tới hết mà không dừng.
    from backend.services import cham459901_service as svc
    hong = tmp_path / "GL02.zip"
    hong.write_bytes(b"khong phai zip")
    token = svc.init_progress()
    try:
        assert svc.cancel_progress(token)
        svc.run_process([("GL02.zip", hong)], token)
        p = svc.get_progress(token)
        assert p["done"] and p["cancelled"] and not p["error"], p
    finally:
        svc.bo_luot(token)


def test_song_phuong_phan_loai(tmp_path, caplog):
    from backend.services import doi_chieu_song_phuong_service as svc
    hong = tmp_path / "du_lieu.zip"
    hong.write_bytes(b"PK" + b"than hong")   # qua cửa magic bytes → tới bước báo tiến độ
    token = svc.init_progress()
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc.run_process(hong, token)
        p = svc.get_progress(token)
        assert p["done"] and p["error"]
        assert p["pct"] >= 5                        # tiến độ từ con về tới _progress của cha
        assert _thay_tach(caplog)
    finally:
        svc.bo_luot(token)


def test_osb(tmp_path, caplog):
    from backend.services import doi_chieu_osb_job as svc
    gl02 = tmp_path / "GL02.zip"
    gl02.write_bytes(b"khong phai zip")
    osb = tmp_path / "OSB.xlsx"
    osb.write_bytes(b"khong phai xlsx")
    token = svc.init_progress()
    try:
        with caplog.at_level(logging.INFO, logger="backend.core.tien_trinh_doi_chieu"):
            svc.run_process(gl02, [osb], "459902", "20260715", token)
        p = svc.get_progress(token)
        assert p["done"] and p["error"]
        assert p["pct"] >= 10                       # tiến độ từ con về tới _progress của cha
        assert _thay_tach(caplog)
    finally:
        svc.bo_luot(token)
