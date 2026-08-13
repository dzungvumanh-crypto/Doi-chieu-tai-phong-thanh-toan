"""
Test resolve_path() — chống lệch chuẩn hoá Unicode NFC/NFD trong tên thư mục.

Bối cảnh: thư mục "templates/Phòng Tổng hợp" trên đĩa (và trong git) ở dạng NFD,
còn chuỗi gõ trong mã nguồn là NFC. Windows không chuẩn hoá tên file nên hai chuỗi
này khác nhau về byte → os.path.exists() trả về False dù thư mục vẫn ở đó, và
os.makedirs() từng tạo ra một thư mục **thứ hai trùng tên** (bản NFC rỗng, đã xoá).

Test dựng lại đúng tình huống đó bằng thư mục tạm.
"""
import os
import unicodedata

import pytest

from backend.core.paths import TEMPLATES_DIR, resolve_path, template_path

_TEN_NFC = unicodedata.normalize("NFC", "Phòng Tổng hợp")
_TEN_NFD = unicodedata.normalize("NFD", "Phòng Tổng hợp")


def test_hai_dang_chuan_hoa_khac_nhau_ve_byte():
    """Nếu assert này sai thì cả module paths.py là thừa."""
    assert _TEN_NFC != _TEN_NFD


def test_thu_muc_tao_dang_NFD_van_tim_duoc_bang_chuoi_NFC(tmp_path):
    goc = tmp_path / _TEN_NFD / "Nghỉ phép"
    goc.mkdir(parents=True)

    tim = resolve_path(str(tmp_path), _TEN_NFC, "Nghỉ phép")
    assert os.path.exists(tim)
    assert os.path.samefile(tim, str(goc))


def test_thu_muc_tao_dang_NFC_van_tim_duoc_bang_chuoi_NFD(tmp_path):
    goc = tmp_path / _TEN_NFC / "Nghỉ phép"
    goc.mkdir(parents=True)

    tim = resolve_path(str(tmp_path), _TEN_NFD, "Nghỉ phép")
    assert os.path.exists(tim)
    assert os.path.samefile(tim, str(goc))


def test_tim_duoc_ca_file_nam_sau_thu_muc_lech_dang(tmp_path):
    thu_muc = tmp_path / _TEN_NFD / "Nghỉ phép"
    thu_muc.mkdir(parents=True)
    (thu_muc / "don_xin_nghi_phep_tp.docx").write_bytes(b"x")

    tim = resolve_path(str(tmp_path), _TEN_NFC, "Nghỉ phép", "don_xin_nghi_phep_tp.docx")
    assert os.path.exists(tim)


def test_khong_ton_tai_thi_tra_duong_dan_ghep_thang(tmp_path):
    """Caller còn fallback riêng (vd _pick_template) nên không được ném lỗi."""
    tim = resolve_path(str(tmp_path), "Khong Co Thu Muc", "abc.docx")
    assert not os.path.exists(tim)
    assert tim.endswith(os.path.join("Khong Co Thu Muc", "abc.docx"))


# ─── Trạng thái thật của repo ────────────────────────────────────────────────

def test_khong_con_thu_muc_trung_ten_trong_templates():
    """Hai thư mục cùng tên khác chuẩn hoá làm resolve_path() trỏ vào bản sai."""
    dem = {}
    for d in os.listdir(TEMPLATES_DIR):
        if os.path.isdir(os.path.join(TEMPLATES_DIR, d)):
            key = unicodedata.normalize("NFC", d)
            dem[key] = dem.get(key, 0) + 1
    trung = [k for k, v in dem.items() if v > 1]
    assert not trung, f"Thư mục trùng tên khác chuẩn hoá Unicode: {trung}"


@pytest.mark.parametrize("parts", [
    ("Phòng Tổng hợp", "Báo cáo giao dịch chuyển tiền qua Swift",
     "D00054-01204001-01204001-202605-ST-M-01.xlsx"),
    ("Phòng KSNB&HTVH", "Bàn giao cho lưu trữ", "Bia_ho_so.docx"),
    ("don_xin_nghi_phep_tpl.docx",),
])
def test_template_co_dau_van_mo_duoc_bang_chuoi_trong_ma_nguon(parts):
    assert os.path.exists(template_path(*parts)), f"Không tìm thấy: {'/'.join(parts)}"
