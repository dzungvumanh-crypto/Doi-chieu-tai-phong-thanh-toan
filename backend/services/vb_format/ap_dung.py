"""Áp quy chuẩn lên file .docx: sửa định dạng, sửa chữ, đánh dấu vùng đã sửa.

## Nguyên tắc: chỉ ghi khi giá trị ĐANG SAI

Không quét một lượt rồi ghi đè tất cả. Lý do là vùng đánh dấu: nếu cứ ghi đè
thì mọi đoạn đều "đã sửa" và cả văn bản vàng khè — người dùng không còn biết
chỗ nào thật sự sai. Nên trước mỗi lần ghi đều so với **giá trị đang có hiệu
lực**, kể cả khi giá trị đó đến từ style chứ không đặt thẳng trên run.

`_hieu_luc_run()` và `_hieu_luc_doan()` làm đúng việc leo ngược chuỗi style để
biết cỡ chữ / căn lề thực sự đang hiển thị. Bỏ bước này mà đọc thẳng
`run.font.size` thì mọi văn bản soạn bằng style (đa số văn bản Word) đều trả
`None`, bị hiểu là "chưa đặt" và bị ghi đè toàn bộ.

## Ba màu đánh dấu

Vàng = sửa định dạng, xanh lá = sửa chữ (viết hoa, đánh số), xanh ngọc = ghép
cụm từ liền dòng. Ba loại này người kiểm tra xử lý khác nhau: sửa định dạng thì
liếc qua là xong, còn sửa chữ thì phải đọc lại xem máy có làm hỏng câu không.
Cùng một màu là bắt họ đọc lại tất cả.
"""
import logging
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Cm, Length, Mm, Pt, RGBColor, Twips
from docx.text.paragraph import Paragraph

from . import do_chu, nhan_dien

_log = logging.getLogger(__name__)

_CAN_LE = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_TEN_CAN_LE = {"left": "trái", "center": "giữa", "right": "phải", "justify": "đều hai bên"}

# Sai số bỏ qua khi so số đo — Word lưu lề theo EMU, đổi qua lại mm luôn lệch
# vài phần nghìn. Không có ngưỡng này thì lề 20 mm nào cũng bị coi là sai.
_SAI_SO_MM = 0.3
_SAI_SO_PT = 0.05


def nhom_bang(doc, khoi) -> list[int | None]:
    """Mỗi đoạn thuộc bảng THỨ MẤY — `None` nếu không nằm trong bảng nào.

    `duyet_doan()` chỉ nói "có nằm trong bảng hay không", nên hai bảng dán sát
    nhau nhìn ra y hệt một bảng. Thiếu thông tin này thì luật lan thể thức sang
    ô cùng bảng sẽ kéo luôn cả bảng số liệu đứng ngay sau — đã thử, đúng vậy.

    ## Vì sao gom cả danh sách bảng ra trước

    Không dùng `id()` của phần tử lấy tại chỗ: lxml **dựng proxy theo yêu cầu
    rồi thu hồi**, nên `id()` của một proxy vừa bị thu hồi được cấp lại cho
    phần tử khác. Kết quả đo được: các ô của cùng một bảng nhận số nhóm khác
    nhau, còn ô của hai bảng khác nhau lại trùng số — bảng số liệu bị sửa xen
    kẽ từng ô một, nhìn như lỗi ngẫu nhiên.

    Gom `doc.element.body.iter(w:tbl)` vào một danh sách rồi so bằng `is`:
    danh sách giữ tham chiếu nên mọi proxy sống tới hết hàm, `is` mới đáng tin.
    """
    bang = list(doc.element.body.iter(qn("w:tbl")))
    ket_qua: list[int | None] = []
    for p, _ in khoi:
        el, nhom = p._p.getparent(), None
        while el is not None:
            if el.tag == qn("w:tbl"):
                nhom = next((k for k, b in enumerate(bang) if b is el), None)
                break
            el = el.getparent()
        ket_qua.append(nhom)
    return ket_qua


def _so(v) -> str:
    """6.0 → "6"; 1.5 → "1,5" — nhật ký cho người đọc, không phải cho máy."""
    f = float(v)
    return (str(int(f)) if f == int(f) else f"{f:g}").replace(".", ",")


# ── Duyệt tài liệu ───────────────────────────────────────────────────────────
def duyet_doan(doc) -> list[tuple[Paragraph, bool]]:
    """Mọi đoạn trong thân văn bản, ĐÚNG thứ tự xuất hiện, kèm cờ nằm-trong-bảng.

    `doc.paragraphs` bỏ qua đoạn nằm trong ô bảng, mà khối Quốc hiệu / tên đơn
    vị đầu trang thường được dựng bằng bảng hai cột. Đi thẳng vào cây XML là
    cách duy nhất giữ được đúng thứ tự giữa đoạn thường và bảng.
    """
    ket_qua: list[tuple[Paragraph, bool]] = []

    # Cha của Paragraph phải là đối tượng CÓ `.part` (Paragraph.style đi qua đó
    # để tra bảng style). Truyền phần tử XML của ô bảng vào sẽ vỡ ở đúng chỗ
    # đọc style — mà chỉ vỡ với văn bản có bảng, nên dễ lọt qua lúc thử.
    def _di(phan_tu, trong_bang: bool):
        for con in phan_tu.iterchildren():
            if con.tag == qn("w:p"):
                ket_qua.append((Paragraph(con, doc), trong_bang))
            elif con.tag == qn("w:tbl"):
                for hang in con.findall(qn("w:tr")):
                    for o in hang.findall(qn("w:tc")):
                        _di(o, True)

    _di(doc.element.body, False)
    return ket_qua


# ── Giá trị đang có hiệu lực (leo ngược chuỗi style) ─────────────────────────
def _hieu_luc_run(run, p: Paragraph, thuoc_tinh: str):
    gia_tri = getattr(run.font, thuoc_tinh)
    if gia_tri is not None:
        return gia_tri
    style = p.style
    for _ in range(10):                       # chặn vòng lặp nếu style tự tham chiếu
        if style is None:
            break
        gia_tri = getattr(style.font, thuoc_tinh, None)
        if gia_tri is not None:
            return gia_tri
        style = style.base_style
    return None


def _hieu_luc_doan(p: Paragraph, thuoc_tinh: str):
    gia_tri = getattr(p.paragraph_format, thuoc_tinh)
    if gia_tri is not None:
        return gia_tri
    # Thụt lề của đoạn có số tự động: Word lấy thụt lề trong ĐỊNH NGHĨA DANH
    # SÁCH trước style. Bỏ bước này thì đoạn "1. Thực trạng" (không tự khai lề)
    # bị đọc là lề 0 → không ép về 0 → chữ thụt 1,6 cm + 1 cm, lệch hẳn so với
    # "2. Giải pháp" ngay dưới (đoạn này có lề ở style nên được ép về 0).
    if thuoc_tinh in ("left_indent", "first_line_indent"):
        ind = _ind_danh_so(p)
        if thuoc_tinh == "left_indent" and "left" in ind:
            return Twips(ind["left"])
        if thuoc_tinh == "first_line_indent":
            if "hanging" in ind:
                return Twips(-ind["hanging"])
            if "firstLine" in ind:
                return Twips(ind["firstLine"])
    style = p.style
    for _ in range(10):
        if style is None:
            break
        gia_tri = getattr(style.paragraph_format, thuoc_tinh, None)
        if gia_tri is not None:
            return gia_tri
        style = style.base_style
    return None


def _dat_phong_chu(run, ten: str) -> None:
    """Đặt phông cho CẢ bốn loại ký tự, không chỉ ascii.

    `run.font.name` của python-docx chỉ ghi w:ascii và w:hAnsi. Chữ tiếng Việt
    có dấu trong file do Word tạo lại thường rơi vào nhánh w:cs (complex
    script); bỏ nhánh đó thì trên máy khác chữ có dấu hiện bằng phông khác chữ
    không dấu — cùng một dòng mà hai kiểu chữ.
    """
    run.font.name = ten
    rFonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for thuoc in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(thuoc), ten)


