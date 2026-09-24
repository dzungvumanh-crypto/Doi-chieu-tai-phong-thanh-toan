"""Đường kẻ ngang dưới Tiêu ngữ, tên đơn vị ban hành và trích yếu.

## Đây không phải gạch chân

Điều 7.2 và 8.2 nói "phía dưới có **đường kẻ ngang, nét liền**", kèm độ dài
riêng: dưới Tiêu ngữ dài **bằng** dòng chữ, dưới tên đơn vị và trích yếu dài
**1/3 đến 1/2** dòng chữ. Gạch chân (`w:u`) không làm được điều đó — nó luôn
dài đúng bằng chữ, không ngắn hơn được, và nằm sát chân chữ.

Mẫu 979 vẽ bằng đối tượng đường thẳng rời: đếm trong `document.xml` của
`Phần VB_Hướng dẫn thể thức văn bản.docx` có **7 thẻ `<v:line>`**, và **không
có** thẻ gạch chân nào, cũng không có viền đoạn (`w:pBdr`). Module này làm
đúng như vậy.

## Vì sao không dùng viền đoạn cho gọn

`w:pBdr/w:bottom` dễ viết hơn nhiều, nhưng nó kéo dài hết bề ngang của đoạn.
Quy định đòi 1/3–1/2 dòng chữ — viền đoạn không cắt ngắn được, nên dùng nó là
đổi một cái sai (gạch chân) lấy một cái sai khác.

## Chạy lại lần hai không vẽ chồng

`da_co_duong_ke()` dò cả `<v:line>` lẫn `<w:drawing>` ở đoạn kế tiếp trước khi
vẽ. Thiếu bước này thì mỗi lần chuẩn hoá lại chồng thêm một vạch nữa.
"""
import logging

from docx.oxml import parse_xml
from docx.oxml.ns import qn

from . import do_chu

_log = logging.getLogger(__name__)

_VML = 'xmlns:v="urn:schemas-microsoft-com:vml"'
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

# Tỷ lệ độ dài đường kẻ so với dòng chữ, theo Điều 7.2 / 8.2 / 11.2.
# Tiêu ngữ lấy trọn 1,0. Tên đơn vị lấy 1/2 — cận TRÊN của dải "1/3 đến 1/2",
# đúng mức đo được trên Phụ lục V (0,50–0,57 ở mọi mẫu có tên đơn vị). Người
# dùng từng đề nghị 2/3 (23/09/2026): vượt dải Điều 8.2 nên không lấy.
# Trích yếu giữ 0,4: trích yếu dài cả dòng (~440 pt) mà kẻ 1/2 là vạch dài
# hơn cả tên đơn vị, lệch hẳn khối đầu.
TY_LE = {
    "tieu_ngu": 1.0,
    "ten_dv_ban_hanh": 0.5,
    "trich_yeu": 0.4,
}

_DAI_TOI_THIEU_PT = 20.0


# Dấu hiệu của một đối tượng ĐƯỜNG THẲNG. Word cũ ghi bằng VML (`<v:line>`),
# Word từ 2007 ghi bằng DrawingML: một shape có hình dựng sẵn là "line" (menu
# Insert → Shapes → Line, Word gọi là "Straight Connector").
_HINH_DUONG_KE = ('<v:line', 'prstGeom prst="line"', 'prst="straightConnector1"')


def _co_hinh_duong_ke(xml: str) -> bool:
    return any(dau in xml for dau in _HINH_DUONG_KE)


