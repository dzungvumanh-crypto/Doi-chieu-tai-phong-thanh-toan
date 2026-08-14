# DESIGN.md — Patterns & Business Logic

## Timestamps
Dùng `_vn_now()` từ `backend/database.py` cho mọi timestamp (UTC+7, naive datetime). Không dùng `datetime.utcnow()`.

## Tên bảng
Bảng nhân sự tên là **`user_tttt`**. Tên cũ `ksnb_staff` đã bị đổi (xem `_ensure_indexes()` trong
`backend/db/migrations.py`) — các file trong `Plan/` và `Upgrade/` là tài liệu lịch sử, vẫn ghi tên cũ.
**Không copy tên bảng từ hai thư mục đó.**

## Đường dẫn template có dấu tiếng Việt
Dùng `template_path()` từ `backend/core/paths.py`, **không** `os.path.join(..., "templates", "Phòng ...")`.

Tên thư mục trên đĩa và trong git ở dạng Unicode **NFD**; chuỗi gõ trong mã nguồn là **NFC**. Windows
không chuẩn hoá tên file → hai chuỗi khác nhau về byte → `os.path.exists()` trả `False` dù thư mục vẫn ở
đó, và `os.makedirs()` đẻ ra thư mục **thứ hai trùng tên**.

Thư mục con (`Nghỉ phép`, `Bàn giao cho lưu trữ`) cũng NFD — đưa **toàn bộ** các đoạn vào
`template_path()`, đừng resolve nửa chừng rồi `os.path.join` tiếp.

> Đã xảy ra thật: `templates/` từng có hai thư mục "Phòng Tổng hợp" (một NFD có dữ liệu, một NFC rỗng).
> `leaves.py` trỏ vào bản rỗng nên mẫu đơn riêng theo chức danh **không bao giờ được dùng** — không lỗi,
> không log, chỉ lặng lẽ rơi về mẫu chung. `tests/test_paths.py` canh không cho tái diễn.

## Schema Migrations
Thêm câu SQL vào list `schema_migrations` trong `backend/db/migrations.py::_ensure_indexes()`.
Chạy idempotent khi khởi động.

Lỗi bị nuốt **có chủ đích** (nghĩa là migration đã chạy ở lần khởi động trước):
`duplicate column`, `already exists`, `already another table`.

Mọi lỗi khác — **kể cả `no such table`** — được log ERROR và raise, chặn khởi động.
Riêng `database is locked` chỉ log WARNING và bỏ qua, thử lại ở lần khởi động sau.

> `no such table` từng nằm trong danh sách nuốt lỗi. Hậu quả: migration viết sai tên bảng
> thất bại **im lặng** — không log, không chặn khởi động, cột không được thêm. Đừng đưa lại vào.

## Authentication & Sessions
- JWT verify bởi `get_current_staff` trong `deps.py` — role đọc từ **DB** mỗi request, không lấy từ token
- Session lưu trong DB (`backend/core/sessions.py` → bảng `login_sessions`) — **không** mất khi restart
- 401 từ backend → `SessionExpiredError` → `_handle_api_error()` redirect về `/login`
- Trong `asyncio.gather()`: check `isinstance(e, api.SessionExpiredError)` trước `Exception`

## RBAC — deps.py

| Dependency | Roles được phép |
|---|---|
| `get_current_staff` | Tất cả đã đăng nhập |
| `require_admin` | admin |
| `require_hkv_or_above` | admin, hau_kiem_vien |
| `require_pho_phong_or_above` | admin, hau_kiem_vien, truong_phong, pho_phong |
| `require_handover_write` | admin, hau_kiem_vien, truong_phong, pho_phong, chuyen_vien |
| `require_ksnb` | Tất cả trừ chuyen_vien |
| `require_ksv` | truong_phong, pho_phong |
| `require_gd_level` | giam_doc, pho_giam_doc |
| `require_admin_or_gd` | admin, giam_doc, pho_giam_doc |

## Role Hierarchy
```
admin > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien
```
- `controller` deprecated → migrate sang `pho_phong`
- GĐ/PGĐ bắt buộc thuộc phòng **Ban Giám đốc** (code `BGD`, is_source=False)
- Chuyên viên bắt buộc thuộc phòng nguồn (is_source=True)
- Admin **không** tham gia quy trình duyệt nghỉ phép
- GĐ/PGĐ xem được tất cả màn hình nhưng chỉ thao tác ở bước duyệt GĐ

## Frontend Async Pattern
```python
# Gọi song song:
a, b = await asyncio.gather(
    asyncio.to_thread(api.get, "/api/foo"),
    asyncio.to_thread(api.get, "/api/bar"),
    return_exceptions=True,
)
# Xử lý lỗi:
try:
    result = await asyncio.to_thread(api.post, "/api/...", body)
except Exception as e:
    if _handle_api_error(e):  # True + redirect nếu SessionExpiredError
        return
```

