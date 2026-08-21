"""Tốc độ dựng bản xem trước đơn nghỉ phép — Word thường trú + ảnh nhẹ.

Không đo giây ở đây (máy CI không có Word). Chỗ dễ hỏng nằm ở đường rẽ: khi Word
thường trú không dựng được thì phải lui về cách chạy một lần, còn khi Word báo
chính file đơn có vấn đề thì KHÔNG được chạy lại — bắt người dùng chờ hai lượt
Word chỉ để nhận đúng một lỗi.
"""
import io
import sys

import pytest
from PIL import Image

sys.path.insert(0, ".")

from backend.services import leave_pdf


# ── Word thường trú hỏng thì lui về cách chạy một lần ────────────────────────

def test_word_thuong_tru_hong_thi_lui_ve_cach_cu(monkeypatch):
    goi = []

    def _hong(_b):
        goi.append("thuong_tru")
        raise leave_pdf._ServerDown("thử: không dựng được")

    monkeypatch.setattr(leave_pdf._server, "convert", _hong)
    monkeypatch.setattr(leave_pdf, "_docx_to_pdf_mot_lan",
                        lambda b: goi.append("mot_lan") or b"%PDF-fake")
    monkeypatch.setattr(leave_pdf, "_SERVER_ON", True)

    assert leave_pdf.docx_to_pdf(b"docx") == b"%PDF-fake"
    assert goi == ["thuong_tru", "mot_lan"]


def test_word_bao_loi_noi_dung_thi_khong_chay_lai(monkeypatch):
    """Word trả lời "ERR ..." = đã mở được Word, chính file đơn có vấn đề.

    Chạy lại kiểu cũ cũng hỏng y hệt, chỉ tốn thêm ~4 giây của người dùng.
    """
    goi = []

    def _loi(_b):
        goi.append("thuong_tru")
        raise leave_pdf.PdfConvertError("Word chuyển đổi thất bại: thử")

    monkeypatch.setattr(leave_pdf._server, "convert", _loi)
    monkeypatch.setattr(leave_pdf, "_docx_to_pdf_mot_lan",
                        lambda b: goi.append("mot_lan") or b"%PDF-fake")
    monkeypatch.setattr(leave_pdf, "_SERVER_ON", True)

    with pytest.raises(leave_pdf.PdfConvertError):
        leave_pdf.docx_to_pdf(b"docx")
    assert goi == ["thuong_tru"], "không được gọi Word lượt thứ hai"


def test_tat_word_thuong_tru_bang_env(monkeypatch):
    goi = []
    monkeypatch.setattr(leave_pdf._server, "convert",
                        lambda b: goi.append("thuong_tru") or b"x")
    monkeypatch.setattr(leave_pdf, "_docx_to_pdf_mot_lan",
                        lambda b: goi.append("mot_lan") or b"%PDF-fake")
    monkeypatch.setattr(leave_pdf, "_SERVER_ON", False)

    assert leave_pdf.docx_to_pdf(b"docx") == b"%PDF-fake"
    assert goi == ["mot_lan"]


def test_warm_up_tat_thi_khong_dung_Word(monkeypatch):
    monkeypatch.setattr(leave_pdf, "_SERVER_ON", False)
    monkeypatch.setattr(leave_pdf._server, "start",
                        lambda: pytest.fail("không được bật Word khi WORD_SERVER=0"))
    assert leave_pdf.warm_up() is False


def test_warm_up_hong_thi_nghi_mot_luc_moi_thu_lai(monkeypatch):
    """Máy chủ không có Word: mỗi người mở màn nghỉ phép lại đẻ một PowerShell
    vô ích. Hỏng một lần thì nghỉ, đừng đập liên tục."""
    lan = []

    def _hong():
        lan.append(1)
        raise leave_pdf._ServerDown("thử: không có Word")

    monkeypatch.setattr(leave_pdf, "_SERVER_ON", True)
    monkeypatch.setattr(leave_pdf, "_warm_fail_at", 0.0)
    monkeypatch.setattr(leave_pdf._server, "alive", lambda: False)
    monkeypatch.setattr(leave_pdf._server, "start", _hong)

    assert leave_pdf.warm_up() is False
    assert leave_pdf.warm_up() is False
    assert len(lan) == 1, "lần thứ hai phải bị chặn bởi thời gian nghỉ"


# ── Không diệt nhầm tiến trình khác ──────────────────────────────────────────

def _bat_taskkill(monkeypatch):
    """Ghi lại mọi lệnh taskkill được gọi, không cho chạy thật."""
    da_diet = []

    def _run(cmd, *a, **k):
        if cmd and cmd[0] == "taskkill":
            da_diet.append(cmd)
        return None

    monkeypatch.setattr(leave_pdf.subprocess, "run", _run)
    return da_diet


