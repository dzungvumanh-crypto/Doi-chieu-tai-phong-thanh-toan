"""Nhận dạng loại file và nhóm theo ngày cho pipeline ILO1000."""

import re
import zipfile
from datetime import date, timedelta
from pathlib import Path


# ── Regex nhận dạng date từ tên file ─────────────────────────────────────────
_RE_GL02_CSV = re.compile(r'gl02[_\s](\d{8})', re.IGNORECASE)
_RE_GL02_ZIP = re.compile(r'GL02[_\s](\d{8})', re.IGNORECASE)
_RE_EICP_DAY = re.compile(r'eicp\s+(\d+)', re.IGNORECASE)


def detect_file_type(path: Path) -> str:
    """Trả về: 'hub' | 'citad' | 'eicp' | 'osb' | 'core_csv' | 'core_zip' | 'unknown'."""
    name = path.name
    low  = name.lower()

    if low.startswith('phub_') and low.endswith('.xlsx'):
        return 'hub'
    if low.startswith('osb') and low.endswith('.xlsx'):
        return 'osb'
    if re.search(r'eicp', low) and (low.endswith('.xls') or low.endswith('.xlsx')):
        return 'eicp'
    if re.search(r'gl02', low) and low.endswith('.zip'):
        return 'core_zip'
    if re.search(r'gl02', low) and low.endswith('.csv'):
        return 'core_csv'
    if low.endswith('.csv') and _is_citad_csv(path):
        return 'citad'
    return 'unknown'


def _is_citad_csv(path: Path) -> bool:
    """Đọc header của CSV để xác nhận là file CITAD."""
    try:
        with path.open('r', encoding='utf-8-sig', errors='ignore') as f:
            header = f.readline().strip()
        return 'SERIAL_NO' in header and 'RELATION_NO' in header and 'TRX_STATUS' in header
    except Exception:
        return False


def extract_date(path: Path, file_type: str) -> str | None:
    """Trích ngày YYYYMMDD từ tên file. Trả None nếu không nhận dạng được."""
    name = path.name
    if file_type in ('core_csv',):
        m = _RE_GL02_CSV.search(name)
        return m.group(1) if m else None
    if file_type == 'core_zip':
        m = _RE_GL02_ZIP.search(name)
        return m.group(1) if m else None
    if file_type == 'eicp':
        # EICP chỉ có ngày (DD), không có năm/tháng → trả None, gán sau
        return None
    if file_type == 'citad':
        return _read_citad_date(path)
    if file_type == 'osb':
        # Tên file OSB KHÔNG đáng tin để suy ngày — xác nhận thật: file
        # "OSB n 11-12.7.xlsx" chứa dữ liệu ngày 11-12/08, không phải tháng 7
        # như tên gợi ý. Ngày thật đọc từ cột 'Ngày hạch toán' lúc load_osb().
        return None
    return None