def da_co_duong_ke(p) -> bool:
    """Đã có sẵn một đường kẻ cho đoạn `p` rồi hay chưa.

    Phải soi HAI chỗ, vì có hai cách người soạn đặt vạch:

    * **Đoạn kế tiếp** — cách phần mềm này vẽ: một đoạn riêng chỉ chứa vạch.
    * **Chính đoạn `p`** — cách Word đặt khi người dùng vẽ tay: hình được
      *neo* vào đoạn có chữ, `positionV relativeFrom="paragraph"` đẩy nó
      xuống dưới dòng chữ. Nhìn trên màn hình y hệt, nhưng nằm trong cùng một
      `<w:p>` với chữ.

    Bỏ sót vế thứ hai là **vẽ chồng vạch thứ hai lên văn bản vốn đã đúng** —
    đã xảy ra thật với "TB Swift code Quảng Ninh.docx": cả Tiêu ngữ lẫn tên
    đơn vị ban hành đều có sẵn một Straight Connector neo trong đoạn, chuẩn
    hoá xong thành hai vạch chồng nhau.

    Ở chính đoạn `p` chỉ nhận đúng hình ĐƯỜNG THẲNG, không nhận mọi
    `<w:drawing>`: đoạn tên đơn vị hay có logo kèm theo, coi logo là vạch thì
    văn bản thiếu hẳn đường kẻ mà không có lỗi nào báo.
    """
    if _co_hinh_duong_ke(p._p.xml):
        return True
    ke = p._p.getnext()
    if ke is None or ke.tag != qn("w:p"):
        return False
    xml = ke.xml
    # Đoạn kế tiếp: nới tay hơn — một đoạn RỖNG chỉ chứa hình thì hình đó gần
    # như chắc chắn là vạch, và đó cũng đúng thứ phần mềm này tự vẽ ra.
    if _co_hinh_duong_ke(xml) or "<w:drawing" in xml or "<v:rect" in xml:
        return True

    # Xa hơn một đoạn: vạch neo vào một dòng TRỐNG bên dưới. Gặp thật trên Tờ
    # trình Microgateway — trích yếu, một dòng trống, rồi dòng trống chứa
    # Straight Connector; soi mỗi đoạn liền dưới thì vẽ thêm vạch thứ hai
    # ngay trên vạch của tác giả. Chỉ đi qua dòng không có chữ (gặp chữ là
    # sang phần khác), tối đa 3 dòng, và chỉ nhận đúng hình đường thẳng.
    for _ in range(3):
        if "".join(t.text or "" for t in ke.iter(qn("w:t"))).strip():
            return False
        ke = ke.getnext()
        if ke is None or ke.tag != qn("w:p"):
            return False
        xml = ke.xml
        if _co_hinh_duong_ke(xml):
            return True
    return False


def go_gach_chan(p) -> bool:
    """Bỏ mọi cách kẻ vạch SAI HÌNH THỨC trên đoạn. Trả True nếu có gì bị gỡ.

    Hai cách đều cho ra một vạch nhìn giống đường kẻ ngang, và cả hai đều
    không làm được thứ Điều 7.2 / 8.2 đòi:

    * **Gạch chân** (`w:u`) luôn dài đúng bằng chữ, không ngắn hơn được.
    * **Viền dưới của đoạn** (`w:pBdr/w:bottom`) luôn dài hết bề ngang đoạn.

    Quy định đòi vạch dưới tên đơn vị và trích yếu chỉ dài **1/3 đến 1/2** dòng
    chữ — cả hai cách trên đều chịu. Gỡ đi rồi vẽ lại bằng đối tượng đường
    thẳng rời, đúng cách mẫu 979 làm.

    Không gỡ thì thành **hai vạch chồng nhau**: `da_co_duong_ke()` cố ý không
    nhận `w:pBdr` là "đã có vạch", vì nhận nó nghĩa là chấp nhận một vạch sai
    độ dài và bỏ luôn việc vẽ vạch đúng.

    Chỉ nhấc riêng `w:bottom`, không xoá cả `w:pBdr`: đoạn có thể đang có viền
    trên / trái / phải mà người soạn cố ý đặt.
    """
    da_go = False
    for r in p.runs:
        if r.font.underline:
            r.font.underline = False
            da_go = True

    pPr = p._p.find(qn("w:pPr"))
    pBdr = pPr.find(qn("w:pBdr")) if pPr is not None else None
    if pBdr is not None:
        duoi = pBdr.find(qn("w:bottom"))
        if duoi is not None:
            pBdr.remove(duoi)
            da_go = True
        if len(pBdr) == 0:
            pBdr.getparent().remove(pBdr)
    return da_go


def _dai_duong_ke(p, ma: str, co_pt: float, dam: bool, nghieng: bool) -> float | None:
    rong = do_chu.be_rong_pt(p.text.strip(), co_pt, dam, nghieng)
    if not rong:
        return None
    dai = rong * TY_LE.get(ma, 0.4)
    return max(dai, _DAI_TOI_THIEU_PT)


# ── Chỉnh vạch tác giả đã vẽ sẵn ────────────────────────────────────────────
_EMU_MOI_PT = 12700
_NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_V = "urn:schemas-microsoft-com:vml"


def _doan_chua_vach(p) -> list:
    """Các `<w:p>` đang chứa vạch của đoạn `p` — cùng phạm vi dò với `da_co_duong_ke`."""
    ket_qua = [p._p] if _co_hinh_duong_ke(p._p.xml) else []
    ke = p._p.getnext()
    for _ in range(4):
        if ke is None or ke.tag != qn("w:p"):
            break
        if _co_hinh_duong_ke(ke.xml):
            ket_qua.append(ke)
            break
        if "".join(t.text or "" for t in ke.iter(qn("w:t"))).strip():
            break
        ke = ke.getnext()
    return ket_qua


_NS_WPG = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
_NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _la_vach(khung) -> bool:
    return any(g.get("prst") in ("line", "straightConnector1")
               for g in khung.iter(f"{{{_NS_A}}}prstGeom"))


