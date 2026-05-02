"""
Dịch vụ gom tập chứng từ hậu kiểm

Thuật toán (theo ngày, cross-date packing):
1. Lấy tổng chứng từ ngày n. Nếu > ngưỡng → chia ngày đó thành nhiều tập.
2. Nếu tổng ngày n ≤ ngưỡng → cộng dồn ngày n+1.
3. Nếu tổng tích lũy > ngưỡng HOẶC số dòng user > 16 → đóng tập, bắt đầu tập mới.

Ngưỡng chứng từ: 350 bình thường; 300 khi tập có ≥ 5 ngày khác nhau.
Giới hạn dòng: tối đa 16 dòng user trên bìa (8 dòng × 2 cột).
User lớn (> 350 CT/ngày): xếp sau các user bình thường, lấp đầy chỗ còn lại
trong tập cuối, rồi tạo tập mới 350, tập mới tiếp theo cho phần dư.
"""
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import date
import math


MAX_SHEETS_NORMAL       = 350   # giới hạn chứng từ mặc định
MAX_SHEETS_MANY_DATES   = 300   # giới hạn khi tập có ≥ DATE_THRESHOLD ngày
DATE_THRESHOLD          = 5     # số ngày để áp dụng giới hạn chặt hơn
MAX_UNITS               = 16    # tối đa 16 dòng user trên bìa (8 × 2 cột)


@dataclass
class EntryUnit:
    """Đơn vị nguyên tử: 1 user trong 1 ngày GD"""
    entry_ids: List[int]
    source_user_id: int
    user_code: str
    full_name: Optional[str]
    transaction_date: date
    sheet_count: int
    is_large: bool = False  # True nếu user bị cắt do vượt ngưỡng (xếp cuối bìa)


@dataclass
class BundleResult:
    """Kết quả 1 tập"""
    sequence: int
    total_bundles_in_group: int
    total_sheets: int
    units: List[EntryUnit] = field(default_factory=list)
    label_seq: int = 1
    label_total: int = 1


def to_roman(n: int) -> str:
    val  = [1000,900,500,400,100,90,50,40,10,9,5,4,1]
    syms = ['M','CM','D','CD','C','XC','L','XL','X','IX','V','IV','I']
    result = ''
    for i in range(len(val)):
        while n >= val[i]:
            result += syms[i]
            n -= val[i]
    return result


def bundle_label(seq: int, total: int) -> str:
    return f"{to_roman(seq)}/{to_roman(total)}"


def group_entries_by_date(entries: List[EntryUnit]) -> Dict[date, List[EntryUnit]]:
    groups: Dict[date, List[EntryUnit]] = {}
    for e in entries:
        groups.setdefault(e.transaction_date, []).append(e)
    return dict(sorted(groups.items()))


def _effective_max_sheets(n_dates: int) -> int:
    return MAX_SHEETS_MANY_DATES if n_dates >= DATE_THRESHOLD else MAX_SHEETS_NORMAL


def _make_sub_unit(source: EntryUnit, sheet_count: int, carry_ids: bool) -> EntryUnit:
    return EntryUnit(
        entry_ids=source.entry_ids if carry_ids else [],
        source_user_id=source.source_user_id,
        user_code=source.user_code,
        full_name=source.full_name,
        transaction_date=source.transaction_date,
        sheet_count=sheet_count,
        is_large=True,
    )


def _greedy_sheet_pack(units: List[EntryUnit], max_sheets: int) -> List[List[EntryUnit]]:
    """First Fit Decreasing — mỗi bin được đảm bảo ≤ max_sheets."""
    sorted_units = sorted(units, key=lambda u: u.sheet_count, reverse=True)
    bins: List[List[EntryUnit]] = []
    bin_totals: List[int] = []

    for unit in sorted_units:
        placed = False
        for i, total in enumerate(bin_totals):
            if total + unit.sheet_count <= max_sheets:
                bins[i].append(unit)
                bin_totals[i] += unit.sheet_count
                placed = True
                break
        if not placed:
            bins.append([unit])
            bin_totals.append(unit.sheet_count)

    return bins