def _read_citad_date(path: Path) -> str | None:
    """Đọc TRX_DATE từ dòng đầu tiên của CITAD CSV (dùng csv.reader để xử lý quoted fields)."""
    import csv
    try:
        with path.open('r', encoding='utf-8-sig', errors='ignore', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header or 'TRX_DATE' not in header:
                return None
            idx = header.index('TRX_DATE')
            for _ in range(2):
                row = next(reader, None)
                if row and len(row) > idx:
                    val = row[idx].strip()
                    if re.match(r'^\d{8}$', val):
                        return val
    except Exception:
        pass
    return None


def _eicp_day(path: Path) -> int | None:
    """Trích số ngày (DD) từ tên file EICP."""
    m = _RE_EICP_DAY.search(path.name)
    return int(m.group(1)) if m else None


def group_files_by_date(paths: list[Path], log=None) -> dict[str, dict]:
    """
    Phân loại và nhóm file theo ngày.
    Trả về: {yyyymmdd: {hub: Path, citad: [Path], eicp: [Path], core: [Path]}}
    """
    groups: dict[str, dict] = {}
    eicp_pending: list[tuple[Path, int]] = []  # (path, day_num)
    citad_pool: list[Path] = []  # citad KHÔNG gán theo ngày ở đây — xem cuối hàm
    osb_pool:   list[Path] = []  # OSB cũng vậy — tên file không đáng tin về ngày
    hub_pool:   list[Path] = []  # Hub cũng vậy — xem cuối hàm

    def _get_or_create(date_str: str) -> dict:
        if date_str not in groups:
            groups[date_str] = {'hub': [], 'citad': [], 'eicp': [], 'core': [], 'osb': []}
        return groups[date_str]

    for p in paths:
        ft = detect_file_type(p)
        if ft == 'unknown':
            if log:
                log(f'  [SKIP] Không nhận dạng được: {p.name}')
            continue

        # Citad: KHÔNG đoán ngày theo file — 1 file citad có thể gộp chung dữ
        # liệu NHIỀU ngày (xác nhận qua dữ liệu thật 14-15/7/2026: cả 5 file
        # cổng đều có cả TRX_DATE 14 lẫn 15 trộn lẫn). Đoán ngày theo 2 dòng
        # đầu (cách cũ) gán SAI nguyên file vào 1 ngày, ngày kia mất trắng
        # citad. Thay vào đó: gom vào pool chung, lọc theo TRX_DATE khi load
        # (xem cuối hàm + load_citad()).
        if ft == 'citad':
            citad_pool.append(p)
            continue

        # OSB: cùng lý do như Citad — tên file không đáng tin (xác nhận thật:
        # "OSB n 11-12.7.xlsx" chứa dữ liệu tháng 8, không phải tháng 7). Gom
        # pool chung, lọc theo cột 'Ngày hạch toán' khi load (load_osb()).
        if ft == 'osb':
            osb_pool.append(p)
            continue

        # Hub: cùng lý do như Citad/OSB — tên file không đáng tin (xác nhận
        # thật 2026-08-19: 5 file pHub cùng tên ngày xuất 13/08 nhưng bên
        # trong trộn lẫn dữ liệu 4 ngày khác nhau, 10-13/08). Cách cũ (đoán
        # ngày theo tên, không khớp thì dồn HẾT vào 1 nhóm duy nhất) từng làm
        # mất trắng Hub 1 ngày trong batch thật. Gom pool chung, lọc theo
        # 'Ngày giờ kênh trả' + cửa sổ carryover khi load (xem load_hub()).
        if ft == 'hub':
            hub_pool.append(p)
            continue

        date_str = extract_date(p, ft)

        if ft == 'eicp':
            day_num = _eicp_day(p)
            if day_num is not None:
                eicp_pending.append((p, day_num))
            elif log:
                log(f'  [WARN] EICP không trích được ngày: {p.name}')
            continue

        if date_str is None:
            if log:
                log(f'  [WARN] Không trích được ngày từ: {p.name}')
            continue

        g = _get_or_create(date_str)
        if ft in ('core_csv', 'core_zip'):
            g['core'].append(p)

    # Gán TOÀN BỘ pool citad/osb/hub cho mọi nhóm ngày TRƯỚC — mỗi file citad/
    # osb/hub có thể chứa dữ liệu nhiều ngày, nên không thể biết trước file nào
    # cần cho ngày nào; load_citad()/load_osb()/load_hub() sẽ tự lọc đúng ngày
    # (+ carryover) lúc xử lý. PHẢI làm trước phần EICP/merge bên dưới — cả 2
    # đều dùng `len(groups[d]['citad'])` để biết ngày nào "thực sự chấm"; làm
    # sau (như code cũ) khiến điều kiện đó LUÔN rỗng, EICP carryover T-1 không
    # bao giờ thực sự kích hoạt (bug phát hiện 2026-08-20 lúc sửa Hub, tách
    # riêng khỏi việc Hub — sửa luôn vì cùng gốc "citad rỗng lúc kiểm tra").
    if citad_pool:
        for g in groups.values():
            g['citad'] = citad_pool
        if log:
            log(f'  [INFO] {len(citad_pool)} file citad — gán chung cho mọi ngày, lọc theo TRX_DATE lúc xử lý.')

    if osb_pool:
        for g in groups.values():
            g['osb'] = osb_pool
        if log:
            log(f'  [INFO] {len(osb_pool)} file OSB — gán chung cho mọi ngày, lọc theo Ngày hạch toán lúc xử lý.')

    if hub_pool:
        for g in groups.values():
            g['hub'] = hub_pool
        if log:
            log(f'  [INFO] {len(hub_pool)} file hub — gán chung cho mọi ngày, lọc theo Ngày giờ kênh trả lúc xử lý.')

    # Gán EICP vào ngày tương ứng (chỉ dùng day number, bỏ qua năm/tháng)
    eicp_unmatched: list[Path] = []
    for p, day_num in eicp_pending:
        matched = False
        for date_str in groups:
            if int(date_str[6:8]) == day_num:
                groups[date_str]['eicp'].append(p)
                matched = True
                break
        if not matched:
            eicp_unmatched.append(p)

    # EICP không khớp nhóm ngày nào có sẵn (VD tên file không theo công thức chuẩn,
    # hoặc ngày đó không có Citad/Core riêng — chỉ tồn tại qua carryover thứ 2)
    # → gán vào group có đủ citad+core nhất, không âm thầm bỏ dữ liệu. (Hub
    # từng có cơ chế fallback tương tự — đã bỏ, Hub giờ là pool lọc theo dòng.)
    if eicp_unmatched and groups:
        best_group = max(groups.keys(), key=lambda d: len(groups[d]['citad']) + len(groups[d]['core']))
        for p in eicp_unmatched:
            groups[best_group]['eicp'].append(p)
            if log:
                log(f'  [INFO] Gán EICP ({p.name}) vào nhóm {best_group} (không khớp ngày nào có sẵn)')
    elif eicp_unmatched and log:
        for p in eicp_unmatched:
            log(f'  [WARN] Không gán được ngày cho EICP: {p.name}')

    # Chạy trước merge_monday_carryover: khi thứ 2 tự gộp thêm dữ liệu cuối tuần,
    # KHÔNG được để việc đó "lan" ngược vào ngày thứ 3 (thứ 3 chỉ cần EICP gốc
    # của thứ 2, không cần cả cuối tuần thứ 2 đã gộp thêm).
    merge_previous_day_eicp(groups, log)
    merge_monday_carryover(groups, log)

    return groups


def _parse_date(date_str: str) -> date:
    return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def merge_previous_day_eicp(groups: dict, log=None) -> None:
    """
    Ngày chấm bình thường (không phải thứ 2 — thứ 2 dùng merge_monday_carryover
    riêng, phạm vi rộng hơn): gộp thêm EICP của T-1 vào nhóm ngày T, theo đúng
    tài liệu gốc bước 1 ("Xuất dữ liệu hub gồm cần đối chiếu t và trước ngày
    cần chấm đối chiếu 1 ngày t-1"). Lệnh vào hệ thống sau giờ cutoff T-1
    chuyển "chờ đi kênh" sang T — EICP của lệnh đó vẫn nằm trong file T-1, cần
    gộp vào để tra đúng Trace. Citad/Core giữ nguyên chỉ ngày T.
    COPY (không xoá khỏi nhóm T-1 gốc) — T-1 vẫn tự ra báo cáo riêng bình thường.

    (Hub trước đây cũng gộp ở đây theo file — đã bỏ 2026-08-19: Hub giờ là
    pool lọc theo dòng "Ngày giờ kênh trả" + cửa sổ T/T-1 ngay lúc load_hub(),
    xem pipeline.py::_run_one_day() và detect.py::group_files_by_date().)
    """
    # Chỉ áp dụng cho nhóm THỰC SỰ chấm (có Citad) — nhóm không có Citad (VD
    # thứ 7/CN đơn thuần chỉ có Core rơi vào) sẽ bị SKIP ở bước xử lý sau,
    # không cần áp T-1; quan trọng hơn: nếu vẫn áp cho chúng, danh sách eicp
    # của nhóm đó bị nối dài trước khi merge_monday_carryover đọc lại (T-2/T-3),
    # khiến dữ liệu T-1-của-T-1 bị "lan" 2 lớp vào thứ 2 một cách dư thừa.
    target_keys = [d for d in groups if _parse_date(d).weekday() != 0 and groups[d].get('citad')]

    for t_str in target_keys:
        t_date = _parse_date(t_str)
        prev_str = (t_date - timedelta(days=1)).strftime('%Y%m%d')

        g = groups[t_str]
        src = groups.get(prev_str, {})

        if src.get('eicp'):
            g['eicp'] = g['eicp'] + src['eicp']
            if log:
                log(f'[{t_str}] Gộp thêm EICP của T-1 ({prev_str}).')
        elif log:
            log(
                f'[{t_str}] CẢNH BÁO — thiếu EICP T-1 ({prev_str}). '
                'Có thể sót giao dịch chờ đi kênh từ hôm trước (T-1).'
            )


def merge_monday_carryover(groups: dict, log=None) -> None:
    """
    Chấm thứ 2: Citad không chạy phiên thứ 7/CN nên toàn bộ lệnh "chờ đi kênh"
    phát sinh sau giờ cutoff thứ 6 + cả thứ 7 + CN đều dồn sang phiên sáng thứ 2.
    Gộp thêm EICP của thứ 6,7,CN (T-3,T-2,T-1) và Core của thứ 7,CN (T-2,T-1)
    vào nhóm thứ 2 để bắt được các lệnh này. Citad giữ nguyên chỉ ngày thứ 2 (T).
    Đây là COPY (không xoá khỏi nhóm gốc) — thứ 6 vẫn tự ra báo cáo riêng bình thường.

    (Hub trước đây cũng gộp ở đây theo file — đã bỏ 2026-08-19, xem
    merge_previous_day_eicp() để biết lý do: Hub giờ là pool lọc theo dòng,
    cửa sổ carryover cho thứ 2 áp dụng ngay ở load_hub() qua
    pipeline.py::_osb_carryover_days().)
    """
    monday_keys = [d for d in groups if _parse_date(d).weekday() == 0]

    for mon_str in monday_keys:
        mon_date = _parse_date(mon_str)
        fri_str = (mon_date - timedelta(days=3)).strftime('%Y%m%d')
        sat_str = (mon_date - timedelta(days=2)).strftime('%Y%m%d')
        sun_str = (mon_date - timedelta(days=1)).strftime('%Y%m%d')

        g = groups[mon_str]
        missing: list[str] = []

        for label, d_str in (('thứ 6', fri_str), ('thứ 7', sat_str), ('CN', sun_str)):
            src = groups.get(d_str, {})
            if src.get('eicp'):
                g['eicp'] = g['eicp'] + src['eicp']
            else:
                missing.append(f'EICP {label} ({d_str})')

        for label, d_str in (('thứ 7', sat_str), ('CN', sun_str)):
            src = groups.get(d_str, {})
            if src.get('core'):
                g['core'] = g['core'] + src['core']
            else:
                missing.append(f'Core {label} ({d_str})')

        if log:
            log(f'[{mon_str}] Chấm thứ 2 — gộp thêm dữ liệu cuối tuần (EICP thứ 6-7-CN, Core thứ 7-CN).')
            if missing:
                log(
                    f'[{mon_str}] CẢNH BÁO — thiếu: {", ".join(missing)}. '
                    'Kết quả thứ 2 có thể sót giao dịch chờ đi kênh cuối tuần.'
                )
