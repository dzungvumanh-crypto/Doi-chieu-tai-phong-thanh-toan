"""Job management cho "Đối chiếu đến" — Kênh↔Hub + Hub↔Core chạy TỰ ĐỘNG nối tiếp trong 1 job.

Quyết định 2026-08-28: "Đối chiếu đến" không phải 2 tính năng độc lập, mà là 1 chu trình khép
kín — người dùng đưa 1 thư mục gốc + ngày + ngân hàng, hệ thống tự chạy Kênh↔Hub rồi Hub↔Core,
chỉ báo 1 kết quả cuối (đúng model ACH: nhiều pha bên trong, 1 job/1 báo cáo cuối). Thay hẳn 2
service riêng `doi_chieu_song_phuong_kenh_service.py`/`_core_service.py` (đã xoá).

Đặt tên `kenh_core`, KHÔNG dùng `_den` — tránh trùng tên module `doi_chieu_song_phuong_den*` đã
xoá 2026-08-25 (thiết kế sai, dựa trên khoá Ngày+Số tiền), dễ gây nhầm lẫn khi tra lịch sử.

Lỗi 1 bước KHÔNG chặn bước còn lại (đúng triết lý "báo đủ, không crash cả job" toàn dự án) — chỉ
khi CẢ 2 bước đều lỗi mới đánh dấu job lỗi.

Mỗi lần chạy chỉ ĐÚNG 1 ngân hàng (giữ nguyên quyết định giới hạn RAM của Hub↔Core, card 91) —
Kênh↔Hub cũng lọc theo `ma_nh` (xem `doi_chieu_song_phuong_kenh/pipeline.py::main_from_dir`).
"""

import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from backend.services import doi_chieu_song_phuong_common as common
from backend.services.doi_chieu_song_phuong_common import do_thoi_gian
from backend.services.doi_chieu_song_phuong_core import export as core_export
from backend.services.doi_chieu_song_phuong_core.export import export_excel as export_core_excel
from backend.services.doi_chieu_song_phuong_core.pipeline import doi_chieu_hub_core
from backend.services.doi_chieu_song_phuong_kenh import export as kenh_export
from backend.services.doi_chieu_song_phuong_kenh.export import export_bao_cao
from backend.services.doi_chieu_song_phuong_kenh.load_hub import hub_filename_glob
from backend.services.doi_chieu_song_phuong_kenh.pipeline import main_from_dir as kenh_main_from_dir

TEMP_DIR = Path("data/temp_doi_chieu_song_phuong_kenh_core")
CLEANUP_TTL = 4 * 3600
CAC_NGAN_HANG = ("201", "202", "203", "311")

STAGE_LABELS = ["Kênh↔Hub", "Hub↔Core", "Hoàn tất"]

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _new_job(ngay: str, ma_nh: str) -> tuple[str, dict]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "status": "pending",   # pending | running | done | error | cancelled
        "logs": [],
        "files": [],
        "error": None,
        "ngay": ngay,
        "ma_nh": ma_nh,
        "ket_qua": {
            "kenh_hub": None, "hub_core": None,  # None nếu bước đó lỗi/bỏ qua
            # Trạng thái cấp JOB (Phần 3, 2026-08-30) — tách "chưa đối chiếu được" (thiếu cả 1
            # loại file) khỏi "chênh lệch thật" (số liệu trong "kenh_hub"/"hub_core" ở trên).
            # KHÔNG đổi nhãn per-row KETQUADOICHIEU/trạng thái đơn vị — chỉ thêm cờ cấp job.
            "trang_thai": {"kenh_hub": None, "hub_core": None},
        },
        "stage": 0,
        "cancel_event": threading.Event(),
        "_ts": time.time(),
        "output_dir": str(TEMP_DIR / job_id),
    }
    with _lock:
        _jobs[job_id] = job
    return job_id, job


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job and job["status"] in ("pending", "running"):
        job["cancel_event"].set()
        return True
    return False