def pack_date_group(
    units: List[EntryUnit],
    max_sheets: int = MAX_SHEETS_NORMAL,
    max_units: int = MAX_UNITS,
) -> List[List[EntryUnit]]:
    """
    Chia units của 1 ngày thành các tập, tuân theo 2 ràng buộc:
      - Tổng chứng từ mỗi tập ≤ max_sheets
      - Số dòng user mỗi tập ≤ max_units

    Với user lớn (sheet_count > max_sheets):
      1. Pack tất cả user bình thường trước (FFD).
      2. User lớn lấp đầy phần còn trống của tập cuối, rồi tạo tập mới 350,
         tập mới tiếp theo cho phần dư — cho đến hết.
         Số chứng từ hiển thị trên mỗi tập đúng theo phần được cắt.
    """
    normal = [u for u in units if u.sheet_count <= max_sheets]
    large  = [u for u in units if u.sheet_count >  max_sheets]

    # ── Pack user bình thường ──────────────────────────────────────────────────
    if not normal:
        bins: List[List[EntryUnit]] = []
        bin_totals: List[int] = []
    elif sum(u.sheet_count for u in normal) <= max_sheets and len(normal) <= max_units:
        bins = [list(normal)]
        bin_totals = [sum(u.sheet_count for u in normal)]
    elif len(normal) > max_units:
        bins = []
        for i in range(0, len(normal), max_units):
            chunk = normal[i : i + max_units]
            if sum(u.sheet_count for u in chunk) <= max_sheets:
                bins.append(chunk)
            else:
                bins.extend(_greedy_sheet_pack(chunk, max_sheets))
        bin_totals = [sum(u.sheet_count for u in b) for b in bins]
    else:
        bins = _greedy_sheet_pack(normal, max_sheets)
        bin_totals = [sum(u.sheet_count for u in b) for b in bins]

    if not large:
        return bins or [units]

    # ── Phân bổ từng user lớn: lấp đầy tập cuối → tập mới 350 → phần dư ─────
    for lu in large:
        remaining = lu.sheet_count
        ids_given = False          # entry_ids chỉ gắn vào lần đầu tiên

        # Lấp đầy chỗ trống trong tập cuối (nếu có)
        if bins and len(bins[-1]) < max_units:
            space = max_sheets - bin_totals[-1]
            if space > 0:
                portion = min(space, remaining)
                bins[-1].append(_make_sub_unit(lu, portion, carry_ids=True))
                bin_totals[-1] += portion
                remaining -= portion
                ids_given = True

        # Tạo tập mới cho phần còn lại, mỗi tập tối đa max_sheets
        while remaining > 0:
            portion = min(max_sheets, remaining)
            bins.append([_make_sub_unit(lu, portion, carry_ids=not ids_given)])
            bin_totals.append(portion)
            remaining -= portion
            ids_given = True

    return [b for b in bins if b]


def generate_bundles_for_entries(
    entries_data: List[dict],
) -> List[BundleResult]:
    """Tạo danh sách BundleResult theo thuật toán cross-date packing."""
    if not entries_data:
        return []

    # Bước 1: Gom theo (source_user_id, transaction_date) → EntryUnit nguyên tử
    unit_map: Dict[Tuple[int, date], EntryUnit] = {}
    for e in entries_data:
        key = (e["source_user_id"], e["transaction_date"])
        if key not in unit_map:
            unit_map[key] = EntryUnit(
                entry_ids=[e["id"]],
                source_user_id=e["source_user_id"],
                user_code=e["user_code"],
                full_name=e.get("full_name"),
                transaction_date=e["transaction_date"],
                sheet_count=e["sheet_count"],
            )
        else:
            unit_map[key].entry_ids.append(e["id"])
            unit_map[key].sheet_count += e["sheet_count"]

    by_date = group_entries_by_date(list(unit_map.values()))

    results: List[BundleResult] = []
    buf_units: List[EntryUnit] = []
    buf_total  = 0
    buf_dates: set = set()
    seq = 1

    def _flush_buffer():
        nonlocal seq, buf_units, buf_total, buf_dates
        if buf_units:
            results.append(BundleResult(
                sequence=seq,
                total_bundles_in_group=0,
                total_sheets=buf_total,
                units=list(buf_units),
            ))
            seq += 1
        buf_units, buf_total, buf_dates = [], 0, set()

    def _emit_single_day(day_units: List[EntryUnit]):
        nonlocal seq
        bins = pack_date_group(day_units, MAX_SHEETS_NORMAL, MAX_UNITS)
        local_total = len(bins)
        for local_seq, bin_units in enumerate(bins, 1):
            results.append(BundleResult(
                sequence=seq,
                total_bundles_in_group=0,
                total_sheets=sum(u.sheet_count for u in bin_units),
                units=bin_units,
                label_seq=local_seq,
                label_total=local_total,
            ))
            seq += 1

    for txn_date in sorted(by_date.keys()):
        day_units  = by_date[txn_date]
        day_total  = sum(u.sheet_count for u in day_units)
        day_unit_count = len(day_units)

        new_dates      = buf_dates | {txn_date}
        new_total      = buf_total + day_total
        new_unit_count = len(buf_units) + day_unit_count
        eff_max        = _effective_max_sheets(len(new_dates))

        if new_total > eff_max or new_unit_count > MAX_UNITS:
            _flush_buffer()
            if day_total > MAX_SHEETS_NORMAL or day_unit_count > MAX_UNITS:
                _emit_single_day(day_units)
            else:
                buf_units = list(day_units)
                buf_total = day_total
                buf_dates = {txn_date}
        else:
            buf_units.extend(day_units)
            buf_total  = new_total
            buf_dates  = new_dates

    _flush_buffer()

    n = len(results)
    for r in results:
        r.total_bundles_in_group = n

    return results
