"""Orchestrator: đối chiếu HUB↔CORE cho 1 ngân hàng, 1 ngày T.

Dò file HUB (T, T-1, T-2, T-3) và CORE/GL02 (T, T+1, T+2, T+3) trong cả thư mục ngày lẫn thư
mục cha `dữ liệu/` — quyết định 2026-08-26: một số ngày dữ liệu được cung cấp rời (VD
`GL02_20260820_1000.zip` không có thư mục `20.8/`), không di chuyển file, code tự dò cả 2 nơi.

CORE đọc từ CSV đã phân loại sẵn nếu có (`{ma_nh}_DEN.csv`, đúng file thẻ Phân loại dữ liệu xuất
ra), chỉ giải mã lại GL02 zip khi không thấy CSV — quyết định 2026-08-28, giảm số lần phải giải
mã AES ~150-160MB (nguyên nhân MemoryError thật khi chạy nhiều NH liên tiếp, xem Implementation-
notes.html card 91).
"""

from pathlib import Path
from typing import Callable

import pandas as pd

from backend.services import doi_chieu_song_phuong_service as ipcas_svc
from backend.services.doi_chieu_song_phuong_common import (
    cong_ngay, nhan_offset, thu_muc_ngay_ung_vien, tim_file, tim_file_glob,
)
from backend.services.doi_chieu_song_phuong_kenh.load_hub import (
    build_key_hub_core, filter_before_reconcile_core, hub_filename, load_hub_zip,
)
from backend.services.doi_chieu_song_phuong_kenh.load_kenh import _tu_khoa_ten_file

from . import load_core, load_osb, match
from .config import NHAN_HUB_T_CORE_T


def _tim_file_hub(goc_dir: Path, ngay: str, ma_nh: str) -> Path | None:
    return tim_file(goc_dir, ngay, hub_filename(ngay, ma_nh))


def _tim_file_core_hoac_csv(
    goc_dir: Path, ngay: str, ma_nh: str, log: Callable[[str], None] = lambda msg: None,
) -> tuple[str, Path] | None:
    """Ưu tiên `{ma_nh}_DEN*.csv` (đã phân loại sẵn, đọc thẳng — không giải mã) — khớp glob,
    KHÔNG đòi tên chính xác `{ma_nh}_DEN.csv`: dữ liệu thật xuất thủ công (ngoài module Phân
    loại dữ liệu) luôn kèm hậu tố ngày/giờ xuất (VD `202_DEN_20260827_1408.csv`, người chấm xác
    nhận 2026-08-28 đây đúng là dữ liệu CORE của ngày trong tên thư mục, không phải ngày trong
    tên file). Nhiều file cùng khớp → lấy file sửa đổi gần nhất, có cảnh báo. Không thấy CSV nào
    mới tới `GL02_{ngay}_1000.zip` (cần giải mã AES + phân loại). Trả `(loai, path)`, `loai` là
    `"csv"`/`"zip"`, hoặc `None` nếu không thấy cái nào."""
    matches = tim_file_glob(goc_dir, ngay, f"{ma_nh}_DEN*.csv")
    if matches:
        if len(matches) > 1:
            newest = max(matches, key=lambda p: p.stat().st_mtime)
            log(f"[CẢNH BÁO] {len(matches)} file khớp '{ma_nh}_DEN*.csv' trong {newest.parent} "
                f"— dùng file mới nhất '{newest.name}' (còn lại: "
                f"{', '.join(p.name for p in matches if p != newest)})")
            return ("csv", newest)
        return ("csv", matches[0])
    p = tim_file(goc_dir, ngay, f"GL02_{ngay}_1000.zip")
    if p is not None:
        return ("zip", p)
    return None


def _tim_file_osb(goc_dir: Path, ngay: str, ma_nh: str) -> Path | None:
    """So khớp từ khoá (`osb` + mã ngân hàng) trong tên file, không phân biệt dấu/hoa-thường —
    dữ liệu thật đã thấy cả `osb {ma_nh}.xlsx` và `osb den {ma_nh} {ngày}.xlsx`/`OSB den ...`.
    Không thấy theo tên thì thử `find_osb_by_ma_dich_vu` (dữ liệu xuất thẳng từ IPCAS tên
    `DULIEUCHITIETHACHTOAN_*.xlsx`, không mang mã NH trong tên file — người chấm báo thiếu
    2026-08-28, xem docstring hàm đó)."""
    can_co = {"osb", ma_nh.lower()}
    for d in (*thu_muc_ngay_ung_vien(goc_dir, ngay), goc_dir):
        if not d.exists():
            continue
        for f in d.glob("*.xlsx"):
            if can_co <= _tu_khoa_ten_file(f.name):
                return f
        found = load_osb.find_osb_by_ma_dich_vu(d, ma_nh)
        if found is not None:
            return found
    return None


def _doc_hub(path: Path, log: Callable[[str], None]) -> pd.DataFrame:
    df = load_hub_zip(path.read_bytes(), log=log)
    df = filter_before_reconcile_core(df, log)
    df[match.KEY_COL] = build_key_hub_core(df)
    return df


