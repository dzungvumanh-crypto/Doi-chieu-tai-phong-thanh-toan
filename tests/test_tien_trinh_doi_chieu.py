"""Chạy pipeline đối chiếu ở tiến trình riêng — `backend/core/tien_trinh_doi_chieu.py`.

Mỗi ca ở đây là một chỗ luồng → tiến trình có thể hỏng LẶNG LẼ nếu làm sai: log không
về, lỗi đổi kiểu, Dừng không dừng, con mồ côi giữ RAM sau khi backend bị giết.
Các hàm `_ham_*` phải ở cấp module: tiến trình con import lại file này theo tên.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_tien_trinh_doi_chieu.py -v
"""
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from backend.core import tien_trinh_doi_chieu as ttdc


@pytest.fixture(autouse=True)
def _bat_tien_trinh(tien_trinh_that):
    pass  # conftest mặc định chạy trong luồng — file này thử chính đường tách tiến trình


# ── Hàm chạy trong tiến trình con ──

def _ham_ok(so, log_callback, cancel_event):
    from concurrent.futures import ThreadPoolExecutor
    # Log từ nhiều luồng cùng lúc — Connection.send không an toàn luồng nếu thiếu khoá
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda i: log_callback(f"luồng {i}"), range(40)))
    logging.getLogger("thu.tien_trinh_con").warning("cảnh báo từ con %d", so)
    log_callback("xong")
    return {"pid": os.getpid(), "duong_dan": Path("ket_qua") / f"{so}.xlsx"}


class LoiRieng(ValueError):
    pass


class LoiKhoMo(Exception):
    def __init__(self, a, b):
        super().__init__(f"{a}-{b}")


def _ham_loi(log_callback, cancel_event):
    raise LoiRieng("cột SO_TIEN sai định dạng")


def _ham_loi_kho_mo(log_callback, cancel_event):
    raise LoiKhoMo(1, 2)


def _ham_cho_huy(log_callback, cancel_event):
    log_callback("bắt đầu")
    while not cancel_event.wait(0.05):
        pass
    return None


def _ham_lo_huy(log_callback, cancel_event):
    log_callback(f"pid {os.getpid()}")
    time.sleep(120)
    return "không được tới đây"


def _ham_chet(log_callback, cancel_event):
    os._exit(7)


def _ham_kq_khong_pickle(log_callback, cancel_event):
    return threading.Lock()


def _ham_doc_env(log_callback, cancel_event):
    import backend.core.config  # noqa: F401 — nạp .env đúng như module thật
    return os.environ.get("SECRET_KEY")


def _ham_co_summary(log_callback, cancel_event, summary_callback):
    summary_callback({"khop": 3}, ghi_chu="tạm")
    log_callback("sau summary")
    return 1


# ── Ca chạy bình thường ──

def test_chay_o_tien_trinh_khac_log_ve_du_va_dung_kieu(caplog):
    log = []
    with caplog.at_level(logging.INFO):
        kq = ttdc.chay_tach(_ham_ok, ten="thử", log_callback=log.append, so=5)

    assert kq["pid"] != os.getpid()
    assert kq["duong_dan"] == Path("ket_qua") / "5.xlsx"
    assert sorted(log[:-1]) == sorted(f"luồng {i}" for i in range(40))
    assert log[-1] == "xong"
    # logging trong con được cha ghi hộ, giữ tên logger và mức
    ban_ghi = [r for r in caplog.records if r.name == "thu.tien_trinh_con"]
    assert [(r.levelno, r.getMessage()) for r in ban_ghi] == [(logging.WARNING, "cảnh báo từ con 5")]
    assert any("RAM đỉnh" in r.getMessage() for r in caplog.records)


def test_callback_khac_ve_dung_thu_tu_voi_log():
    # ACH: summary phải tới TRƯỚC khi job đổi trạng thái — thứ tự với log phải giữ nguyên
    ve = []
    kq = ttdc.chay_tach(
        _ham_co_summary, ten="thử", log_callback=lambda m: ve.append(("log", m)),
        callbacks={"summary_callback": lambda d, ghi_chu: ve.append(("summary", d, ghi_chu))},
    )
    assert kq == 1
    assert ve == [("summary", {"khop": 3}, "tạm"), ("log", "sau summary")]


_ENV = Path(__file__).resolve().parent.parent / ".env"