def start(goc_dir: str, ngay: str, ma_nh: str) -> str:
    """Chạy "Đối chiếu đến" (Kênh↔Hub + Hub↔Core) cho 1 ngân hàng `ma_nh`, ngày `ngay`
    (YYYYMMDD), từ 1 thư mục gốc `goc_dir` (chứa thư mục con theo ngày). Trả job_id."""
    if ma_nh not in CAC_NGAN_HANG:
        raise ValueError(f"Mã ngân hàng không hợp lệ: {ma_nh}")
    job_id, job = _new_job(ngay, ma_nh)
    Path(job["output_dir"]).mkdir(parents=True, exist_ok=True)

    threading.Thread(
        target=_run, args=(job_id, goc_dir, ngay, ma_nh, job["output_dir"]), daemon=True,
    ).start()
    return job_id


def start_upload(files: list[tuple[str, bytes]], ngay: str, ma_nh: str) -> str:
    """Lưu file tải lên qua trình duyệt (giữ nguyên tên gốc) vào 1 thư mục tạm phẳng, rồi chạy
    y hệt chế độ thư mục server — tái dùng toàn bộ logic dò file hiện có (`common.tim_file()`
    luôn thử đúng thư mục GỐC nếu không thấy thư mục con theo ngày, nên 1 thư mục phẳng chứa đủ
    file cần thiết vẫn hoạt động đúng, không cần sửa gì ở tầng pipeline).

    Quyết định 2026-08-28 (đợt 3): thêm chế độ này vì chọn thư mục server qua dialog duyệt
    thư mục "rất khó khăn" — cho phép tải thẳng nhiều file (HUB zip, kênh xlsx, GL02 zip/CSV,
    OSB xlsx) qua trình duyệt, giống chế độ đã có ở ACH và Phân loại dữ liệu."""
    if ma_nh not in CAC_NGAN_HANG:
        raise ValueError(f"Mã ngân hàng không hợp lệ: {ma_nh}")
    if not files:
        raise ValueError("Chưa chọn file nào.")
    job_id, job = _new_job(ngay, ma_nh)
    upload_dir = Path(job["output_dir"]) / "_upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        (upload_dir / os.path.basename(name)).write_bytes(data)

    threading.Thread(
        target=_run, args=(job_id, str(upload_dir), ngay, ma_nh, job["output_dir"]), daemon=True,
    ).start()
    return job_id


_NHAN_TRANG_THAI = {"da_doi_chieu": "Đã đối chiếu", "chua_doi_chieu": "CHƯA ĐỐI CHIẾU"}


def _export_bao_cao_tong_hop(
    ket_qua_kenh: dict | None, ket_qua_core: dict | None, trang_thai: dict, out_path: Path,
) -> Path | None:
    """Gộp sheet TrangThai (Phần 3, 2026-08-30) + Bảng 1 (Kênh↔Hub) + TongHop (Hub↔Core) vào 1
    workbook — "1 báo cáo cuối" theo quyết định 2026-08-28. Bỏ qua sheet nào bước đó không có kết
    quả (lỗi/thiếu file). Trả None nếu cả 2 bước đều không có kết quả.

    Sheet TrangThai đặt ĐẦU workbook — người nhận file (không xem UI/log) biết ngay bước nào
    "chưa đối chiếu được" (thiếu dữ liệu 1 bên) thay vì đọc nhầm là "không có chênh lệch".

    `engine="xlsxwriter"` — nhất quán với `core/export.py`/`kenh/export.py` (đã đo nhanh hơn
    openpyxl ~30%, xem Implementation-notes.html); sheet này nhỏ nên tác động thấp nhưng đổi cho
    đồng bộ quy ước toàn module, 2026-08-30."""
    if ket_qua_kenh is None and ket_qua_core is None:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        pd.DataFrame([
            {
                "Bước": nhan,
                "Trạng thái": _NHAN_TRANG_THAI.get((trang_thai.get(key) or {}).get("trang_thai"), "—"),
                "Lý do": (trang_thai.get(key) or {}).get("ly_do") or "",
            }
            for key, nhan in (("kenh_hub", "Kênh↔Hub"), ("hub_core", "Hub↔Core"))
        ]).to_excel(writer, sheet_name="TrangThai", index=False)
        if ket_qua_kenh is not None:
            kenh_export.build_bang1_rows([ket_qua_kenh]).to_excel(
                writer, sheet_name="Bang1_KenhHub", index=False,
            )
        if ket_qua_core is not None:
            core_export.build_tong_hop(
                ket_qua_core["core_df"], ket_qua_core["hub_df"],
            ).to_excel(writer, sheet_name="TongHop_HubCore", index=False)
    return out_path


