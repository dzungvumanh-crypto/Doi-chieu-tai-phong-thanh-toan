"""Soát THỨ TỰ đánh số: Điều / khoản / tiểu khoản / điểm / tiết / mục La Mã.

`bien_doi.chuan_danh_so()` chỉ sửa KÝ HIỆU ("1)" → "1.", "a." → "a)"); nó
không biết Điều 5 đứng ngay sau Điều 3, hay điểm đi "a) b) d)". Module này
dựng lại cây phân cấp theo kiểu máy trạng thái của `DocumentParser` bên
legal-merger — mỗi cấp nhớ số cuối cùng, gặp cấp trên thì xoá số cấp dưới —
rồi báo chỗ nhảy số / trùng số / lùi số.

## Chỉ báo, không sửa

Cùng lý do với danh sách đánh số tự động của Word (card VB979 mục 2): đánh
lại số là phải đếm lại cả văn bản, và mọi câu viện dẫn "theo khoản 3 Điều 5"
trỏ vào số CŨ. Sửa số mà không sửa viện dẫn là đổi nghĩa văn bản không báo.

## Nội dung trong ngoặc kép bị che (Mask của legal-merger)

Văn bản sửa đổi, bổ sung trích nguyên văn: “Điều 5. … 1. … a) …”. Số trong
ngoặc là số của văn bản ĐƯỢC SỬA, đếm chung với số của văn bản đang soát là
báo nhầm hàng loạt. Khối mở bằng dấu ngoặc ở đầu đoạn và đóng bằng dấu ngoặc
ở cuối đoạn (có thể cách nhiều đoạn) được bỏ qua trọn. Mở mà không đóng thì
KHÔNG che — che tới hết văn bản là tắt lặng lẽ cả phần còn lại.

## Tiểu khoản và tiết chỉ nhận ở đây

"1.1" và "(i)" không có mã thể thức riêng trong `nhan_dien` (QĐ 979 không
quy định cỡ chữ cho hai cấp này) — thêm mã là đổi cách định dạng cả loạt
văn bản. Nên chỉ nhận chúng từ đoạn `noi_dung` để soát số, không đụng mã.
"""
import re

from docx.oxml.ns import qn

from .nhan_dien import CHU_CAI_DIEM, RE_KHOAN, RE_MUC, RE_MUC_LA_MA, RE_PHAN_CHUONG

# Số La Mã i–xx xếp DÀI → NGẮN (lấy từ legal-merger `_ROMAN_PAT`): để ngắn
# trước thì "xi" khớp "x" rồi dừng, "(xi)" không còn khớp cả cụm.
_LA_MA_NHO = r"(?:xx|xix|xviii|xvii|xvi|xv|xiv|xiii|xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)"
RE_TIET = re.compile(rf"^\(({_LA_MA_NHO})\)\s+\S")
# `(?!\d)` ở phần sau: "1.500 đồng" là số tiền, không phải tiểu khoản 1.50.
RE_TIEU_KHOAN = re.compile(r"^(\d{1,2})\.(\d{1,2})(?!\d)\.?\s+\S")
RE_SO_DIEU = re.compile(r"^Điều\s+(\d+)")
RE_DIEM_CHU = re.compile(rf"^([{CHU_CAI_DIEM}]{{1,2}})\s*[).]")

_CAP_NGOAC = (("“", "”"), ("«", "»"), ("‘", "’"))


def _lech_ngoac(t: str) -> int:
    """+1 nếu đoạn còn mở ngoặc chưa đóng, -1 nếu đóng ngoặc mở từ đoạn trên, 0 nếu cân."""
    d = sum(t.count(mo) - t.count(dong) for mo, dong in _CAP_NGOAC)
    if t.count('"') % 2:
        # Ngoặc thẳng không phân biệt mở / đóng: đứng đầu đoạn là mở, còn lại là đóng.
        d += 1 if t.startswith('"') else -1
    return (d > 0) - (d < 0)