# ── Sửa chữ theo từng khoảng, giữ nguyên run ─────────────────────────────────
def ap_sua_text(p: Paragraph, sua: list[tuple[int, int, str]]) -> set[int]:
    """Áp danh sách (đầu, cuối, chữ mới) lên các run của đoạn.

    Trả về chỉ số các run bị đụng tới, để bên gọi tô màu đúng chỗ.

    Đi NGƯỢC từ cuối lên đầu: mỗi lần ghi là độ dài đoạn đổi, mọi chỉ số phía
    sau lệch theo. Đi xuôi thì phải cộng trừ bù, sai một lần là ghi đè lên
    giữa một chữ khác mà không có gì báo.
    """
    if not sua:
        return set()
    runs = p.runs
    if not runs:
        return set()

    # Mốc bắt đầu của từng run trên chuỗi ghép
    moc: list[int] = []
    tong = 0
    for r in runs:
        moc.append(tong)
        tong += len(r.text)

    da_sua: set[int] = set()
    for dau, cuoi, moi in sorted(sua, key=lambda x: x[0], reverse=True):
        if dau >= cuoi or cuoi > tong:
            continue
        lien_quan = [i for i, r in enumerate(runs)
                     if moc[i] < cuoi and moc[i] + len(r.text) > dau]
        if not lien_quan:
            continue
        dau_tien = lien_quan[0]
        r0 = runs[dau_tien]
        cuc_bo_dau = dau - moc[dau_tien]
        if len(lien_quan) == 1:
            cuc_bo_cuoi = cuoi - moc[dau_tien]
            r0.text = r0.text[:cuc_bo_dau] + moi + r0.text[cuc_bo_cuoi:]
        else:
            # Khoảng sửa vắt qua nhiều run: dồn chữ mới vào run ĐẦU (nó mang
            # định dạng của chỗ bắt đầu), xoá phần bị phủ ở các run sau.
            r0.text = r0.text[:cuc_bo_dau] + moi
            for i in lien_quan[1:-1]:
                runs[i].text = ""
            cuoi_cung = lien_quan[-1]
            runs[cuoi_cung].text = runs[cuoi_cung].text[cuoi - moc[cuoi_cung]:]
        da_sua.update(lien_quan)
        # Chuỗi ghép đã đổi → dựng lại mốc cho các lần sửa còn lại (đứng TRƯỚC
        # khoảng vừa ghi nên chỉ cần mốc phía trước, nhưng dựng lại cả cho gọn).
        moc, tong = [], 0
        for r in runs:
            moc.append(tong)
            tong += len(r.text)
    return da_sua


def _to_mau(p: Paragraph, chi_so: set[int] | None, mau: str) -> None:
    try:
        gia_tri = getattr(WD_COLOR_INDEX, mau)
    except AttributeError:
        _log.warning("Màu đánh dấu không hợp lệ: %s — dùng YELLOW", mau)
        gia_tri = WD_COLOR_INDEX.YELLOW
    runs = p.runs
    muc_tieu = range(len(runs)) if chi_so is None else chi_so
    for i in muc_tieu:
        if 0 <= i < len(runs) and runs[i].text:
            runs[i].font.highlight_color = gia_tri


def _xoa_danh_dau(p: Paragraph) -> None:
    for r in p.runs:
        r.font.highlight_color = None


# ── Định dạng một đoạn ───────────────────────────────────────────────────────
def _them(ds: list, loai: str, mo_ta: str) -> None:
    if (loai, mo_ta) not in ds:
        ds.append((loai, mo_ta))


def muc_gach_pho_bien(khoi, ma_list: list[str]) -> dict[str, float]:
    """Vị trí dấu gạch (cm, lề trái + thụt dòng đầu) gặp NHIỀU NHẤT, theo TỪNG mã thể thức.

    Là mốc "cấp ngoài cùng" cho `_le_muc_con`. Đo TRƯỚC khi áp định dạng —
    sau đó mọi đoạn đã bị ép cùng một mức, không còn gì để so. Hoà thì lấy mức
    nông hơn.

    Tách theo mã vì mỗi thành phần có mức thụt riêng: gộp chung thì 3 dòng
    "- Ban …" của khối Kính trình (sát lề) kéo mốc về 0 và mọi gạch đầu dòng
    của lời văn (thụt 1 cm) thành "mục con" — phản biện tái hiện được.
    """
    dem: dict[str, dict[float, int]] = {}
    for (p, _tb), ma in zip(khoi, ma_list):
        if ma in ("trong", "bang") or not nhan_dien.RE_GACH_DAU.match((p.text or "").strip()):
            continue
        le = _hieu_luc_doan(p, "left_indent")
        dau = _hieu_luc_doan(p, "first_line_indent")
        vi_tri = round(((le.cm if le is not None else 0.0)
                        + (dau.cm if dau is not None else 0.0)) * 20) / 20
        theo_ma = dem.setdefault(ma, {})
        theo_ma[vi_tri] = theo_ma.get(vi_tri, 0) + 1
    return {ma: min(d, key=lambda v: (-d[v], v)) for ma, d in dem.items()}


def _le_muc_con(p: Paragraph, hien_cm: float, dau_cm: float, mong_cm: float,
                thut, muc_gach_cm: float | None, chung: dict) -> float | None:
    """Đoạn gạch đầu dòng thụt sâu hơn cấp ngoài cùng — trả lề trái phải đặt (cm).

    None = không phải mục con, ép về mức chung như lời văn thường.

    Quy chuẩn đặt `le_trai_cm = 0` cho lời văn để dọn những khoảng thụt vô cớ
    do sao chép qua lại. Nhưng gạch đầu dòng thụt sâu hơn là **cách duy nhất
    trong .docx để tác giả nói "đây là mục con"** — QĐ 979 chỉ đánh số tới
    *điểm* (a, b, c), dưới đó không có cấp nào được khai, nên phân cấp chỉ còn
    trông vào thụt lề.

    Ép về 0 là **xoá phẳng phân cấp tác giả đã viết ra**: bốn mục con nằm ngang
    hàng với chính mục cha của chúng, đọc ra thành năm mục ngang cấp — sai
    nghĩa, không lỗi nào báo.

    Chỉ nhận khi: mức chung là 0 (không đụng thành phần có thụt riêng), đoạn mở
    đầu bằng dấu gạch, tác giả CÓ đặt lề trái (thụt dòng đầu lệch 1,27 cm vì dán
    từ văn bản khác không phải phân cấp — vẫn dọn về lề 0), và DẤU GẠCH đứng
    sâu hơn `muc_gach_cm` — vị trí gạch phổ biến nhất của cùng thành phần.

    So vị trí dấu gạch (lề trái + thụt dòng đầu), KHÔNG so riêng lề trái: danh
    sách dựng bằng thụt treo (lề 709, treo 142) có gạch ở đúng 1 cm, ngang hàng
    mọi gạch khác. Chỉ nhìn lề trái thì nhận nhầm là mục con, giữ lề 709 rồi
    cộng thêm thụt dòng đầu 1 cm → gạch trôi ra 2,25 cm (Tờ trình bàn giao
    chứng từ, "Tài liệu trình kèm"). So với mốc CỦA VĂN BẢN chứ không với 1 cm
    cố định: bullet mặc định của Word để cấp 1 ở 0 và cấp 2 ở 0,63 cm — mốc cố
    định là ép phẳng cả hai cấp.

    Lề trả về giữ nguyên độ sâu tương đối: gạch sâu hơn mốc bao nhiêu thì sau
    chuẩn hoá vẫn sâu hơn gạch cấp ngoài cùng bấy nhiêu.
    """
    if not chung.get("giu_thut_muc_con") or mong_cm != 0.0:
        return None
    if not nhan_dien.RE_GACH_DAU.match((p.text or "").strip()):
        return None
    if hien_cm <= mong_cm + 0.02:
        return None
    if muc_gach_cm is None or thut is None:
        return hien_cm
    sau_hon = hien_cm + dau_cm - muc_gach_cm
    return mong_cm + sau_hon if sau_hon > 0.02 else None


