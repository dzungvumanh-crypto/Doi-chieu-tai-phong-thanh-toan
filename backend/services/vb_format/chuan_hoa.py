"""Điều phối một lượt chuẩn hoá: đọc .docx → sửa → trả .docx mới + nhật ký.

## Vì sao chia làm hai lượt sửa chữ

Lượt 1 sửa hoa/thường và đánh số. Lượt 2 mới ghép cụm từ liền dòng, và tính
lại trên chữ ĐÃ sửa của lượt 1.

Gộp một lượt thì hai luật giẫm chân nhau ở đúng chỗ hay gặp nhất: "tổng giám
đốc" vừa nằm trong từ điển viết hoa vừa nằm trong danh sách cụm từ liền dòng.
Cả hai cùng đòi ghi vào một khoảng ký tự, chỉ một cái được ghi, cái còn lại rơi
mất — mà rơi cái nào thì tuỳ thứ tự trong danh sách, tức là không đoán được.

## Vì sao không bôi màu những sửa đổi áp cho cả văn bản

Giãn dòng, cách đoạn, phông chữ, thụt dòng đầu gần như luôn phải sửa ở **mọi**
đoạn — văn bản soạn bằng mặc định của Word không đoạn nào đúng. Bôi màu hết thì
cả trang vàng khè và người kiểm tra không còn chỗ nào để nhìn. Những sửa đổi
đó vào phần "Sửa chung cho cả văn bản" của nhật ký; màu chỉ dành cho chỗ khác
biệt riêng của từng đoạn (cỡ chữ, đậm/nghiêng, căn lề) và cho chữ bị sửa.
"""
import io
import logging

from docx import Document

from . import ap_dung, bien_doi, nhan_dien, quy_chuan

_log = logging.getLogger(__name__)

