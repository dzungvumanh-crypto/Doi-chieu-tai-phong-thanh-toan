"""Orchestrator: đối chiếu 1 ngày cho toàn bộ `RECONCILE_UNITS`.

Ngày được tự nhận diện từ tên file HUB (`doichieugd_YYYYMMDD__NN_DEN_9999_N.zip`)
có trong thư mục đầu vào — không dựa vào tên thư mục (không đáng tin, VD `21.8`).
"""

import re
import threading
from pathlib import Path
from typing import Callable

from backend.services.doi_chieu_song_phuong_common import do_thoi_gian

from .config import RECONCILE_UNITS
from .load_hub import filter_before_reconcile, hub_filename, load_hub_zip
from .load_kenh import find_kenh_path, kenh_filename, load_kenh_file
from .process import (
    check_unexpected_one_sided, classify_kenh_hub_den, dem_lech_tien_tren_khop, match_unit,
    summarize_unit,
)

_HUB_NAME_RE = re.compile(r"doichieugd_(\d{8})__\d{2}_DEN_9999_N\.zip")


def detect_ngay(input_dir: str | Path) -> str | None:
    """Tìm ngày (YYYYMMDD) từ tên file HUB đầu tiên khớp mẫu trong thư mục."""
    for p in Path(input_dir).iterdir():
        m = _HUB_NAME_RE.match(p.name)
        if m:
            return m.group(1)
    return None