def _run(job_id: str, goc_dir: str, ngay: str, ma_nh: str, output_dir: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    job["status"] = "running"
    t_job0 = time.perf_counter()
    goc_dir_p = Path(goc_dir)
    output_dir_p = Path(output_dir)
    files: list[str] = []
    loi: list[str] = []
    ket_qua_kenh: dict | None = None
    ket_qua_core: dict | None = None

    def log(msg: str) -> None:
        with _lock:
            job["logs"].append(msg)

    try:
        log(f"[JOB {job_id}] Bắt đầu Đối chiếu đến — NH {ma_nh}, ngày {ngay}...")

        # ── Bước 1/2 — Kênh↔Hub ──────────────────────────────────────────────
        log("=== Bước 1/2 — Kênh↔Hub ===")
        hub_matches = common.tim_file_glob(goc_dir_p, ngay, hub_filename_glob(ngay, ma_nh))
        hub_path = None
        if len(hub_matches) > 1:
            # Đổi 2026-08-30: KHÔNG tự đoán "mới nhất" nữa (khác hành vi cũ) — nhiều người dùng
            # có thể trỏ chung 1 thư mục server (mode 2) cùng lúc, tự đoán dễ đọc nhầm file người
            # khác vừa thả vào, ra kết quả sai mà không ai biết.
            log(f"[Kênh↔Hub] [LỖI] {len(hub_matches)} file HUB khớp cùng lúc trong "
                f"{hub_matches[0].parent} — KHÔNG tự chọn (tránh đọc nhầm khi nhiều người dùng "
                f"chung thư mục): {', '.join(p.name for p in hub_matches)}. Cần dọn bớt file "
                f"trùng hoặc dùng thư mục riêng cho mỗi phiên.")
        elif hub_matches:
            hub_path = hub_matches[0]

        if hub_path is None:
            ly_do = (
                "nhiều file HUB khớp cùng lúc, không tự chọn được — xem log"
                if hub_matches else "không tìm thấy file HUB"
            )
            loi.append(f"Kênh↔Hub: {ly_do} — bỏ qua bước này.")
            log(f"[Kênh↔Hub] {loi[-1]}")
            job["ket_qua"]["trang_thai"]["kenh_hub"] = {
                "trang_thai": "chua_doi_chieu", "ly_do": ly_do,
            }
        else:
            if job["cancel_event"].is_set():
                job["status"] = "cancelled"
                log("[JOB] Đã dừng theo yêu cầu.")
                return
            with do_thoi_gian(log, "Bước 1/2 Kênh↔Hub (tổng)"):
                ket_qua_kenh = kenh_main_from_dir(
                    hub_path.parent, ngay=ngay, ma_nh=ma_nh,
                    log_callback=lambda m: log(f"[Kênh↔Hub] {m}"),
                    cancel_event=job["cancel_event"],
                    hub_path_override=hub_path,
                )
            if ket_qua_kenh is None:
                if job["cancel_event"].is_set():
                    job["status"] = "cancelled"
                    log("[JOB] Đã dừng theo yêu cầu.")
                    return
                loi.append("Kênh↔Hub: không xác định được kết quả (xem log).")
                job["ket_qua"]["trang_thai"]["kenh_hub"] = {
                    "trang_thai": "chua_doi_chieu", "ly_do": "không xác định được kết quả (xem log)",
                }
            else:
                with do_thoi_gian(log, "ghi Excel+CSV Kênh↔Hub"):
                    kenh_files = export_bao_cao([ket_qua_kenh], output_dir_p)
                files.extend(p.name for p in kenh_files)

                chenh_lech: dict[str, dict] = {}
                canh_bao: list[dict] = []
                for dv in ket_qua_kenh["don_vi"]:
                    if dv["trang_thai"] != "ok":
                        continue
                    key = f"{dv['ma_nh']}-{dv['loai']}"
                    s = dv["summary"]
                    chenh_lech[key] = {"chenh_so_mon": s["chenh_so_mon"], "chenh_so_tien": s["chenh_so_tien"]}
                    if dv["canh_bao_trang_thai"]:
                        canh_bao.append({"don_vi": key, "trang_thai": dv["canh_bao_trang_thai"]})
                job["ket_qua"]["kenh_hub"] = {"chenh_lech": chenh_lech, "canh_bao": canh_bao}
                job["ket_qua"]["trang_thai"]["kenh_hub"] = {"trang_thai": "da_doi_chieu", "ly_do": None}

        job["stage"] = 1

        # ── Bước 2/2 — Hub↔Core ──────────────────────────────────────────────
        log("=== Bước 2/2 — Hub↔Core ===")
        if job["cancel_event"].is_set():
            job["status"] = "cancelled"
            log("[JOB] Đã dừng theo yêu cầu.")
            return
        hub_t_da_doc = (ket_qua_kenh or {}).get("hub_theo_nh", {}).get(ma_nh)
        try:
            with do_thoi_gian(log, "Bước 2/2 Hub↔Core (tổng)"):
                ket_qua_core = doi_chieu_hub_core(
                    goc_dir_p, ngay, ma_nh, log_callback=lambda m: log(f"[Hub↔Core] {m}"),
                    hub_t_override=hub_t_da_doc,
                )
        except ValueError as e:
            loi.append(f"Hub↔Core: {e}")
            log(f"[Hub↔Core] {e}")
            job["ket_qua"]["trang_thai"]["hub_core"] = {"trang_thai": "chua_doi_chieu", "ly_do": str(e)}
        else:
            base_name = f"hub_core_{ma_nh}_{ngay}"
            with do_thoi_gian(log, "ghi Excel+CSV Hub↔Core"):
                hub_core_files = export_core_excel(ket_qua_core, output_dir_p, base_name)
            files.extend(p.name for p in hub_core_files)

            core_df, hub_df = ket_qua_core["core_df"], ket_qua_core["hub_df"]
            job["ket_qua"]["hub_core"] = {
                "so_dong_core": len(core_df),
                "so_dong_hub": len(hub_df),
                "phan_bo_core": core_df["KETQUADOICHIEU"].value_counts().to_dict(),
                "phan_bo_hub": hub_df["KETQUADOICHIEU"].value_counts().to_dict(),
            }
            job["ket_qua"]["trang_thai"]["hub_core"] = {"trang_thai": "da_doi_chieu", "ly_do": None}

        job["stage"] = 2

        if job["ket_qua"]["kenh_hub"] is None and job["ket_qua"]["hub_core"] is None:
            job["status"] = "error"
            job["error"] = " | ".join(loi) or "Cả 2 bước đều không có kết quả."
            log(f"[JOB] {job['error']}")
            return

        with do_thoi_gian(log, "ghi báo cáo tổng hợp"):
            bao_cao_path = _export_bao_cao_tong_hop(
                ket_qua_kenh, ket_qua_core, job["ket_qua"]["trang_thai"],
                output_dir_p / f"bao_cao_tong_hop_{ma_nh}_{ngay}.xlsx",
            )
        if bao_cao_path:
            files.insert(0, bao_cao_path.name)
            log(f"[JOB] Đã gộp báo cáo tổng kết: {bao_cao_path.name}")

        job["files"] = files
        job["status"] = "done"
        log(f"[JOB] Hoàn thành — {len(files)} file kết quả."
            + (f" Lỗi/bỏ qua: {' | '.join(loi)}" if loi else ""))
        log(f"[TIMING] Tổng thời gian job: {time.perf_counter() - t_job0:.1f}s")

    except Exception as e:
        import traceback
        job["error"] = str(e)
        job["status"] = "error"
        log(f"[ERROR] {e}")
        log(traceback.format_exc())

    finally:
        job["_ts"] = time.time()
        _cleanup_old_jobs()


def get_output_file(job_id: str, filename: str) -> Path | None:
    job = get_job(job_id)
    if not job:
        return None
    safe_name = os.path.basename(filename)
    path = Path(job["output_dir"]) / safe_name
    return path if path.exists() else None


def _cleanup_old_jobs() -> None:
    now = time.time()
    with _lock:
        expired = [
            jid for jid, j in _jobs.items()
            if j["status"] in ("done", "error", "cancelled") and now - j["_ts"] > CLEANUP_TTL
        ]
        for jid in expired:
            del _jobs[jid]
    for jid in expired:
        job_dir = TEMP_DIR / jid
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