## Event handler async — đừng bọc `asyncio.create_task`
```python
ui.upload(on_upload=_upload_sig)          # ĐÚNG — truyền thẳng hàm async
ui.button("Xóa", on_click=_delete_sig)    # ĐÚNG

ui.upload(on_upload=lambda e: asyncio.create_task(_upload_sig(e)))   # SAI
```
NiceGUI nhớ "đang vẽ vào chỗ nào" bằng ngăn xếp slot gắn theo **asyncio task**
(`Slot.stacks[id(current_task())]`). `create_task` / `ensure_future` sinh task mới → ngăn xếp rỗng →
`ui.notify`, `ui.timer`, `ui.navigate.*` ném `RuntimeError: slot stack for this task is empty`, rơi vào
handler ngoại lệ toàn cục → **màn hình không đổi gì, cũng không có thông báo lỗi**.

Truyền thẳng thì `handle_event()` await coroutine bên trong `with parent_slot:` nên slot còn nguyên qua
mọi `await`. Nếu buộc phải chạy trong task rời, mọi thao tác UI phải nằm trong `with element:`.

## Leave Approval Workflow
```
pending_ksv → pending_tong_hop → pending_gd → approved | rejected | cancelled
```
- Bước 1 — KSV: Trưởng phòng / Phó phòng (auto-assign khi tạo đơn)
- Bước 2 — Tổng hợp: nhân viên phòng TH chọn GĐ/PGĐ duyệt tiếp
- Bước 3 — GĐ: GĐ hoặc PGĐ nếu có `DelegationRecord` còn hiệu lực
- `resubmit`: rejected → pending_ksv (re-assign KSV)
- `cancel`: huỷ khi pending hoặc approved
- `used_leave_days` điều chỉnh qua `_apply_status_transition()` (idempotent)

## Ngày của tập chứng từ (`bundles.cover_units`)
Ngày trên bảng "Tra cứu lưu trữ" **không** phải một cột trong `bundles`. `_get_dates_for_bundle()`
đọc `cover_units` (JSON: mỗi unit = người nộp + ngày + số tờ), chỉ khi rỗng mới fallback sang
`bundle_items → document_entries.transaction_date`.

Sửa ngày (`PATCH /api/bundles/storage-view`) **ghi lại `cover_units`**, không bao giờ
`UPDATE document_entries` — entry là số liệu bàn giao đã chốt của phòng nguồn, dùng chung cho báo
cáo khối lượng. Tháng/năm lấy từ `bundle_groups.notes` ("Tháng MM/YYYY"), không nhận từ client.

Tập không còn ngày nào sẽ **bị loại khỏi bảng** (`_decompose_bundles_to_rows` chỉ xét dòng có
1 ngày hoặc >1 ngày) mà vẫn nằm trong DB → mọi đường ghi ngày phải chặn danh sách ngày rỗng.

## Word Template Generation
```python
from docxtpl import DocxTemplate
tpl = DocxTemplate("templates/don_xin_nghi_phep_tpl.docx")
tpl.render(context_dict)
buf = io.BytesIO(); tpl.save(buf)
```
Dùng `_download_headers(filename)` từ `backend/api/bundles.py` cho RFC 6266 Content-Disposition.

## Đơn nghỉ phép bản PDF + chữ ký (`backend/services/leave_pdf.py`)
```
docx (docxtpl) → [Word COM qua PowerShell] → PDF gốc (cache RAM theo nội dung)
                                              ├→ pypdfium2 render → PNG xem trước
                                              └→ pypdfium2 dán ảnh chữ ký → PDF tải về
```
- **Word chỉ chạy khi cache trượt** (5–7 giây/lần). Khoá cache = template + mtime + toàn bộ
  ctx → đổi người duyệt/số ngày là tự dựng lại. Dán chữ ký ~0,02 giây nên mỗi lần ký thêm
  KHÔNG gọi Word.
- `_word_lock` tuần tự hoá: hai request cùng lúc sẽ đẻ hai tiến trình WINWORD tranh nhau.
- Toạ độ chữ ký tính bằng **mm từ góc TRÊN-TRÁI trang** (hệ của trình duyệt); `stamp()` lật
  trục y khi ghi vào PDF.
- `leave_signatures.image` là **bản sao** ảnh lúc ký, không phải khoá ngoại sang
  `user_signatures`: người ký đổi/xoá ảnh cá nhân thì đơn đã ký không đổi theo.
- Vị trí gợi ý dò bằng `find_text_box()` trên chính bản in (`match_case=True` — chữ thường
  "Trưởng phòng" còn nằm ở dòng "Chức vụ:").

> `stamp()` phải dùng **cùng một đối tượng trang** cho `insert_obj()` và `gen_content()`.
> `doc[i]` nạp trang MỚI mỗi lần gọi → gen_content trên đối tượng khác thì ảnh vừa chèn bị
> bỏ, PDF lưu ra y như chưa ký mà **không có lỗi nào**.

Máy chủ không có Word → `PdfConvertError` → API trả 503; frontend tự lui về tải bản `.docx`
(`/download?fmt=docx`) và vẫn cho duyệt đơn không kèm chữ ký. Quy trình nghỉ phép không được
đứng lại vì không chuyển đổi được PDF.