def _thu_vach(ds_doan) -> tuple[list, list] | None:
    """(khung DrawingML, v:line) của ĐÚNG MỘT vạch. None = không chắc là một vạch rời → không đụng.

    Phản biện chỉ ra ba ca sửa nhầm, cả ba đều từ chối ở đây:
    * Hai vạch cùng neo một đoạn (Tiêu ngữ và tên đơn vị neo chung, toạ độ tuyệt
      đối) → cả hai bị ép cùng độ dài, kéo về giữa cùng một cột.
    * Vạch nằm trong NHÓM HÌNH cùng logo → đổi `cx` của nhóm mà không đổi
      `a:chExt` là méo cả nhóm.
    Một vạch Word ghi hai lần (DrawingML + VML dự phòng) — đếm theo DrawingML,
    chỉ khi không có DrawingML mới đếm VML nằm ngoài `mc:Fallback`.
    """
    khung, vml = [], []
    for doan in ds_doan:
        for k in list(doan.iter(f"{{{_NS_WP}}}anchor")) + list(doan.iter(f"{{{_NS_WP}}}inline")):
            if _la_vach(k):
                if any(True for _ in k.iter(f"{{{_NS_WPG}}}wgp")):
                    return None
                khung.append(k)
        for v in doan.iter(f"{{{_NS_V}}}line"):
            cha = v.getparent()
            while cha is not None and cha.tag not in (f"{{{_NS_V}}}group", f"{{{_NS_MC}}}Fallback"):
                cha = cha.getparent()
            if cha is not None and cha.tag == f"{{{_NS_V}}}group":
                return None
            vml.append((v, cha is not None))
    so = len(khung) if khung else sum(1 for _, du_phong in vml if not du_phong)
    if so != 1:
        return None
    return khung, [v for v, _ in vml]


def _trong_bang(el) -> bool:
    while el is not None:
        if el.tag == qn("w:tc"):
            return True
        el = el.getparent()
    return False


def _pt(gia_tri: str) -> float | None:
    """Toạ độ VML → point. "67.95pt" / "0" được; đơn vị khác (in, cm, px) → None."""
    g = (gia_tri or "").strip()
    if g.endswith("pt"):
        g = g[:-2]
    elif g not in ("", "0"):
        return None                                # số trần không đơn vị: không đoán
    try:
        return float(g or 0)
    except ValueError:
        return None


