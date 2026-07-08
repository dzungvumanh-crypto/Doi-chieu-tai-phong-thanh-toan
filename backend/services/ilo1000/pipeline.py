"""Pipeline ILO1000: orchestrator chính, chạy mỗi ngày."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .detect import group_files_by_date
from .export import export_excel
from .load_citad import load_citad
from .load_core import load_core
from .load_eicp import build_eicp_maps, load_eicp
from .load_hub import load_hub
from .process import process_citad, process_core, process_hub


def _run_one_day(
    date_str: str,
    files: dict,
    output_dir: str,
    log: Callable,
    cancel_event: threading.Event,
) -> Path | None:
    """Xử lý 1 ngày. Trả None nếu bị cancel hoặc thiếu file thiết yếu."""

    log(f'[{date_str}] Kiểm tra file đầu vào...')
    # core và citad là bắt buộc; hub là tùy chọn (nếu thiếu TT sẽ không khớp hub)
    missing = [k for k in ('citad', 'core') if not files.get(k)]
    if missing:
        log(f'[{date_str}] SKIP — thiếu file bắt buộc: {", ".join(missing)}')
        return None
    if not files.get('hub'):
        log(f'[{date_str}] WARN — không có file Hub, TT sẽ chỉ khớp theo Citad.')

    # Nếu có cả ZIP lẫn CSV của GL02, ưu tiên CSV (ZIP thường bị mã hóa)
    core_files = files.get('core', [])
    csv_cores = [p for p in core_files if p.suffix.lower() == '.csv']
    if csv_cores:
        core_files = csv_cores
        files = {**files, 'core': core_files}

    ngay_int = int(date_str)

    # ── Load song song (I/O bound) ──
    import pandas as pd

    log(f'[{date_str}] Đang đọc file song song...')
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_hub   = ex.submit(load_hub, files.get('hub', [])) if files.get('hub') else None
        f_citad = ex.submit(load_citad, files['citad'])
        f_eicp  = ex.submit(load_eicp,  files.get('eicp', []))
        f_core  = ex.submit(load_core,  files['core'], log)

        eicp_df = f_eicp.result()
        if cancel_event.is_set():
            return None

        hub_raw = f_hub.result() if f_hub else pd.DataFrame()
        if cancel_event.is_set():
            return None

        citad_raw = f_citad.result()
        if cancel_event.is_set():
            return None

        core_raw = f_core.result()
        if cancel_event.is_set():
            return None

    log(f'[{date_str}] HUB {len(hub_raw):,} · CITAD {len(citad_raw):,} · EICP {len(eicp_df):,} · CORE {len(core_raw):,} dòng')

    # ── Build EICP maps ──
    eicp_maps = build_eicp_maps(eicp_df)

    # ── Process tuần tự (CPU, phụ thuộc nhau) ──
    log(f'[{date_str}] Xử lý Hub...')
    hub_out, hub_lookups = process_hub(hub_raw, eicp_maps, ngay_int)
    if cancel_event.is_set():
        return None

    log(f'[{date_str}] Xử lý Citad...')
    citad_out, citad_mapdc = process_citad(citad_raw, hub_lookups, ngay_int)
    if cancel_event.is_set():
        return None

    log(f'[{date_str}] Xử lý Core (pivot + TT)...')
    core_out = process_core(core_raw, citad_mapdc, hub_lookups, ngay_int)
    if cancel_event.is_set():
        return None

    # ── Tóm tắt TT ──
    tt_summary = core_out['TT'].value_counts().to_dict() if 'TT' in core_out.columns else {}
    total = len(core_out)
    matched = sum(v for k, v in tt_summary.items() if k not in ('', 'nan'))
    log(f'[{date_str}] TT: Hủy={tt_summary.get("Hủy", 0):,} · Khớp citad/hub={matched:,} · Chưa khớp={tt_summary.get("", 0):,} / {total:,}')

    # ── Export ──
    log(f'[{date_str}] Xuất file Excel...')
    out_path = export_excel(hub_out, citad_out, eicp_df, core_out, ngay_int, output_dir)
    log(f'[{date_str}] Hoàn thành → {out_path.name}')
    return out_path


def main_from_dir(
    input_dir: str,
    output_dir: str,
    ngay: str | None = None,
    log_callback: Callable | None = None,
    cancel_event: threading.Event | None = None,
) -> Path | None:
    """
    Entry point: nhận thư mục chứa file đầu vào, nhóm theo ngày, xử lý từng ngày.
    Trả về Path file cuối cùng (hoặc None nếu không có output hoặc bị cancel).
    """
    log = log_callback or (lambda msg: None)
    cancel = cancel_event or threading.Event()

    all_paths = list(Path(input_dir).iterdir())
    log(f'Tổng file phát hiện: {len(all_paths)}')

    day_groups = group_files_by_date(all_paths, log)
    if not day_groups:
        log('[WARN] Không nhóm được file theo ngày.')
        return None

    log(f'Số ngày cần xử lý: {len(day_groups)}')

    output_paths: list[Path] = []
    for date_str in sorted(day_groups.keys()):
        if cancel.is_set():
            return None
        out = _run_one_day(date_str, day_groups[date_str], output_dir, log, cancel)
        if out:
            output_paths.append(out)

    return output_paths[-1] if output_paths else None
