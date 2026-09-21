"""Nhận dạng loại file và nhóm theo ngày cho pipeline ILO1000."""

import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

from backend.services.lich_lam_viec import LICH_RONG, LichLamViec, la_ngay_lam_viec
from .config import OSB_COL_MA_GD, OSB_COL_CN_THUC_HIEN
from .load_osb import _SHEET_NAME as _OSB_SHEET_NAME


# ── Regex nhận dạng date từ tên file ─────────────────────────────────────────
_RE_GL02_CSV = re.compile(r'gl02[_\s](\d{8})', re.IGNORECASE)
_RE_GL02_ZIP = re.compile(r'GL02[_\s](\d{8})', re.IGNORECASE)
_RE_GL02_RANGE = re.compile(r'gl02[_\s](\d{8,16})', re.IGNORECASE)
_RE_EICP_DAY = re.compile(r'eicp\s+(\d+)', re.IGNORECASE)


def detect_file_type(path: Path) -> str:
    """Trả về: 'hub' | 'citad' | 'eicp' | 'osb' | 'core_csv' | 'core_zip' |
    'core_thua' | 'osb_thua' | 'unknown'.

    'core_thua'/'osb_thua': pool tồn đọng xuyên batch (xem
    `process.py` phần "Pool tồn đọng xuyên batch") — người chấm tự nạp lại
    file thừa cũ làm input phụ, giống hub/citad/core/osb hiện có. Nhận dạng
    theo NỘI DUNG (có cả 2 cột 'TT' và 'Đối chiếu' cùng lúc, bên cạnh cột gốc
    Core/OSB) chứ KHÔNG theo tên file — đúng nguyên tắc chung của module này
    (Hub/Citad/OSB cũng không tin tên file, xem comment `group_files_by_date()`
    bên dưới); phải kiểm TRƯỚC các rule theo tên/đuôi file khác, vì 1 file
    pool có thể trùng đuôi `.xlsx` với hub/osb.

    'osb': nhận theo 2 đường — (1) tên file bắt đầu bằng "osb" (quy ước cũ,
    vẫn giữ làm fallback cho file lỗi/không đọc được và các file mẫu tay cũ),
    HOẶC (2) nội dung có đủ 2 cột `OSB_COL_MA_GD`/`OSB_COL_CN_THUC_HIEN` (file
    OSB gốc thật xuất từ IPCAS, tên kiểu "DULIEUCHITIETHACHTOAN_..." không
    bao giờ bắt đầu bằng "osb" — xem `_sniff_osb_xlsx()`).
    """
    name = path.name
    low  = name.lower()

    if low.endswith('.xlsx'):
        pool_kind = _sniff_pool_xlsx(path)
        if pool_kind:
            return pool_kind
        if _sniff_osb_xlsx(path):
            return 'osb'

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


def _scan_first_rows(path: Path, max_scan: int = 10, sheet_name=0):
    """Đọc `max_scan` dòng đầu 1 sheet, KHÔNG header — dùng chung cho
    `_sniff_pool_xlsx()`/`find_pool_header_row()`/`_sniff_osb_xlsx()`.

    `sheet_name=0` (mặc định, sheet đầu tiên) đủ cho pool tồn đọng (file
    người chấm tự dựng tay, luôn chỉ 1 sheet). File OSB gốc thật có thể có
    NHIỀU sheet — truyền tên sheet cụ thể khi cần (xem `_sniff_osb_xlsx()`).

    Dùng `engine='calamine'`, KHÔNG `openpyxl` (kể cả `read_only=True`): file
    xlsx thật xuất từ hệ thống lõi của dự án (Citad/Core/OSB — pool tồn đọng
    được dựng tay TỪ các export đó) có thể mang tag `<dimension ref="A1"/>`
    sai lệch bất kể số dòng thật — `openpyxl(read_only=True)` tin thẳng tag
    đó và ÂM THẦM chỉ đọc được dòng đầu tiên, không lỗi không cảnh báo (đã
    tái phát nhiều lần ở các module đối chiếu khác của dự án, xem skill
    `bank-reconciliation` mục "Reading a required xlsx file"). Trả None nếu
    đọc lỗi (file hỏng, không phải xlsx thật, sheet không tồn tại, v.v.).
    """
    try:
        import pandas as pd
        return pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=max_scan, engine='calamine')
    except Exception:
        return None


