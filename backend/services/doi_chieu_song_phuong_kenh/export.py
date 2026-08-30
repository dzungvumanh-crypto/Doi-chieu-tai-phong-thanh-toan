"""Xuất kết quả đối chiếu Kênh↔Hub — 1 file Excel, 3 sheet (quyết định 2026-08-28, người dùng
yêu cầu gộp thành 1 báo cáo, thay hẳn thiết kế cũ "1 file Bảng 1 + nhiều cặp file chi tiết/đơn
vị"): `Bang1_TongHop` (tổng hợp), `Hub_ChiTiet` (toàn bộ dòng HUB đã gắn cột "TRẠNG THÁI KÊNH"),
`Kenh_ChiTiet` (toàn bộ dòng KÊNH đã gắn cột "TRẠNG THÁI TẠI HUB") — 2 sheet chi tiết gộp MỌI đơn
vị (SPRT+SPT) trong `day_results` vào cùng 1 sheet, phân biệt bằng cột "Ngày"/"Ngân hàng"/"Loại"
chèn ở đầu.

Bảng 1 theo đúng mẫu Table 0 trong `đối chiếu kênh hub Song phương.docx` — tài liệu còn định
nghĩa "Bảng 1" cho CHIỀU ĐI, module này chỉ làm chiều ĐẾN (quyết định chủ dự án 2026-08-25) nên
không dựng cột chiều đi: không có dữ liệu thật để dựng, dựng bảng rỗng/giả sẽ gây hiểu nhầm.

Nội dung chi tiết lấy nguyên từ `don_vi["chi_tiet"]` (`process.classify_kenh_hub_den`, theo Bước
1/2 tài liệu v3 27/08/2026) — không đổi logic phân loại, chỉ đổi cách gộp file xuất ra.

⚠️ Gộp 1 sheet chỉ an toàn vì `doi_chieu_song_phuong_kenh_core_service.py` giới hạn mỗi job 1
ngân hàng (tối đa 2 đơn vị SPRT+SPT/lần) — tổng vẫn dưới giới hạn ~1.048.576 dòng/sheet của Excel
(NH nhiều giao dịch nhất quan sát được, 311, ~800k dòng HUB thô/ngày). KHÔNG gọi hàm này với
`day_results` gộp nhiều ngân hàng cùng lúc.
"""

from pathlib import Path

import pandas as pd

from .config import RECONCILE_UNITS

_BANG1_COLS = [
    "Ngày", "Ngân hàng", "Loại", "Số món HUB (1)", "Số tiền HUB (2)",
    "Số món kênh (3)", "Số tiền kênh (4)", "Chênh số món (5)=(3)-(1)",
    "Chênh tiền (6)=(4)-(2)", "Nguyên nhân",
]