# Cấp nào xoá số của cấp nào. Không suy từ thứ bậc được: Điều đánh số LIÊN
# TỤC qua Chương và Mục, Chương liên tục qua Phần — xoá theo thứ bậc là báo
# "Điều 12 bắt đầu lại" ở mỗi chương mới.
_XOA = {
    "phan":       ("muc", "khoan", "tieu_khoan", "diem", "tiet"),
    "chuong":     ("muc", "khoan", "tieu_khoan", "diem", "tiet"),
    "muc":        ("khoan", "tieu_khoan", "diem", "tiet"),
    "dieu":       ("khoan", "tieu_khoan", "diem", "tiet"),
    "la_ma":      ("khoan", "tieu_khoan", "diem", "tiet"),
    "khoan":      ("tieu_khoan", "diem", "tiet"),
    "tieu_khoan": ("diem", "tiet"),
    "diem":       ("tiet",),
    "tiet":       (),
}
# Cấp CHA của từng cấp — có cha đang mở thì bắt đầu lại từ 1 là lỗi.
_CHA = {
    "khoan": ("dieu", "la_ma", "muc"),
    "tieu_khoan": ("khoan",),
    "diem": ("khoan", "tieu_khoan"),
    "tiet": ("diem",),
    "muc": ("chuong", "phan"),
}
# Điều / Chương / Phần về 1 là văn bản mới bắt đầu (Quy chế ban hành kèm
# Quyết định có Điều 1 riêng) — không báo.
_VE_MOT_HOP_LE = ("dieu", "chuong", "phan", "la_ma")

# Mã thể thức mở đầu một văn bản / khối mới → xoá hết số đang nhớ.
# `quoc_hieu`: mẫu biểu ở phụ lục (TT 17/2024) mỗi mẫu có Quốc hiệu riêng,
# thường nằm trong bảng, và đánh "1." lại từ đầu. KHÔNG có `quyen_han_chuc_vu`:
# mã đó đoán theo từ khoá ("QUYỀN", "TRƯỞNG"…) nên nhận nhầm được giữa văn bản,
# và mỗi lần nhầm là xoá bộ đếm — cảnh báo sai lan ra các Điều sau.
_MA_XOA_HET = frozenset({"quoc_hieu", "ten_loai", "phu_luc_so", "tieu_de_phu_luc",
                         "noi_nhan_tieu_de"})


def _la_ma_sang_so(s: str) -> int | None:
    gt = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    s = s.lower()
    if not s or any(c not in gt for c in s):
        return None
    tong = 0
    for i, c in enumerate(s):
        v = gt[c]
        tong += -v if i + 1 < len(s) and gt[s[i + 1]] > v else v
    return tong


def _so_sang_la_ma(n: int) -> str:
    bang = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    ra = ""
    for v, k in bang:
        while n >= v:
            ra += k
            n -= v
    return ra


def _chu_sang_so(s: str) -> int | None:
    """"a" → 1 … "y" → 23, "aa" → 24 … — theo bảng chữ cái Điều 12.5.b."""
    n = len(CHU_CAI_DIEM)
    if len(s) == 1 and s in CHU_CAI_DIEM:
        return CHU_CAI_DIEM.index(s) + 1
    if len(s) == 2 and s[0] == s[1] and s[0] in CHU_CAI_DIEM:
        return n + CHU_CAI_DIEM.index(s[0]) + 1
    return None


def _so_sang_chu(v: int) -> str:
    n = len(CHU_CAI_DIEM)
    return CHU_CAI_DIEM[v - 1] if v <= n else CHU_CAI_DIEM[v - n - 1] * 2