def test_khong_diet_pid_khong_phai_winword(tmp_path, monkeypatch):
    """PID trong file cũ có thể đã được Windows cấp lại cho tiến trình khác."""
    f = tmp_path / "word.pid"
    f.write_text("4,999999", encoding="ascii")
    da_diet = _bat_taskkill(monkeypatch)
    monkeypatch.setattr(leave_pdf, "_kiem_truoc_khi_diet",
                        lambda pid: (False, "KHONG_PHAI_WORD"))

    leave_pdf._kill_pids(str(f))
    assert da_diet == []


def test_khong_diet_word_dang_mo_cua_so(tmp_path, monkeypatch, caplog):
    """Bẫy nguy hiểm nhất: nếu bản Word ngầm là WINWORD duy nhất đang chạy, người
    vận hành double-click một .docx là tài liệu đó chui vào ĐÚNG tiến trình này
    (đã đo: PID không đổi, MainWindowHandle 0 → khác 0). Diệt lúc đó là giết bản
    Word có người đang gõ dở."""
    f = tmp_path / "word.pid"
    f.write_text("1234", encoding="ascii")
    da_diet = _bat_taskkill(monkeypatch)
    monkeypatch.setattr(leave_pdf, "_kiem_truoc_khi_diet",
                        lambda pid: (False, "CO_CUA_SO bao_cao_quy_3.docx - Word"))

    with caplog.at_level("WARNING"):
        leave_pdf._kill_pids(str(f))

    assert da_diet == [], "không được diệt Word đang có cửa sổ"
    assert "bao_cao_quy_3.docx" in caplog.text, "phải ghi log cho người vận hành biết"


def test_van_diet_ban_ngam_thuc_su_treo(tmp_path, monkeypatch):
    """Ngược lại: bản ngầm rỗng, không cửa sổ thì vẫn phải dọn được."""
    f = tmp_path / "word.pid"
    f.write_text("1234", encoding="ascii")
    da_diet = _bat_taskkill(monkeypatch)
    monkeypatch.setattr(leave_pdf, "_kiem_truoc_khi_diet", lambda pid: (True, "DIET_DUOC"))

    leave_pdf._kill_pids(str(f))
    assert da_diet == [["taskkill", "/F", "/PID", "1234"]]


def test_tra_khong_duoc_thi_khong_diet(tmp_path, monkeypatch):
    """Không hỏi được Windows về tiến trình đó thì tuyệt đối không bắn."""
    f = tmp_path / "word.pid"
    f.write_text("1234", encoding="ascii")
    da_diet = _bat_taskkill(monkeypatch)

    def _no(*a, **k):
        raise OSError("thử: không chạy được powershell")

    monkeypatch.setattr(leave_pdf.subprocess, "run", _no)
    duoc, ly_do = leave_pdf._kiem_truoc_khi_diet("1234")
    assert duoc is False and "không tra được" in ly_do


# ── Ảnh xem trước: bỏ màu khi không có màu ───────────────────────────────────

def _anh(mau):
    im = Image.new("RGB", (40, 30), (255, 255, 255))
    im.putpixel((5, 5), mau)
    return im


def test_anh_den_trang_thi_bo_bot_kenh_mau():
    ra = leave_pdf._bo_mau_thua(_anh((0, 0, 0)))
    assert ra.mode == "L"


def test_anh_co_mau_thi_giu_nguyen():
    """Mẫu đơn có logo hoặc dấu đỏ phải giữ đúng màu."""
    ra = leave_pdf._bo_mau_thua(_anh((220, 20, 20)))
    assert ra.mode == "RGB"
    assert ra.getpixel((5, 5)) == (220, 20, 20)


def test_page_png_van_doc_duoc_sau_khi_bo_mau():
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    doc.new_page(595.44, 842.04)
    buf = io.BytesIO()
    doc.save(buf)

    png, w_mm, h_mm, n = leave_pdf.page_png(buf.getvalue(), 0, dpi=72)
    im = Image.open(io.BytesIO(png))
    assert im.mode == "L"                       # trang trắng → không cần 3 kênh
    assert n == 1
    assert 209 < w_mm < 211 and 296 < h_mm < 298


# ── Endpoint bật sẵn ─────────────────────────────────────────────────────────

def test_endpoint_bat_san_khong_doi_word_len(monkeypatch):
    """`/preview/warmup` phải trả lời NGAY. Nó chỉ dọn đường; bắt người dùng chờ
    Word khởi động ở đây thì đúng bằng không làm gì cả.

    Đồng thời canh thứ tự route: `/preview/warmup` không được rơi vào tay
    `/{leave_id}/preview`.
    """
    import threading as _th

    from fastapi.testclient import TestClient

    from backend.core.deps import get_current_staff
    from backend.main import app

    xong = _th.Event()
    monkeypatch.setattr(leave_pdf, "warm_up",
                        lambda: (xong.wait(5), True)[1])   # giả vờ Word lên rất lâu

    app.dependency_overrides[get_current_staff] = lambda: {"id": 1, "role": "chuyen_vien"}
    try:
        r = TestClient(app).post("/api/leaves/preview/warmup")
    finally:
        xong.set()
        app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