def _doc_core(loai: str, path: Path, ma_nh: str, log: Callable[[str], None]) -> pd.DataFrame:
    """`loai="csv"`: đọc thẳng `{ma_nh}_DEN.csv` đã phân loại sẵn — không giải mã. `loai="zip"`:
    giải mã + phân loại GL02 (tái dùng `doi_chieu_song_phuong_service.process_zip`, không sửa
    module phân loại) rồi đọc đúng file `{ma_nh}_DEN.csv` vừa sinh ra."""
    if loai == "csv":
        log(f"đọc thẳng CSV đã phân loại sẵn {path.name} (bỏ qua giải mã GL02)...")
        csv_path = path
    else:
        log(f"đang giải mã + phân loại {path.name}...")
        result = ipcas_svc.process_zip(path.read_bytes())
        csv_path = ipcas_svc.TEMP_DIR / result["token"] / f"{ma_nh}_DEN.csv"
    df = load_core.load_core_den_csv(csv_path)
    so_trace = load_core.build_so_trace(df)
    df[match.KEY_COL] = load_core.build_key_den(df, so_trace)
    return df


def doi_chieu_hub_core(
    goc_dir: str | Path, ngay: str, ma_nh: str,
    log_callback: Callable[[str], None] | None = None,
) -> dict:
    """Đối chiếu HUB↔CORE 1 ngân hàng, ngày `ngay` (YYYYMMDD). Trả
    `{"ma_nh", "ngay", "core_df", "hub_df"}` — 2 DataFrame đã gắn cột `KETQUADOICHIEU`.

    Raise `ValueError` nếu thiếu file bắt buộc (HUB T, CORE T)."""
    log = log_callback or (lambda msg: None)
    goc_dir = Path(goc_dir)

    hub_theo_offset: dict[int, pd.DataFrame] = {}
    for off in (0, -1, -2, -3):
        p = _tim_file_hub(goc_dir, cong_ngay(ngay, off), ma_nh)
        nhan = nhan_offset(off)
        if p is None:
            log(f"[HUB {nhan}] không tìm thấy file" + (" — BẮT BUỘC" if off in (0, -1) else " (bỏ qua)"))
            continue
        log(f"[HUB {nhan}] đang đọc {p.name}...")
        hub_theo_offset[off] = _doc_hub(p, log)

    if 0 not in hub_theo_offset:
        raise ValueError(f"Không tìm thấy file HUB ngày {ngay} cho NH {ma_nh} — không thể đối chiếu.")

    core_theo_offset: dict[int, pd.DataFrame] = {}
    for off in (0, 1, 2, 3):
        nhan = nhan_offset(off)
        found = _tim_file_core_hoac_csv(
            goc_dir, cong_ngay(ngay, off), ma_nh, lambda m, nhan=nhan: log(f"[CORE {nhan}] {m}"),
        )
        if found is None:
            log(f"[CORE {nhan}] không tìm thấy file CSV/GL02" + (" — BẮT BUỘC" if off in (0, 1) else " (bỏ qua)"))
            continue
        loai, p = found
        core_theo_offset[off] = _doc_core(loai, p, ma_nh, lambda m, nhan=nhan: log(f"[CORE {nhan}] {m}"))

    if 0 not in core_theo_offset:
        raise ValueError(f"Không tìm thấy file CSV/GL02 ngày {ngay} — không thể đối chiếu.")

    osb_path = _tim_file_osb(goc_dir, ngay, ma_nh)
    osb_df = None
    if osb_path is not None:
        log(f"[OSB] đang đọc {osb_path.name}...")
        osb_df = load_osb.load_osb_file(osb_path)
    else:
        log("[OSB] không tìm thấy file — bỏ qua Bước 2.6 (HUB thừa sẽ không đối chiếu OSB).")

    log("Đang phân loại CORE...")
    core_df = core_theo_offset[0].copy()
    core_df["KETQUADOICHIEU"] = match.classify_core(core_df, hub_theo_offset)

    log("Đang phân loại HUB...")
    hub_df = hub_theo_offset[0].copy()
    hub_df["KETQUADOICHIEU"] = match.classify_hub(hub_df, core_theo_offset, osb_df)

    n_core_khop = int((core_df["KETQUADOICHIEU"] == NHAN_HUB_T_CORE_T).sum())
    n_hub_khop = int((hub_df["KETQUADOICHIEU"] == NHAN_HUB_T_CORE_T).sum())
    if n_core_khop != n_hub_khop:
        log(f"[CẢNH BÁO] Bất biến vỡ: core khớp '{NHAN_HUB_T_CORE_T}' = {n_core_khop:,} dòng, "
            f"hub khớp '{NHAN_HUB_T_CORE_T}' = {n_hub_khop:,} dòng — không bằng nhau.")

    log(f"Hoàn thành NH {ma_nh} ngày {ngay}: core {len(core_df):,} dòng, hub {len(hub_df):,} dòng, "
        f"khớp '{NHAN_HUB_T_CORE_T}' = {n_core_khop:,} dòng.")

    return {"ma_nh": ma_nh, "ngay": ngay, "core_df": core_df, "hub_df": hub_df}