def _ten(cap: str, v: int, cha: int | None = None) -> str:
    """Tên hiển thị của một số ở một cấp — dùng cả cho số bị thiếu."""
    if cap == "dieu":
        return f"Điều {v}"
    if cap == "chuong":
        return f"Chương {_so_sang_la_ma(v)}"
    if cap == "phan":
        return f"Phần {_so_sang_la_ma(v)}"
    if cap == "muc":
        return f"Mục {v}"
    if cap == "la_ma":
        return f"mục {_so_sang_la_ma(v)}."
    if cap == "khoan":
        return f"khoản {v}."
    if cap == "tieu_khoan":
        return f"{cha}.{v}" if cha is not None else f"tiểu khoản thứ {v}"
    if cap == "diem":
        return f"điểm {_so_sang_chu(v)})"
    return f"tiết ({_so_sang_la_ma(v).lower()})"


def _doc_so(ma: str, txt: str) -> tuple[str, int, int | None] | None:
    """(cấp, số, số của khoản cha nếu là tiểu khoản) — None nếu đoạn không mang số."""
    t = txt.strip()
    if ma == "dieu":
        m = RE_SO_DIEU.match(t)
        return ("dieu", int(m.group(1)), None) if m else None
    if ma == "phan_chuong":
        m = RE_PHAN_CHUONG.match(t)
        if not m:
            return None
        g = m.group(2)
        v = int(g) if g.isdigit() else _la_ma_sang_so(g)
        cap = "phan" if m.group(1).lower().startswith("ph") else "chuong"
        return (cap, v, None) if v else None
    if ma == "muc":
        m = RE_MUC.match(t)
        # Tiểu mục bỏ qua: quá hiếm để đáng thêm một cấp nữa.
        if not m or m.group(1).lower().startswith("ti"):
            return None
        g = m.group(2)
        v = int(g) if g.isdigit() else _la_ma_sang_so(g)
        return ("muc", v, None) if v else None
    if ma == "muc_la_ma":
        m = RE_MUC_LA_MA.match(t)
        v = _la_ma_sang_so(m.group(1)) if m else None
        return ("la_ma", v, None) if v else None
    if ma in ("khoan", "khoan_co_tieu_de"):
        m = RE_KHOAN.match(t)
        return ("khoan", int(m.group(1)), None) if m else None
    if ma == "diem":
        m = RE_DIEM_CHU.match(t)
        v = _chu_sang_so(m.group(1)) if m else None
        return ("diem", v, None) if v else None
    if ma == "noi_dung":
        m = RE_TIEU_KHOAN.match(t)
        if m:
            return ("tieu_khoan", int(m.group(2)), int(m.group(1)))
        m = RE_TIET.match(t)
        if m:
            return ("tiet", _la_ma_sang_so(m.group(1)), None)
    return None


def vung_trich_dan(txt: list[str]) -> set[int]:
    """Chỉ số các đoạn nằm trong khối trích dẫn “…” (xem docstring module).

    Đoạn mở đầu bằng ngoặc mà đóng ngay trong đoạn thì chỉ che nếu dấu đóng ở
    CUỐI đoạn (“1. Nội dung…”.). Câu thường mở bằng “Chuyển đổi số” là … phải
    để nguyên — chỉ xét "mở đầu bằng ngoặc" là che từ đó tới dấu đóng ngoặc
    kế tiếp, có khi cách cả chục khoản.
    """
    che: set[int] = set()
    i, n = 0, len(txt)
    while i < n:
        t = txt[i].strip()
        if not t.startswith(tuple(mo for mo, _ in _CAP_NGOAC) + ('"',)):
            i += 1
            continue
        if _lech_ngoac(t) <= 0:
            if t.rstrip(" .;,")[-1:] in ("”", "»", "’", '"'):
                che.add(i)
            i += 1
            continue
        j = next((k for k in range(i + 1, n) if _lech_ngoac(txt[k].strip()) < 0), None)
        if j is None:
            i += 1                              # mở không đóng → không che
            continue
        che.update(range(i, j + 1))
        i = j + 1
    return che


