"""So khớp HUB↔Kênh theo đơn vị (ngân hàng, loại) — existence-check theo khoá.

⚠️ Khoá theo loại: SPRT dùng `MSGREF`, SPT dùng `TXID` (cả 2 đã strip nháy đơn phía HUB
ở `load_hub.load_hub_zip`). Đối chiếu chỉ dựa vào tồn tại/không tồn tại khoá — KHÔNG
group theo chi nhánh/số tiền, KHÔNG dung sai tiền/thời gian (đã xác nhận bằng dữ liệu
thật: 0/873.189 cặp khớp lệch tiền ngày 21.8/08/2026 — xem
docs/TU-DIEN-LENH-THANH-TOAN.md mục 4.5).
"""

import pandas as pd

from backend.services.ach.so_tien import doc_so_tien

from .config import (
    COT_TRANG_THAI_KENH, COT_TRANG_THAI_TAI_HUB, EXPECTED_ONE_SIDED_STATUSES, HUB_AMOUNT_COL,
    KENH_AMOUNT_COL, KENH_KEY_COL, LOAI_KENH_THANH_TOAN, LOAI_KHOA_HUB, NHAN_CHUYEN_TIEP,
    NHAN_HUB_THUA, NHAN_KENH_THANH_CONG, NHAN_KENH_THUA, NHAN_TRACE_HUY, NHAN_TU_CHOI_KENH_KHONG_TC,
)


def match_unit(hub_df: pd.DataFrame, kenh_df: pd.DataFrame, loai: str) -> dict:
    """So khớp 1 đơn vị (ngân hàng, loại) trong 1 ngày.

    `hub_df`: đã strip nháy đơn + đã loại dòng TXID có `-`
    (`load_hub.load_hub_zip` + `load_hub.filter_before_reconcile`).
    `kenh_df`: nguyên trạng từ `load_kenh.load_kenh_file`.

    Trả dict 5 DataFrame — bất biến: `len(matched_hub)+len(only_hub)==len(hub)` và
    `len(matched_kenh)+len(only_kenh)==len(kenh_df)`.
    """
    khoa_hub = LOAI_KHOA_HUB[loai]
    ktt = LOAI_KENH_THANH_TOAN[loai]

    hub = hub_df[hub_df["KENH_THANH_TOAN"] == ktt].reset_index(drop=True)
    kenh_keys = set(kenh_df[KENH_KEY_COL])
    hub_keys = set(hub[khoa_hub])

    mask_hub_matched = hub[khoa_hub].isin(kenh_keys)
    mask_kenh_matched = kenh_df[KENH_KEY_COL].isin(hub_keys)

    return {
        "hub": hub,
        "matched_hub": hub[mask_hub_matched].reset_index(drop=True),
        "only_hub": hub[~mask_hub_matched].reset_index(drop=True),
        "matched_kenh": kenh_df[mask_kenh_matched].reset_index(drop=True),
        "only_kenh": kenh_df[~mask_kenh_matched].reset_index(drop=True),
    }


def summarize_unit(match_result: dict, kenh_df: pd.DataFrame, ma_nh: str, loai: str) -> dict:
    """Tổng hợp kiểu Bảng 1 tài liệu: đếm + tổng tiền HUB (loại trạng thái một-phía
    đương nhiên, VD RJCT) so với kênh, ra chênh lệch (kênh - hub)."""
    hub = match_result["hub"]
    hub_in_scope = hub[~hub["TRANG_THAI_LENH"].isin(EXPECTED_ONE_SIDED_STATUSES)]

    so_mon_hub = len(hub_in_scope)
    so_tien_hub = (
        int(doc_so_tien(hub_in_scope[HUB_AMOUNT_COL], "hub", HUB_AMOUNT_COL).sum())
        if so_mon_hub else 0
    )
    so_mon_kenh = len(kenh_df)
    so_tien_kenh = (
        int(doc_so_tien(kenh_df[KENH_AMOUNT_COL], "kenh", KENH_AMOUNT_COL).sum())
        if so_mon_kenh else 0
    )

    return {
        "ma_nh": ma_nh, "loai": loai,
        "so_mon_hub": so_mon_hub, "so_tien_hub": so_tien_hub,
        "so_mon_kenh": so_mon_kenh, "so_tien_kenh": so_tien_kenh,
        "chenh_so_mon": so_mon_kenh - so_mon_hub,
        "chenh_so_tien": so_tien_kenh - so_tien_hub,
    }


