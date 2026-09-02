# Checklist trước khi mở PR — đúc từ lịch sử review của Khánh

**Đọc file này TRƯỚC khi mở bất kỳ PR nào**, đặc biệt khi PR có: upload file, chạy job nền,
đường dẫn/tên file do người dùng nhập, hoặc thêm quyền/menu mới.

## Vì sao file này tồn tại

Rà lại lịch sử review PR #43, #54, #63, #66, #68, #69, #70 (dùng agent đọc toàn bộ comment
GitHub của `khanhbq693`) cho thấy: phần lớn thời gian review của Khánh là **lặp lại đúng vài
loại lỗi cốt lõi**, không phải lỗi mới mỗi lần. Nguyên nhân thường là port code giữa các nhánh
song song (Cham_ILO1000 ↔ develop) mang theo bản CŨ của một chỗ đã fix, hoặc copy pattern cũ
trước khi `develop` sửa nó. File này liệt kê đúng những loại lỗi đó kèm pattern chuẩn đã có sẵn
trong code — mục tiêu là tự bắt được trước khi Khánh phải bắt hộ.

Không phải checklist lý thuyết — mỗi mục dưới đây gắn với ≥ 1 PR thật đã bị yêu cầu sửa lại vì
đúng lỗi đó, nhiều mục lặp lại ở 3-4 PR khác nhau.

---

## 1. Hợp đồng API frontend ↔ backend

**Lỗi lặp lại ở PR #43, #54, #63**: gọi `api.post_multipart` — hàm này **không tồn tại** trong
`frontend/api_client.py`. Hàm đúng là `api.post_upload(path, files, data=None, timeout=None)`,
payload đúng dạng:
```python
files=[("files", (name, data, "application/octet-stream")) for name, data in ...]
```
Vì bộ test API dùng `TestClient` gọi thẳng backend, lớp lỗi này **không bao giờ bị bắt bởi
pytest** — nút bấm chết hẳn trên UI thật mà toàn bộ test vẫn xanh.

☐ Đụng tới `frontend/` → chạy `pytest tests/test_kiem_nap_trang_frontend.py -v` (import THẬT mọi
  trang, bắt lỗi tên hàm/import sai — xem docstring file này, có kể vụ thật 30/08/2026 mất cả
  trang đăng nhập vì port nửa vời).
☐ Trang mới/sửa có gọi `_sidebar(...)` không — nhớ `await` (hàm đã đổi `async def` từ PR #22,
  17/08; bản cũ trên `Cham_ILO1000` còn sync — port code cũ sang dễ quên `await`, lỗi này im
  lặng: sidebar/menu biến mất, không exception nào raise).
☐ Nếu có thể, tự chạy `python frontend/main.py` hoặc mở tay trang vừa sửa trên trình duyệt trước
  khi đẩy commit — test import không thay được việc BẤM THỬ nút.

## 2. An toàn tên file / path traversal

