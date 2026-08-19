"""Pipeline ILO1000: orchestrator chính, chạy mỗi ngày."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .detect import group_files_by_date
from .export import export_excel
from .load_citad import load_citad
from .load_core import load_core
from .load_eicp import build_eicp_maps, load_eicp
from .load_hub import load_hub
from .load_osb import build_osb_key, label_moi_cu, load_osb
from .process import (
    detect_huy, match_citad_leftover_with_osb, process_citad, process_core,
    process_hub, used_citad_keys,
)


def _osb_carryover_days(ngay_int: int) -> set[int]:
    """
    Ngày cần load OSB cho ngày T đang chấm: T + T-1 (ngày thường); T + thứ
    6,7,CN nếu T là thứ 2 — "OSB cũ chưa đi" carry sang, cùng cửa sổ carryover
    đã áp dụng cho Hub/Eicp ở `detect.py` (Citad không chạy phiên T7/CN).
    """
    d = date(ngay_int // 10000, (ngay_int // 100) % 100, ngay_int % 100)
    days = {ngay_int}
    back = (1, 2, 3) if d.weekday() == 0 else (1,)
    for delta in back:
        prev = d - timedelta(days=delta)
        days.add(int(prev.strftime('%Y%m%d')))
    return days


def _dedup_core_batch(core_raw_by_date: dict):
    """
    Gộp Core của TOÀN BỘ batch (nhiều ngày, xem `main_from_dir()`) rồi dedup —
    dùng để tính `huy_map` xuyên ngày. 1 file GL02 gốc có thể được export CẢ
    CSV (thường) lẫn ZIP (mã hoá) chứa CÙNG dữ liệu (xác nhận thật 2026-08-19:
    CSV và ZIP của "1000_gl02_2026081120260812" giống hệt nhau từng dòng,
    288.074 dòng gộp → 144.037 sau dedup). Vì file-date-extraction gán CSV/ZIP
    vào 2 khóa ngày KHÁC NHAU (mỗi file tự chứa nhiều ngày trộn lẫn),
    `load_core()`'s dedup nội bộ (dedup trong 1 lời gọi) không bắt được cặp
    trùng lặp XUYÊN 2 khóa này — phải dedup lại ở mức toàn batch tại đây.
    """
    import pandas as pd
    if not core_raw_by_date:
        return pd.DataFrame()
    combined = pd.concat(core_raw_by_date.values(), ignore_index=True)
    return combined.drop_duplicates().reset_index(drop=True)


def _filter_core_by_date(core_raw, date_str: str):
    """
    Lọc `core_raw` (đã nạp cho CẢ BATCH nhiều ngày, xem `main_from_dir()`) về
    đúng TRDATE của ngày đang chấm. 1 file GL02 gốc có thể tự chứa NHIỀU ngày
    trộn lẫn (xác nhận thật 2026-08-19: "1000_gl02_2026081120260812.csv" chứa
    cả TRDATE 11 và 12/08) — không lọc lại thì sheet 'core' xuất ra của MỌI
    ngày trong batch giống hệt nhau (đều chứa toàn bộ batch, không riêng
    ngày đang chấm).
    """
    if 'TRDATE' not in core_raw.columns:
        return core_raw
    return core_raw[
        core_raw['TRDATE'].fillna('').astype(str).str.strip() == date_str
    ].copy()


def _run_one_day(
    date_str: str,
    files: dict,
    core_raw,
    huy_map: dict,
    output_dir: str,
    log: Callable,
    cancel_event: threading.Event,
) -> Path | None:
    """Xử lý 1 ngày. Trả None nếu bị cancel hoặc thiếu file thiết yếu.

    `core_raw`/`huy_map` được nạp/tính sẵn ở main_from_dir() trên TOÀN BỘ batch
    (không phải chỉ ngày này) — cần vậy để phát hiện đúng Hủy khác ngày.
    """

    log(f'[{date_str}] Kiểm tra file đầu vào...')
    # core và citad là bắt buộc; hub là tùy chọn (nếu thiếu TT sẽ không khớp hub)
    missing = [k for k in ('citad', 'core') if not files.get(k)]
    if missing:
        log(f'[{date_str}] SKIP — thiếu file bắt buộc: {", ".join(missing)}')
        return None
    if not files.get('hub'):
        log(f'[{date_str}] WARN — không có file Hub, TT sẽ chỉ khớp theo Citad.')

    ngay_int = int(date_str)
    core_raw = _filter_core_by_date(core_raw, date_str)

    # ── Load song song (I/O bound) — Core đã nạp sẵn từ main_from_dir() ──
    import pandas as pd

    log(f'[{date_str}] Đang đọc file song song...')
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_hub   = ex.submit(load_hub, files.get('hub', [])) if files.get('hub') else None
        f_citad = ex.submit(load_citad, files['citad'], ngay_int)
        f_eicp  = ex.submit(load_eicp,  files.get('eicp', []))
        f_osb   = ex.submit(load_osb, files.get('osb', []), _osb_carryover_days(ngay_int)) if files.get('osb') else None

        eicp_df = f_eicp.result()
        if cancel_event.is_set():
            return None

        hub_raw = f_hub.result() if f_hub else pd.DataFrame()
        if cancel_event.is_set():
            return None

        citad_raw = f_citad.result()
        if cancel_event.is_set():
            return None

        osb_df = f_osb.result() if f_osb else pd.DataFrame()
        if cancel_event.is_set():
            return None

    log(
        f'[{date_str}] HUB {len(hub_raw):,} · CITAD {len(citad_raw):,} · EICP {len(eicp_df):,} · '
        f'OSB {len(osb_df):,} (kể cả carryover) · CORE {len(core_raw):,} dòng'
    )

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
    core_out = process_core(core_raw, citad_mapdc, hub_lookups, ngay_int, huy_map)
    if cancel_event.is_set():
        return None

    # ── Khớp Citad còn thừa (chưa được Core dùng) với OSB ──
    # docx mục III: "Những dòng còn lại tiếp tục map với file OSB ngày cũ và
    # mới" — CITAD còn thừa, không phải Core map trực tiếp OSB (xác nhận với
    # Business Owner 2026-08-19, kiểm chứng khóa bằng dữ liệu thật 11-12/8).
    log(f'[{date_str}] Khớp Citad còn thừa với OSB...')
    used_mapdc = used_citad_keys(core_out, citad_mapdc)
    osb_key = build_osb_key(osb_df) if not osb_df.empty else None
    citad_out = match_citad_leftover_with_osb(citad_out, used_mapdc, osb_key)
    if not osb_df.empty:
        osb_df = osb_df.copy()
        osb_df['Nhóm'] = label_moi_cu(osb_df, ngay_int)

    # ── Tóm tắt TT ──
    tt_summary = core_out['TT'].value_counts().to_dict() if 'TT' in core_out.columns else {}
    total = len(core_out)
    matched = sum(v for k, v in tt_summary.items() if k not in ('', 'nan'))
    osb_matched = int((citad_out['TT'] == 'OSB').sum()) if 'TT' in citad_out.columns else 0
    log(
        f'[{date_str}] TT: Hủy={tt_summary.get("Hủy", 0):,} · Đã hủy={tt_summary.get("Đã hủy", 0):,} · '
        f'Khớp citad/hub={matched:,} · Chưa khớp={tt_summary.get("", 0):,} / {total:,} · '
        f'Citad khớp OSB={osb_matched:,}'
    )

    # ── Export ──
    log(f'[{date_str}] Xuất file Excel...')
    out_path = export_excel(hub_out, citad_out, eicp_df, core_out, ngay_int, output_dir, osb_df=osb_df)
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

    # ── Nạp Core TOÀN BỘ các ngày trước, để phát hiện đúng Hủy khác ngày ──
    # (lệnh lập 1 ngày, hủy ngày khác — nếu chỉ xét Core từng ngày riêng lẻ sẽ
    # không bao giờ thấy đủ cặp Nợ/Có để nhận ra là đã hủy)
    import pandas as pd

    log('Đang nạp Core toàn bộ các ngày để phát hiện Hủy xuyên ngày...')
    core_raw_by_date: dict = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            date_str: ex.submit(load_core, files['core'], log)
            for date_str, files in day_groups.items()
            if files.get('core')
        }
        for date_str, fut in futures.items():
            core_raw_by_date[date_str] = fut.result()

    all_core_df = _dedup_core_batch(core_raw_by_date)
    huy_map = detect_huy(all_core_df)
    n_huy    = sum(1 for v in huy_map.values() if v == 'Hủy')
    n_da_huy = sum(1 for v in huy_map.values() if v == 'Đã hủy')
    log(f'Phát hiện {n_huy:,} REFERENCE Hủy cùng ngày · {n_da_huy:,} REFERENCE Đã hủy (khác ngày) — toàn batch.')

    output_paths: list[Path] = []
    for date_str in sorted(day_groups.keys()):
        if cancel.is_set():
            return None
        core_raw = core_raw_by_date.get(date_str, pd.DataFrame())
        out = _run_one_day(date_str, day_groups[date_str], core_raw, huy_map, output_dir, log, cancel)
        if out:
            output_paths.append(out)

    return output_paths[-1] if output_paths else None
