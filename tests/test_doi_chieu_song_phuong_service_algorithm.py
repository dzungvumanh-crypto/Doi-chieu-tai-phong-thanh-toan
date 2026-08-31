"""
Test thuật toán module Phân loại dữ liệu Đối chiếu Song phương (`doi_chieu_song_phuong_service.py`).

Tập trung vào đường tắt giải mã numba cho ZipCrypto cổ điển (2026-09-01, xem
Implementation-notes.html card 100) — phát hiện file GL02 thật dùng ZipCrypto (không phải AES-256
như tài liệu cũ ghi), viết lại vòng lặp giải mã bằng numba (nhanh ~35-39 lần so với vòng lặp Python
thuần của pyzipper). Vì pyzipper không hỗ trợ GHI ZipCrypto cổ điển (chỉ ghi được AES), test tự
dựng 1 file ZIP ZipCrypto hợp lệ bằng tay (đúng thuật toán PKWARE) để verify đường tắt — không phụ
thuộc dữ liệu GL02 thật (đã verify riêng, xem card 100, không lặp lại ở đây).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_doi_chieu_song_phuong_service_algorithm.py -v
"""

import io
import os
import struct
import zlib

import pandas as pd
import pyzipper
import pytest

from backend.services import doi_chieu_song_phuong_service as svc

_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (0xEDB88320 ^ (_c >> 1)) if (_c & 1) else (_c >> 1)
    _CRC_TABLE.append(_c)


def _crc1(crc, ch):
    return (crc >> 8) ^ _CRC_TABLE[(crc ^ ch) & 0xFF]


def _derive_keys(pwd: bytes):
    key0, key1, key2 = 305419896, 591751049, 878082192
    for p in pwd:
        key0 = _crc1(key0, p)
        key1 = (key1 + (key0 & 0xFF)) & 0xFFFFFFFF
        key1 = (key1 * 134775813 + 1) & 0xFFFFFFFF
        key2 = _crc1(key2, key1 >> 24)
    return key0, key1, key2


def _encrypt(data: bytes, key0, key1, key2):
    out = bytearray()
    for p in data:
        k = key2 | 2
        out.append(p ^ (((k * (k ^ 1)) >> 8) & 0xFF))
        key0 = _crc1(key0, p)
        key1 = (key1 + (key0 & 0xFF)) & 0xFFFFFFFF
        key1 = (key1 * 134775813 + 1) & 0xFFFFFFFF
        key2 = _crc1(key2, key1 >> 24)
    return bytes(out), key0, key1, key2


def _make_zipcrypto_zip(filename: str, content: bytes, pwd: bytes) -> bytes:
    """Tự dựng 1 file ZIP mã hoá ZipCrypto cổ điển (đúng thuật toán PKWARE, giống hệt
    `pyzipper.zipfile.CRCZipDecrypter`) — pyzipper CHỈ hỗ trợ ghi AES, không ghi được ZipCrypto,
    nên không thể dùng `pyzipper.AESZipFile` để tạo fixture loại này."""
    crc = zlib.crc32(content) & 0xFFFFFFFF
    co = zlib.compressobj(6, zlib.DEFLATED, -15)
    compressed = co.compress(content) + co.flush()

    key0, key1, key2 = _derive_keys(pwd)
    header = os.urandom(11) + bytes([(crc >> 24) & 0xFF])
    enc_header, key0, key1, key2 = _encrypt(header, key0, key1, key2)
    enc_data, key0, key1, key2 = _encrypt(compressed, key0, key1, key2)
    ciphertext = enc_header + enc_data

    name_b = filename.encode()
    flag = 0x1
    csize = len(ciphertext)
    usize = len(content)

    local = struct.pack(
        "<IHHHHHIIIHH", 0x04034B50, 20, flag, 8, 0, 0x21, crc, csize, usize, len(name_b), 0,
    ) + name_b + ciphertext

    central = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50, 20, 20, flag, 8, 0, 0x21, crc, csize, usize,
        len(name_b), 0, 0, 0, 0, 0, 0,
    ) + name_b

    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(local), 0)
    return local + central + eocd


_GL02_CONTENT = (
    b"BUSCD,UNIT,TRCD,CUSTOMER,TRTP,REFERENCE,REMARK,DRAMOUNT,CRAMOUNT,CRTDTM\r\n"
    b"1000,X,Y,1000-003046287,Z,REF1,GHI CHU,0,50000,20260101\r\n"
    b"1000,X,Y,1000-003046328,Z,REF2,GHI CHU,100000,0,20260101\r\n"
)