# Cấp đếm một dãy duy nhất, không tách theo style tiêu đề (xem `soat_thu_tu`).
_KHONG_TACH = frozenset({"dieu", "chuong", "phan", "muc", "la_ma"})

_RE_TEN_DE_MUC = re.compile(r"^(?:heading|tiêu đề)\s*(\d)$", re.I)


def muc_de_muc(p) -> int | None:
    """Cấp dàn ý của đoạn (1 = Heading 1…), None nếu là đoạn thường.

    Đọc `w:outlineLvl` trên đoạn rồi leo chuỗi style; không có thì nhận theo
    tên style "Heading N" / "Tiêu đề N". 9 là mức "Body Text" của Word.
    """
    def _lvl(pPr) -> int | None:
        if pPr is None:
            return None
        o = pPr.find(qn("w:outlineLvl"))
        if o is None:
            return None
        v = int(o.get(qn("w:val"), "9"))
        return v + 1 if v < 9 else 0

    v = _lvl(p._p.pPr)
    st = p.style
    while v is None and st is not None:
        v = _lvl(st.element.pPr)
        if v is None:
            m = _RE_TEN_DE_MUC.match(st.name or "")
            v = int(m.group(1)) if m else None
        st = st.base_style
    return v or None


def soat_thu_tu(ma_list: list[str], txt: list[str], trong_bang: list[bool],
                de_muc: list[int | None] | None = None) -> list[dict]:
    """Trả `[{stt, trich, loi}]` — `stt` đếm từ 1, khớp cột "Đoạn" của nhật ký.

    `de_muc` (từ `muc_de_muc`) tách các dãy số theo cấp tiêu đề của Word. Tài
    liệu hướng dẫn hay có tiêu đề "1. Truy cập" (Heading 1) → "1.1" (Heading 2)
    → các bước "1. 2. 3." (Normal): cùng dáng chữ "1." nhưng là hai danh sách
    khác cấp. Đếm chung là báo "trùng số" ở mọi bước đầu — đo trên
    "HDSD phần mềm bàn giao chứng từ.docx": 8 cảnh báo, không cái nào đúng.
    Nên mỗi cấp tiêu đề đếm riêng, và gặp tiêu đề thì danh sách thường bên dưới
    đánh lại từ đầu. Văn bản soạn toàn style Normal: mọi đoạn cùng cấp None,
    hành vi như không có tham số này.
    """
    che = vung_trich_dan(txt)
    de_muc = de_muc or [None] * len(txt)
    dang: dict[tuple[str, int | None], int] = {}   # (cấp số, cấp tiêu đề) → số cuối
    khoan_o: dict[int | None, int] = {}             # cấp tiêu đề → số khoản đang mở
    ra: list[dict] = []

    def _xoa_duoi(L: int) -> None:
        """Gặp tiêu đề cấp L: mọi dãy thường và dãy ở cấp tiêu đề sâu hơn đóng lại."""
        for k in [k for k in dang if k[1] is None or k[1] > L]:
            del dang[k]
        for k in [k for k in khoan_o if k is None or k > L]:
            del khoan_o[k]

    def _khoan_cha(L: int | None) -> int | None:
        """Khoản mà tiểu khoản ở cấp L thuộc về: cùng cấp, không có thì cấp tiêu đề gần nhất ở trên."""
        if L in khoan_o:
            return khoan_o[L]
        tren = [k for k in khoan_o if k is not None and (L is None or k < L)]
        return khoan_o[max(tren)] if tren else None

    for i, (ma, t) in enumerate(zip(ma_list, txt)):
        # ── Mốc văn bản mới — xét TRƯỚC khi bỏ ô bảng: Quốc hiệu của mẫu biểu
        # hay nằm trong bảng hai cột ──
        if i in che:
            continue
        if ma in _MA_XOA_HET:
            dang.clear()
            khoan_o.clear()
            continue
        # ── Bỏ qua: đoạn trống, ô bảng (cột STT của bảng số liệu) ──
        if ma == "trong" or trong_bang[i]:
            continue
        L = de_muc[i]
        if L is not None:
            _xoa_duoi(L)
        doc = _doc_so(ma, t)
        if doc is None:
            continue
        cap, v, cha_tk = doc
        # Điều / Chương / Mục / mục La Mã không lồng vào chính nó → một dãy
        # duy nhất, bất kể style. Đo trên TT 15/2024: Điều 8 có outline level,
        # Điều 7 thì không (người soạn đặt style không đồng nhất) — tách theo
        # cấp tiêu đề là báo "Điều 8 là số đầu tiên". Khoá 0 thì `_xoa_duoi`
        # không bao giờ xoá (nó chỉ xoá None và cấp > L, mà L ≥ 1).
        if cap in _KHONG_TACH:
            L = 0

        # ── So với số trước cùng cấp ──
        truoc = dang.get((cap, L))
        co_cha = any(k[0] in _CHA.get(cap, ()) for k in dang)
        khoan_cha = _khoan_cha(L) if cap == "tieu_khoan" else None
        cha_hien = khoan_cha
        loi = None
        if cap == "tieu_khoan" and khoan_cha is not None and cha_tk != khoan_cha:
            loi = (f"«{cha_tk}.{v}» nằm dưới khoản {khoan_cha} — số đầu của tiểu "
                   f"khoản phải là {khoan_cha}")
            cha_hien = cha_tk
        elif truoc is None:
            if v != 1 and (co_cha or cap in _VE_MOT_HOP_LE):
                loi = f"{_ten(cap, v, cha_hien)} là số đầu tiên — thiếu {_ten(cap, 1, cha_hien)}"
        elif v == truoc:
            loi = f"{_ten(cap, v, cha_hien)} bị trùng số với đoạn trước cùng cấp"
        elif v == truoc + 1:
            pass
        elif v == 1:
            if cap not in _VE_MOT_HOP_LE and co_cha:
                loi = (f"{_ten(cap, 1, cha_hien)} đánh lại từ đầu dù chưa sang "
                       f"cấp trên mới (số trước là {_ten(cap, truoc, cha_hien)})")
        elif v > truoc + 1:
            thieu = [_ten(cap, k, cha_hien) for k in range(truoc + 1, v)]
            ds = ", ".join(thieu[:3]) + (" …" if len(thieu) > 3 else "")
            loi = f"{_ten(cap, v, cha_hien)} đứng sau {_ten(cap, truoc, cha_hien)} — thiếu {ds}"
            if cap == "diem" and "đ)" in ds:
                loi += " (Điều 12.5.b: điểm theo chữ cái tiếng Việt, sau d) là đ))"
        else:
            loi = f"{_ten(cap, v, cha_hien)} đứng sau {_ten(cap, truoc, cha_hien)} — số bị lùi"

        if loi:
            ra.append({"stt": i + 1, "trich": t.strip()[:90], "loi": loi})

        # ── Ghi nhớ: lấy số MỚI làm mốc để một chỗ sai không kéo theo cả dãy ──
        # Đoạn thường chỉ xoá dãy thường: bước "1." dưới tiêu đề "1.1" không được
        # xoá dãy tiểu khoản của tiêu đề, không thì "1.2" bị báo là số đầu tiên.
        # Cấp khung (Điều, Chương…) thì ngược lại: đóng dãy cấp dưới ở MỌI cấp
        # tiêu đề — khoản của Điều trước dù đặt style gì cũng đã hết.
        if cap in _KHONG_TACH:
            for k in [k for k in dang if k[0] in _XOA[cap]]:
                del dang[k]
            khoan_o.clear()
        else:
            for c in _XOA[cap]:
                dang.pop((c, L), None)
        dang[(cap, L)] = v
        if cap == "khoan":
            khoan_o[L] = v
    return ra