def main_from_dir(
    input_dir: str | Path,
    ngay: str | None = None,
    ma_nh: str | None = None,
    log_callback: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    hub_path_override: Path | None = None,
) -> dict | None:
    """Đối chiếu 1 ngày, các đơn vị trong `RECONCILE_UNITS`.

    `ma_nh`: lọc chỉ chạy đơn vị của 1 ngân hàng (VD dùng bởi service điều phối
    Kênh↔Hub + Hub↔Core hợp nhất, quyết định 2026-08-28 — mỗi lần chạy 1 NH). Mặc định
    `None` giữ nguyên hành vi cũ — chạy toàn bộ `RECONCILE_UNITS`.

    `hub_path_override`: dùng thẳng đường dẫn HUB đã resolve sẵn ở tầng gọi (glob-tolerant, xem
    `doi_chieu_song_phuong_kenh_core_service.py`) thay vì tự dò lại bằng tên chính xác — tránh 2
    lần resolve HUB lệch nhau khi file HUB không đúng tên chuẩn (đã dính lỗi CSV CORE/OSB cùng
    dạng). Chỉ có ý nghĩa khi `ma_nh` đã lọc còn 1 giá trị (mọi đơn vị của NH đó dùng chung 1 file
    HUB); mặc định `None` giữ nguyên hành vi tự dò cũ cho caller độc lập/test hiện có.

    Trả `{"ngay": ..., "don_vi": [...]}` — mỗi phần tử `don_vi` có `trang_thai`
    ("ok" | "thieu_file_hub" | "thieu_file_kenh"). Khi "ok", kèm `match_result`
    (dict DataFrame từ `process.match_unit`), `kenh_df`, `summary` (có `chenh_so_mon`/
    `chenh_so_tien` — số tuyệt đối, KHÔNG dùng %, xem `SKILL.md`/quy tắc dự án: 1 lệnh
    chiếm tỉ lệ % rất nhỏ vẫn có thể mang giá trị hàng nghìn tỷ), `lech_tien`,
    `canh_bao_trang_thai`, `chi_tiet` (dict `{"hub":..., "kenh":...}` từ
    `process.classify_kenh_hub_den` — file gốc gắn cột trạng thái từng dòng, theo v3).

    Trả None nếu bị huỷ giữa chừng hoặc không xác định được ngày.
    """
    log = log_callback or (lambda msg: None)
    cancel = cancel_event or threading.Event()
    input_dir = Path(input_dir)

    ngay = ngay or detect_ngay(input_dir)
    if not ngay:
        log("[LỖI] Không tìm thấy file HUB (doichieugd_*_DEN_9999_N.zip) trong thư mục — "
            "không xác định được ngày đối chiếu.")
        return None
    log(f"Ngày đối chiếu: {ngay}")

    units = [u for u in RECONCILE_UNITS if ma_nh is None or u["ma_nh"] == ma_nh]
    don_vi_results = []
    for unit in units:
        if cancel.is_set():
            return None
        ma_nh, loai = unit["ma_nh"], unit["loai"]
        nhan = f"[{ma_nh}-{loai}]"

        hub_path = hub_path_override or (input_dir / hub_filename(ngay, ma_nh))
        if not hub_path.exists():
            log(f"{nhan} BỎ QUA — thiếu file HUB: {hub_path.name}")
            don_vi_results.append({"ma_nh": ma_nh, "loai": loai, "ngay": ngay, "trang_thai": "thieu_file_hub"})
            continue

        kenh_path = find_kenh_path(input_dir, ma_nh, loai)
        if kenh_path is None:
            log(f"{nhan} BỎ QUA — thiếu file kênh: {kenh_filename(ma_nh, loai)} "
                f"(đã thử cả tên đảo thứ tự {ma_nh}/{loai})")
            don_vi_results.append({"ma_nh": ma_nh, "loai": loai, "ngay": ngay, "trang_thai": "thieu_file_kenh"})
            continue

        log(f"{nhan} Đang đọc HUB ({hub_path.name})...")
        with do_thoi_gian(log, f"{nhan} đọc+parse HUB"):
            hub_raw = load_hub_zip(hub_path.read_bytes(), log=lambda msg, nhan=nhan: log(f"{nhan} {msg}"))
            hub = filter_before_reconcile(hub_raw, log=lambda msg, nhan=nhan: log(f"{nhan} {msg}"))
        if cancel.is_set():
            return None

        log(f"{nhan} Đang đọc kênh ({kenh_path.name})...")
        with do_thoi_gian(log, f"{nhan} đọc file kênh"):
            kenh_df = load_kenh_file(str(kenh_path), ma_nh, loai)
        if cancel.is_set():
            return None

        log(f"{nhan} Đang so khớp...")
        mr = match_unit(hub, kenh_df, loai)

        # ── Bất biến bắt buộc ──
        assert len(mr["matched_hub"]) + len(mr["only_hub"]) == len(mr["hub"]), \
            f"{nhan} Bất biến HUB vỡ (matched+only != tổng)"
        assert len(mr["matched_kenh"]) + len(mr["only_kenh"]) == len(kenh_df), \
            f"{nhan} Bất biến KÊNH vỡ (matched+only != tổng)"

        canh_bao = check_unexpected_one_sided(mr)
        if canh_bao:
            log(f"{nhan} [CẢNH BÁO] Trạng thái chỉ-hub ngoài dự kiến (khác RJCT): {canh_bao}")

        summary = summarize_unit(mr, kenh_df, ma_nh, loai)
        lech = dem_lech_tien_tren_khop(mr, kenh_df, loai)
        if lech["so_cap_lech"]:
            log(f"{nhan} [CẢNH BÁO] {lech['so_cap_lech']} cặp khớp khoá nhưng LỆCH tiền!")

        log(f"{nhan} Khớp {len(mr['matched_hub']):,}/{len(mr['hub']):,} dòng — "
            f"chỉ-hub {len(mr['only_hub']):,}, chỉ-kênh {len(mr['only_kenh']):,} — "
            f"chênh số món {summary['chenh_so_mon']:+,}, chênh số tiền {summary['chenh_so_tien']:+,} đồng")

        log(f"{nhan} Đang dựng file chi tiết (gắn cột trạng thái từng dòng)...")
        chi_tiet = classify_kenh_hub_den(hub_raw, kenh_df, loai)

        don_vi_results.append({
            "ma_nh": ma_nh, "loai": loai, "ngay": ngay, "trang_thai": "ok",
            "match_result": mr, "kenh_df": kenh_df,
            "summary": summary, "lech_tien": lech,
            "canh_bao_trang_thai": canh_bao,
            "chi_tiet": chi_tiet,
        })

    log(f"Hoàn thành đối chiếu ngày {ngay}.")
    return {"ngay": ngay, "don_vi": don_vi_results}