class TestZipCryptoNumbaFastPath:
    def test_giai_ma_dung_noi_dung_goc(self):
        """Đường tắt numba phải giải mã+giải nén ra ĐÚNG nội dung gốc — so với chính
        `zlib`/thuật toán tham chiếu, không qua pyzipper (test độc lập với pyzipper)."""
        pwd = svc.ZIP_PASSWORD
        zip_bytes = _make_zipcrypto_zip("gl02.csv", _GL02_CONTENT, pwd)
        with pyzipper.AESZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.setpassword(pwd)
            out = svc._doc_1_file_thanh_vien(zf, "gl02.csv", pwd)
        assert out == _GL02_CONTENT

    def test_sai_mat_khau_raise(self):
        """Sai mật khẩu phải bị bắt sớm qua check_byte (giống `CRCZipDecrypter`), không âm thầm
        trả về rác."""
        zip_bytes = _make_zipcrypto_zip("gl02.csv", _GL02_CONTENT, b"mat-khau-dung")
        with pyzipper.AESZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.setpassword(b"mat-khau-sai")
            with pytest.raises(ValueError, match="Sai mật khẩu"):
                svc._doc_1_file_thanh_vien(zf, "gl02.csv", b"mat-khau-sai")

    def test_khop_ket_qua_voi_pyzipper_that(self):
        """So trực tiếp với `zf.read()` gốc của pyzipper trên CÙNG 1 file — phải giống hệt (đúng
        thuật toán, không chỉ 'trông giống')."""
        pwd = svc.ZIP_PASSWORD
        zip_bytes = _make_zipcrypto_zip("gl02.csv", _GL02_CONTENT, pwd)
        with pyzipper.AESZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.setpassword(pwd)
            expected = zf.read("gl02.csv", pwd=pwd)
        with pyzipper.AESZipFile(io.BytesIO(zip_bytes)) as zf2:
            zf2.setpassword(pwd)
            actual = svc._doc_1_file_thanh_vien(zf2, "gl02.csv", pwd)
        assert actual == expected

    def test_entry_aes_that_khong_bi_nham_thanh_zipcrypto(self):
        """Entry AES THẬT (ghi bằng `pyzipper.AESZipFile(..., encryption=WZ_AES)`) phải rơi về
        `zf.read()` gốc, KHÔNG được đường tắt ZipCrypto xử lý nhầm — dù `compress_type` sau khi
        pyzipper decode extra field AES cũng trả về 8 (giống hệt ZipCrypto), phải phân biệt bằng
        `wz_aes_version`."""
        pwd = b"aes-pwd"
        buf = io.BytesIO()
        with pyzipper.AESZipFile(buf, "w", compression=pyzipper.ZIP_DEFLATED,
                                  encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(pwd)
            zf.writestr("gl02.csv", _GL02_CONTENT)
        buf.seek(0)
        with pyzipper.AESZipFile(buf) as zf2:
            info = zf2.getinfo("gl02.csv")
            assert getattr(info, "wz_aes_version", None) is not None, \
                "fixture phải thật sự là AES để test có ý nghĩa"
            zf2.setpassword(pwd)
            out = svc._doc_1_file_thanh_vien(zf2, "gl02.csv", pwd)
        assert out == _GL02_CONTENT

    def test_process_zip_end_to_end_voi_zipcrypto(self, monkeypatch, tmp_path):
        """`process_zip()` đầy đủ (giải mã + định tuyến + ghi 8 CSV) trên ZIP ZipCrypto — đúng
        kịch bản GL02 thật, không phải fixture AES như các test khác trong dự án."""
        monkeypatch.setattr(svc, "TEMP_DIR", tmp_path / "_out")
        zip_bytes = _make_zipcrypto_zip("gl02.csv", _GL02_CONTENT, svc.ZIP_PASSWORD)

        result = svc.process_zip(zip_bytes)

        assert result["total_rows"] == 2
        out_dir = svc.TEMP_DIR / result["token"]
        # Dòng 1 (NH 201): DRAMOUNT=0 -> ĐI. Dòng 2 (NH 202): CRAMOUNT=0 -> ĐẾN (xem docstring
        # module: CRAMOUNT=0 => ĐẾN, DRAMOUNT=0 => ĐI).
        di_201 = pd.read_csv(out_dir / "201_DI.csv", dtype=str)
        assert len(di_201) == 1
        assert di_201.iloc[0]["REFERENCE"] == "REF1"
        den_202 = pd.read_csv(out_dir / "202_DEN.csv", dtype=str)
        assert len(den_202) == 1
        assert den_202.iloc[0]["REFERENCE"] == "REF2"