def _dong_bo_dau_doan(p: Paragraph, co, dam, phong: str | None) -> bool:
    """Chép cỡ chữ / đậm / phông xuống `w:pPr/w:rPr`. Trả True nếu có sửa.

    Số thứ tự và dấu chấm tròn của **danh sách tự động** không nằm trong một
    `<w:r>` nào — Word sinh chúng lúc hiển thị và lấy định dạng từ `rPr` của
    **dấu đoạn** (`w:pPr/w:rPr`). Sửa cỡ chữ cho từng run vì thế không chạm tới
    chúng.

    Đã gặp thật trên một Tờ trình: lời văn đã về cỡ 14 nhưng số "4." "5." và
    "I." "II." vẫn in ra bằng nửa con chữ, vì dấu đoạn còn giữ `w:sz = 16`
    (cỡ 8) của bản gốc. Nhìn ra ngay là hỏng, mà không có lỗi nào báo và nhật
    ký cũng không ghi gì — cỡ chữ của run đúng cả.

    Chỉ đụng vào đoạn CÓ đánh số / dấu chấm tròn tự động. Đoạn thường thì `rPr`
    của dấu đoạn không hiện ra ở đâu cả — ghi vào đó là sửa hàng nghìn đoạn mà
    không ai thấy khác gì, và mỗi đoạn lại đẻ một dòng nhật ký vô nghĩa.

    Chỉ ghi những thuộc tính thành phần thể thức KHAI RÕ: `dam = None` nghĩa là
    "giữ nguyên", ép vào đây là tự quyết thay người soạn. Đoạn rỗng đã bị lọc
    từ trước (`ma == "trong"`), nên không lo đổi chiều cao dòng trắng.
    """
    if co is None and dam is None and not phong:
        return False
    if _tim_numPr(p) is None:
        return False
    pPr = p._p.get_or_add_pPr()
    rPr = pPr.find(qn("w:rPr"))
    if rPr is None:
        rPr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        # rPr phải là con CUỐI của pPr theo lược đồ; sai chỗ thì Word bỏ qua cả đoạn.
        pPr.append(rPr)

    da_sua = False

    def _dat(ten: str, thuoc: dict) -> None:
        nonlocal da_sua
        cu = rPr.find(qn(f"w:{ten}"))
        moi = parse_xml(
            f'<w:{ten} {nsdecls("w")} '
            + " ".join(f'w:{k}="{v}"' for k, v in thuoc.items()) + "/>")
        if cu is not None:
            if all(cu.get(qn(f"w:{k}")) == str(v) for k, v in thuoc.items()):
                return
            rPr.remove(cu)
        rPr.append(moi)
        da_sua = True

    if co:
        nua_diem = str(int(round(float(co) * 2)))
        _dat("sz", {"val": nua_diem})
        _dat("szCs", {"val": nua_diem})
    if dam is not None:
        _dat("b", {"val": "1" if dam else "0"})
        _dat("bCs", {"val": "1" if dam else "0"})
    if phong:
        _dat("rFonts", {"ascii": phong, "hAnsi": phong, "cs": phong})
    return da_sua


def _dinh_dang_doan(p: Paragraph, ma: str, tp: dict, chung: dict,
                    muc_gach_cm: float | None = None,
                    truoc_pt: float | None = None) -> list[tuple[str, str]]:
    """Áp cỡ chữ / kiểu chữ / căn lề cho đoạn.

    Trả `[(loại, mô tả), …]`. `loại` là "chung" khi sửa đổi đó áp đồng loạt
    cho cả văn bản (giãn dòng, cách đoạn, phông chữ…) — những thứ đó vào mục
    "Sửa chung" của nhật ký và KHÔNG bôi màu; "rieng" là khác biệt của riêng
    đoạn đó (cỡ chữ, đậm/nghiêng, căn lề) — có bôi màu.

    Phân loại bằng nhãn trả về chứ không bằng cách đoán tiền tố chuỗi ở bên
    gọi: đổi một chữ trong nhãn là phân loại im lặng sai, không lỗi nào báo.
    """
    ghi_nhan: list[tuple[str, str]] = []
    pf = p.paragraph_format

    # ── Phông chữ và màu chữ: áp cho MỌI đoạn, kể cả ô bảng ──
    if chung.get("ep_phong_chu"):
        ten = chung.get("phong_chu") or "Times New Roman"
        for r in p.runs:
            if r.text and _hieu_luc_run(r, p, "name") != ten:
                _dat_phong_chu(r, ten)
                _them(ghi_nhan, "chung", f"phông chữ → {ten}")
    if chung.get("ep_mau_den"):
        for r in p.runs:
            mau = r.font.color
            if r.text and mau is not None and mau.rgb is not None and str(mau.rgb) != "000000":
                r.font.color.rgb = RGBColor(0, 0, 0)
                _them(ghi_nhan, "chung", "màu chữ → đen")

    # Ô bảng số liệu: cỡ chữ và căn lề do người soạn quyết (Điều 4.2 cho phép
    # bảng biểu trình bày riêng). Dừng ở đây.
    if ma in ("bang", "trong") or not tp:
        return ghi_nhan

    # ── Cỡ chữ ──
    co = tp.get("co")
    if co:
        moi = Pt(float(co))
        for r in p.runs:
            if not r.text:
                continue
            hien = _hieu_luc_run(r, p, "size")
            if hien is None or abs(hien.pt - float(co)) > _SAI_SO_PT:
                r.font.size = moi
                _them(ghi_nhan, "rieng", f"cỡ chữ → {_so(co)}")

    # ── Đậm / nghiêng ──
    for khoa, thuoc, nhan in (("dam", "bold", "chữ đậm"), ("nghieng", "italic", "chữ nghiêng")):
        mong_muon = tp.get(khoa)
        if mong_muon is None:
            continue
        for r in p.runs:
            if not r.text:
                continue
            if bool(_hieu_luc_run(r, p, thuoc)) != bool(mong_muon):
                setattr(r.font, thuoc, bool(mong_muon))
                _them(ghi_nhan, "rieng", f"{nhan} → {'bật' if mong_muon else 'tắt'}")

    # ── Dấu đoạn: nơi Word lấy định dạng cho SỐ tự động ──
    if _dong_bo_dau_doan(p, co, tp.get("dam"),
                         chung.get("phong_chu") if chung.get("ep_phong_chu") else None):
        _them(ghi_nhan, "chung", "định dạng của số/gạch đầu dòng tự động")

    # ── Căn lề ──
    can = tp.get("can")
    if can in _CAN_LE:
        hien = _hieu_luc_doan(p, "alignment")
        if hien != _CAN_LE[can]:
            pf.alignment = _CAN_LE[can]
            _them(ghi_nhan, "rieng", f"căn {_TEN_CAN_LE[can]}")

    # ── Thụt dòng đầu và thụt cả đoạn ──
    thut = tp.get("thut_cm")
    dau_goc = _hieu_luc_doan(p, "first_line_indent")
    dau_goc_cm = 0.0 if dau_goc is None else dau_goc.cm
    if thut is not None:
        hien_cm = dau_goc_cm
        if abs(hien_cm - float(thut)) > 0.02:
            pf.first_line_indent = Cm(float(thut))
            _them(ghi_nhan, "chung", "thụt dòng đầu theo từng thành phần thể thức")
    le_trai = tp.get("le_trai_cm")
    if le_trai is not None:
        hien = _hieu_luc_doan(p, "left_indent")
        hien_cm = 0.0 if hien is None else hien.cm
        le_con = _le_muc_con(p, hien_cm, dau_goc_cm, float(le_trai), thut,
                             muc_gach_cm, chung)
        if le_con is not None:
            if abs(hien_cm - le_con) > 0.02:
                pf.left_indent = Cm(le_con)
            _them(ghi_nhan, "chung", "giữ nguyên thụt lề của mục con")
        elif abs(hien_cm - float(le_trai)) > 0.02:
            pf.left_indent = Cm(float(le_trai))
            _them(ghi_nhan, "chung", "lề trái đoạn theo từng thành phần thể thức")

    # ── Giãn dòng và cách đoạn ──
    # Thành phần khai riêng thì ÉP CHÍNH XÁC (kể cả ép về 0); không khai thì
    # theo giá trị chung và chỉ NÂNG LÊN cho đủ mức tối thiểu Điều 12.6 đòi.
    #
    # Hai cách xử lý khác nhau là có chủ đích. Khối thể thức đầu trang phải ép
    # chính xác về dòng đơn / 0pt — Điều 7.3 và 8.2 nói Quốc hiệu, Tiêu ngữ,
    # tên đơn vị "trình bày cách nhau dòng đơn", nên ở đó "chỉ nâng lên" là sai
    # hướng: file đang giãn 1,5 sẽ được giữ nguyên 1,5 và Tiêu ngữ vẫn nằm xa
    # Quốc hiệu. Ngược lại với lời văn, quy định chỉ nêu mức TỐI THIỂU nên ai
    # để 8pt vẫn hợp lệ, hạ xuống 6pt là sửa thứ không sai.
    gian = tp.get("gian_dong")
    ep_chinh_xac = gian is not None
    if gian is None:
        gian = chung.get("gian_dong")
    if gian:
        hien = _hieu_luc_doan(p, "line_spacing")
        # line_spacing trả float khi là bội số, trả Length khi đặt cứng theo pt
        hien_so = hien if isinstance(hien, (int, float)) else None
        if hien_so is None or abs(float(hien_so) - float(gian)) > 0.01:
            pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            pf.line_spacing = float(gian)
            _them(ghi_nhan, "rieng" if ep_chinh_xac else "chung",
                  f"giãn dòng → {_so(gian)}")

    cach = tp.get("cach_doan_pt")
    ep_chinh_xac = cach is not None
    if cach is None:
        cach = chung.get("cach_doan_pt")
    if cach is not None:
        hien = _hieu_luc_doan(p, "space_after")
        hien_pt = 0.0 if hien is None else hien.pt
        lech = (abs(hien_pt - float(cach)) > _SAI_SO_PT if ep_chinh_xac
                else hien_pt < float(cach) - _SAI_SO_PT)
        if lech:
            pf.space_after = Pt(float(cach))
            _them(ghi_nhan, "rieng" if ep_chinh_xac else "chung",
                  f"cách đoạn → {_so(cach)} pt")
        if ep_chinh_xac and float(cach) > 0 and _tat_cach_doan_cung_style(p):
            _them(ghi_nhan, "rieng", "tắt «không cách đoạn cùng style»")
    # ── Khoảng trống TRƯỚC đoạn ──
    # Khoảng cách giữa hai đoạn là `space_after` của đoạn trên CỘNG
    # `space_before` của đoạn dưới. Để cả hai cùng có giá trị thì con số thật
    # không hiện ở đâu cả: file đặt 7pt/7pt cho ra khoảng cách 14pt, mà hộp
    # Paragraph của Word chỉ hiện hai số 7. Đưa `space_before` về 0 để khoảng
    # cách chỉ do `space_after` quyết định — đúng một nguồn, nhìn là biết.
    #
    # `truoc_pt` = bên gọi ĐÒI một khoảng trước đoạn (khối phê duyệt dưới họ
    # tên người ký — xem `la_khoi_ky_moi`). Ép chính xác, không bỏ về 0.
    hien_tr = _hieu_luc_doan(p, "space_before")
    hien_tr_pt = 0.0 if hien_tr is None else hien_tr.pt
    if truoc_pt is not None:
        if abs(hien_tr_pt - float(truoc_pt)) > _SAI_SO_PT:
            pf.space_before = Pt(float(truoc_pt))
            _them(ghi_nhan, "rieng", f"cách khối trên {_so(truoc_pt)} pt (một dòng)")
    elif chung.get("bo_khoang_truoc_doan") and hien_tr_pt > _SAI_SO_PT:
        pf.space_before = Pt(0)
        _them(ghi_nhan, "chung", "bỏ khoảng trống trước đoạn")

    return ghi_nhan


