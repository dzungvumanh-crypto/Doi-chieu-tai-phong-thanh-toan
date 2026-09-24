"""Pipeline ILO1000: orchestrator chính, chạy mỗi ngày."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from backend.services.lich_lam_viec import LICH_RONG, LichLamViec, la_ngay_lam_viec, tai_lich

from .config import OSB_COL_MA_GD
from .detect import carryover_window, detect_file_type, group_files_by_date
from .export import export_excel, export_pool_file
from .load_citad import load_citad
from .load_core import load_core
from .load_eicp import build_eicp_maps, load_eicp
from .load_hub import load_hub
from .load_osb import build_osb_key, label_moi_cu, load_osb
from .load_pool import load_pool_files
from .process import (
    build_core_thua_forward, build_core_thua_pool, build_mapdc_label_map,
    build_pool_label, detect_huy, mark_pool_doi_chieu, label_citad_provenance,
    process_citad, process_core, process_hub, used_citad_keys, used_label_map_keys,
)


def _osb_carryover_days(ngay_int: int, lich: LichLamViec = LICH_RONG) -> set[int]:
    """
    Cửa sổ ngày cần nạp cho ngày T đang chấm: T + T-1 (ngày thường); T + toàn
    bộ chuỗi ngày nghỉ liên tiếp trước đó (Citad không chạy phiên các ngày
    nghỉ, dữ liệu "chưa đi kênh" dồn sang phiên đi làm lại) — xem
    `detect.carryover_window()`. Dùng chung cho cả OSB ("OSB cũ chưa đi") và
    Hub (`load_hub(..., ngay_ints=...)`) — tên hàm giữ nguyên từ lúc chỉ phục
    vụ OSB, logic đã tổng quát cho cả 2 nguồn (2026-08-19), nay tổng quát thêm
    cho MỌI kỳ nghỉ dài (2026-09-05), không riêng cuối tuần thứ 6-7-CN.

    `lich=LICH_RONG` (mặc định) => chỉ theo thứ Bảy/CN, hệt hành vi cũ.
    """
    d = date(ngay_int // 10000, (ngay_int // 100) % 100, ngay_int % 100)
    days = {ngay_int}
    for prev in carryover_window(d, lich):
        days.add(int(prev.strftime('%Y%m%d')))
    return days


def _hub_forward_window(ngay: date, lich: LichLamViec = LICH_RONG) -> list[date]:
    """
    Đối xứng NGƯỢC với `carryover_window()` (chỉ lùi về T-1) — Hub cần nhìn
    THÊM 1 ngày về SAU (T+1): xác nhận bằng dữ liệu thật 09/09/2026, so
    chương trình với bản tay Việt — bản tay nạp thêm 14.566 dòng Hub ngày
    10/09 khi chấm ngày 09/09; thiếu cửa sổ này khiến 14.318/14.345 dòng
    Core "chưa khớp" đáng lẽ phải mang nhãn 'Chờ đi kênh' (đã tự verify: nạp
    thêm đúng T+1 rồi chạy lại, số dòng lệch giảm từ 14.345 xuống 27).

    Trả về [T+1] cho ngày thường. Nếu T+1 rơi vào ngày nghỉ (T7/CN/lễ) —
    CHƯA có dữ liệu thật xác nhận trường hợp này, suy rộng đối xứng với
    `carryover_window()`: mở rộng tiếp qua hết chuỗi ngày nghỉ, gồm luôn
    ngày làm việc đầu tiên sau chuỗi đó (phiên Hub thật gần nhất).
    """
    days: list[date] = []
    d = ngay + timedelta(days=1)
    days.append(d)
    while not la_ngay_lam_viec(d, lich):
        d += timedelta(days=1)
        days.append(d)
    return days


def _citad_forward_days(ngay_int: int, batch_days: set[int]) -> set[int]:
    """
    Cửa sổ Citad = T ∪ MỌI ngày LỚN HƠN HOẶC BẰNG T có mặt trong batch đang
    chấm (Q1 → (b), chốt 2026-09-23 qua AskUserQuestion) — đúng cách bản tay
    Việt làm: dán hết Citad của cả batch vào 1 sheet rồi VLOOKUP 1 lần. KHÔNG
    còn giới hạn "chỉ 1 phiên kế tiếp" như đề xuất ban đầu của kế hoạch (dựa
    trên `_hub_forward_window()`) — brief 2026-09-23 đính chính lại thành
    "mọi ngày Citad có mặt trong batch". KHÔNG thêm cửa sổ LÙI (Q2): Core của
    ngày T không thể đã đi kênh ở phiên của ngày TRƯỚC T.

    `batch_days`: tập `ngay_int` (YYYYMMDD) của TOÀN BỘ các ngày có nhóm file
    trong batch (`day_groups.keys()` ở `main_from_dir()`) — không cần biết
    trước ngày nào THẬT SỰ có dữ liệu Citad; `load_citad()` tự lọc về đúng
    TRX_DATE có thật, ngày không có Citad thật trong tập này không sinh ra
    dòng nào. So sánh bằng SỐ NGUYÊN (không parse `date`) vẫn đúng thứ tự
    thời gian vì `ngay_int` luôn có định dạng cố định 8 chữ số (YYYYMMDD).
    """
    return {d for d in batch_days if d >= ngay_int}


def _hub_carryover_days(
    ngay_int: int,
    lich: LichLamViec = LICH_RONG,
    batch_days: 'set[int] | None' = None,
) -> set[int]:
    """Cửa sổ Hub đầy đủ = `_osb_carryover_days()` (T + về trước) CỘNG cửa sổ
    tới. Cửa sổ tới ƯU TIÊN `batch_days` nếu có: dùng `_citad_forward_days()`
    — RỘNG BẰNG ĐÚNG cửa sổ Citad (Q7, chốt 2026-09-23, hệ quả BẮT BUỘC của
    Q1 → (b)) — nếu Hub chỉ mở 1 phiên kế tiếp như trước trong khi Citad đã mở
    rộng ra cả batch, dòng Citad ở ngày xa hơn trong cửa sổ sẽ có Trace rỗng
    (không tra được qua Hub/EICP) → khoá `Map dc` cụt → khớp nhầm.
    `batch_days=None` (hàm thuần gọi lẻ, không biết batch — VD test cũ) → rơi
    về hành vi CŨ: chỉ 1 chuỗi nghỉ kế tiếp (`_hub_forward_window()`)."""
    days = _osb_carryover_days(ngay_int, lich)
    if batch_days is not None:
        days |= _citad_forward_days(ngay_int, batch_days)
        return days
    d = date(ngay_int // 10000, (ngay_int // 100) % 100, ngay_int % 100)
    for fwd in _hub_forward_window(d, lich):
        days.add(int(fwd.strftime('%Y%m%d')))
    return days


def _ngay_se_bi_hap_thu(date_str: str, day_groups: dict, lich: LichLamViec) -> bool:
    """
    True nếu `date_str` là 1 ngày KHÔNG làm việc (T7/CN/lễ) MÀ sẽ được gộp
    (qua `carryover_window()`) vào báo cáo của 1 ngày LÀM VIỆC khác cũng có
    mặt trong `day_groups` — khi đó không cần tự xuất file riêng cho nó nữa,
    dữ liệu đã nằm đủ trong báo cáo ngày hấp thụ (xem `merge_monday_carryover()`
    ở detect.py — hàm đó đã gộp Core, ở đây chỉ quyết định có xuất FILE riêng
    hay không, không đụng dữ liệu/thuật toán).

    Chỉ gọi cho ngày đang xét là ngày KHÔNG làm việc; luôn trả False (tự xuất
    riêng như bình thường) nếu KHÔNG tìm thấy ngày làm việc nào trong CÙNG
    batch sẽ hấp thụ nó — batch có thể kết thúc đúng vào kỳ nghỉ, chưa có
    ngày đi làm lại, xuất riêng vẫn còn hơn mất trắng dữ liệu.
    """
    ngay = _parse_yyyymmdd(date_str)
    for other_str in day_groups:
        if other_str == date_str:
            continue
        other_ngay = _parse_yyyymmdd(other_str)
        if not la_ngay_lam_viec(other_ngay, lich):
            continue
        if ngay in carryover_window(other_ngay, lich):
            return True
    return False


def _parse_yyyymmdd(date_str: str) -> date:
    return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def _pool_label_from_filename(paths: list[Path], prefixes: tuple[str, ...]) -> str:
    """
    Nhãn HIỂN THỊ cho pool tồn đọng cũ (in trên cột TT của sheet Citad, VD
    "Core 5-8.9") — lấy từ tên file người chấm đặt, bỏ tiền tố quen thuộc
    (VD "Core thừa 5-8.9.xlsx" → "5-8.9"). CHỈ dùng để hiển thị, không dùng
    để nhận dạng loại file (luôn theo nội dung, xem detect.py) hay để quyết
    định dòng nào còn tồn đọng (luôn theo cột 'Đối chiếu') — sai nhãn nhiều
    nhất chỉ làm dòng chữ khó đọc, không làm sai kết quả khớp.

    Nhiều file cùng loại → lấy tên ĐẦU TIÊN theo thứ tự bảng chữ cái để nhãn
    ổn định giữa các lần chạy. Không có file nào → chuỗi rỗng.
    """
    if not paths:
        return ''
    name = sorted(p.stem for p in paths)[0]
    low = name.lower()
    for prefix in prefixes:
        if low.startswith(prefix):
            return name[len(prefix):].strip()
    return name.strip()


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


def _filter_core_by_date(core_raw, date_strs: str | set[str]):
    """
    Lọc `core_raw` (đã nạp cho CẢ BATCH nhiều ngày, xem `main_from_dir()`) về
    đúng (các) TRDATE thuộc phiên đang chấm. 1 file GL02 gốc có thể tự chứa
    NHIỀU ngày trộn lẫn (xác nhận thật 2026-08-19: "1000_gl02_2026081120260812
    .csv" chứa cả TRDATE 11 và 12/08) — không lọc lại thì sheet 'core' xuất ra
    của MỌI ngày trong batch giống hệt nhau (đều chứa toàn bộ batch, không
    riêng ngày đang chấm).

    `date_strs`: 1 ngày (str, hành vi cũ) hoặc TẬP nhiều ngày (set[str]) —
    ngày đi làm lại sau cuối tuần/nghỉ lễ cần giữ lại CẢ TRDATE của các ngày
    nghỉ đã được `merge_monday_carryover()` gộp file vào (xem `_run_one_day()`),
    không chỉ đúng 1 ngày T. Thiếu bước này thì việc gộp file Core ở
    `detect.merge_monday_carryover()` chỉ có tác dụng cho `huy_map` xuyên ngày
    (tính trên `all_core_df` ở `main_from_dir()`), còn sheet 'core' xuất ra của
    chính ngày đi làm lại vẫn bị lọc sạch dữ liệu các ngày nghỉ đã gộp — phát
    hiện 2026-09-05 khi tổng quát hoá carryover cho kỳ nghỉ dài (áp dụng ngược
    luôn cho cuối tuần chuẩn — Thứ 2 trước đây cũng bị lọc mất dữ liệu Thứ 7/CN
    đã gộp, chỉ là không ai để ý vì Core Thứ 7/CN thường rỗng hoặc trùng dữ liệu
    Core của chính ngày Thứ 2).
    """
    if 'TRDATE' not in core_raw.columns:
        return core_raw
    trdate = core_raw['TRDATE'].fillna('').astype(str).str.strip()
    if isinstance(date_strs, str):
        return core_raw[trdate == date_strs].copy()
    return core_raw[trdate.isin(date_strs)].copy()


def _run_one_day(
    date_str: str,
    files: dict,
    core_raw,
    huy_map: dict,
    output_dir: str,
    log: Callable,
    cancel_event: threading.Event,
    lich: LichLamViec = LICH_RONG,
    core_pool_label_map: 'dict | None' = None,
    osb_pool_label_map: 'dict | None' = None,
    pool_state: 'dict | None' = None,
    batch_days: 'set[int] | None' = None,
) -> Path | None:
    """Xử lý 1 ngày. Trả None nếu bị cancel hoặc thiếu file thiết yếu.

    `core_raw`/`huy_map` được nạp/tính sẵn ở main_from_dir() trên TOÀN BỘ batch
    (không phải chỉ ngày này) — cần vậy để phát hiện đúng Hủy khác ngày.

    `core_pool_label_map`/`osb_pool_label_map`: {Map dc → nhãn} của pool tồn
    đọng NẠP TỪ BATCH TRƯỚC (VD "Core 5-8.9") — dùng để gán TT của sheet Citad
    khi không khớp Core/OSB hôm nay, xem `process.label_citad_provenance()`.
    `pool_state`: dict dùng chung xuyên suốt các ngày trong batch (mutate tại
    chỗ, không trả về) để `main_from_dir()` tổng hợp pool "thừa" mới sau khi
    xử lý xong TOÀN BỘ batch — xem `process.py` phần "Pool tồn đọng xuyên
    batch". Cả 3 tham số này None (mặc định) → hành vi y hệt trước khi có
    tính năng pool, chỉ khớp Core/OSB hôm nay như cũ.

    `batch_days`: tập `ngay_int` của TOÀN BỘ các ngày có nhóm file trong batch
    (`day_groups.keys()` ở `main_from_dir()`) — cửa sổ Citad "tới" (PLAN_B1,
    Q1=(b), chốt 2026-09-23) = T ∪ mọi ngày > T trong tập này, xem
    `_citad_forward_days()`. None (mặc định) → coi batch chỉ có đúng ngày này
    (không mở rộng gì, hệt hành vi cũ).
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
    ngay = date(ngay_int // 10000, (ngay_int // 100) % 100, ngay_int % 100)
    # Giữ lại TRDATE của chính ngày T + mọi ngày NGHỈ trong cửa sổ carryover đã
    # được merge_monday_carryover() gộp file Core vào `files['core']` — không
    # chỉ đúng ngày T (xem docstring _filter_core_by_date()). Ngày làm việc cuối
    # cửa sổ (nếu có) không tính — nó tự có báo cáo Core riêng của chính nó.
    core_dates = {date_str} | {
        d.strftime('%Y%m%d') for d in carryover_window(ngay, lich)
        if not la_ngay_lam_viec(d, lich)
    }
    core_raw = _filter_core_by_date(core_raw, core_dates)

    # ── Cửa sổ Citad "tới" = T ∪ mọi ngày > T có mặt trong batch (Q1=(b)) —
    # Hub PHẢI mở cửa sổ tới RỘNG BẰNG ĐÚNG cửa sổ này (Q7, bắt buộc): nếu
    # không, dòng Citad ở ngày xa hơn sẽ có Trace rỗng (không tra được qua
    # Hub/EICP) → khoá Map dc cụt → khớp nhầm. batch_days=None (chưa biết
    # batch) → cả 2 cửa sổ coi như chỉ có đúng ngày này (không đổi gì).
    citad_window = _citad_forward_days(ngay_int, batch_days if batch_days is not None else {ngay_int})

    # ── Load song song (I/O bound) — Core đã nạp sẵn từ main_from_dir() ──
    import pandas as pd

    log(f'[{date_str}] Đang đọc file song song...')
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_hub   = ex.submit(load_hub, files.get('hub', []), _hub_carryover_days(ngay_int, lich, batch_days=batch_days)) if files.get('hub') else None
        f_citad = ex.submit(load_citad, files['citad'], citad_window)
        f_eicp  = ex.submit(load_eicp,  files.get('eicp', []))
        f_osb   = ex.submit(load_osb, files.get('osb', []), _osb_carryover_days(ngay_int, lich)) if files.get('osb') else None

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
    citad_out, citad_mapdc = process_citad(citad_raw, hub_lookups, ngay_int, log=log)
    if cancel_event.is_set():
        return None

    log(f'[{date_str}] Xử lý Core (pivot + TT)...')
    core_out = process_core(core_raw, citad_mapdc, hub_lookups, ngay_int, huy_map)
    if cancel_event.is_set():
        return None

    # ── PLAN_B3 (2026-09-23): log tổng hợp Trace Hub trùng ≥2 giao dịch —
    # số tuyệt đối, không %. Chi tiết "giải bằng Số tiền/chi nhánh/không giải
    # được" từng Trace đã có log WARNING riêng ở process_core() khi không
    # giải được — dòng này chỉ cho biết QUY MÔ ảnh hưởng của ngày đang chấm.
    dup_traces_hub = hub_lookups.get('trace_trung', {}).get('keys', set())
    if dup_traces_hub and 'Trace' in core_out.columns:
        n_core_anh_huong = int(core_out['Trace'].astype(str).isin(dup_traces_hub).sum())
        log(
            f'[{date_str}] Trace Hub trùng: {len(dup_traces_hub):,} nhóm · '
            f'{n_core_anh_huong:,} dòng Core rơi vào nhóm này (xem log WARNING '
            f'phía trên nếu có Trace không giải được bằng Số tiền/chi nhánh).'
        )

    # ── Lọc citad_out về ĐÚNG TRX_DATE == T trước khi tính TT/xuất/tồn đọng ──
    # citad_raw/citad_mapdc ở trên dùng CẢ CỬA SỔ (để Core tra được), nhưng
    # sheet 'citad' xuất ra và mọi phần tồn đọng phía sau CHỈ được chứa đúng 1
    # ngày T — nếu không, dòng T+1 sẽ xuất hiện ở BÁO CÁO CỦA 2 NGÀY, "Citad
    # thừa" đếm trùng, và citad_mapdc_by_day[T] lẫn khoá của T+1 (PLAN_B1 mục 2).
    if 'TRX_DATE' in citad_out.columns:
        citad_out = citad_out[
            citad_out['TRX_DATE'].fillna('').astype(str).str.strip() == date_str
        ].copy()

    # ── Khớp Citad còn thừa (chưa được Core dùng) với OSB ──
    # docx mục III: "Những dòng còn lại tiếp tục map với file OSB ngày cũ và
    # mới" — CITAD còn thừa, không phải Core map trực tiếp OSB (xác nhận với
    # Business Owner 2026-08-19, kiểm chứng khóa bằng dữ liệu thật 11-12/8).
    log(f'[{date_str}] Khớp Citad còn thừa với OSB + pool tồn đọng...')
    used_mapdc = used_citad_keys(core_out, citad_mapdc)
    if not osb_df.empty:
        osb_df = osb_df.copy()
        osb_df['Nhóm'] = label_moi_cu(osb_df, ngay_int)
    osb_today_label_map = build_mapdc_label_map(
        pd.DataFrame({'Map dc': build_osb_key(osb_df)}) if not osb_df.empty else pd.DataFrame(),
        'Map dc', f'OSB {ngay_int}',
    )
    # Q5 (PLAN_B1, chốt 2026-09-23): Citad ở TRX_DATE=T có thể đã bị Core của
    # MỘT NGÀY KHÁC trong cùng batch "tiêu thụ" trước (cửa sổ tới giờ rộng
    # bằng cả batch, xem `_citad_forward_days()`) — đọc dict tích luỹ TỪ CÁC
    # NGÀY ĐÃ XỬ LÝ TRƯỚC ngày này (main_from_dir() luôn duyệt tăng dần) để
    # không hiện nhầm "Citad thừa" ở báo cáo của chính ngày T.
    cross_day_used_map = pool_state.get('citad_used_cross_day') if pool_state is not None else None

    citad_out = citad_out.copy()
    citad_out['TT'] = label_citad_provenance(
        citad_out, used_mapdc, ngay_int,
        core_pool_label_map=core_pool_label_map,
        osb_today_label_map=osb_today_label_map,
        osb_pool_label_map=osb_pool_label_map,
        cross_day_used_map=cross_day_used_map,
    )

    if pool_state is not None:
        pool_state.setdefault('citad_mapdc_by_day', {})[ngay_int] = set(
            citad_out['Map dc'].astype(str)
        ) if 'Map dc' in citad_out.columns else set()
        pool_state.setdefault('core_leftover_frames', []).append(build_core_thua_pool(core_out))

        # Ghi lại các Map dc mà Core của NGÀY NÀY vừa dùng, cho các NGÀY SAU
        # trong batch tra lại (đoạn trên) — setdefault để ngày SỚM HƠN "chiếm"
        # trước nếu (hiếm) trùng khoá giữa nhiều ngày.
        cd_used = pool_state.setdefault('citad_used_cross_day', {})
        for k in used_mapdc:
            cd_used.setdefault(k, ngay_int)

        # OSB hôm nay CHƯA bị 1 dòng Citad nào tiêu thụ (khớp Core/pool Core
        # ưu tiên cao hơn, hoặc không khớp Citad nào cả) vẫn phải mang sang
        # pool "OSB thừa" của batch sau — cùng nguyên tắc với Core thừa.
        if not osb_df.empty and 'TT' in citad_out.columns:
            used_osb_today = used_label_map_keys(citad_out['TT'], citad_out['Map dc'], osb_today_label_map)
            osb_key_today = build_osb_key(osb_df).astype(str)
            osb_leftover_today = osb_df.loc[~osb_key_today.isin(used_osb_today)].copy()
        else:
            osb_leftover_today = osb_df.iloc[0:0].copy()
        pool_state.setdefault('osb_leftover_frames', []).append(osb_leftover_today)

    # ── Tóm tắt TT ──
    tt_summary = core_out['TT'].value_counts().to_dict() if 'TT' in core_out.columns else {}
    total = len(core_out)
    matched = sum(v for k, v in tt_summary.items() if k not in ('', 'nan'))
    citad_thua_df = citad_out[citad_out['TT'] == ''] if 'TT' in citad_out.columns else citad_out.iloc[0:0]
    citad_khop_pool_osb = int(
        citad_out['TT'].astype(str).str.startswith('OSB').sum()
    ) if 'TT' in citad_out.columns else 0
    log(
        f'[{date_str}] TT: Hủy={tt_summary.get("Hủy", 0):,} · Đã hủy={tt_summary.get("Đã hủy", 0):,} · '
        f'Khớp citad/hub={matched:,} · Chưa khớp={tt_summary.get("", 0):,} / {total:,} · '
        f'Citad khớp OSB={citad_khop_pool_osb:,} · Citad thừa={len(citad_thua_df):,}'
    )

    # ── Export ──
    log(f'[{date_str}] Xuất file Excel...')
    out_path = export_excel(hub_out, citad_out, eicp_df, core_out, ngay_int, output_dir, osb_df=osb_df)
    if not citad_thua_df.empty:
        thua_path = export_pool_file(citad_thua_df, output_dir, f'Citad thừa {ngay.day}.{ngay.month}')
        log(f'[{date_str}] {len(citad_thua_df):,} dòng Citad thừa (không khớp Core/OSB/pool nào) → {thua_path.name}')
    log(f'[{date_str}] Hoàn thành → {out_path.name}')
    return out_path


def main_from_dir(
    input_dir: str,
    output_dir: str,
    ngay: str | None = None,
    log_callback: Callable | None = None,
    cancel_event: threading.Event | None = None,
    db: sqlite3.Connection | None = None,
) -> Path | None:
    """
    Entry point: nhận thư mục chứa file đầu vào, nhóm theo ngày, xử lý từng ngày.
    Trả về Path file cuối cùng (hoặc None nếu không có output hoặc bị cancel).

    `db`: nếu truyền, đọc lịch nghỉ lễ/làm bù thật (`tai_lich()`) để tính đúng
    cửa sổ carryover cho MỌI kỳ nghỉ dài (không chỉ cuối tuần chuẩn) — xem
    `detect.carryover_window()`. Không truyền (mặc định) => dùng `LICH_RONG`,
    hệt hành vi cũ (chỉ theo thứ Bảy/CN).
    """
    log = log_callback or (lambda msg: None)
    cancel = cancel_event or threading.Event()

    all_paths = list(Path(input_dir).iterdir())
    log(f'Tổng file phát hiện: {len(all_paths)}')

    # ── Xác định lịch nghỉ lễ thật (nếu có db) TRƯỚC khi nhóm ngày chính thức ──
    # Nhóm sơ bộ (lịch rỗng, không log) chỉ để biết khoảng ngày cần tra —
    # group_files_by_date() không đọc nội dung file lớn (GL02/EICP), chỉ đọc
    # 2 dòng đầu CSV citad để nhận dạng loại file, nên gọi 2 lần không tốn kém.
    lich: LichLamViec = LICH_RONG
    if db is not None:
        so_bo = group_files_by_date(all_paths, log=None)
        if so_bo:
            ngay_list = [
                date(int(d[:4]), int(d[4:6]), int(d[6:8])) for d in so_bo
            ]
            # Lùi thêm 14 ngày trước ngày sớm nhất trong batch — đủ rộng cho
            # kỳ nghỉ dài nhất thực tế (Tết) mà không phải đoán trước độ dài.
            lo = min(ngay_list) - timedelta(days=14)
            hi = max(ngay_list)
            lich = tai_lich(db, lo, hi)

    day_groups = group_files_by_date(all_paths, log, lich)
    if not day_groups:
        log('[WARN] Không nhóm được file theo ngày.')
        return None

    log(f'Số ngày cần xử lý: {len(day_groups)}')

    # Cửa sổ Citad/Hub "tới" (Q1=(b)/Q7, PLAN_B1) cần biết TOÀN BỘ ngày có
    # nhóm file trong batch — không chỉ ngày có Citad thật; load_citad() tự
    # lọc về đúng TRX_DATE thật có trong file, xem `_citad_forward_days()`.
    batch_days_int = {int(d) for d in day_groups}

    # ── Pool tồn đọng xuyên batch (Core thừa / OSB thừa nạp lại từ lần chấm
    # trước — người chấm tự nạp lại, giống hub/citad/core/osb) — xem
    # process.py phần "Pool tồn đọng xuyên batch". Nhãn dải ngày tính từ NGÀY
    # CỦA BATCH ĐANG XỬ LÝ (day_groups), không phải TRDATE thật tồn đọng bên
    # trong pool — xem `build_pool_label()`.
    core_thua_paths = [p for p in all_paths if detect_file_type(p) == 'core_thua']
    osb_thua_paths  = [p for p in all_paths if detect_file_type(p) == 'osb_thua']
    old_core_pool = load_pool_files(core_thua_paths)
    old_osb_pool  = load_pool_files(osb_thua_paths)

    # Nhãn cho FILE MỚI xuất ra (Core/OSB thừa của LẦN NÀY) tính từ ngày của
    # chính batch đang chấm — xem build_pool_label(). Nhãn hiển thị cho pool
    # CŨ (chỉ in trên cột TT của Citad, không ảnh hưởng khớp) lấy từ TÊN FILE
    # cũ — dữ liệu bên trong pool không có cột lưu lại nhãn dải ngày gốc của
    # chính nó (TRDATE tồn đọng có thể rất cũ, không phản ánh đúng batch nào
    # đã tạo ra pool — xác nhận thật: pool "Core thừa 5-8.9" chứa cả TRDATE
    # 25/08, 28/08 lẫn 07-08/09).
    batch_days  = sorted(_parse_yyyymmdd(d) for d in day_groups)
    batch_label = build_pool_label(batch_days)

    old_core_pool_label = _pool_label_from_filename(core_thua_paths, ('core thừa', 'core thua'))
    old_osb_pool_label  = _pool_label_from_filename(osb_thua_paths, ('osb thừa', 'osb thua'))

    core_pool_label_map = build_mapdc_label_map(old_core_pool, 'Map dc', f'Core {old_core_pool_label}')
    osb_pool_label_map  = build_mapdc_label_map(old_osb_pool, 'Map dc', f'OSB {old_osb_pool_label}')

    if not old_core_pool.empty or not old_osb_pool.empty:
        log(
            f'Pool tồn đọng nạp lại: Core thừa {len(old_core_pool):,} dòng · '
            f'OSB thừa {len(old_osb_pool):,} dòng.'
        )

    pool_state: dict = {}

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

        # Ngày KHÔNG làm việc (T7/CN/lễ) mà dữ liệu của nó đã được gộp vào
        # báo cáo của ngày làm việc kế tiếp (merge_monday_carryover() ở
        # detect.py) thì không tự xuất file riêng nữa — Citad không có phiên
        # thật ngày đó, file riêng chỉ là bản trùng lặp/thiếu Citad gây nhầm
        # (xác nhận nghiệp vụ 2026-09-10: chỉ ngày ĐI LÀM mới có "phiên kênh"
        # thật, cuối tuần dồn hết vào phiên đi làm lại). Không đụng
        # core_raw_by_date/huy_map — 2 cái đó vẫn tính trên toàn batch như cũ.
        ngay_dang_xet = _parse_yyyymmdd(date_str)
        if not la_ngay_lam_viec(ngay_dang_xet, lich) and _ngay_se_bi_hap_thu(date_str, day_groups, lich):
            log(f'[{date_str}] Bỏ qua xuất báo cáo riêng — ngày nghỉ, dữ liệu đã gộp vào báo cáo ngày làm việc kế tiếp.')
            continue

        core_raw = core_raw_by_date.get(date_str, pd.DataFrame())
        out = _run_one_day(
            date_str, day_groups[date_str], core_raw, huy_map, output_dir, log, cancel, lich,
            core_pool_label_map=core_pool_label_map,
            osb_pool_label_map=osb_pool_label_map,
            pool_state=pool_state,
            batch_days=batch_days_int,
        )
        if out:
            output_paths.append(out)

    _export_pool_thua_forward(old_core_pool, old_osb_pool, pool_state, batch_label, output_dir, log)

    return output_paths[-1] if output_paths else None


def _export_pool_thua_forward(
    old_core_pool: 'pd.DataFrame',
    old_osb_pool: 'pd.DataFrame',
    pool_state: dict,
    batch_label: str,
    output_dir: str,
    log: Callable,
) -> None:
    """
    Sau khi xử lý xong TOÀN BỘ batch: điền cột 'Đối chiếu' cho 2 pool cũ nạp
    vào (khớp được ngày nào trong batch này thì ghi ngày đó, không thì
    '#N/A'), rồi xuất pool MỚI (còn tồn đọng + leftover mới phát sinh trong
    chính batch này) cho lần chấm kế tiếp — xem `process.py` phần "Pool tồn
    đọng xuyên batch".
    """
    import pandas as pd

    citad_mapdc_by_day: dict = pool_state.get('citad_mapdc_by_day', {})

    def _mark(old_pool: 'pd.DataFrame') -> 'pd.DataFrame':
        if old_pool.empty or 'Map dc' not in old_pool.columns:
            return old_pool
        old_pool = old_pool.copy()
        doi_chieu = old_pool.get('Đối chiếu')
        for ngay_int in sorted(citad_mapdc_by_day):
            doi_chieu = mark_pool_doi_chieu(
                old_pool['Map dc'], doi_chieu, citad_mapdc_by_day[ngay_int], ngay_int,
            )
        if doi_chieu is not None:
            old_pool['Đối chiếu'] = doi_chieu
        return old_pool

    old_core_pool = _mark(old_core_pool)
    old_osb_pool  = _mark(old_osb_pool)

    core_leftover_frames = pool_state.get('core_leftover_frames', [])
    new_core_leftover = pd.concat(core_leftover_frames, ignore_index=True) if core_leftover_frames else pd.DataFrame()
    core_thua_forward = build_core_thua_forward(old_core_pool, new_core_leftover)
    if not core_thua_forward.empty:
        path = export_pool_file(core_thua_forward, output_dir, f'Core thừa {batch_label}')
        log(f'Pool Core thừa mới cho lần chấm sau: {len(core_thua_forward):,} dòng → {path.name}')

    osb_leftover_frames = pool_state.get('osb_leftover_frames', [])
    new_osb_leftover = pd.DataFrame()
    if osb_leftover_frames:
        new_osb_leftover = pd.concat(osb_leftover_frames, ignore_index=True)
        # 1 dòng OSB vật lý có thể lặp lại ở NHIỀU ngày trong cùng batch (cửa
        # sổ carryover trong-batch T/T-1 của load_osb() khác pool xuyên batch
        # này) — dedup theo 'Mã giao dịch' (khóa tự nhiên của OSB) trước khi
        # mang sang pool, tránh nhân bản.
        if OSB_COL_MA_GD in new_osb_leftover.columns:
            new_osb_leftover = new_osb_leftover.drop_duplicates(subset=[OSB_COL_MA_GD], keep='first')
    osb_thua_forward = build_core_thua_forward(old_osb_pool, new_osb_leftover)
    if not osb_thua_forward.empty:
        path = export_pool_file(osb_thua_forward, output_dir, f'OSB thừa {batch_label}')
        log(f'Pool OSB thừa mới cho lần chấm sau: {len(osb_thua_forward):,} dòng → {path.name}')