def _chinh_drawingml(khung, dai_emu: int, giu_tam: bool) -> tuple[bool, int | None]:
    """Đặt độ dài + vị trí ngang cho một khung DrawingML. Trả (có sửa, độ dài cũ EMU)."""
    da_sua = False
    extent = khung.find(f"{{{_NS_WP}}}extent")
    cu = int(extent.get("cx")) if extent is not None and (extent.get("cx") or "").isdigit() else None
    for ext in [extent, *khung.iter(f"{{{_NS_A}}}ext")]:
        # `a:ext` trong `a:extLst` là khối mở rộng, không có `cx` — bỏ qua.
        if ext is not None and ext.get("cx") is not None and ext.get("cx") != str(dai_emu):
            ext.set("cx", str(dai_emu))
            da_sua = True
    ngang = khung.find(f"{{{_NS_WP}}}positionH")
    if ngang is None:
        return da_sua, cu                          # hình inline: chữ canh giữa thì hình theo
    if giu_tam:
        # Neo trong ô bảng nhưng `layoutInCell="0"`: "column" là cột TRANG, canh
        # giữa đó là kéo vạch ra giữa trang. Giữ tâm tác giả đặt: dời mép trái
        # nửa phần chênh độ dài.
        lech = ngang.find(f"{{{_NS_WP}}}posOffset")
        if lech is not None and cu is not None and cu != dai_emu:
            lech.text = str(int(lech.text) + (cu - dai_emu) // 2)
            da_sua = True
        return da_sua, cu
    canh = ngang.find(f"{{{_NS_WP}}}align")
    if ngang.get("relativeFrom") == "column" and canh is not None and canh.text == "center":
        return da_sua, cu
    for con in list(ngang):
        ngang.remove(con)
    ngang.set("relativeFrom", "column")
    ngang.append(parse_xml(f'<wp:align xmlns:wp="{_NS_WP}">center</wp:align>'))
    return True, cu


def _chinh_vml(vach, dai_pt: float, giu_tam: bool) -> bool:
    """`<v:line>` (bản dự phòng của Word, hoặc vạch do phần mềm này vẽ) → đặt độ dài, canh giữa."""
    x0, y = ((vach.get("from") or "0,0").split(",") + ["0"])[:2]
    x1 = (vach.get("to") or "0,0").split(",")[0]
    style = vach.get("style") or ""
    if giu_tam:
        a, b = _pt(x0), _pt(x1)
        if a is None or b is None:
            return False                           # đơn vị lạ (in, cm…): không đoán
        trai = a + ((b - a) - dai_pt) / 2
        tu, den, style_moi = f"{trai:.2f}pt,{y}", f"{trai + dai_pt:.2f}pt,{y}", style
    else:
        kieu = {k.strip(): v.strip() for k, v in
                (m.split(":", 1) for m in style.split(";") if ":" in m)}
        kieu.pop("margin-left", None)
        kieu["mso-position-horizontal"] = "center"
        kieu["mso-position-horizontal-relative"] = "text"
        tu, den = f"0,{y}", f"{dai_pt:.1f}pt,{y}"
        style_moi = ";".join(f"{k}:{v}" for k, v in kieu.items())
    if (vach.get("from"), vach.get("to"), style) == (tu, den, style_moi):
        return False
    vach.set("from", tu)
    vach.set("to", den)
    vach.set("style", style_moi)
    return True


def chinh_duong_ke_co_san(p, ma: str, co_pt: float, dam: bool = False,
                          nghieng: bool = False) -> bool:
    """Đưa vạch TÁC GIẢ đã vẽ về đúng độ dài quy định và canh giữa. Trả True nếu có sửa.

    `ve_duong_ke()` thấy đã có vạch thì không vẽ — đúng, vì vẽ thêm là hai vạch
    chồng nhau. Nhưng vạch cũ được vẽ theo cỡ chữ CŨ: chuẩn hoá đổi cỡ chữ
    thì chữ dài ra còn vạch đứng yên. Gặp thật (VB goc 23/09/2026, bản gốc cỡ
    8): sau chuẩn hoá vạch dưới Tiêu ngữ còn 73% dòng chữ, dưới tên đơn vị 63%,
    trong khi Điều 7.2 đòi bằng dòng chữ và Điều 8.2 đòi 1/3–1/2.

    Sửa TẠI CHỖ, không xoá rồi vẽ lại: vị trí dọc của vạch là tác giả đặt (neo
    theo đoạn, cách chữ bao nhiêu) — xoá đi là đổi luôn khoảng cách tới dòng
    "Số:" bên dưới. Chỉ đổi độ dài và vị trí ngang (canh giữa cột chứa nó —
    các dòng có vạch đều canh giữa nên vạch nằm cân dưới chữ).

    Word ghi mỗi hình HAI lần (DrawingML trong `mc:Choice`, VML trong
    `mc:Fallback`) — sửa cả hai, không thì Word cũ và Word mới vẽ hai độ dài.
    Không chắc là đúng MỘT vạch rời (xem `_thu_vach`) thì không đụng.
    """
    dai = _dai_duong_ke(p, ma, co_pt, dam, nghieng)
    if dai is None:
        return False
    ds_doan = _doan_chua_vach(p)
    thu = _thu_vach(ds_doan)
    if thu is None:
        return False
    khung, vml = thu
    giu_tam = any(k.get("layoutInCell") == "0" for k in khung) and _trong_bang(p._p)
    da_sua = False
    for k in khung:
        da_sua |= _chinh_drawingml(k, int(round(dai * _EMU_MOI_PT)), giu_tam)[0]
    for v in vml:
        da_sua |= _chinh_vml(v, dai, giu_tam)
    return da_sua


def ve_duong_ke(p, ma: str, co_pt: float, dam: bool = False,
                nghieng: bool = False) -> bool:
    """Chèn một đoạn chứa đường kẻ ngang ngay dưới `p`. Trả True nếu đã vẽ."""
    if da_co_duong_ke(p):
        return False
    dai = _dai_duong_ke(p, ma, co_pt, dam, nghieng)
    if dai is None:
        return False

    # `mso-position-horizontal:center` canh giữa vạch so với cột chứa nó, nên
    # vạch tự cân dưới dòng chữ mà không phải tính toạ độ trái/phải.
    xml = (
        f'<w:p {_W}>'
        f'<w:pPr><w:spacing w:before="0" w:after="0" w:line="60" '
        f'w:lineRule="exact"/><w:jc w:val="center"/></w:pPr>'
        f'<w:r><w:pict {_VML}>'
        f'<v:line style="position:absolute;mso-position-horizontal:center;'
        f'mso-position-horizontal-relative:text;z-index:1" '
        f'from="0,0" to="{dai:.1f}pt,0" strokeweight=".5pt" '
        f'strokecolor="#000000"/>'
        f'</w:pict></w:r></w:p>'
    )
    try:
        p._p.addnext(parse_xml(xml))
    except Exception as e:                                        # noqa: BLE001
        _log.warning("Không chèn được đường kẻ ngang: %s", e)
        return False
    return True