# Thẻ đứng SAU w:contextualSpacing trong w:pPr theo lược đồ.
_SAU_CONTEXTUAL = ("w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection",
                   "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
                   "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def _tat_cach_doan_cung_style(p: Paragraph) -> bool:
    """Tắt `w:contextualSpacing` đang có hiệu lực trên đoạn. Trả True nếu có sửa.

    Thẻ này (ô "Don't add space between paragraphs of the same style") bảo Word
    BỎ khoảng cách đoạn khi đoạn kề cùng style — cả văn bản dùng "Normal" thì
    nghĩa là bỏ gần hết. Gặp thật (VB goc 23/09/2026): ô "Kính trình:" đã được
    đặt cách đoạn 6 pt mà vẫn dính sát "I. Căn cứ trình"; gỡ thẻ là hiện đúng
    6 pt (đã dựng PDF bằng Word để đo). Hộp Paragraph vẫn hiện "After: 6 pt" nên
    không ai nhìn ra vì sao.

    Chỉ gọi cho thành phần quy chuẩn KHAI RIÊNG khoảng cách > 0: ở đó con số là
    điều khoản, không phải thói quen. Lời văn thường không đụng — đổi hàng loạt
    là đổi bố cục của những văn bản người soạn cố ý dựng khít.
    """
    pPr = p._p.get_or_add_pPr()
    el = pPr.find(qn("w:contextualSpacing"))
    if el is not None:
        if el.get(qn("w:val")) in ("0", "false", "off"):
            return False
        el.set(qn("w:val"), "0")
        return True

    # Không khai trên đoạn — xem style có bật không.
    style, bat = p.style, False
    for _ in range(10):
        if style is None:
            break
        st_pPr = style.element.find(qn("w:pPr"))
        cs = st_pPr.find(qn("w:contextualSpacing")) if st_pPr is not None else None
        if cs is not None:
            bat = cs.get(qn("w:val")) not in ("0", "false", "off")
            break
        style = style.base_style
    if not bat:
        return False
    moi = parse_xml(f'<w:contextualSpacing {nsdecls("w")} w:val="0"/>')
    moc = next((pPr.find(qn(t)) for t in _SAU_CONTEXTUAL if pPr.find(qn(t)) is not None), None)
    if moc is not None:
        moc.addprevious(moi)
    else:
        pPr.append(moi)
    return True


def _ep_hoa_thuong(p: Paragraph, kieu: str | None) -> set[int]:
    """Ép cả đoạn thành in hoa (hoặc in thường). Trả chỉ số run đã đổi.

    Sửa THẮNG từng run chứ không gọi `ap_sua_text()` với một khoảng phủ cả đoạn:
    khoảng phủ nhiều run sẽ dồn chữ về run đầu và làm rỗng các run còn lại — đổi
    hoa/thường vốn không đổi độ dài, không có lý do gì phải trả giá đó.
    """
    if kieu not in ("hoa", "thuong"):
        return set()
    da_doi: set[int] = set()
    for i, r in enumerate(p.runs):
        moi = r.text.upper() if kieu == "hoa" else r.text.lower()
        if moi != r.text:
            r.text = moi
            da_doi.add(i)
    return da_doi


# ── Khối chữ ký ──────────────────────────────────────────────────────────────
# Chiều cao một dòng đơn của Times New Roman = 1,15 × cỡ chữ (ascent 1825 +
# descent 443 + lineGap 87 trên 2048 đơn vị/em) — đúng con số Word dùng cho
# giãn dòng "Single".
_DONG_DON_TNR = 1.15

# Thẻ đứng SAU w:sz / w:szCs trong w:rPr theo lược đồ — chèn sz trước thẻ đầu tiên gặp.
_SAU_SZ = ("w:highlight", "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText",
           "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
           "w:specVanish", "w:oMath", "w:rPrChange")


def mot_dong_pt(co_pt: float) -> float:
    return round(float(co_pt) * _DONG_DON_TNR, 1)


def _hang_bang(p: Paragraph) -> list:
    """Mọi `w:tr` bao quanh đoạn, từ trong ra ngoài."""
    ket_qua, el = [], p._p.getparent()
    while el is not None:
        if el.tag == qn("w:tr"):
            ket_qua.append(el)
        el = el.getparent()
    return ket_qua


def la_khoi_ky_moi(ma_list: list[str], i: int, khoi=None) -> bool:
    """Đoạn `i` mở đầu một khối ký THỨ HAI ngay DƯỚI họ tên người ký.

    Mẫu 06 (Tờ trình): dưới "Họ và tên" là khối "PHÊ DUYỆT CỦA [NGƯỜI CÓ THẨM
    QUYỀN]" / "Ý KIẾN CỦA [LÃNH ĐẠO]", cách một dòng trống. Nhận bằng vị trí,
    không bằng chữ: `quyen_han_chuc_vu` mà đoạn có chữ liền trước là họ tên.

    Hai ca KHÔNG phải (phản biện dựng lại được cả hai):

    * **Hai chữ ký song song** — ô trái "KT. GIÁM ĐỐC … Nguyễn Văn A", ô phải
      "TRƯỞNG PHÒNG … Trần Văn B" cùng một hàng bảng. Thứ tự đọc XML đặt ô phải
      ngay sau họ tên ô trái, nhưng trên trang nó nằm NGANG chứ không ở dưới;
      cộng khoảng trước là chữ ký bên phải tụt một dòng. Chặn: đoạn nằm trong
      cùng hàng bảng (`w:tr`) với họ tên.
    * **Tác giả đã để dòng trống** giữa họ tên và khối mới — cộng thêm một dòng
      nữa là cách hai dòng.

    `khoi = None` (gọi riêng lẻ trong test) thì bỏ qua kiểm hàng bảng.
    """
    if ma_list[i] != "quyen_han_chuc_vu":
        return False
    j = next((k for k in range(i - 1, -1, -1) if ma_list[k] != "trong"), -1)
    if j < 0 or ma_list[j] != "ho_ten_nguoi_ky":
        return False
    if j != i - 1:
        return False                       # đã có dòng trống ngăn cách
    if khoi is not None:
        hang_ten = _hang_bang(khoi[j][0])
        if any(any(h is t for t in hang_ten) for h in _hang_bang(khoi[i][0])):
            return False
    return True


def chua_cho_ky(khoi, ma_list: list[str], co_pt: float) -> int:
    """Dòng trống giữa chức vụ và họ tên người ký lấy cỡ chữ của khối ký. Trả số dòng đã sửa.

    Chỗ ký là các dòng TRỐNG tác giả để giữa "GIÁM ĐỐC" và họ tên. Chiều cao
    dòng trống do cỡ chữ của DẤU ĐOẠN quyết định — mà vòng chuẩn hoá bỏ qua
    đoạn trống (mã `trong`), nên chúng giữ nguyên cỡ của bản gốc. Gặp thật (VB
    goc 23/09/2026): 5 dòng trống cỡ 8 dưới chức vụ đã lên cỡ 14 → chỗ ký chỉ
    còn ~1,6 cm. Đưa dòng trống về cỡ 14, dòng đơn, cách đoạn 0: 5 dòng ≈ 2,8 cm.

    Giữ nguyên SỐ dòng tác giả để — không tự thêm hay bớt: quy định không nêu
    chỗ ký cao bao nhiêu, và mỗi người ký một cỡ chữ ký.
    Dòng trống có hình (ảnh chữ ký, con dấu) thì để yên.
    """
    so = 0
    nua_diem = str(int(round(float(co_pt) * 2)))
    for i, ma in enumerate(ma_list):
        if ma != "quyen_han_chuc_vu":
            continue
        j = next((k for k in range(i + 1, len(ma_list)) if ma_list[k] != "trong"), -1)
        if j < 0 or ma_list[j] != "ho_ten_nguoi_ky":
            continue
        for k in range(i + 1, j):
            p = khoi[k][0]
            xml = p._p.xml
            if "<w:drawing" in xml or "<w:pict" in xml:
                continue
            da_sua = False
            for r in p.runs:
                if r.font.size is None or abs(r.font.size.pt - float(co_pt)) > _SAI_SO_PT:
                    r.font.size = Pt(float(co_pt))
                    da_sua = True
            pPr = p._p.get_or_add_pPr()
            rPr = pPr.find(qn("w:rPr"))
            if rPr is None:
                rPr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
                # Lược đồ: rPr đứng TRƯỚC sectPr và pPrChange (văn bản bật Track Changes).
                moc = next((pPr.find(qn(t)) for t in ("w:sectPr", "w:pPrChange")
                            if pPr.find(qn(t)) is not None), None)
                if moc is not None:
                    moc.addprevious(rPr)
                else:
                    pPr.append(rPr)
            for ten in ("w:sz", "w:szCs"):
                el = rPr.find(qn(ten))
                if el is not None:
                    if el.get(qn("w:val")) != nua_diem:
                        el.set(qn("w:val"), nua_diem)
                        da_sua = True
                    continue
                moi = parse_xml(f'<{ten} {nsdecls("w")} w:val="{nua_diem}"/>')
                if ten == "w:szCs" and rPr.find(qn("w:sz")) is not None:
                    rPr.find(qn("w:sz")).addnext(moi)
                else:
                    moc = next((rPr.find(qn(t)) for t in _SAU_SZ
                                if rPr.find(qn(t)) is not None), None)
                    if moc is not None:
                        moc.addprevious(moi)
                    else:
                        rPr.append(moi)
                da_sua = True
            pf = p.paragraph_format
            for thuoc in ("space_before", "space_after"):
                v = _hieu_luc_doan(p, thuoc)
                if v is None or v.pt > _SAI_SO_PT:
                    setattr(pf, thuoc, Pt(0))
                    da_sua = True
            ls = _hieu_luc_doan(p, "line_spacing")
            if not isinstance(ls, (int, float)) or abs(float(ls) - 1.0) > 0.01:
                pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
                pf.line_spacing = 1.0
                da_sua = True
            so += da_sua
    return so


# ── Danh sách tự động của Word ───────────────────────────────────────────────
def _tim_numPr(p: Paragraph):
    """Thẻ w:numPr đang chi phối đoạn — trên chính đoạn, hoặc trên style của nó.

    Bấm nút bullet trên thanh công cụ Word thì thẻ nằm trên ĐOẠN. Nhưng chọn
    style "List Bullet" / "List Paragraph" (và mọi đoạn do python-docx tạo với
    `style=`) thì thẻ nằm trên STYLE, đoạn không có gì cả. Chỉ đọc trên đoạn là
    bỏ sót đúng nửa số văn bản — mà bỏ sót thì không lỗi, chỉ là dấu chấm tròn
    nằm nguyên đó và không ai hiểu vì sao phần mềm "không làm gì".
    """
    pPr = p._p.pPr
    if pPr is not None and pPr.numPr is not None:
        return pPr.numPr
    style = p.style
    for _ in range(10):
        if style is None:
            break
        el = getattr(style, "element", None)
        st_pPr = el.find(qn("w:pPr")) if el is not None else None
        if st_pPr is not None:
            numPr = st_pPr.find(qn("w:numPr"))
            if numPr is not None:
                return numPr
        style = style.base_style
    return None


def _kieu_danh_so(doc, p: Paragraph) -> str | None:
    """'bullet' / 'so' / None — đoạn có dùng đánh số tự động của Word không.

    Số hiển thị trên màn hình do Word tự tính, KHÔNG nằm trong file dưới dạng
    chữ. Đọc bằng python-docx chỉ thấy một tham chiếu numId. Nên chỉ chuyển
    được loại 'bullet' (dấu chấm tròn — không có số nào phải tính); loại có số
    thì đổi thành chữ gõ tay đồng nghĩa với tự đếm lại toàn bộ, sai một chỗ là
    lệch số cả văn bản mà không ai biết. Mặc định để nguyên và ghi cảnh báo.
    """
    co_danh_so, lvl = _tim_lvl(p)
    if not co_danh_so:
        return None
    if lvl is None:
        return "khong_ro"
    fmt = lvl.find(qn("w:numFmt"))
    val = fmt.get(qn("w:val")) if fmt is not None else None
    return "bullet" if val == "bullet" else "so"


def _ind_danh_so(p: Paragraph) -> dict[str, int]:
    """Thụt lề (twip) khai trong định nghĩa cấp danh sách của đoạn: left / hanging / firstLine."""
    _co, lvl = _tim_lvl(p)
    ind = lvl.find(qn("w:pPr") + "/" + qn("w:ind")) if lvl is not None else None
    if ind is None:
        return {}
    ket_qua: dict[str, int] = {}
    for khoa, ten in (("left", "w:left"), ("left", "w:start"),
                      ("hanging", "w:hanging"), ("firstLine", "w:firstLine")):
        v = ind.get(qn(ten))
        if v is not None and v.lstrip("-").isdigit() and khoa not in ket_qua:
            ket_qua[khoa] = int(v)
    return ket_qua


def _tim_lvl(p: Paragraph):
    """`(có đánh số tự động không, thẻ w:lvl đang áp cho đoạn)`.

    Có đánh số mà không tra ra được định nghĩa cấp (thiếu numbering part,
    numId trỏ vào hư không) thì trả `(True, None)`.
    """
    numPr = _tim_numPr(p)
    if numPr is None:
        return False, None
    nut_id = numPr.find(qn("w:numId"))
    if nut_id is None:
        return False, None
    num_id = nut_id.get(qn("w:val"))
    nut_lvl = numPr.find(qn("w:ilvl"))
    muc = nut_lvl.get(qn("w:val")) if nut_lvl is not None else "0"
    if num_id in (None, "0"):
        return False, None
    try:
        goc = p.part.numbering_part.element
    except (AttributeError, KeyError, NotImplementedError, ValueError):
        return True, None

    abs_id = None
    for num in goc.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            el = num.find(qn("w:abstractNumId"))
            abs_id = el.get(qn("w:val")) if el is not None else None
            break
    if abs_id is None:
        return True, None

    for abs_num in goc.findall(qn("w:abstractNum")):
        if abs_num.get(qn("w:abstractNumId")) != abs_id:
            continue
        for lvl in abs_num.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) == muc:
                return True, lvl
    return True, None


