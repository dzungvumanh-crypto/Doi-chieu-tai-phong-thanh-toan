# -*- coding: utf-8 -*-
"""Dò file thừa trên máy đích khi deploy — file đã bị xoá khỏi dự án nhưng vẫn
nằm lại trên máy chính.

Vì sao cần: `deploy.bat` chép bằng `robocopy /E`, chỉ thêm và ghi đè, **không bao
giờ xoá**. File nào bị xoá khỏi dự án sẽ nằm lại vĩnh viễn trên máy đích.

Với hầu hết file thì đó chỉ là rác. Nhưng `frontend/main.py` nạp trang bằng
`pkgutil.iter_modules(frontend/pages)` — **mọi file .py trong thư mục đó đều tự
thành một trang**. Nên một trang đã xoá khỏi dự án vẫn sống trên máy chính, vẫn
mở được bằng địa chỉ cũ, và gọi vào API đã bị gỡ. Admin bị nặng nhất vì
`api_client.has_feature()` trả True cho mọi mã quyền khi role là admin, kể cả mã
đã bị xoá khỏi danh mục — nên lớp chặn quyền không cứu được.

> Đã xảy ra thật: PR #31 viết lại module ACH, xoá `frontend/pages/doi_chieu_ach.py`
> cùng 11 file khác. Không có bước này thì trang cũ vẫn sống trên máy chính.

Phạm vi quét = đúng 4 thư mục `deploy.bat` chép: `backend`, `frontend`, `templates`,
`scripts`.

Chỉ **tự xoá** file `.py` thừa trong `backend/`, `frontend/` và `scripts/`, vì đó luôn
là mã nguồn cũ. Mọi thứ khác (kể cả file trong `templates/`) chỉ **liệt kê ra**, không
đụng tới: mẫu Word có thể do người dùng tự thêm trên máy chính, xoá là mất thật.

Bỏ qua `__pycache__` và `*.pyc` — `deploy.bat` vốn không chép chúng, và bước xoá
`__pycache__` sau đó đã dọn rồi.

Dùng:
    python scripts/deploy_don_file_thua.py <thư-mục-nguồn> <thư-mục-đích> check
    python scripts/deploy_don_file_thua.py <thư-mục-nguồn> <thư-mục-đích> fix

Mã thoát: 0 = không có gì phải xoá, 1 = có file thừa, 2 = lỗi.
"""
import os
import sys

# Đúng 3 cây thư mục `deploy.bat` chép sang bằng robocopy /E
CAY_QUET = ("backend", "frontend", "templates", "scripts")

# Chỉ tự xoá mã nguồn cũ, và chỉ trong 2 cây này
CAY_DUOC_XOA = ("backend", "frontend", "scripts")
DUOI_DUOC_XOA = ".py"


def _liet_ke(goc: str, cay: str) -> set:
    """Đường dẫn tương đối của mọi file trong <goc>/<cay>, bỏ __pycache__ và *.pyc."""
    ket_qua = set()
    thu_muc = os.path.join(goc, cay)
    if not os.path.isdir(thu_muc):
        return ket_qua

    for goc_con, ten_thu_muc, ten_file in os.walk(thu_muc):
        ten_thu_muc[:] = [t for t in ten_thu_muc if t != "__pycache__"]
        for ten in ten_file:
            if ten.endswith(".pyc"):
                continue
            duong_dan = os.path.join(goc_con, ten)
            ket_qua.add(os.path.relpath(duong_dan, goc).replace("\\", "/"))
    return ket_qua


def _tim_thua(nguon: str, dich: str) -> tuple:
    """Trả về (thua_xoa_duoc, thua_chi_bao) — đường dẫn tương đối so với gốc."""
    xoa_duoc, chi_bao = [], []
    for cay in CAY_QUET:
        ben_nguon = _liet_ke(nguon, cay)
        for rel in sorted(_liet_ke(dich, cay) - ben_nguon):
            if cay in CAY_DUOC_XOA and rel.endswith(DUOI_DUOC_XOA):
                xoa_duoc.append(rel)
            else:
                chi_bao.append(rel)
    return xoa_duoc, chi_bao