# Cột đánh dấu pool tồn đọng — người chấm mỗi khi tự dựng/sửa lại file có
# thể đặt tên khác nhau cho cùng 1 khái niệm "đã đối chiếu chưa". Xác nhận
# thật 2026-09-15: file "Core thua ngay 11.9.xlsx" (bắt nguồn từ chính file
# chương trình xuất ra, có 'Đối chiếu') sau khi người chấm chỉnh sửa lại có
# cột đổi tên thành "Cham" — không nhận ra được nếu chỉ so khớp đúng 1 chuỗi
# 'Đối chiếu'. Nhận theo NỘI DUNG, không theo tên file — xem
# `feedback_nhan_dien_file_theo_noi_dung` (memory dự án): mỗi người chấm đặt
# tên/nhãn khác nhau, phải xây bảng quy đổi riêng, không cứng 1 chuỗi.
_DOI_CHIEU_MARKER_ALIASES = {'đối chiếu', 'doi chieu', 'cham', 'chấm'}


def _is_doi_chieu_marker(text) -> bool:
    return isinstance(text, str) and text.strip().lower() in _DOI_CHIEU_MARKER_ALIASES


def _sniff_pool_xlsx(path: Path) -> str | None:
    """Quét 10 dòng đầu sheet đầu tiên tìm cột đánh dấu "đã đối chiếu chưa"
    (xem `_DOI_CHIEU_MARKER_ALIASES`) — chỉ pool tồn đọng mới có cột này
    (Core/OSB gốc không có). Không giả định header nằm ở dòng cố định nào
    (mỗi lần người chấm tự dựng file có thể khác nhau) — gộp text của CẢ 10
    dòng lại rồi tra thành viên, không cần định vị đúng dòng header thật.
    """
    df = _scan_first_rows(path)
    if df is None:
        return None

    headers: set[str] = set()
    for val in df.to_numpy().flatten():
        if isinstance(val, str):
            headers.add(val.strip())

    if not any(_is_doi_chieu_marker(h) for h in headers):
        return None
    if 'TRDATE' in headers and 'REFERENCE' in headers:
        return 'core_thua'
    if 'Mã giao dịch' in headers or 'CN thực hiện' in headers:
        return 'osb_thua'
    return None


def _sniff_osb_xlsx(path: Path) -> bool:
    """Nhận diện file OSB gốc (bảng 510202, xuất từ IPCAS) theo NỘI DUNG —
    tên file thật do IPCAS xuất ra (VD "DULIEUCHITIETHACHTOAN_...xlsx")
    không bao giờ bắt đầu bằng "osb" nên rule tên file cũ bỏ sót hoàn toàn.
    So khớp không phân biệt hoa/thường/khoảng trắng thừa (`strip().lower()`)
    — dự án đã 2 lần gặp thật hiện tượng lệch casing tên cột giữa các lần
    xuất file khác nhau ('map dc' vs 'Map dc', 'Cham' vs 'Đối chiếu').

    Quét sheet `_OSB_SHEET_NAME` ('Sheet 1', cùng tên `load_osb._SHEET_NAME`
    dùng để đọc dữ liệu thật) TRƯỚC, rơi về sheet đầu tiên nếu workbook không
    có sheet đó — xác nhận thật 15/09/2026: file OSB gốc IPCAS xuất ra có 2
    sheet, 'Config' (bảng chú giải mã, KHÔNG có header thật) đứng TRƯỚC
    'Sheet 1' (chứa header thật) trong thứ tự sheet. Quét mù sheet đầu tiên
    (0) sẽ luôn đọc nhầm 'Config' và không bao giờ nhận ra được file OSB thật.
    """
    df = _scan_first_rows(path, sheet_name=_OSB_SHEET_NAME)
    if df is None:
        df = _scan_first_rows(path)
    if df is None:
        return False
    headers = {v.strip().lower() for v in df.to_numpy().flatten() if isinstance(v, str)}
    required = {OSB_COL_MA_GD.lower(), OSB_COL_CN_THUC_HIEN.lower()}
    return required.issubset(headers)