**Lỗi lặp lại ở PR #43, #54, #63, #68**: ghép `token`/`filename` do client gửi thẳng vào
`Path` rồi ghi/đọc/xoá. `os.path.basename()` tự chế **không đủ an toàn trên Windows** —
`%5C` (`\`) không bị router chặn như `%2F`, và `pathlib` coi `\` là dấu phân cách thư mục, nên
`..\..\data` lọt qua rồi `shutil.rmtree()` xoá nhầm `data/` (chứa SQLite thật).

☐ Mọi chỗ ghép tên file từ client vào path: dùng `safe_filename()` (`backend/core/uploads.py`)
  — **không** viết `os.path.basename()`/tự cắt chuỗi tay.
☐ Token dạng UUID (thư mục job/kết quả): validate bằng `uuid.UUID(token)` rồi kiểm
  `(TEMP_DIR / token).resolve().is_relative_to(TEMP_DIR.resolve())` trước khi dùng.
☐ File trùng tên trong 1 lượt upload nhiều file: phải raise 400 rõ ràng (xem `ach.py::start_job`
  dòng ~116-127) — không âm thầm ghi đè.

## 3. Đường dẫn thư mục máy chủ do client nhập (`folder_path`)

**Lỗi lặp lại ở PR #43, #63, #68/#69/#70** — 3 PR ba cách xử lý khác nhau (không giới hạn / gỡ
hẳn / siết quyền nhưng quên giới hạn phạm vi). Xu hướng dự án đang đi tới: **bỏ hẳn tính năng
này**, chỉ còn "tải file lên" (xem PR#54 gỡ ACH, PR#70 gỡ Song phương + ILO1000 — cả hai lần đều
vì cùng lý do: vá allowlist từng endpoint dễ sót, một endpoint mới thêm sau quên vá là lại mở
lỗ hổng).

☐ **Trước khi thêm "chọn thư mục server" cho module mới — hỏi trước, đừng tự làm.** Codebase
  đang chủ động thu hẹp tính năng này, không mở rộng.
☐ Nếu bắt buộc phải giữ (như Chấm 459901): allowlist fail-closed đúng khuôn `cham459901_folder_roots()`
  (`backend/core/config.py`) — chưa cấu hình `.env` thì **raise rõ ràng**, không mặc định "không
  giới hạn".
☐ Khi port code cũ giữa 2 nhánh sang nhau: grep `folder_path`, `open_folder_picker`, `/api/fs/`
  trong code sắp port — nếu thấy, dừng lại hỏi trước khi mang sang, đừng port nguyên xi.

## 4. Upload không ôm RAM

**Lỗi lặp lại ở PR #43, #54, #63**: `await f.read()` trần hoặc gom `dict[str, bytes]` trước khi
ghi — một file vài trăm MB là tiến trình chết giữa lúc đang nhận, hoặc đỉnh RAM gấp đôi dung
lượng thật.

☐ Nhận file từ client: `save_upload_to()` ghi thẳng theo khối (không giữ trong RAM), hoặc
  `read_limited()` nếu bắt buộc phải có bytes trong tay — **không bao giờ** `await f.read()` trần.
☐ Trần dung lượng (`_MAX_UPLOAD`) phải kẹp: `max(_MB, min(so_mb('X_MAX_UPLOAD_MB', 500) * _MB,
  MAX_REQUEST_BYTES - 8*_MB))` (mẫu `backend/api/ach.py` dòng ~41) — hằng số cứng (800MB, 1GB…)
  sẽ mâu thuẫn với `MAX_REQUEST_MB` mặc định 600 mà `BodySizeLimitMiddleware` chặn trước, khiến
  client chỉ thấy socket đứt kiểu "[WinError 10054]" thay vì thông báo 413 rõ ràng.
☐ Job đăng ký theo mẫu `tao_job()/bo_job()/chay_job()` (`ach_service.py`) — tách "tạo job + thư
  mục input" khỏi "chạy pipeline" để ghi file xen giữa, và `bo_job()` dọn sạch khi upload lỗi/đứt
  giữa chừng (không để lại job "pending" mồ côi).
☐ Job chạy nền: `threading.Thread`, **không** `BackgroundTasks` (Starlette chạy nó trong
  threadpool 40-token dùng chung của anyio — giữ token đó vài phút làm nghẽn mọi endpoint sync
  khác của cả hệ thống, lỗi từng bị "quên" lại 1 lần ở PR #63 sau khi #43 đã sửa).

## 5. RBAC — tách quyền xem/chạy + khai báo feature code

**Lỗi lặp lại ở PR #54 (A1), #68/#69**: endpoint chạy/sửa/xoá gộp chung permission với endpoint
chỉ xem, hoặc feature code dùng trong route nhưng quên khai báo trong `FEATURES` — không ai cấp
được quyền đó qua màn Phân quyền, chỉ admin dùng được mà không log/báo gì.

☐ Module có thao tác "chạy/sửa/xoá" tách 2 mã: `menu.X` (xem trang/poll/download) và
  `X.process` (chạy/dừng) — khuôn mẫu `backend/api/ach.py` (`_XEM`/`_CHAY`).
☐ Thêm feature code mới: khai ở **CẢ HAI** `FEATURES` dict và `FEATURE_GROUPS` tree trong
  `backend/core/features.py` — thiếu 1 trong 2 thì `_assert_feature_coverage()` chặn khởi động
  (an toàn), nhưng vẫn nhớ làm cả 2 cùng lúc để khỏi mất công sửa lại.
☐ Chạy `pytest tests/test_feature_codes_declared.py -v` sau khi thêm `require_feature()`/
  `require_any_feature()`/`has_feature()` mới — kể cả dạng gọi keyword-arg.
☐ Nếu tách quyền MỚI cho module ĐANG CHẠY (không phải module mới toanh): cần migration
  `INSERT OR IGNORE` cấp bù quyền mới cho mọi nhóm đang có quyền cũ, không thì user cũ mất nút
  chạy ngay lúc deploy mà "bấm không có gì xảy ra" không rõ lý do.

## 6. Đường dẫn tuyệt đối

☐ Mọi `TEMP_DIR`/thư mục dữ liệu: `BASE_DIR / "data" / "..."` — không viết `Path("data/...")`
  tương đối (phụ thuộc thư mục làm việc lúc khởi động, rủi ro khi deploy).

## 7. Xử lý lỗi — không bắt trần, không nuốt im lặng

☐ Không `except Exception:`/`except ValueError:` trần rồi gán 1 thông điệp cứng cho MỌI nguyên
  nhân — tạo lớp lỗi riêng khi cần phân biệt (mẫu `LoiDinhDangSoTien(ValueError)` ở
  `ach/so_tien.py`), để lỗi tương lai khác không bị hiểu nhầm.
☐ Vòng poll (frontend): dùng `api.la_loi_mang(e)` để phân biệt "mất mạng" (thử lại, đếm
  `poll_fails`, có ngưỡng dừng, huỷ timer khi dừng) với "máy chủ trả lời lỗi dứt khoát" (VD 404
  job hết hạn — dừng ngay, không thử lại). Không được nuốt `SessionExpiredError` — phải để
  `_handle_api_error()` redirect `/login`.
☐ `try/except` nuốt lỗi mà không log là vi phạm rõ trong `SKILL.md` — luôn log hoặc phân loại
  lại, đừng chỉ `pass`/`continue`.
☐ Đổi chữ ký hàm nội bộ (VD thêm tham số `cutoff`) → grep toàn bộ call site, đừng để 1 chỗ gọi
  cũ bị `except` nuốt mất `TypeError` rồi lịch dọn/cron không bao giờ chạy mà không ai biết.

## 8. Dữ liệu thật có ô trống/NaN — đừng chỉ test giá trị "sạch"

**Lỗi lặp lại ở PR #66, #69** (cùng 1 lỗi 2 lần): thắt chặt parser số tiền từ
`to_numeric(errors='coerce').fillna(0)` (chịu ô trống) sang `astype(str)` + regex nghiêm ngặt
(raise khi gặp `''`/`'nan'`) — file GL02/tồn tháng trước là loại **người dùng sửa tay bằng
Excel**, xác suất có ô trống rất cao. Test không bắt được vì helper luôn truyền `'0'` tường minh.

☐ Viết/sửa parser đọc số tiền — dùng lại `ach/so_tien.py::doc_so_tien()` làm chuẩn, đừng viết
  hàm mới riêng.
☐ Test cho hàm đọc file Excel/CSV: **bắt buộc** có ít nhất 1 case ô trống/NaN/giá trị lạ, không
  chỉ test giá trị "sạch" — đây chính là input thật gây lỗi nhiều nhất trong dự án này.
☐ Sửa luật parse ở 1 module (VD ACH) → grep xem module khác (459901, Song phương, ILO1000) có
  đọc CÙNG loại file nguồn (GL02) với luật cũ không — nếu có, sửa đồng bộ hoặc ghi rõ lý do tại
  sao cố tình khác nhau.

## 9. Tài liệu đồng bộ với code

☐ Code/comment nhắc "xem Implementation-notes.html card X" → card đó phải **thực sự tồn tại**
  trong cùng PR, không để treo cho lần sau.
☐ `docs/Implementation-notes.html`, `SKILL.md`, `DESIGN.md` đã dọn vào `docs/` từ 13/08 (trên
  `develop`) — viết vào đúng vị trí đó, đừng tạo lại bản ở gốc repo (xung đột `modify/delete` khi
  rebase, mất nội dung mới nếu giải sai chiều).
☐ Thêm biến `.env` bắt buộc mới (mật khẩu, allowlist...) → đăng ký vào
  `scripts/deploy_env_check.py::CHI_CANH_BAO` để `deploy.bat` cảnh báo khi máy đích thiếu, và
  thêm dòng giải thích vào `.env.example`.
☐ Không viết cứng bí mật (mật khẩu ZIP, token) vào source dù chỉ tạm thời — đọc từ `.env` ngay
  từ đầu, kể cả khi module đang code dở.

## 10. Rebase/xung đột khi nhánh sống lâu song song với `develop`

**Bài học PR #69/#70**: `develop` merge bằng squash làm mất tổ tiên chung → xung đột dạng
**add/add** (git không có gì để so 3-way, người giải phải chọn nguyên 1 bên cho cả file). Lấy
nhầm bên "theirs" có thể **âm thầm lùi lại một fix vừa merge xong, mà test cũ vẫn xanh** (vì
file test cũng bị lấy theo bản cũ).

☐ Nhánh feature không nên sống quá 1-2 tuần song song với `develop` — rebase sớm, đừng để dồn.
☐ Trước khi mở PR từ nhánh lạc hậu nhiều: `git merge-base <nhánh> develop` + xem trước bằng
  `git merge-tree` để biết phạm vi xung đột, đặc biệt liệt kê rõ file nào là add/add.
☐ Giải xung đột add/add ở file thuộc `features.py`/`migrations.py`/`ach/*`/RBAC: **lấy bản
  `develop` làm gốc, mang tính năng của nhánh sang** — không lấy nguyên bản nhánh cũ đè lên.
☐ Có nhiều PR song song cùng sửa 1 file/module: nêu rõ trong PR description thứ tự merge đề
  xuất và rủi ro nếu merge sai thứ tự (đừng để người review tự suy luận).

## 11. Phạm vi & giao tiếp

☐ Phát hiện tác động NGOÀI phạm vi ban đầu (tốt hay xấu) khi đang sửa việc khác → ghi rõ vào PR
  description/comment, đừng chỉ âm thầm tự sửa hoặc âm thầm bỏ qua.
☐ Trộn commit tối ưu hiệu năng/refactor không liên quan vào 1 PR đã đủ phức tạp (VD PR#68 bị
  yêu cầu tách 4 commit perf ra PR riêng) — nếu PR đã lớn, cân nhắc tách phần độc lập ra trước.
☐ Đọc kỹ toàn bộ luồng review trước khi báo "đã sửa xong" — Khánh thường review nhiều vòng, vòng
  sau có thể nêu vấn đề nặng hơn vòng đầu (VD #70: vòng 1 chỉ nói B2, vòng 2 mới yêu cầu đổi
  hướng bỏ hẳn tính năng).

---

## Cách dùng file này

- Đọc lướt cả 11 mục trước khi bắt đầu code 1 tính năng mới liên quan upload/job nền/quyền/thư
  mục máy chủ.
- Trước khi báo "xong, sẵn sàng review": đối chiếu lại đúng những mục liên quan tới PR đang làm,
  tick từng dòng thay vì chỉ chạy test suite rồi coi là đủ.
- Sau mỗi vòng review mới của Khánh phát hiện 1 loại lỗi CHƯA có trong danh sách này (không phải
  biến thể của lỗi đã liệt kê) — thêm mục mới vào đây ngay, đừng để trôi qua.