def _xoa(dich: str, danh_sach: list) -> int:
    """Xoá từng file rồi dọn thư mục rỗng còn lại. Trả về số file đã xoá."""
    da_xoa = 0
    thu_muc_cham = set()
    for rel in danh_sach:
        duong_dan = os.path.join(dich, rel.replace("/", os.sep))

        # Chốt an toàn: tuyệt đối không đi ra ngoài cây được phép xoá
        that = os.path.realpath(duong_dan)
        hop_le = any(
            that.startswith(os.path.realpath(os.path.join(dich, c)) + os.sep)
            for c in CAY_DUOC_XOA
        )
        if not hop_le:
            print(f"      [BO QUA] Ngoai pham vi cho phep: {rel}")
            continue

        try:
            os.remove(duong_dan)
            thu_muc_cham.add(os.path.dirname(duong_dan))
            da_xoa += 1
            print(f"      [DA XOA] {rel}")
        except OSError as e:
            print(f"      [LOI] Khong xoa duoc {rel}: {e}")

    # Thư mục rỗng sau khi xoá (VD backend/services/doi_chieu_ach/) — dọn từ trong ra
    for thu_muc in sorted(thu_muc_cham, key=len, reverse=True):
        for _ in range(5):   # leo tối đa 5 cấp, đủ sâu cho cây của dự án
            try:
                if not os.listdir(thu_muc) or os.listdir(thu_muc) == ["__pycache__"]:
                    if os.path.isdir(os.path.join(thu_muc, "__pycache__")):
                        for f in os.listdir(os.path.join(thu_muc, "__pycache__")):
                            os.remove(os.path.join(thu_muc, "__pycache__", f))
                        os.rmdir(os.path.join(thu_muc, "__pycache__"))
                    os.rmdir(thu_muc)
                    print(f"      [DA XOA] {os.path.relpath(thu_muc, dich)}/ (thu muc rong)")
                    thu_muc = os.path.dirname(thu_muc)
                else:
                    break
            except OSError:
                break
    return da_xoa


def main() -> int:
    if len(sys.argv) < 4:
        print("  [LOI] Thieu tham so: <thu-muc-nguon> <thu-muc-dich> <check|fix>")
        return 2

    nguon, dich, che_do = sys.argv[1], sys.argv[2], sys.argv[3].lower()

    for ten, duong_dan in (("nguon", nguon), ("dich", dich)):
        if not os.path.isdir(duong_dan):
            print(f"  [LOI] Khong thay thu muc {ten}: {duong_dan}")
            return 2

    if os.path.realpath(nguon) == os.path.realpath(dich):
        print("  [BO QUA] Nguon va dich la mot -- khong co gi de so sanh.")
        return 0

    try:
        xoa_duoc, chi_bao = _tim_thua(nguon, dich)
    except OSError as e:
        print(f"  [LOI] Khong doc duoc thu muc: {e}")
        return 2

    if not xoa_duoc and not chi_bao:
        print("  [OK] May dich khong co file thua.")
        return 0

    if chi_bao:
        print(f"  [XEM LAI] {len(chi_bao)} file chi co tren may dich, KHONG tu xoa")
        print("            (co the do nguoi dung tu them -- kiem tra bang mat):")
        for rel in chi_bao[:20]:
            print(f"      {rel}")
        if len(chi_bao) > 20:
            print(f"      ... va {len(chi_bao) - 20} file nua")

    if not xoa_duoc:
        return 1

    if che_do == "fix":
        print(f"  Dang xoa {len(xoa_duoc)} file .py cu tren may dich...")
        da_xoa = _xoa(dich, xoa_duoc)
        print(f"  [OK] Da xoa {da_xoa}/{len(xoa_duoc)} file.")
        return 0

    print(f"  [FILE THUA] {len(xoa_duoc)} file .py da bi xoa khoi du an nhung con tren may dich:")
    for rel in xoa_duoc:
        print(f"      {rel}")
    print("  Trang trong frontend/pages/ van tu dong duoc nap -- de lai la con mo duoc bang dia chi cu.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