def _loc_chong_lan(sua: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Bỏ những khoảng sửa đè lên khoảng đã nhận trước đó.

    Hai luật khác nhau cùng đòi ghi vào một khoảng ký tự thì chỉ luật đứng
    trước được ghi. Không lọc thì `ap_sua_text()` ghi chồng: khoảng sau ghi đè
    lên chữ mới của khoảng trước, kết quả là một chuỗi lai không giống cả hai.
    """
    ket_qua: list[tuple[int, int, str]] = []
    da_chiem: list[tuple[int, int]] = []
    for dau, cuoi, moi in sua:
        if any(dau < c and d < cuoi for d, c in da_chiem):
            continue
        ket_qua.append((dau, cuoi, moi))
        da_chiem.append((dau, cuoi))
    return ket_qua


def _sua_chu(p, ma: str, tp: dict, cfg: dict, tu_dien,
             txt_truoc: str | None) -> set[int]:
    """Lượt 1 — ép hoa/thường, chuẩn đánh số, viết hoa. Trả chỉ số run đã sửa."""
    txt = p.text
    if not txt.strip():
        return set()

    # Tiêu ngữ có luật riêng về dấu nối và dấu cách (Điều 7.2), không liên quan
    # tới hoa/thường nên chạy trước và độc lập.
    if ma == "tieu_ngu" and cfg["chung"].get("chuan_tieu_ngu"):
        da_sua = ap_dung.ap_sua_text(p, bien_doi.chuan_tieu_ngu(txt))
        if da_sua:
            return da_sua

    # Ép in hoa cả đoạn thì mọi luật viết hoa khác thành vô nghĩa: kết quả đằng
    # nào cũng là chữ hoa. Chạy riêng, không trộn với nhóm dưới.
    if tp.get("hoa"):
        return ap_dung._ep_hoa_thuong(p, tp["hoa"])

    sua: list[tuple[int, int, str]] = []
    sua += bien_doi.chuan_danh_so(txt, ma, cfg["danh_so"])
    vh = cfg["viet_hoa"]
    if vh.get("vien_dan"):
        sua += bien_doi.viet_hoa_vien_dan(txt)
    if vh.get("tu_dien"):
        sua += bien_doi.viet_hoa_tu_dien(txt, tu_dien)
    if vh.get("dau_cau"):
        sua += bien_doi.viet_hoa_dau_cau(
            txt, bien_doi.cho_phep_hoa_dau_doan(ma, txt_truoc))
    return ap_dung.ap_sua_text(p, _loc_chong_lan(sua))


def chuan_hoa(du_lieu: bytes, cau_hinh: dict | None = None) -> tuple[bytes, dict]:
    """Chuẩn hoá một file .docx theo quy chuẩn.

    Trả `(bytes file kết quả, báo cáo)`. Báo cáo gồm:
      `sua_chung`  danh sách sửa đổi áp cho cả văn bản (lề trang, giãn dòng…)
      `doan`       từng đoạn đã sửa: vị trí, thành phần thể thức, trích dẫn, việc đã làm
      `luu_y`      những chỗ CỐ Ý không đụng tới, kèm lý do
      `thong_ke`   số đoạn đọc được / số đoạn đã sửa
    """
    cfg = quy_chuan.hop_nhat(cau_hinh)
    doc = Document(io.BytesIO(du_lieu))

    dd = cfg["danh_dau"]
    bat_mau = bool(dd.get("bat"))
    tu_dien = bien_doi.TuDien(cfg["viet_hoa"].get("cum_tu") or [])
    mau_lien_dong = (bien_doi.regex_lien_dong(cfg["lien_dong"].get("cum_tu") or [])
                     if cfg["lien_dong"].get("ap_dung") else None)

    sua_chung = ap_dung.dat_trang(doc, cfg["trang"])

    khoi = ap_dung.duyet_doan(doc)
    ma_list = nhan_dien.phan_loai([(p.text, tb) for p, tb in khoi])

    nhat_ky: list[dict] = []
    luu_y: list[str] = []
    so_doan_sua = 0
    da_canh_bao_so_tu_dong = False
    # Đoạn CÓ CHỮ liền trước — dùng để biết đoạn hiện tại có mở đầu một câu
    # mới hay chỉ là phần xuống dòng của câu trên (xem `cho_phep_hoa_dau_doan`).
    txt_truoc: str | None = None

    for stt, ((p, _tb), ma) in enumerate(zip(khoi, ma_list), start=1):
        if ma == "trong":
            continue
        txt_hien_tai = p.text
        if dd.get("xoa_danh_dau_cu"):
            ap_dung._xoa_danh_dau(p)

        tp = cfg["thanh_phan"].get(ma, {})
        viec: list[str] = []

        # ── Danh sách tự động của Word ──
        kieu = ap_dung._kieu_danh_so(doc, p)
        if kieu == "bullet" and cfg["danh_so"].get("bo_bullet_tu_dong"):
            ap_dung._go_danh_so_tu_dong(doc, p)
            ky_tu = cfg["danh_so"].get("ky_tu_gach", "-")
            if p.runs:
                p.runs[0].text = f"{ky_tu} " + p.runs[0].text
            else:
                p.add_run(f"{ky_tu} ")
            viec.append("chuyển dấu chấm tròn tự động thành gạch đầu dòng")
        elif kieu == "so" and not cfg["danh_so"].get("bo_so_tu_dong"):
            if not da_canh_bao_so_tu_dong:
                luu_y.append(
                    "Văn bản có danh sách ĐÁNH SỐ tự động của Word. Số hiển thị do "
                    "Word tự tính nên không đọc ra được để chuẩn hoá — phần mềm giữ "
                    "nguyên. Muốn đúng quy định thì gõ số thẳng vào dòng (1. 2. 3. "
                    "hoặc a) b) c)) rồi tắt đánh số tự động."
                )
                da_canh_bao_so_tu_dong = True

        # ── Lượt 1: sửa chữ ──
        run_noi_dung = _sua_chu(p, ma, tp, cfg, tu_dien, txt_truoc)
        if run_noi_dung:
            viec.append("sửa chữ (viết hoa / đánh số / gạch đầu dòng)")

        # ── Lượt 2: ghép cụm từ liền dòng, tính trên chữ đã sửa ở lượt 1 ──
        run_lien_dong: set[int] = set()
        if mau_lien_dong is not None:
            gd = bien_doi.ghep_lien_dong(p.text, mau_lien_dong)
            run_lien_dong = ap_dung.ap_sua_text(p, gd)
            if run_lien_dong:
                viec.append("ghép cụm từ không cho tách dòng")

        # ── Định dạng ──
        dinh_dang = ap_dung._dinh_dang_doan(p, ma, tp, cfg["chung"])
        rieng = [mo_ta for loai, mo_ta in dinh_dang if loai == "rieng"]
        for loai, mo_ta in dinh_dang:
            if loai == "chung":
                if mo_ta not in sua_chung:
                    sua_chung.append(mo_ta)
            else:
                viec.append(mo_ta)

        # ── Đánh dấu: cụ thể đè lên tổng quát ──
        if bat_mau and (rieng or run_noi_dung or run_lien_dong):
            if rieng:
                ap_dung._to_mau(p, None, dd.get("mau_dinh_dang", "YELLOW"))
            if run_noi_dung:
                ap_dung._to_mau(p, run_noi_dung, dd.get("mau_noi_dung", "BRIGHT_GREEN"))
            if run_lien_dong:
                ap_dung._to_mau(p, run_lien_dong, dd.get("mau_lien_dong", "TURQUOISE"))

        txt_truoc = txt_hien_tai

        if viec:
            so_doan_sua += 1
            nhat_ky.append({
                "stt": stt,
                "ma": ma,
                "nhan": quy_chuan.NHAN_THANH_PHAN.get(ma, "Ô bảng" if ma == "bang" else ma),
                "trich": (p.text or "")[:90],
                "viec": viec,
            })

    ra = io.BytesIO()
    doc.save(ra)
    return ra.getvalue(), {
        "sua_chung": sua_chung,
        "doan": nhat_ky,
        "luu_y": luu_y,
        "thong_ke": {
            "tong_doan": sum(1 for m in ma_list if m != "trong"),
            "doan_da_sua": so_doan_sua,
        },
    }
