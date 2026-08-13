"""
Đường dẫn có dấu tiếng Việt — chống lệch chuẩn hoá Unicode (NFC/NFD).

Windows lưu tên file **đúng y như lúc tạo**, không tự chuẩn hoá Unicode. Cùng một
cái tên "Phòng Tổng hợp" có hai cách mã hoá khác nhau về byte:

    NFC  "ò" = 1 ký tự U+00F2
    NFD  "ò" = "o" + dấu huyền rời (U+006F U+0300)

Thư mục trong repo đang ở dạng NFD (được tạo từ máy Mac hoặc từ bản giải nén giữ
nguyên NFD), còn chuỗi gõ trong mã nguồn là NFC. Kết quả: `os.path.exists()` trả
về **False** dù thư mục hiện rành rành trong Explorer, và `os.makedirs()` sẽ tạo
ra một thư mục **thứ hai trùng tên** — đúng thứ đã xảy ra với "Phòng Tổng hợp".

`resolve_path()` đi từng đoạn đường dẫn và so tên sau khi chuẩn hoá NFC, nên trỏ
đúng thư mục bất kể nó được tạo ở dạng nào.
"""
import os
import unicodedata
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _match_entry(parent: str, name: str) -> Optional[str]:
    """Tìm mục con của `parent` trùng tên `name` sau khi chuẩn hoá NFC."""
    target = _nfc(name)
    try:
        entries = os.listdir(parent)
    except OSError:
        return None
    for e in entries:
        if _nfc(e) == target:
            return os.path.join(parent, e)
    return None


def resolve_path(base: str, *parts: str) -> str:
    """Ghép đường dẫn, mỗi đoạn khớp theo tên đã chuẩn hoá NFC.

    Đoạn nào không tìm thấy thì ghép thẳng phần còn lại và trả về — để caller tự
    quyết bằng `os.path.exists()` (nhiều chỗ có sẵn fallback hợp lệ khi thiếu file).
    """
    cur = base
    for i, part in enumerate(parts):
        direct = os.path.join(cur, part)
        if os.path.exists(direct):
            cur = direct
            continue
        found = _match_entry(cur, part)
        if found is None:
            return os.path.join(cur, *parts[i:])
        cur = found
    return cur


def template_path(*parts: str) -> str:
    """Đường dẫn dưới `templates/`, chịu được lệch NFC/NFD."""
    return resolve_path(TEMPLATES_DIR, *parts)
