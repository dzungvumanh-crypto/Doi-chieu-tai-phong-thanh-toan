"""Nhận dạng loại file và nhóm theo ngày cho pipeline ILO1000."""

import re
import zipfile
from pathlib import Path


# ── Regex nhận dạng date từ tên file ─────────────────────────────────────────
_RE_GL02_CSV = re.compile(r'gl02[_\s](\d{8})', re.IGNORECASE)
_RE_GL02_ZIP = re.compile(r'GL02[_\s](\d{8})', re.IGNORECASE)
_RE_PHUB     = re.compile(r'_(\d{8})\d{6}\.xlsx', re.IGNORECASE)
_RE_EICP_DAY = re.compile(r'eicp\s+(\d+)', re.IGNORECASE)


def detect_file_type(path: Path) -> str:
    """Trả về: 'hub' | 'citad' | 'eicp' | 'core_csv' | 'core_zip' | 'unknown'."""
    name = path.name
    low  = name.lower()

    if low.startswith('phub_') and low.endswith('.xlsx'):
        return 'hub'
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
    if file_type == 'hub':
        m = _RE_PHUB.search(name)
        return m.group(1) if m else None
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

    def _get_or_create(date_str: str) -> dict:
        if date_str not in groups:
            groups[date_str] = {'hub': [], 'citad': [], 'eicp': [], 'core': []}
        return groups[date_str]

    for p in paths:
        ft = detect_file_type(p)
        if ft == 'unknown':
            if log:
                log(f'  [SKIP] Không nhận dạng được: {p.name}')
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
        if ft == 'hub':
            g['hub'].append(p)
        elif ft == 'citad':
            g['citad'].append(p)
        elif ft in ('core_csv', 'core_zip'):
            g['core'].append(p)

    # Gán EICP vào ngày tương ứng (chỉ dùng day number, bỏ qua năm/tháng)
    for p, day_num in eicp_pending:
        matched = False
        for date_str in groups:
            if int(date_str[6:8]) == day_num:
                groups[date_str]['eicp'].append(p)
                matched = True
                break
        if not matched and log:
            log(f'  [WARN] Không gán được ngày cho EICP: {p.name} (ngày {day_num})')

    # Hub không khớp ngày → gán vào group nào có đủ citad+core nhất
    if groups:
        # Thu thập hub files từ các group không có citad/core
        hub_only_groups = {d: g for d, g in groups.items() if g['hub'] and not g['citad'] and not g['core']}
        full_groups = {d: g for d, g in groups.items() if not g['hub'] and (g['citad'] or g['core'])}

        if hub_only_groups and full_groups:
            # Lấy hub file(s) từ group hub-only, gán vào group có dữ liệu nhất
            best_full = max(full_groups.keys(), key=lambda d: len(full_groups[d]['citad']) + len(full_groups[d]['core']))
            for d, g in hub_only_groups.items():
                groups[best_full]['hub'].extend(g['hub'])
                if log:
                    names = ', '.join(p.name for p in g['hub'])
                    log(f'  [INFO] Gán hub ({names}) vào nhóm {best_full} (ngày hub khác: {d})')
            # Xóa group hub-only rỗng
            for d in hub_only_groups:
                del groups[d]

    return groups
