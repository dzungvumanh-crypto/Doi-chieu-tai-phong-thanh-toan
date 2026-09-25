"""Bìa tập chứng từ: nhớ phần chuẩn bị mẫu docxtpl giữa các tập (card HN7)."""
import io
import zipfile
from datetime import date
from types import SimpleNamespace as NS

from backend.services import cover_service as cs
from backend.services.bundle_service import BundleResult


def _tap(i: int, nguoi_giu: str) -> BundleResult:
    units = [NS(user_code=f"U{i}{j}", full_name=f"Người nộp {i}-{j}", transaction_date=date(2026, 9, 1 + j),
                sheet_count=10 + j, is_large=False) for j in range(3)]
    return BundleResult(sequence=i, total_bundles_in_group=3, total_sheets=100 + i, units=units,
                        label_seq=i, label_total=3, custodian_name=nguoi_giu)


def _than(docx_bytes: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf-8")


def test_moi_tap_ra_dung_noi_dung_rieng():
    # Mẫu Jinja dùng chung — ngữ cảnh của tập trước không được rò sang tập sau
    than = _than(cs.generate_covers_docx("Phòng Thử", [_tap(1, "Giữ Một"), _tap(2, "Giữ Hai"), _tap(3, "Giữ Ba")]))
    for i, ten in ((1, "Giữ Một"), (2, "Giữ Hai"), (3, "Giữ Ba")):
        assert ten in than
        assert f"Người nộp {i}-0" in than
    assert "{{" not in than


def test_ky_tu_xml_trong_ten_khong_bi_cat():
    # Tắt autoescape thì "&HTVH" và "<B>" bị bộ đọc recover nuốt mất, không báo lỗi
    than = _than(cs.generate_covers_docx("Phòng KSNB&HTVH", [_tap(1, "Trần <B> & C")]))
    assert "KSNB&amp;HTVH" in than
    assert "Trần &lt;B&gt; &amp; C" in than


def test_chuan_bi_mau_chi_chay_mot_lan():
    cs._patch_nho.cache_clear()
    cs._EnvNho._dich.cache_clear()
    cs.generate_covers_docx("Phòng Thử", [_tap(i, f"G{i}") for i in range(1, 6)])
    # Thân tài liệu là một chuỗi vào duy nhất; 4 tập sau đều trúng bộ nhớ
    assert cs._patch_nho.cache_info().hits >= 4
    assert cs._EnvNho._dich.cache_info().hits >= 4