@pytest.mark.skipif(
    not _ENV.exists() or "SECRET_KEY" not in _ENV.read_text(encoding="utf-8"),
    reason="không có .env chứa SECRET_KEY (CI) — không có gì để nạp đè, test sẽ xanh giả",
)
def test_con_dung_moi_truong_cua_cha_khong_nap_de_env(monkeypatch):
    # config.py nạp .env với override=True — con mà nạp đè thì sửa .env chưa restart là
    # cha/con đọc hai mật khẩu ZIP khác nhau. SECRET_KEY chắc chắn có trong .env.
    monkeypatch.setenv("SECRET_KEY", "khoa-cua-tien-trinh-cha")
    assert ttdc.chay_tach(_ham_doc_env, ten="thử") == "khoa-cua-tien-trinh-cha"


def test_loi_giu_nguyen_kieu_va_mang_vet_cua_con():
    # ACH phân biệt ValueError với lớp con của nó để chọn nhánh xử lý — đổi kiểu là sai nhánh
    with pytest.raises(LoiRieng, match="SO_TIEN") as ei:
        ttdc.chay_tach(_ham_loi, ten="thử")
    assert "_ham_loi" in str(ei.value.__cause__)


def test_loi_khong_mo_goi_duoc_van_giu_thong_bao():
    with pytest.raises(ttdc.LoiTienTrinhCon, match="LoiKhoMo: 1-2"):
        ttdc.chay_tach(_ham_loi_kho_mo, ten="thử")


def test_ket_qua_khong_pickle_duoc_bao_loi_ro():
    with pytest.raises(TypeError):
        ttdc.chay_tach(_ham_kq_khong_pickle, ten="thử")


def test_con_chet_ngang_bao_loi_khong_treo():
    t0 = time.monotonic()
    with pytest.raises(ttdc.LoiTienTrinhCon, match="mã thoát 7"):
        ttdc.chay_tach(_ham_chet, ten="thử")
    assert time.monotonic() - t0 < 20


# ── Dừng ──

def test_dung_hop_tac_tra_none():
    huy = threading.Event()
    threading.Timer(0.5, huy.set).start()
    assert ttdc.chay_tach(_ham_cho_huy, ten="thử", cancel_event=huy) is None


def test_dung_khong_nghe_thi_giet_sau_han(monkeypatch):
    monkeypatch.setattr(ttdc, "HAN_DUNG_GIAY", 1)
    huy = threading.Event()
    log = []
    threading.Timer(0.5, huy.set).start()
    t0 = time.monotonic()
    assert ttdc.chay_tach(_ham_lo_huy, ten="thử", log_callback=log.append, cancel_event=huy) is None
    assert time.monotonic() - t0 < 15
    assert any("buộc dừng" in d for d in log)
    pid = int(log[0].split()[1])
    assert not _con_song(pid)


# ── Công tắc và hàm không nạp lại được ──

def test_ham_long_bi_tu_choi_khi_bat():
    with pytest.raises(TypeError, match="DOI_CHIEU_TIEN_TRINH"):
        ttdc.chay_tach(lambda log_callback, cancel_event: 1, ten="thử")


def test_tat_thi_chay_trong_luong(monkeypatch):
    monkeypatch.setenv("DOI_CHIEU_TIEN_TRINH", "0")
    assert ttdc.chay_tach(lambda log_callback, cancel_event: os.getpid(), ten="thử") == os.getpid()


# ── Backend bị taskkill /F → con không được sống tiếp giữ RAM ──

def _con_song(pid: int) -> bool:
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        ma = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(ma))
        return ma.value == 259                 # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


@pytest.mark.skipif(os.name != "nt", reason="đo bằng API tiến trình Windows")
def test_cha_bi_giet_thi_con_tu_thoat():
    goc = Path(__file__).resolve().parent
    ma = (
        "import sys; sys.path[:0] = [r'%s', r'%s'];"
        "from backend.core import tien_trinh_doi_chieu as t;"
        "import test_tien_trinh_doi_chieu as m;"
        "t.chay_tach(m._ham_lo_huy, ten='thử', log_callback=lambda s: print(s, flush=True))"
    ) % (goc, goc.parent)
    cha = subprocess.Popen([sys.executable, "-c", ma], stdout=subprocess.PIPE, text=True,
                           encoding="utf-8")
    try:
        pid_con = int(cha.stdout.readline().split()[1])
        assert _con_song(pid_con)
        cha.kill()          # TerminateProcess — atexit không chạy, giống taskkill /F
        cha.wait(10)
        for _ in range(50):
            if not _con_song(pid_con):
                break
            time.sleep(0.1)
        assert not _con_song(pid_con), "tiến trình con mồ côi vẫn chạy sau khi cha chết"
    finally:
        if cha.poll() is None:
            cha.kill()