def find_pool_header_row(path: Path, max_scan: int = 10) -> int | None:
    """Dòng header (0-based, dùng thẳng cho `pandas.read_excel(header=...)`)
    của 1 file pool tồn đọng — dòng ĐẦU TIÊN (trong `max_scan` dòng) có chứa
    cột đánh dấu "đã đối chiếu chưa" (xem `_DOI_CHIEU_MARKER_ALIASES`). Không
    giả định vị trí cố định: người chấm tự dựng file này bằng tay, cấu trúc
    có thể khác nhau mỗi lần (xác nhận thật: file "Core thừa" có header ở
    dòng 1, file "OSB thừa" có 1 dòng trống trước header). Trả None nếu
    không tìm thấy hoặc file lỗi.
    """
    df = _scan_first_rows(path, max_scan)
    if df is None:
        return None
    for i in range(len(df)):
        if any(_is_doi_chieu_marker(v) for v in df.iloc[i].values):
            return i
    return None


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


def extract_gl02_date_range(path: Path) -> list[str]:
    """
    Trích TOÀN BỘ các ngày YYYYMMDD từ tên file GL02 (core_csv/core_zip).

    8 chữ số = 1 ngày. 16 chữ số = ngày ĐẦU + ngày CUỐI ghép liền (file GL02
    gộp nhiều ngày liên tiếp vào 1 file) — xác nhận dữ liệu thật: file
    "1000_gl02_2026090520260908.csv" (16 số = 20260905+20260908) chứa TRDATE
    cả 4 ngày 05,06,07,08/09 trộn lẫn bên trong (đúng như comment cũ ở
    `_filter_core_by_date()`/`_dedup_core_batch()` đã ghi nhận cho case 2
    ngày "1000_gl02_2026081120260812.csv").

    Trước đây chỉ lấy 8 số ĐẦU (ngày bắt đầu) làm khóa nhóm duy nhất — nếu
    không có file GL02/zip nào khác đặt tên đúng ngày giữa khoảng (VD Thứ 2
    07/09 không có file GL02 riêng, chỉ nằm lẫn trong file 05-08/09 này) thì
    ngày đó KHÔNG BAO GIỜ có nhóm để xử lý — dữ liệu Core của nó biến mất
    khỏi MỌI file kết quả, không log, không lỗi. Xác nhận thật 10/09/2026:
    47.966/110.481 dòng Core (43%, gồm cả nguyên Thứ 2 07/09 — ngày làm việc
    đầy đủ) mất trắng theo cách cũ trên lô dữ liệu 5-8.9.2026.

    Trả về list rỗng nếu không nhận dạng được tên file.
    """
    m = _RE_GL02_RANGE.search(path.name)
    if not m:
        return []
    digits = m.group(1)
    if len(digits) == 8:
        return [digits]
    if len(digits) != 16:
        # Độ dài lạ (vd lẫn số khác trong tên file) — an toàn nhất là lấy 8 số
        # đầu như hành vi cũ, không đoán thêm.
        return [digits[:8]]
    start_s, end_s = digits[:8], digits[8:]
    try:
        start_d = date(int(start_s[:4]), int(start_s[4:6]), int(start_s[6:8]))
        end_d = date(int(end_s[:4]), int(end_s[4:6]), int(end_s[6:8]))
    except ValueError:
        return [start_s]
    if end_d < start_d:
        return [start_s]
    out: list[str] = []
    d = start_d
    while d <= end_d:
        out.append(d.strftime('%Y%m%d'))
        d += timedelta(days=1)
    return out


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


