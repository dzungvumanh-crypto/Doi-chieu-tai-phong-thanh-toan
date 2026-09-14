# -*- coding: utf-8 -*-
"""
test_doi_chieu_citad_buffer_dup.py
-------------------------------------
Bug thật (14/09/2026, Phòng Thanh toán báo): trên trang CITAD, ô chọn loại
tiền (vd đổi USD → EUR) đổi giá trị NGAY LẬP TỨC, nhưng bảng kết quả
(tr.grid-footer) chỉ cập nhật SAU khi trang truy vấn lại xong — nếu
Extension (content.js, autoSaveIfNew()) đọc đúng lúc giữa 2 mốc đó, số liệu
CŨ (còn của USD) bị gắn nhầm nhãn loại tiền MỚI (EUR) rồi gửi lên server.

Không sửa được ở content.js (đổi rồi phải bắt mọi máy trạm cài lại Extension
— chi phí vận hành cao, người dùng từ chối phương án này). Xử lý hoàn toàn ở
server thay vào đó: nếu 2 loại tiền KHÁC nhau (cùng cổng/chiều/loại DV) có
soMon VÀ soTien TRÙNG TUYỆT ĐỐI — xác suất trùng thật giữa 2 dòng tiền độc
lập gần như bằng 0 — gắn cờ `_suspect_dup_tien` để frontend cảnh báo, KHÔNG
chặn lưu (khoá lại đúng hành vi "vẫn lưu, chỉ cảnh báo" đã thống nhất, tránh
âm thầm mất dữ liệu thật nếu chẳng may 2 loại tiền trùng số thật).
"""
from backend.services import doi_chieu_citad_service as svc

OWNER = "_test_dup_owner"


def setup_function():
    svc._citad_buffer.pop(OWNER, None)
    svc._ph_buffer.pop(OWNER, None)


def _citad_item(tien, so_mon, so_tien, cong="1", loai="ih", chieu="di"):
    return {
        "key": f"citad_{cong}_{tien}_{chieu}_{loai}", "cong": cong, "loai": loai,
        "chieu": chieu, "tien": tien, "soMon": so_mon, "soTien": so_tien,
    }


def test_trung_tuyet_doi_ca_2_ben_deu_bi_gan_co():
    svc.buffer_save_citad(OWNER, _citad_item("USD", 15, 12500.0))
    svc.buffer_save_citad(OWNER, _citad_item("EUR", 15, 12500.0))

    items = {i["tien"]: i for i in svc.buffer_get_citad(OWNER)}
    assert items["USD"].get("_suspect_dup_tien") == "EUR"
    assert items["EUR"].get("_suspect_dup_tien") == "USD"
    # Vẫn CÒN đủ cả 2 item — không bị chặn/loại bỏ, chỉ cảnh báo.
    assert len(items) == 2


def test_khac_soTien_thi_khong_gan_co():
    svc.buffer_save_citad(OWNER, _citad_item("USD", 15, 12500.0))
    svc.buffer_save_citad(OWNER, _citad_item("EUR", 15, 999.0))

    items = {i["tien"]: i for i in svc.buffer_get_citad(OWNER)}
    assert "_suspect_dup_tien" not in items["USD"]
    assert "_suspect_dup_tien" not in items["EUR"]


def test_khac_cong_thi_khong_gan_co_du_trung_so():
    svc.buffer_save_citad(OWNER, _citad_item("USD", 15, 12500.0, cong="1"))
    svc.buffer_save_citad(OWNER, _citad_item("EUR", 15, 12500.0, cong="9"))

    items = {(i["tien"], i["cong"]): i for i in svc.buffer_get_citad(OWNER)}
    assert "_suspect_dup_tien" not in items[("USD", "1")]
    assert "_suspect_dup_tien" not in items[("EUR", "9")]


def test_item_napas_pssmdp_khong_bi_so_sanh():
    # cong/loai/chieu/tien của item Napas/PSS-MDP chỉ điền cho đủ field bắt
    # buộc (luôn cong='1', loai='ih', chieu='den', tien='VNĐ') — không mang
    # ý nghĩa thật, so sánh sẽ sai nếu không loại trừ qua `source`.
    napas = _citad_item("VNĐ", 5, 1000.0, chieu="den")
    napas["source"] = "napas"
    pssmdp = _citad_item("VNĐ", 5, 1000.0, chieu="den")
    pssmdp["key"] = "citad_pssmdp_quyettoanloden"
    pssmdp["source"] = "pssmdp"
    svc.buffer_save_citad(OWNER, napas)
    svc.buffer_save_citad(OWNER, pssmdp)

    items = svc.buffer_get_citad(OWNER)
    assert all("_suspect_dup_tien" not in i for i in items)


def test_co_tu_bien_mat_khi_1_ben_duoc_gui_lai_so_khac():
    svc.buffer_save_citad(OWNER, _citad_item("USD", 15, 12500.0))
    svc.buffer_save_citad(OWNER, _citad_item("EUR", 15, 12500.0))
    items = {i["tien"]: i for i in svc.buffer_get_citad(OWNER)}
    assert items["USD"].get("_suspect_dup_tien") == "EUR"

    # EUR được quét lại đúng — số liệu THẬT, khác USD.
    svc.buffer_save_citad(OWNER, _citad_item("EUR", 3, 40.5))

    items = {i["tien"]: i for i in svc.buffer_get_citad(OWNER)}
    assert "_suspect_dup_tien" not in items["USD"]
    assert "_suspect_dup_tien" not in items["EUR"]


def test_ap_dung_ca_cho_buffer_paymenthub():
    svc.buffer_save_ph(OWNER, [
        {"key": "ph_di_ih_USD", "loai": "ih", "chieu": "di", "tien": "USD", "soMon": 7, "soTien": 200.0},
        {"key": "ph_di_ih_EUR", "loai": "ih", "chieu": "di", "tien": "EUR", "soMon": 7, "soTien": 200.0},
    ])

    items = {i["tien"]: i for i in svc.buffer_get_ph(OWNER)}
    assert items["USD"].get("_suspect_dup_tien") == "EUR"
    assert items["EUR"].get("_suspect_dup_tien") == "USD"