# Khoảng từ đầu số tới đầu chữ khi cấp đánh số không khai thụt treo — 0,25 inch,
# đúng mức Word tự đặt cho danh sách mới.
_KHOANG_SAU_SO_TWIP = 360
# Khoảng hở tối thiểu giữa đuôi số và đầu chữ, tính theo cỡ chữ — rộng hơn một
# dấu cách (0,25 em) một chút cho số và chữ không trông như dính nhau.
_HO_SAU_SO_EM = 0.35


def _so_theo_dinh_dang(n: int, fmt: str | None) -> str | None:
    """Số `n` viết theo `w:numFmt`. None = định dạng không biết cách viết."""
    if fmt in (None, "decimal"):
        return str(n)
    if fmt == "decimalZero":
        return f"{n:02d}"
    if fmt in ("upperRoman", "lowerRoman"):
        la_ma, con = "", n
        for gia_tri, ky_hieu in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
                                 (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                                 (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            while con >= gia_tri:
                la_ma += ky_hieu
                con -= gia_tri
        return la_ma if fmt == "upperRoman" else la_ma.lower()
    if fmt in ("upperLetter", "lowerLetter"):
        chu = chr(ord("A") + (n - 1) % 26) * ((n - 1) // 26 + 1)
        return chu if fmt == "upperLetter" else chu.lower()
    return None


def _bat(rPr, the: str) -> bool | None:
    """Thẻ bật/tắt (w:b, w:i) trong rPr: True / False / None nếu không khai."""
    el = rPr.find(qn(the)) if rPr is not None else None
    if el is None:
        return None
    return el.get(qn("w:val")) not in ("0", "false", "off")


def _dem_muc_danh_so(goc_vb) -> tuple[dict, dict]:
    """Một lượt qua cả văn bản: số đoạn theo (numId, cấp) và số đoạn theo style.

    Chỉ numPr của chính đoạn — bỏ bản chụp cũ trong `w:pPrChange`. Đoạn không
    tự khai numPr thì đếm theo `pStyle` (đánh số khai trên style).
    """
    theo_num: dict[tuple[str, str], int] = {}
    theo_style: dict[str, int] = {}
    for el in goc_vb.iter(qn("w:p")):
        ppr = el.pPr
        if ppr is None:
            continue
        numPr = ppr.numPr
        if numPr is not None:
            nid = numPr.find(qn("w:numId"))
            il = numPr.find(qn("w:ilvl"))
            if nid is not None:
                khoa = (nid.get(qn("w:val")), il.get(qn("w:val")) if il is not None else "0")
                theo_num[khoa] = theo_num.get(khoa, 0) + 1
        elif ppr.pStyle is not None:
            theo_style[ppr.pStyle.val] = theo_style.get(ppr.pStyle.val, 0) + 1
    return theo_num, theo_style


def _be_rong_so_lon_nhat_twip(p: Paragraph, lvl, bo_nho: dict | None = None) -> int | None:
    """Chỗ (twip) cần để số RỘNG NHẤT của cấp danh sách này lọt, kèm khoảng hở.

    Lấy số rộng nhất cả cấp chứ không phải số của riêng đoạn: "I." và "III."
    cùng cấp phải có chữ thẳng hàng. Số lớn nhất ước bằng số đoạn cùng
    abstractNum + cùng cấp trong văn bản, cộng số bắt đầu lớn nhất (kể cả
    `startOverride`) — đánh số lại giữa chừng thì ước DƯ, tức khoảng hở rộng
    hơn cần một chút, không bao giờ để số tràn. Số La Mã rộng nhất không phải
    số lớn nhất ("VIII" rộng hơn "X") nên đo cả dãy.

    `bo_nho`: một dict dùng chung cho cả lượt chuẩn hoá. Không có nó thì mỗi đoạn
    có số lại duyệt cả cây XML — phản biện đo được 1.500 đoạn đánh số mất ~1 phút.
    """
    if bo_nho is None:
        bo_nho = {}
    cap = lvl.get(qn("w:ilvl")) or "0"
    if not cap.isdigit():
        return None
    fmt_el = lvl.find(qn("w:numFmt"))
    fmt = fmt_el.get(qn("w:val")) if fmt_el is not None else None
    if _so_theo_dinh_dang(1, fmt) is None:
        return None                     # bullet / định dạng lạ: không viết được số
    try:
        goc = p.part.numbering_part.element
    except (AttributeError, KeyError, NotImplementedError, ValueError):
        return None
    abs_id = lvl.getparent().get(qn("w:abstractNumId"))

    # ── Số bắt đầu và danh sách numId dùng chung abstractNum ──
    bat_dau = lvl.find(qn("w:start"))
    dau = int(bat_dau.get(qn("w:val"))) if bat_dau is not None and         (bat_dau.get(qn("w:val")) or "").isdigit() else 1
    num_ids: set[str] = set()
    for num in goc.findall(qn("w:num")):
        el = num.find(qn("w:abstractNumId"))
        if el is None or el.get(qn("w:val")) != abs_id:
            continue
        num_ids.add(num.get(qn("w:numId")))
        for ov in num.findall(qn("w:lvlOverride")):
            so = ov.find(qn("w:startOverride"))
            if ov.get(qn("w:ilvl")) == cap and so is not None and                     (so.get(qn("w:val")) or "").isdigit():
                dau = max(dau, int(so.get(qn("w:val"))))

    # ── Đếm số mục cùng cấp (đếm một lần cho cả văn bản) ──
    if "dem" not in bo_nho:
        bo_nho["dem"] = _dem_muc_danh_so(p._p.getroottree().getroot())
    theo_num, theo_style = bo_nho["dem"]
    dem = sum(n for (nid, il), n in theo_num.items() if nid in num_ids and il == cap)
    pPr = p._p.pPr
    if (pPr is None or pPr.numPr is None) and p.style is not None:
        dem += theo_style.get(p.style.style_id, 0)

    mau_el = lvl.find(qn("w:lvlText"))
    mau = mau_el.get(qn("w:val")) if mau_el is not None else f"%{int(cap) + 1}."

    # ── Kiểu chữ của số: rPr của cấp đè lên dấu đoạn, dấu đoạn đè lên run đầu ──
    rpr_lvl = lvl.find(qn("w:rPr"))
    rpr_dau = pPr.find(qn("w:rPr")) if pPr is not None else None
    run0 = p.runs[0] if p.runs else None
    co = None
    for rpr in (rpr_lvl, rpr_dau):
        sz = rpr.find(qn("w:sz")) if rpr is not None else None
        if sz is not None and (sz.get(qn("w:val")) or "").isdigit():
            co = int(sz.get(qn("w:val"))) / 2
            break
    if co is None:
        hl = _hieu_luc_run(run0, p, "size") if run0 is not None else None
        co = hl.pt if hl is not None else 14.0
    kieu = {}
    for the, thuoc in (("w:b", "bold"), ("w:i", "italic")):
        gt = _bat(rpr_lvl, the)
        if gt is None:
            gt = _bat(rpr_dau, the)
        if gt is None:
            gt = bool(_hieu_luc_run(run0, p, thuoc)) if run0 is not None else False
        kieu[thuoc] = gt

    # ── Đo (nhớ theo cấp + kiểu chữ: các đoạn cùng cấp khỏi đo lại) ──
    khoa = ("do", fmt, mau, dau, dem, co, kieu["bold"], kieu["italic"])
    if khoa in bo_nho:
        return bo_nho[khoa]
    rong_nhat = 0.0
    ket_qua: int | None = None
    for n in range(dau, dau + min(max(dem, 1), 200)):
        chu = re.sub(r"%(\d)", lambda m: _so_theo_dinh_dang(n, fmt)
                     if m.group(1) == str(int(cap) + 1) else "8", mau)
        w = do_chu.be_rong_pt(chu, co, kieu["bold"], kieu["italic"])
        if w is None:
            break
        rong_nhat = max(rong_nhat, w)
    else:
        ket_qua = int(round((rong_nhat + _HO_SAU_SO_EM * co) * 20))
    bo_nho[khoa] = ket_qua
    return ket_qua


def _giu_tab_sau_so(p: Paragraph, bo_nho: dict | None = None) -> bool:
    """Đặt điểm dừng tab ngay sau số tự động khi đoạn không còn thụt treo.

    Sau số tự động Word chèn một TAB. Danh sách dựng bằng thụt treo (lề trái
    1,5 cm, treo 0,5 cm) thì tab dừng ở chính lề trái — chữ nằm sát sau số.
    Chuẩn hoá ép lời văn về lề trái 0 + thụt dòng đầu 1 cm: hết thụt treo, tab
    trôi tới điểm dừng MẶC ĐỊNH kế tiếp (2,54 cm). Gặp thật trên Tờ trình
    Microgateway: "a.        Giao Trung tâm Thanh toán" — cách ~1,5 cm.

    Đặt tab stop RIÊNG trên đoạn, không đổi `w:suff` thành dấu cách: `suff`
    nằm trong định nghĩa danh sách dùng chung, đổi là đổi luôn những đoạn
    cùng danh sách mà vẫn giữ thụt treo (ô bảng chẳng hạn).

    Chọn điểm dừng theo thứ tự:
      1. Tab tác giả tự đặt trên đoạn mà số RỘNG NHẤT của cấp đó vẫn lọt → giữ
         nguyên. "I. Căn cứ trình" có tab 993 vừa khít — thay bằng thụt treo
         720 của danh sách là nới khoảng cách từ 0,75 lên 1,27 cm vô cớ.
      2. Có tab tác giả nhưng số tràn qua ("III." ở 567 tràn tab 993) → đặt
         ngay sau số rộng nhất. Tác giả đã tỏ ý muốn khoảng hẹp hơn thụt treo.
      3. Không có tab nào → thụt treo của cấp (hoặc 360), nhưng không hẹp hơn
         số rộng nhất — "10." rộng hơn treo 360 thì chữ không dính số.
    Đo không được (máy thiếu phông, định dạng số lạ) thì lùi về bước 3 không
    có chặn dưới. Tab `clear` (xoá tab của style) không phải tab tác giả đặt —
    bỏ qua, và không bao giờ gỡ (gỡ là trả tab của style về).

    `bo_nho`: dict dùng chung cho cả lượt, xem `_be_rong_so_lon_nhat_twip`.
    """
    co_danh_so, lvl = _tim_lvl(p)
    if not co_danh_so:
        return False
    if lvl is not None:
        suff = lvl.find(qn("w:suff"))
        if suff is not None and suff.get(qn("w:val")) in ("space", "nothing"):
            return False

    # Còn thụt treo thì lề trái đã là điểm dừng của tab, không có gì hỏng.
    # Đọc giá trị HIỆU LỰC (gồm cả thụt lề của định nghĩa danh sách) — đoạn
    # không tự khai lề trái thì Word lấy lề của danh sách, tính là 0 thì tab
    # đặt TRƯỚC vị trí số, vô tác dụng.
    dau = _hieu_luc_doan(p, "first_line_indent")
    if dau is not None and dau < 0:
        return False
    vi_tri_so = Length(int(_hieu_luc_doan(p, "left_indent") or 0) + int(dau or 0)).twips

    treo = _ind_danh_so(p).get("hanging")
    dich = vi_tri_so + (treo if treo else _KHOANG_SAU_SO_TWIP)
    pf = p.paragraph_format

    # ── Chọn điểm dừng ──
    tab = [(i, int(t.position.twips)) for i, t in enumerate(pf.tab_stops)
           if t.alignment != WD_TAB_ALIGNMENT.CLEAR]
    rong = _be_rong_so_lon_nhat_twip(p, lvl, bo_nho) if lvl is not None else None
    if rong is not None:
        can = vi_tri_so + rong
        tab_tac_gia = sorted(t for _, t in tab if vi_tri_so < t < dich - 20)
        vua = [t for t in tab_tac_gia if t >= can]
        if vua:
            dich = vua[0]
        elif tab_tac_gia:
            dich = can
        else:
            dich = max(dich, can)

    # Tab tác giả đặt GIỮA vị trí số và chỗ chữ phải bắt đầu mà số tràn qua là
    # tab của bố cục cũ. Để lại thì Word đặt chữ dính sát số, KHÔNG nhảy sang
    # điểm dừng kế tiếp — đo thật trên "III.Đề xuất triển khai" (tab 993 của
    # tác giả, số bắt đầu ở 567). Chỉ gỡ tab khai trên chính đoạn; tab ở style
    # thì không đụng.
    cu = [i for i, t in tab if vi_tri_so < t < dich - 20]
    da_co = any(abs(t - dich) <= 20 for _, t in tab)
    if da_co and not cu:
        return False
    for i in reversed(cu):
        del pf.tab_stops[i]
    if not da_co:
        pf.tab_stops.add_tab_stop(Twips(dich))
    return True


def dat_dau_cach_sau_so(khoi, ma_list: list[str]) -> int:
    """Sau số / dấu tự động của Word là MỘT dấu cách thay cho tab. Trả số cấp đã đổi.

    Người dùng chốt 23/09/2026: khoảng từ ký hiệu đầu dòng tới chữ là đúng một
    dấu cách, như số gõ tay "III. Thẩm quyền" — `bien_doi.chuan_danh_so` đã ép
    "1. " / "a) " / "- " cho chữ gõ tay, số tự động thì chưa. Gặp thật (VB goc):
    "I." "II." "IV." tự động cách chữ ~0,9 cm (tab tới thụt treo 1,27 cm của
    danh sách), còn "III." gõ tay cách một dấu cách — cùng cấp mà hai kiểu.

    Tab không làm được "một dấu cách": điểm dừng tab là một vị trí cố định, số
    hẹp ("I.") thì hở rộng, số rộng ("VIII.") tràn qua là nhảy sang điểm dừng
    kế tiếp. `w:suff="space"` bảo Word chèn đúng một dấu cách sau số, không đo gì.

    `suff` nằm trong ĐỊNH NGHĨA cấp danh sách, dùng chung mọi đoạn cùng cấp —
    nên cấp nào có đoạn nằm trong ô bảng SỐ LIỆU (`bang`) thì để nguyên: bảng
    giữ thụt treo của người soạn, đổi tab sang dấu cách là lệch cột của họ.
    """
    cap_dung: list = []
    cap_cam: list = []
    for (p, _tb), ma in zip(khoi, ma_list):
        if ma == "trong":
            continue
        co, lvl = _tim_lvl(p)
        if not co or lvl is None:
            continue
        dich = cap_cam if ma == "bang" else cap_dung
        if not any(lvl is x for x in dich):
            dich.append(lvl)

    so = 0
    for lvl in cap_dung:
        if any(lvl is x for x in cap_cam):
            continue
        suff = lvl.find(qn("w:suff"))
        if suff is not None:
            # "nothing": tác giả tự gõ khoảng cách vào lvlText ("Điều %1. ") —
            # đổi sang "space" là thành hai dấu cách. Chỉ đổi tab.
            if suff.get(qn("w:val")) in ("space", "nothing"):
                continue
            suff.set(qn("w:val"), "space")
        else:
            # Lược đồ: w:suff đứng ngay TRƯỚC w:lvlText.
            moi = parse_xml(f'<w:suff {nsdecls("w")} w:val="space"/>')
            moc = lvl.find(qn("w:lvlText"))
            if moc is not None:
                moc.addprevious(moi)
            else:
                lvl.append(moi)
        so += 1
    return so


def _go_danh_so_tu_dong(doc, p: Paragraph) -> None:
    """Bỏ đánh số tự động của đoạn, giữ nguyên chữ.

    Hai đường khác nhau tuỳ thẻ w:numPr nằm ở đâu:

    * Trên đoạn → xoá thẳng thẻ đó.
    * Trên STYLE → KHÔNG được xoá, vì style dùng chung: xoá một lần là mọi đoạn
      khác cùng style cũng mất dấu đầu dòng, kể cả đoạn phần mềm chưa xét tới.
      Thay vào đó đổi đoạn này về style thường — cách đó cũng gỡ luôn phần thụt
      lề riêng của style danh sách, thứ mà quy định không cho phép.

    Văn bản còn Track Changes thì sửa luôn BẢN CHỤP CŨ trong `w:pPrChange`.
    Để nguyên thì Word so bản chụp (còn đánh số) với hiện tại (hết) và hiểu là
    tác giả vừa xoá dấu gạch — vẫn vẽ dấu gạch cũ màu đỏ cạnh "- " gõ tay: bản
    in có hiện sửa đổi ra "– - Thực hiện…" (Tờ trình Microgateway, 8 dòng), còn
    người nhận bấm Reject All thì hai dấu gạch ở lại vĩnh viễn. Bản chụp chỉ
    mất đúng thẻ đánh số — mọi sửa định dạng khác của tác giả vẫn còn.
    """
    pPr = p._p.pPr
    cu = [el for el in pPr.findall(qn("w:pPrChange") + "/" + qn("w:pPr"))] \
        if pPr is not None else []
    if pPr is not None and pPr.numPr is not None:
        pPr.remove(pPr.numPr)
        for chup in cu:
            for numPr in chup.findall(qn("w:numPr")):
                chup.remove(numPr)
        return
    style_cu = p.style.style_id if p.style is not None else None
    try:
        p.style = doc.styles["Normal"]
    except KeyError:                       # tài liệu không có style "Normal"
        _log.warning("Không đổi được style danh sách về Normal")
        return
    for chup in cu:
        ps = chup.find(qn("w:pStyle"))
        if ps is not None and ps.get(qn("w:val")) == style_cu:
            ps.set(qn("w:val"), p.style.style_id)


def go_bullet_tu_dong(doc, khoi, ky_tu: str = "-") -> set[int]:
    """Đổi mọi danh sách CHẤM TRÒN tự động thành gạch đầu dòng gõ tay.

    Trả chỉ số (0-based, theo `khoi`) các đoạn đã đổi.

    ## Vì sao phải chạy TRƯỚC khi phân loại thể thức

    Dấu chấm tròn của danh sách tự động không nằm trong `p.text` — Word vẽ nó
    lúc hiển thị. Nên `nhan_dien` đọc dòng "Như trên;" mà không thấy dấu gạch
    đầu dòng nào, trong khi luật nhận khối Nơi nhận là "các dòng mở đầu bằng
    gạch đầu dòng, gặp dòng khác thì dừng". Kết quả đo được trên "TB Swift code
    Quảng Ninh.docx": cả sáu dòng Nơi nhận rơi vào mã `bang`, mà `bang` thì
    bước áp dụng cố ý không đụng cỡ chữ — khối Nơi nhận giữ nguyên mọi thứ của
    bản gốc, không cỡ 11, không căn trái, không giãn dòng đơn.

    Đổi trước rồi mới phân loại thì `p.text` đã có "- " thật và luật nhận khối
    chạy đúng như với văn bản gõ tay. Cùng lý do với `bo_ngat_trang_thu_cong()`.
    """
    da_doi: set[int] = set()
    for i, (p, _tb) in enumerate(khoi):
        # Đoạn RỖNG trong danh sách bullet phải để yên. Người soạn gõ Enter hai
        # lần giữa danh sách là có một mục trống; thêm "- " vào đó là biến một
        # dòng trắng thành một gạch đầu dòng không có chữ, và đoạn ấy từ mã
        # `trong` nhảy sang `noi_dung` — sai cả nhật ký lẫn số đoạn đếm được.
        if not p.text.strip():
            continue
        if _kieu_danh_so(doc, p) != "bullet":
            continue
        _go_danh_so_tu_dong(doc, p)
        if p.runs:
            p.runs[0].text = f"{ky_tu} " + p.runs[0].text
        else:
            p.add_run(f"{ky_tu} ")
        da_doi.add(i)
    return da_doi


# ── Số trang ─────────────────────────────────────────────────────────────────
def _da_co_so_trang(section) -> bool:
    """Section này đã có trường PAGE ở bất kỳ đầu/chân trang nào chưa.

    Phải soi đủ SÁU chỗ. Trước đây chỉ soi header mặc định, nên văn bản đã đánh
    số ở **chân trang** hoặc ở **header trang đầu** sẽ bị đánh thêm một số nữa —
    in ra hai con số chồng nhau, đúng thứ người dùng gặp trên một Tờ trình.
    """
    for ten in ("header", "first_page_header", "even_page_header",
                "footer", "first_page_footer", "even_page_footer"):
        phan = getattr(section, ten, None)
        if phan is None:
            continue
        try:
            xml = phan._element.xml
        except AttributeError:                                # noqa: PERF203
            continue
        if "PAGE" in xml or "fldSimple" in xml:
            return True
    return False


def _them_so_trang(section, co_chu: float, phong: str) -> bool:
    """Chèn số trang canh giữa vào lề trên, bỏ trang đầu (Điều 4.4).

    Chỉ chèn khi header đang TRỐNG và văn bản CHƯA đánh số ở đâu cả. Header có
    sẵn thường là logo hoặc dòng chỉ dẫn của đơn vị — ghi đè lên đó là xoá mất
    nội dung người dùng cố ý đặt; còn đánh thêm khi đã có số ở chân trang là in
    ra hai con số.
    """
    if _da_co_so_trang(section):
        return False
    section.different_first_page_header_footer = True
    header = section.header
    header.is_linked_to_previous = False
    if any(dp.text.strip() for dp in header.paragraphs):
        return False
    p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    if p.runs:
        return False
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for kieu, noi_dung in (("begin", None), (None, " PAGE "), ("end", None)):
        r = p.add_run()
        _dat_phong_chu(r, phong)
        r.font.size = Pt(float(co_chu))
        if kieu:
            r._r.append(parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="{kieu}"/>'))
        else:
            r._r.append(parse_xml(
                f'<w:instrText {nsdecls("w")} xml:space="preserve">{noi_dung}</w:instrText>'))
    return True


def _dat_lai_so_trang_dau(section) -> int | None:
    """Ép số trang đếm từ 1. Trả số cũ nếu có sửa, `None` nếu vốn đã đúng.

    `<w:pgNumType w:start="N"/>` trong `sectPr` bắt Word đếm trang từ N chứ
    không từ 1. Nó theo chân văn bản mỗi khi người soạn cắt một phần ra khỏi
    tài liệu dài rồi lưu thành file riêng — thứ hay gặp nhất ở đây.

    Đã xảy ra thật: "TB Swift code Quảng Ninh.docx" mang `w:start="23"`, nên
    dù số trang được chèn đúng chỗ (canh giữa lề trên, bỏ trang đầu) thì trang
    2 vẫn in ra "24". Chèn đúng mà đếm sai thì nhìn vẫn là sai.
    """
    pgnum = section._sectPr.find(qn("w:pgNumType"))
    if pgnum is None:
        return None
    cu = pgnum.get(qn("w:start"))
    if cu is None or cu == "1":
        return None
    pgnum.set(qn("w:start"), "1")
    try:
        return int(cu)
    except ValueError:
        return None


def bo_ngat_trang_thu_cong(doc) -> int:
    """Gỡ mọi ngắt trang do người soạn đặt tay. Trả số chỗ đã gỡ.

    ## Vì sao phải gỡ

    Ngắt trang tay được đặt theo BỐ CỤC CŨ của văn bản. Chuẩn hoá làm chữ cao
    lên (giãn dòng 1,2 theo Điều 12.6, lề trên 20 mm theo Điều 4) nên chỗ
    xuống trang dịch đi — dấu ngắt cũ rơi vào giữa chừng và đẻ ra một trang
    gần như trống.

    Đo trên "TB Swift code Quảng Ninh.docx": bản gốc 2 trang; chuẩn hoá xong
    thành **3 trang**, trong đó trang 2 chỉ có đúng MỘT đoạn văn. Gỡ dấu ngắt
    thì trở lại 2 trang, chữ chảy liền mạch. Đã kiểm riêng từng nguyên nhân:
    trả lề trên về 15 mm vẫn 3 trang, đổi dấu ngắt thành `pageBreakBefore`
    cũng vẫn 3 trang — chỉ gỡ hẳn mới hết.

    ## Gỡ thế nào cho không mất chữ

    Dấu ngắt nằm trong một `<w:r>`. Đoạn nào CHỈ chứa dấu ngắt thì bỏ cả đoạn
    (nó không phải lời văn, chỉ là chỗ chêm); đoạn có chữ thì chỉ nhấc riêng
    thẻ `<w:br>` ra, giữ nguyên chữ. `<w:pageBreakBefore/>` trong `pPr` cũng
    là ngắt trang, gỡ cùng.

    Việc này ghi vào nhật ký "Sửa chung" nên người dùng thấy được; tắt bằng ô
    *Bỏ ngắt trang thủ công* trong tab Cấu hình khi văn bản thật sự cần sang
    trang mới (Phụ lục ban hành kèm theo Quyết định chẳng hạn).
    """
    so = 0
    for p in list(doc.paragraphs):
        el = p._p
        brs = [b for b in el.iter(qn("w:br")) if b.get(qn("w:type")) == "page"]
        pbb = el.find(qn("w:pPr"))
        pbb = pbb.find(qn("w:pageBreakBefore")) if pbb is not None else None
        if not brs and pbb is None:
            continue
        so += 1
        if pbb is not None:
            pbb.getparent().remove(pbb)
        # Đoạn rỗng có thể đang giữ dấu NGẮT SECTION (`sectPr` trong `pPr`) —
        # xoá nó là gộp hai section làm một, mất luôn khổ giấy / lề / hướng
        # trang riêng của phần sau. Chỉ nhấc thẻ ngắt trang ra, giữ lại đoạn.
        giu_sect = (el.find(qn("w:pPr")) is not None
                    and el.find(qn("w:pPr")).find(qn("w:sectPr")) is not None)
        if brs and not p.text.strip() and not giu_sect:
            el.getparent().remove(el)
            continue
        for b in brs:
            b.getparent().remove(b)
    return so


def dat_trang(doc, cfg_trang: dict) -> list[str]:
    """Khổ giấy, định lề, số trang — áp cho MỌI section. Trả mô tả đã sửa."""
    if not cfg_trang.get("ap_dung"):
        return []
    ghi_nhan: list[str] = []
    do = [
        ("page_width", "rong_mm", "khổ giấy rộng"),
        ("page_height", "cao_mm", "khổ giấy cao"),
        ("top_margin", "le_tren_mm", "lề trên"),
        ("bottom_margin", "le_duoi_mm", "lề dưới"),
        ("left_margin", "le_trai_mm", "lề trái"),
        ("right_margin", "le_phai_mm", "lề phải"),
    ]
    for section in doc.sections:
        for thuoc, khoa, nhan in do:
            mong = cfg_trang.get(khoa)
            if mong is None:
                continue
            hien = getattr(section, thuoc)
            if hien is None or abs(hien.mm - float(mong)) > _SAI_SO_MM:
                setattr(section, thuoc, Mm(float(mong)))
                mo_ta = f"{nhan} → {_so(mong)} mm"
                if mo_ta not in ghi_nhan:
                    ghi_nhan.append(mo_ta)
        if cfg_trang.get("danh_so_trang"):
            try:
                if _them_so_trang(section, cfg_trang.get("co_so_trang") or 14,
                                  "Times New Roman"):
                    if "đánh số trang (bỏ trang đầu)" not in ghi_nhan:
                        ghi_nhan.append("đánh số trang (bỏ trang đầu)")
                cu = _dat_lai_so_trang_dau(section)
                if cu is not None:
                    mo_ta = f"đánh số trang lại từ 1 (văn bản gốc đánh từ {cu})"
                    if mo_ta not in ghi_nhan:
                        ghi_nhan.append(mo_ta)
            except Exception as e:                        # noqa: BLE001
                _log.warning("Không chèn được số trang: %s", e)
    return ghi_nhan