def group_files_by_date(paths: list[Path], log=None, lich: LichLamViec = LICH_RONG) -> dict[str, dict]:
    """
    Phân loại và nhóm file theo ngày.
    Trả về: {yyyymmdd: {hub: Path, citad: [Path], eicp: [Path], core: [Path]}}

    `lich`: lịch nghỉ lễ/làm bù thật của dự án (xem `lich_lam_viec.py`), dùng để
    tính đúng cửa sổ gộp carryover (xem `carryover_window()`) — mặc định
    `LICH_RONG` (chỉ tính T7/CN, không biết ngày lễ) để tương thích ngược cho
    caller chưa truyền lịch thật.
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

        if ft == 'eicp':
            day_num = _eicp_day(p)
            if day_num is not None:
                eicp_pending.append((p, day_num))
            elif log:
                log(f'  [WARN] EICP không trích được ngày: {p.name}')
            continue

        if ft in ('core_csv', 'core_zip'):
            # Tên file có thể ghi 1 ngày HOẶC 1 khoảng ngày (16 số = ngày đầu+
            # cuối ghép liền) — xem extract_gl02_date_range(). Gán file này
            # vào MỌI nhóm ngày trong khoảng, không chỉ ngày đầu, để ngày
            # KHÔNG có file GL02/zip riêng của chính nó (vd nằm giữa khoảng)
            # vẫn có nhóm để xử lý thay vì mất trắng.
            date_strs = extract_gl02_date_range(p)
            if not date_strs:
                if log:
                    log(f'  [WARN] Không trích được ngày từ: {p.name}')
                continue
            for ds in date_strs:
                _get_or_create(ds)['core'].append(p)
            if log and len(date_strs) > 1:
                log(
                    f'  [INFO] {p.name} chứa dải ngày {date_strs[0]}–{date_strs[-1]} '
                    f'— gán vào {len(date_strs)} nhóm ngày.'
                )
            continue

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
    eicp_unmatched: list[tuple[Path, int]] = []
    for p, day_num in eicp_pending:
        matched = False
        for date_str in groups:
            if int(date_str[6:8]) == day_num:
                groups[date_str]['eicp'].append(p)
                matched = True
                break
        if not matched:
            eicp_unmatched.append((p, day_num))

    # EICP không khớp nhóm ngày nào có sẵn (VD tên file không theo công thức chuẩn,
    # hoặc ngày đó không có Citad/Core riêng — chỉ tồn tại qua carryover thứ 2)
    # → gán vào group có đủ citad+core nhất, không âm thầm bỏ dữ liệu. (Hub
    # từng có cơ chế fallback tương tự — đã bỏ, Hub giờ là pool lọc theo dòng.)
    # `eicp_fallback_days`: {nhóm đích: {số ngày (DD) đã gán vào đây theo đường
    # này}} — truyền cho merge_previous_day_eicp()/merge_monday_carryover() bên
    # dưới để 2 hàm đó biết dữ liệu T-1 đã có mặt qua đường này, tránh báo
    # "CẢNH BÁO — thiếu EICP T-1" giả khi nhóm ngày T-1 không tồn tại trong batch
    # (VD batch chỉ gửi 1 ngày kèm EICP T-1 rời, không có Core/GL02 riêng cho
    # T-1 — xác nhận thật batch 18.9.2026: "eicp 17.09.XLS" không có nhóm ngày
    # 17/9 nào để khớp, rơi vào đây, rồi merge_previous_day_eicp() lại không
    # biết nên vẫn báo thiếu dù dữ liệu đã nằm trong nhóm 18/9 rồi).
    eicp_fallback_days: dict[str, set[int]] = {}
    if eicp_unmatched and groups:
        best_group = max(groups.keys(), key=lambda d: len(groups[d]['citad']) + len(groups[d]['core']))
        for p, day_num in eicp_unmatched:
            groups[best_group]['eicp'].append(p)
            eicp_fallback_days.setdefault(best_group, set()).add(day_num)
            if log:
                log(f'  [INFO] Gán EICP ({p.name}) vào nhóm {best_group} (không khớp ngày nào có sẵn)')
    elif eicp_unmatched and log:
        for p, _ in eicp_unmatched:
            log(f'  [WARN] Không gán được ngày cho EICP: {p.name}')

    # Chạy trước merge_monday_carryover: khi thứ 2 (hoặc ngày đi làm lại sau kỳ
    # nghỉ dài) tự gộp thêm dữ liệu ngày nghỉ, KHÔNG được để việc đó "lan" ngược
    # vào ngày kế tiếp (ngày kế tiếp chỉ cần EICP gốc của phiên trước, không cần
    # cả phần phiên trước đã tự gộp thêm).
    merge_previous_day_eicp(groups, log, lich, eicp_fallback_days)
    merge_monday_carryover(groups, log, lich, eicp_fallback_days)

    return groups


def _parse_date(date_str: str) -> date:
    return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def carryover_window(ngay: date, lich: LichLamViec = LICH_RONG) -> list[date]:
    """
    Cửa sổ ngày cần gộp EICP/Core cho phiên chấm `ngay`. LUÔN gồm T-1 (cutoff
    thường ngày: lệnh vào sau giờ cắt của T-1 chờ sang phiên T, kể cả khi T-1
    là ngày làm việc bình thường). Nếu T-1 KHÔNG phải ngày làm việc (cuối tuần/
    lễ), đi lùi tiếp qua toàn bộ chuỗi ngày nghỉ liên tiếp đó VÀ gồm luôn ngày
    làm việc gần nhất trước chuỗi (phiên thật gần nhất, cũng có cutoff riêng
    vào T) — tổng quát hoá `_osb_carryover_days()`/`merge_monday_carryover()`
    cũ (chỉ cứng đúng 3 ngày thứ 6-7-CN) cho MỌI kỳ nghỉ dài bao nhiêu ngày
    cũng được, miễn `lich` (từ `tai_lich()`) khai đủ ngày lễ.

    `lich=LICH_RONG` (mặc định) => chỉ theo thứ Bảy/CN, hệt hành vi cũ.

    Trả về danh sách ngày, thứ tự gần nhất (T-1) trước.
    """
    days: list[date] = []
    d = ngay - timedelta(days=1)
    days.append(d)
    while not la_ngay_lam_viec(d, lich):
        d -= timedelta(days=1)
        days.append(d)
    return days


def merge_previous_day_eicp(
    groups: dict, log=None, lich: LichLamViec = LICH_RONG,
    eicp_fallback_days: dict[str, set[int]] | None = None,
) -> None:
    """
    Ngày chấm bình thường (T-1 là ngày làm việc — không phải ngay sau cuối
    tuần/nghỉ lễ, xem merge_monday_carryover() cho trường hợp đó): gộp thêm
    EICP của T-1 vào nhóm ngày T, theo đúng tài liệu gốc bước 1 ("Xuất dữ liệu
    hub gồm cần đối chiếu t và trước ngày cần chấm đối chiếu 1 ngày t-1"). Lệnh
    vào hệ thống sau giờ cutoff T-1 chuyển "chờ đi kênh" sang T — EICP của lệnh
    đó vẫn nằm trong file T-1, cần gộp vào để tra đúng Trace. Citad/Core giữ
    nguyên chỉ ngày T. COPY (không xoá khỏi nhóm T-1 gốc) — T-1 vẫn tự ra báo
    cáo riêng bình thường.

    (Hub trước đây cũng gộp ở đây theo file — đã bỏ 2026-08-19: Hub giờ là
    pool lọc theo dòng "Ngày giờ kênh trả" + cửa sổ T/T-1 ngay lúc load_hub(),
    xem pipeline.py::_run_one_day() và detect.py::group_files_by_date().)

    `eicp_fallback_days`: xem group_files_by_date() — {nhóm: {ngày đã gán EICP
    vào nhóm đó qua đường "không khớp ngày nào có sẵn"}}. Khi nhóm T-1 không
    tồn tại (không có Core/GL02 riêng cho T-1 trong batch) nhưng EICP T-1 đã
    được gán thẳng vào nhóm T qua đường đó rồi, KHÔNG báo thiếu — dữ liệu đã có.
    """
    eicp_fallback_days = eicp_fallback_days or {}

    # Chỉ áp dụng cho nhóm THỰC SỰ chấm (có Citad) — nhóm không có Citad (VD
    # thứ 7/CN đơn thuần chỉ có Core rơi vào) sẽ bị SKIP ở bước xử lý sau,
    # không cần áp T-1; quan trọng hơn: nếu vẫn áp cho chúng, danh sách eicp
    # của nhóm đó bị nối dài trước khi merge_monday_carryover đọc lại, khiến
    # dữ liệu T-1-của-T-1 bị "lan" 2 lớp vào ngày đi làm lại một cách dư thừa.
    target_keys = [
        d for d in groups
        if groups[d].get('citad') and la_ngay_lam_viec(_parse_date(d) - timedelta(days=1), lich)
    ]

    for t_str in target_keys:
        t_date = _parse_date(t_str)
        prev_str = (t_date - timedelta(days=1)).strftime('%Y%m%d')

        g = groups[t_str]
        src = groups.get(prev_str, {})

        if src.get('eicp'):
            g['eicp'] = g['eicp'] + src['eicp']
            if log:
                log(f'[{t_str}] Gộp thêm EICP của T-1 ({prev_str}).')
        elif int(prev_str[6:8]) in eicp_fallback_days.get(t_str, set()):
            if log:
                log(
                    f'[{t_str}] EICP T-1 ({prev_str}) không có nhóm ngày riêng '
                    'trong batch nhưng đã được gán thẳng vào nhóm này ở trên — không thiếu.'
                )
        elif log:
            log(
                f'[{t_str}] CẢNH BÁO — thiếu EICP T-1 ({prev_str}). '
                'Có thể sót giao dịch chờ đi kênh từ hôm trước (T-1).'
            )


def merge_monday_carryover(
    groups: dict, log=None, lich: LichLamViec = LICH_RONG,
    eicp_fallback_days: dict[str, set[int]] | None = None,
) -> None:
    """
    Ngày đi làm lại sau cuối tuần/nghỉ lễ (T-1 KHÔNG phải ngày làm việc — tên
    hàm giữ nguyên từ lúc chỉ xử lý đúng thứ 2, nay tổng quát cho MỌI kỳ nghỉ
    dài bao nhiêu ngày cũng được, xem `carryover_window()`): Citad không chạy
    phiên các ngày nghỉ nên toàn bộ lệnh "chờ đi kênh" phát sinh trong cả kỳ
    nghỉ (kể cả cutoff của phiên làm việc gần nhất trước đó) đều dồn sang phiên
    đi làm lại. Gộp thêm EICP của MỌI ngày trong cửa sổ (kể cả ngày làm việc
    cuối cùng trước kỳ nghỉ — phiên đó cũng có cutoff carryover riêng vào T) và
    Core của các ngày NGHỈ trong cửa sổ (không gộp Core của ngày làm việc cuối
    — ngày đó tự có báo cáo Core riêng của chính nó rồi). Citad giữ nguyên chỉ
    ngày T. Đây là COPY (không xoá khỏi nhóm gốc) — mỗi ngày nguồn vẫn tự ra
    báo cáo riêng bình thường.

    (Hub trước đây cũng gộp ở đây theo file — đã bỏ 2026-08-19, xem
    merge_previous_day_eicp() để biết lý do: Hub giờ là pool lọc theo dòng,
    cửa sổ carryover áp dụng ngay ở load_hub() qua pipeline.py::_osb_carryover_days().)

    `eicp_fallback_days`: xem group_files_by_date()/merge_previous_day_eicp() —
    ngày trong cửa sổ không có nhóm riêng nhưng EICP của nó đã được gán thẳng
    vào nhóm T qua đường "không khớp ngày nào có sẵn" thì không báo thiếu.
    """
    eicp_fallback_days = eicp_fallback_days or {}

    target_keys = [
        d for d in groups
        if groups[d].get('citad') and not la_ngay_lam_viec(_parse_date(d) - timedelta(days=1), lich)
    ]

    for t_str in target_keys:
        t_date = _parse_date(t_str)
        window = carryover_window(t_date, lich)

        g = groups[t_str]
        missing: list[str] = []

        for d in window:
            d_str = d.strftime('%Y%m%d')
            src = groups.get(d_str, {})
            if src.get('eicp'):
                g['eicp'] = g['eicp'] + src['eicp']
            elif int(d_str[6:8]) not in eicp_fallback_days.get(t_str, set()):
                missing.append(f'EICP {d_str}')

        for d in window:
            if la_ngay_lam_viec(d, lich):
                continue  # ngày làm việc cuối chuỗi: chỉ cutoff EICP, Core đã có báo cáo riêng
            d_str = d.strftime('%Y%m%d')
            src = groups.get(d_str, {})
            if src.get('core'):
                g['core'] = g['core'] + src['core']
            else:
                missing.append(f'Core {d_str}')

        if log:
            ngay_str = ', '.join(d.strftime('%d/%m') for d in reversed(window))
            log(f'[{t_str}] Đi làm lại sau nghỉ — gộp thêm dữ liệu các ngày {ngay_str}.')
            if missing:
                log(
                    f'[{t_str}] CẢNH BÁO — thiếu: {", ".join(missing)}. '
                    'Kết quả có thể sót giao dịch chờ đi kênh từ kỳ nghỉ.'
                )