def build_bang1_rows(day_results: list[dict]) -> pd.DataFrame:
    """Bảng 1: 1 dòng/ngày/đơn vị THẬT trong `RECONCILE_UNITS` (đơn vị không có nghiệp vụ,
    VD SPT của NH 203/311, không xuất hiện — quyết định 2026-08-26, xem `config.py`) + dòng
    TỔNG khi có nhiều hơn 1 ngày."""
    rows = []
    totals: dict[tuple, dict] = {}

    for day in day_results:
        ngay = day["ngay"]
        by_unit = {(d["ma_nh"], d["loai"]): d for d in day["don_vi"]}

        for unit in RECONCILE_UNITS:
            ma_nh, loai = unit["ma_nh"], unit["loai"]
            d = by_unit.get((ma_nh, loai))
            if d is None or d["trang_thai"] != "ok":
                trang_thai = d["trang_thai"] if d else "khong_tim_thay"
                rows.append({
                    "Ngày": ngay, "Ngân hàng": ma_nh, "Loại": loai,
                    "Số món HUB (1)": "", "Số tiền HUB (2)": "",
                    "Số món kênh (3)": "", "Số tiền kênh (4)": "",
                    "Chênh số món (5)=(3)-(1)": "", "Chênh tiền (6)=(4)-(2)": "",
                    "Nguyên nhân": f"Lỗi/thiếu dữ liệu: {trang_thai}",
                })
                continue

            s = d["summary"]
            rows.append({
                "Ngày": ngay, "Ngân hàng": ma_nh, "Loại": loai,
                "Số món HUB (1)": s["so_mon_hub"], "Số tiền HUB (2)": s["so_tien_hub"],
                "Số món kênh (3)": s["so_mon_kenh"], "Số tiền kênh (4)": s["so_tien_kenh"],
                "Chênh số món (5)=(3)-(1)": s["chenh_so_mon"], "Chênh tiền (6)=(4)-(2)": s["chenh_so_tien"],
                "Nguyên nhân": "",
            })
            key = (ma_nh, loai)
            t = totals.setdefault(key, {"so_mon_hub": 0, "so_tien_hub": 0, "so_mon_kenh": 0, "so_tien_kenh": 0})
            t["so_mon_hub"] += s["so_mon_hub"]
            t["so_tien_hub"] += s["so_tien_hub"]
            t["so_mon_kenh"] += s["so_mon_kenh"]
            t["so_tien_kenh"] += s["so_tien_kenh"]

    if len(day_results) > 1:
        for (ma_nh, loai), t in totals.items():
            rows.append({
                "Ngày": f"TỔNG {len(day_results)} NGÀY", "Ngân hàng": ma_nh, "Loại": loai,
                "Số món HUB (1)": t["so_mon_hub"], "Số tiền HUB (2)": t["so_tien_hub"],
                "Số món kênh (3)": t["so_mon_kenh"], "Số tiền kênh (4)": t["so_tien_kenh"],
                "Chênh số món (5)=(3)-(1)": t["so_mon_kenh"] - t["so_mon_hub"],
                "Chênh tiền (6)=(4)-(2)": t["so_tien_kenh"] - t["so_tien_hub"],
                "Nguyên nhân": "",
            })

    return pd.DataFrame(rows, columns=_BANG1_COLS)


def _gop_chi_tiet(day_results: list[dict], key: str) -> pd.DataFrame:
    """Gộp `don_vi["chi_tiet"][key]` (`key` = "hub"/"kenh") của mọi đơn vị `ok` trong
    `day_results` thành 1 DataFrame, chèn cột "Ngày"/"Ngân hàng"/"Loại" ở đầu để phân biệt."""
    frames = []
    for day in day_results:
        ngay = day["ngay"]
        for d in day["don_vi"]:
            if d["trang_thai"] != "ok":
                continue
            df = d["chi_tiet"][key].copy()
            df.insert(0, "Loại", d["loai"])
            df.insert(0, "Ngân hàng", d["ma_nh"])
            df.insert(0, "Ngày", ngay)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def export_bao_cao(day_results: list[dict], out_path: str | Path) -> Path:
    """Xuất báo cáo Kênh↔Hub — 1 file Excel, 3 sheet (`Bang1_TongHop`/`Hub_ChiTiet`/
    `Kenh_ChiTiet`, xem docstring module). `day_results` = danh sách kết quả
    `pipeline.main_from_dir()`, 1 phần tử/ngày (>=1 ngày)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # engine="xlsxwriter" (KHÔNG "openpyxl") — 2 sheet chi tiết có thể tới ~800k dòng, xlsxwriter
    # ghi nhanh hơn ~30% (đo thật: 203s vs 280.6s/765k dòng x 18 cột). ⚠️ ĐÃ THỬ + LOẠI BỎ tuỳ
    # chọn `constant_memory=True` của xlsxwriter (nhanh hơn nữa, ~140s) — verify phát hiện nó làm
    # MẤT DỮ LIỆU ÂM THẦM (1 số ô số tiền/ghi chú thành None) trên dữ liệu tiếng Việt thật, không
    # dùng dù nhanh hơn — dữ liệu tài chính không được đánh đổi lấy tốc độ.
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        build_bang1_rows(day_results).to_excel(writer, sheet_name="Bang1_TongHop", index=False)
        _gop_chi_tiet(day_results, "hub").to_excel(writer, sheet_name="Hub_ChiTiet", index=False)
        _gop_chi_tiet(day_results, "kenh").to_excel(writer, sheet_name="Kenh_ChiTiet", index=False)
    return out_path