def dem_lech_tien_tren_khop(match_result: dict, kenh_df: pd.DataFrame, loai: str) -> dict:
    """Đếm số cặp khớp khoá nhưng LỆCH số tiền (dùng doc_so_tien(), không tự viết parser).

    Quyết định nghiệp vụ (2026-08-25): giả định KHÔNG có ca này — nếu tìm thấy, phải
    báo lại, không tự quyết cách xử lý."""
    matched_hub = match_result["matched_hub"]
    if len(matched_hub) == 0:
        return {"so_cap_khop": 0, "so_cap_lech": 0, "vi_du": []}

    khoa_hub = LOAI_KHOA_HUB[loai]
    hub_tien = doc_so_tien(matched_hub[HUB_AMOUNT_COL], "hub", HUB_AMOUNT_COL)

    kenh_lookup = kenh_df.drop_duplicates(subset=[KENH_KEY_COL]).set_index(KENH_KEY_COL)
    kenh_tien_raw = matched_hub[khoa_hub].map(kenh_lookup[KENH_AMOUNT_COL])
    kenh_tien = doc_so_tien(kenh_tien_raw, "kenh", KENH_AMOUNT_COL)

    mask_lech = hub_tien != kenh_tien
    n_lech = int(mask_lech.sum())

    vi_du = []
    if n_lech:
        for i in matched_hub.index[mask_lech][:5]:
            vi_du.append({
                "khoa": matched_hub.loc[i, khoa_hub],
                "so_tien_hub": int(hub_tien.loc[i]),
                "so_tien_kenh": int(kenh_tien.loc[i]),
            })

    return {"so_cap_khop": len(matched_hub), "so_cap_lech": n_lech, "vi_du": vi_du}


def check_unexpected_one_sided(match_result: dict) -> list[str]:
    """Guard kiểm soát cốt lõi: trả danh sách `TRANG_THAI_LENH` xuất hiện trong nhóm
    "chỉ-hub" nhưng KHÔNG thuộc `EXPECTED_ONE_SIDED_STATUSES` (hiện chỉ có `RJCT`).

    Danh sách rỗng = bình thường (đúng như dữ liệu thật 3 ngày mẫu). Danh sách khác
    rỗng = tín hiệu cảnh báo cần điều tra — trạng thái đó trước nay luôn khớp kênh,
    nay xuất hiện một phía bất thường."""
    only_hub = match_result["only_hub"]
    if len(only_hub) == 0:
        return []
    statuses = set(only_hub["TRANG_THAI_LENH"].unique())
    return sorted(statuses - EXPECTED_ONE_SIDED_STATUSES)


def _gan_nhan(nhan: pd.Series, con_lai: pd.Series, mask: pd.Series, nhan_gan: str) -> pd.Series:
    """Gán `nhan_gan` cho các dòng còn `con_lai` VÀ khớp `mask`, trả `con_lai` mới (đã loại các
    dòng vừa gán) — cùng phong cách waterfall top-down dùng ở
    `doi_chieu_song_phuong_core/match.py::_phan_loai_chuoi_khoa`."""
    ap_dung = con_lai & mask
    nhan.loc[ap_dung] = nhan_gan
    return con_lai & ~mask


