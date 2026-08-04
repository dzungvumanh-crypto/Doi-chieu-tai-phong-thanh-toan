# -*- coding: utf-8 -*-
"""Kiểm tra / sửa .env trên máy đích khi deploy.

Vì sao cần: `deploy.bat` copy code nhưng KHÔNG đụng tới `.env` của máy đích — đúng
như thiết kế, để không ghi đè SECRET_KEY và cấu hình riêng. Hệ quả là hai biến sau
phải sửa tay, và quên thì **im lặng không báo gì**:

* `BACKEND_URL` — nếu để `localhost`, mỗi kết nối frontend→backend sau ~5 giây
  nhàn rỗi tốn thêm ~2 giây. Nguyên nhân: trên Windows `localhost` phân giải ra
  ::1 (IPv6) trước, mà uvicorn chỉ lắng nghe IPv4. Đo được: 2062ms so với 18ms.
* `BACKEND_HOST` — trước đây là hằng số cứng trong code, sửa .env không có tác
  dụng. Nay nó điều khiển thật, nên .env thiếu dòng này là mập mờ.

Viết bằng Python thay vì batch vì `for /f` của cmd nuốt dòng trống và vướng dấu
ngoặc trong comment — sửa .env bằng batch thuần rất dễ làm hỏng file.

Dùng:
    python deploy_env_check.py <đường-dẫn-.env> <cổng-backend> check
    python deploy_env_check.py <đường-dẫn-.env> <cổng-backend> fix

Mã thoát: 0 = không có gì phải sửa (hoặc đã sửa xong), 1 = cần sửa, 2 = lỗi.
"""
import io
import os
import sys

DUNG_URL_MAU = "http://127.0.0.1:{port}"


def _doc(path: str) -> list:
    with io.open(path, encoding="utf-8-sig") as f:
        return f.read().splitlines()


def _gia_tri(dong: list, khoa: str):
    """Trả (chỉ_số, giá_trị) của dòng KHOA=..., bỏ qua dòng comment."""
    for i, d in enumerate(dong):
        s = d.strip()
        if s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == khoa:
            return i, v.strip()
    return -1, None


def main() -> int:
    if len(sys.argv) < 4:
        print("  [LOI] Thieu tham so: <.env> <cong> <check|fix>")
        return 2
    path, cong, che_do = sys.argv[1], sys.argv[2], sys.argv[3].lower()

    if not os.path.exists(path):
        # start.bat se tu tao .env khi chay lan dau — khong phai loi
        print(f"  [BO QUA] Chua co {path} -- start.bat se tu tao khi chay lan dau.")
        return 0

    try:
        dong = _doc(path)
    except Exception as e:
        print(f"  [LOI] Khong doc duoc {path}: {e}")
        return 2

    dung_url = DUNG_URL_MAU.format(port=cong)
    can_sua = []

    # ── BACKEND_URL ──────────────────────────────────────────────────────────
    i_url, v_url = _gia_tri(dong, "BACKEND_URL")
    if v_url is None:
        # Khong co dong nay -> code dung mac dinh 127.0.0.1, van dung.
        # Van nen ghi ro de nguoi sau doc .env la hieu.
        can_sua.append(("BACKEND_URL", "(khong co)", dung_url, "them cho ro rang"))
    elif "localhost" in v_url.lower():
        can_sua.append(("BACKEND_URL", v_url, dung_url, "localhost -> cham 2 giay moi ket noi"))
    elif v_url != dung_url:
        can_sua.append(("BACKEND_URL", v_url, dung_url, f"khong khop cong {cong}"))

    # ── BACKEND_HOST ─────────────────────────────────────────────────────────
    # KHONG tu doi gia tri: 0.0.0.0 hay 127.0.0.1 tuy thuoc co may khac goi API
    # hay khong -- day la quyet dinh cua nguoi van hanh, khong phai cua script.
    i_host, v_host = _gia_tri(dong, "BACKEND_HOST")
    if v_host is None:
        can_sua.append(("BACKEND_HOST", "(khong co)", "0.0.0.0", "them, giu nguyen hanh vi cu"))

    if not can_sua:
        print(f"  [OK] .env dung: BACKEND_URL={v_url}, BACKEND_HOST={v_host}")
        return 0

    print("  [CAN SUA] .env tren may dich:")
    for khoa, cu, moi, ly_do in can_sua:
        print(f"      {khoa}: {cu}  ->  {moi}   ({ly_do})")

    if che_do != "fix":
        return 1

    # ── Sửa: chỉ đụng đúng dòng cần đổi, giữ nguyên mọi thứ khác ─────────────
    for khoa, _cu, moi, _ly in can_sua:
        i, _ = _gia_tri(dong, khoa)
        if i >= 0:
            dong[i] = f"{khoa}={moi}"
        else:
            if dong and dong[-1].strip():
                dong.append("")
            dong.append(f"{khoa}={moi}")

    try:
        with io.open(path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(dong) + "\n")
    except Exception as e:
        print(f"  [LOI] Khong ghi duoc {path}: {e}")
        return 2

    print("  [OK] Da sua .env. Cac dong khac (SECRET_KEY, STORAGE_SECRET...) giu nguyen.")
    if v_host is not None:
        print(f"      BACKEND_HOST giu nguyen = {v_host} (script khong tu doi gia tri nay)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