def classify_kenh_hub_den(hub_raw: pd.DataFrame, kenh_df: pd.DataFrame, loai: str) -> dict:
    """Đối chiếu chi tiết chiều ĐẾN (Bước 1/2, tài liệu v3 27/08/2026) — THAY HẲN "Bảng 3" cũ.

    Chạy trên `hub_raw` NGUYÊN VẸN (chưa qua `filter_before_reconcile` — khác Bảng 1, vốn vẫn
    dùng bản đã lọc, không đổi). Trả `{"hub": ..., "kenh": ...}`, mỗi DataFrame là bản sao của
    input (đã scope theo `KENH_THANH_TOAN` đúng loại) kèm cột trạng thái mới ở cuối.

    Bước 1 (kênh, `COT_TRANG_THAI_TAI_HUB`): khớp khoá → lấy TRANG_THAI_LENH của hub; không khớp
    → "KÊNH THỪA".

    Bước 2 (hub, `COT_TRANG_THAI_KENH`) — waterfall trên-xuống, dừng ở bước đầu khớp:
    1. Cặp (TXID, TRACE) trùng dòng khác → "GD có trace hủy"
    2. "-" trong TXID → "GD chuyển tiếp"
    3. RJCT và khoá không có ở kênh → "GD Đã từ chối-kênh không thành công"
    4. Khoá có ở kênh → "KÊNH THÀNH CÔNG"
    5. Còn lại → "HUB THỪA"

    ⚠️ Bước 2.3 trong tài liệu chỉ ghi "không trùng với MSGREF" (không nhắc lại "TXID đối với SP
    THƯỜNG" như các bước khác) — coi đây là viết tắt, dùng khoá NHẤT QUÁN theo `loai`
    (`LOAI_KHOA_HUB[loai]`) giống mọi bước còn lại. Cần verify lại với dữ liệu SPT thật (đơn vị
    202-SPT) khi có.
    """
    khoa_hub = LOAI_KHOA_HUB[loai]
    ktt = LOAI_KENH_THANH_TOAN[loai]

    hub = hub_raw[hub_raw["KENH_THANH_TOAN"] == ktt].reset_index(drop=True).copy()
    kenh = kenh_df.reset_index(drop=True).copy()

    kenh_keys = set(kenh[KENH_KEY_COL])

    # ── Bước 1: cột "TRẠNG THÁI TẠI HUB" trên file kênh ──
    hub_status_lookup = hub.drop_duplicates(subset=[khoa_hub]).set_index(khoa_hub)["TRANG_THAI_LENH"]
    kenh[COT_TRANG_THAI_TAI_HUB] = kenh[KENH_KEY_COL].map(hub_status_lookup).fillna(NHAN_KENH_THUA)

    # ── Bước 2: cột "TRẠNG THÁI KÊNH" trên file hub — waterfall ──
    nhan = pd.Series("", index=hub.index)
    con_lai = pd.Series(True, index=hub.index)

    trace_norm = hub["TRACE"].fillna("").str.strip().str.lstrip("'0")
    co_khoa_trace = (hub["TXID"] != "") & (trace_norm != "")
    khoa_trace = hub["TXID"] + "\x00" + trace_norm
    dem_trace = khoa_trace[co_khoa_trace].value_counts()
    mask_trace_huy = co_khoa_trace & (khoa_trace.map(dem_trace).fillna(0) >= 2)
    con_lai = _gan_nhan(nhan, con_lai, mask_trace_huy, NHAN_TRACE_HUY)

    mask_chuyen_tiep = hub["TXID"].str.contains("-", regex=False)
    con_lai = _gan_nhan(nhan, con_lai, mask_chuyen_tiep, NHAN_CHUYEN_TIEP)

    mask_khop = hub[khoa_hub].isin(kenh_keys)
    mask_rjct_khong_khop = (hub["TRANG_THAI_LENH"] == "RJCT") & ~mask_khop
    con_lai = _gan_nhan(nhan, con_lai, mask_rjct_khong_khop, NHAN_TU_CHOI_KENH_KHONG_TC)

    con_lai = _gan_nhan(nhan, con_lai, mask_khop, NHAN_KENH_THANH_CONG)

    nhan.loc[con_lai] = NHAN_HUB_THUA
    hub[COT_TRANG_THAI_KENH] = nhan

    return {"hub": hub, "kenh": kenh}
