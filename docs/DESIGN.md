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

## Ngày làm việc — đừng viết `weekday() < 5`
Dùng `la_ngay_lam_viec()` / `dem_ngay_lam_viec()` từ `backend/services/lich_lam_viec.py`, sau khi
nạp lịch bằng `tai_lich(db, lo, hi)`. Ngày lễ **và ngày làm bù** đều đổi được kết quả.

Ba nguồn dữ liệu, quy tắc hợp nằm gọn trong `tai_lich()`:

| Bảng | Khai ở màn hình | Chứa gì |
|---|---|---|
| `public_holidays` | Nghỉ phép → tab ngày lễ (admin) | Danh mục ngày lễ chung |
| `duty_special_days` | Phân lịch trực → tab Ngày đặc biệt | `holiday`, `makeup`, `cutoff`, `settlement` |

- **Khai riêng của Sổ trực thắng**: ngày có dòng trong `duty_special_days` thì lấy nguyên
  `day_type` của dòng đó, kể cả khi ngày ấy cũng nằm trong `public_holidays`. Nhà nước hoán đổi
  ngày nghỉ thì một ngày vừa là lễ vừa là bù — hợp thẳng hai tập là hai màn hình đọc ra hai câu
  trả lời trái nhau.
- **`makeup` phải `is_confirmed = 1`** mới tính, cùng điều kiện với `get_makeup_dates()` bên Sổ trực.
- **`cutoff` / `settlement` KHÔNG phải ngày nghỉ** — chúng là ngày làm việc bận hơn bình thường.
  Chúng chỉ có mặt trong `tai_lich()` để chặn ngày đó nhận nhãn lễ từ `public_holidays`.

Bốn nơi đã dùng helper này: hạn nộp chứng từ (`handover_report_service`), quỹ phép
(`leaves.py` + `compute_carry_over` trong `database.py`), chấm công (`attendance.py`).
**Chính sách:** nghỉ phép rơi vào ngày làm bù thì **vẫn trừ vào quỹ phép** — hôm đó là ngày làm
việc thật.

> Ngoại lệ cố ý duy nhất: `_import_spread_dates()` trong `leaves.py` vẫn sinh ngày T2–T6 thuần.
> Đó là bản ghi giả lập để lưu **số** ngày phép đã dùng khi nhập file hạn mức, không phải người
> thật sự vắng mặt — chỉ độ dài danh sách có nghĩa.

> `/api/attendance/month` trả thêm `makeup_days` bên cạnh `holidays`. Frontend cần nó để không tô
> T7 làm bù thành màu cuối tuần trong khi cột Tổng đã cộng công của hôm đó.

> **Test cần bảng `duty_special_days`.** File test nào dựng schema tối giản mà gọi tới đường tính
> ngày làm việc thì phải khai bảng này, không thì `tai_lich()` ném `no such table`. Cố ý **không**
> bắt lỗi đó: bảng thiếu trên máy thật nghĩa là ngày làm bù bị bỏ qua âm thầm — đúng kiểu hỏng mà
> dự án này đã dính một lần (xem mục Schema Migrations).

## Schema Migrations
Thêm câu SQL vào list `schema_migrations` trong `backend/db/migrations.py::_ensure_indexes()`.
Chạy idempotent khi khởi động.

Lỗi bị nuốt **có chủ đích** (nghĩa là migration đã chạy ở lần khởi động trước):
`duplicate column`, `already exists`, `already another table`.

Mọi lỗi khác — **kể cả `no such table`** — được log ERROR và raise, chặn khởi động.
Riêng `database is locked` chỉ log WARNING và bỏ qua, thử lại ở lần khởi động sau.

> `no such table` từng nằm trong danh sách nuốt lỗi. Hậu quả: migration viết sai tên bảng
> thất bại **im lặng** — không log, không chặn khởi động, cột không được thêm. Đừng đưa lại vào.

## Đọc dòng "Request chậm"
Mỗi dòng `slow.request` kèm trạng thái lúc request kết thúc (`backend/core/slow_request.py::trang_thai`):

```
Request chậm: GET /api/auth/me — 2771 ms (ngưỡng 1500 ms, HTTP 200) | loop chặn tối đa 140 ms, trễ tổng 1380 ms · luồng 3/40 chờ 0 · kết nối CSDL 2/48 xếp cổng 0 · đang xử lý 5 · việc nặng 0/4 · đối chiếu 1
```

| Thấy | Nghĩa là |
|---|---|
| `trễ tổng` lớn (hàng trăm ms trở lên), `chặn tối đa` nhỏ, `đối chiếu` ≥ 1 | Luồng đối chiếu giữ GIL — loop bị đói thành nhiều quãng ngắn (card 144) |
| `chặn tối đa` gần bằng `trễ tổng` và lớn | Một cú chặn liền: `async def` gọi hàm đồng bộ nặng không `await` |
| `luồng 40/40 chờ >0` | Threadpool cạn — endpoint `def` giữ luồng lâu |
| `kết nối CSDL 48/48`, `xếp cổng >0` | Bể CSDL cạn (xem mục dưới) |
| Mọi số đều thấp | Thời gian mất ngoài Python: đĩa, mạng, tiến trình khác |

Hai chi tiết đừng "đơn giản hoá":
- **Phải có cả `trễ tổng`, không chỉ `chặn tối đa`.** Tranh GIL không tạo một cú chặn dài mà làm loop đói
  liên tục: đo 3 luồng CPU × 2 s → max 138–231 ms nhưng tổng 790–890 ms (rảnh: tổng 12 ms). Chỉ nhìn
  max là kết luận nhầm "không phải GIL". Tổng đã trừ nền 16 ms/nhịp (sleep trên Windows tự trễ một
  nhịp timer).
- **Phải cộng phần task đo đang ngủ quá giờ** — dòng log được ghi ngay khi loop vừa thoát chỗ chặn,
  trước khi task đo kịp thức. Bỏ đi thì đúng ca cần bắt báo 0.

## Bể kết nối CSDL — chỉ mượn qua `get_db`
Mọi request mượn kết nối bằng `Depends(get_db)`. **Không gọi `_muon()` trực tiếp** ở chỗ nào khác
(ngoại lệ duy nhất: `khoi_tao_pool()` lúc khởi động).

`get_db` có sub-dependency `_qua_cong_db()`: một cổng `async` cho tối đa `DB_POOL_SIZE` request qua cùng
lúc, phần dư chờ bằng `await` — **không giữ luồng**. Không có cổng thì request chờ kết nối đứng chiếm
luồng threadpool (40), request đang cầm kết nối hết luồng để chạy tiếp → hai bên chờ nhau. Đo 16/09/2026:
78 request đồng thời chậm nhất 268 ms, **90 request cả hệ thống đứng 31 giây** rồi ăn 500.

Cổng chỉ đúng khi mọi lượt mượn đều đi qua nó. Gọi `_muon()` thẳng từ luồng khác là cổng cho qua đủ
suất trong khi bể thiếu kết nối → mở lại đúng lỗi trên. Nâng `DB_POOL_SIZE` hay số luồng **không** sửa
được: chỉ dời ngưỡng. Xem card 143 trong Implementation-notes, test `tests/test_be_ket_noi_khoa_cheo.py`.

> Lỗi ném trong dependency chỉ ra console uvicorn, **không** vào `logs/app.log`. Cổng hết giờ chờ nên
> tự `_log.warning` trước khi trả 503 — đừng bỏ dòng log đó.

## Pipeline đối chiếu chạy ở tiến trình riêng — `chay_tach()`

Pipeline nặng (pandas/Excel) chạy trong luồng của backend là giữ GIL, request nhẹ đứng chờ.
Gọi qua `backend/core/tien_trinh_doi_chieu.py::chay_tach()` thì chạy ở tiến trình con; luồng `_run`
của service vẫn ở backend và chuyển log về dict job như cũ. Đã áp cho **cả 7 cửa** (18/09/2026) —
xem card 150. `tests/test_doi_chieu_chay_tien_trinh_rieng.py` đỏ nếu service nào gọi `dang_ky_nguon()`
mà không gọi `chay_tach()` — **thêm cửa đối chiếu mới thì phải đi qua `chay_tach()`**.

Hàm đưa vào `chay_tach()` phải: (1) ở **cấp module** — con import lại theo tên; lambda/hàm lồng bị
từ chối bằng `TypeError`; (2) nhận `log_callback` + `cancel_event` và **mọi tiến độ đi qua hai thứ
đó** (callback khác khai qua `callbacks=`) — ghi vào dict toàn cục của module là ghi vào bản sao
trong con, màn hình đứng 0% không lỗi. Module nào đang báo tiến độ qua `_progress[token]` thì theo
khuôn `_xu_ly_tach()` của 459901 / OSB; (3) tham số và kết quả pickle được; (4) trả `None` khi bị huỷ;
(5) không tự tạo tiến trình con; (6) không đụng `job`/`_jobs` — trả kết quả cho `_run` ghi (khuôn
`_doi_chieu()` của Song phương ĐẾN/ĐI).

`DOI_CHIEU_TIEN_TRINH=0` → chạy trong luồng như cũ (khẩn cấp trên máy chủ).

Ngoài 7 cửa đối chiếu, **SWIFT recon** cũng tách (card 151) — kiểu hỏi–đáp đồng bộ, không có
job: `await run_heavy(chay_tach, tach.<hàm>, ...)`; phần nặng ở `backend/services/swift_recon/tach.py`,
API chỉ ghi file tải lên ra đĩa + đọc/ghi CSDL.

**Khi nào đáng tách:** mã Python thuần giữ GIL (pandas xử lý chuỗi, openpyxl, xlrd, docxtpl, cây
XML) **và** chạy lâu hơn nhiều ~0,8 s mở tiến trình. Việc trong mã C tự nhả GIL (zlib, AES, truy
vấn SQLite, bcrypt) không cần. Dưới ~1 s cứ `run_heavy()` — đọc thử 1 file SWIFT cố ý không tách.

**Không `asyncio.to_thread` trong `backend/api/`** — bể 40 luồng chung, lọt ngoài `MAX_HEAVY`
(DTBB từng vậy tới 18/09/2026). Test canh: `test_api_khong_dung_asyncio_to_thread`.

> **Test:** `conftest.py` mặc định `DOI_CHIEU_TIEN_TRINH=0` — tiến trình con **không thấy `monkeypatch`**
> của test. Test vá `svc.TEMP_DIR` mà chạy tiến trình thật là ghi vào `data/temp_*` THẬT (đã xảy ra
> 18/09/2026). Test cần tiến trình thật thì xin fixture `tien_trinh_that` và chỉ truyền đường dẫn tường minh.

## Authentication & Sessions
- JWT verify bởi `get_current_staff` trong `deps.py` — role đọc từ **DB** mỗi request, không lấy từ token
- Session lưu trong DB (`backend/core/sessions.py` → bảng `login_sessions`) — **không** mất khi restart
- 401 từ backend → `SessionExpiredError` → `_handle_api_error()` redirect về `/login`
- Trong `asyncio.gather()`: check `isinstance(e, api.SessionExpiredError)` trước `Exception`

## Phân quyền — mọi menu và thao tác đi qua Phân quyền theo nhóm

**Quy tắc bắt buộc (người dùng chốt 03/09/2026): không hard-code quyền.** Việc một người
*thấy* menu nào và *bấm được* nút nào phải quyết định bằng mã quyền trong
`backend/core/features.py`, gán qua màn **Phân quyền theo nhóm**. Không viết điều kiện
theo `role`, theo mã phòng, hay theo bất kỳ thuộc tính nào khác của người dùng để mở/khoá
tính năng.

Vì sao: quyền hard-code chỉ đổi được bằng sửa mã nguồn + deploy. Người vận hành nhìn màn
Phân quyền thấy đủ ô tick nhưng tick vào không có tác dụng — không lỗi, không log, và
người tiếp theo đọc code không biết quyền thật nằm ở đâu.

### Thêm một menu hoặc thao tác mới — 4 chỗ, thiếu chỗ nào cũng hỏng lặng lẽ

| # | Chỗ sửa | Nội dung |
|---|---|---|
| 1 | `FEATURES` trong `backend/core/features.py` | Khai mã: `menu.<key>` cho menu, `<key>.<hành động>` cho thao tác |
| 2 | `FEATURE_GROUPS` cùng file | Vẽ ô tick lên màn Phân quyền — soi gương `MENU_TREE` |
| 3 | Route backend | `Depends(require_feature("<mã>"))` — xem `backend/core/deps.py` |
| 4 | Frontend | `api.has_feature("<mã>")`; menu thì để `_dept_group()` tự lọc |

- Thiếu (1) → `_assert_feature_coverage()` chặn khởi động. Đây là lưới an toàn duy nhất.
- Thiếu (2) → mã không được vẽ ra ô tick nào. `PUT /api/groups/{id}/features` **xoá sạch**
  quyền của nhóm rồi ghi lại đúng các ô đang hiển thị → lần bấm Lưu đầu tiên xoá mã đó khỏi
  mọi nhóm. Cũng bị `_assert_feature_coverage()` chặn.
- Thiếu (3) → menu ẩn nhưng gọi thẳng API vẫn chạy.
- Thiếu (4) → hiện menu rồi bấm vào ăn 403.

### Không phải quyền: bước duyệt trong quy trình

`ksv_approver_id`, `gd_approver_id`, chủ đơn — đó là **dữ liệu của từng hồ sơ**, không phải
quyền. Nút "Duyệt" chỉ hiện cho đúng người được giao đơn ấy; kiểm bằng so id, không bằng
mã quyền và cũng không phải thứ admin gán được. Quy tắc trên **không** áp cho nhóm này.

### Ngoại lệ duy nhất được phép hard-code

**Màn Phân quyền chức năng** (`menu.groups` / `group-features`) gate cứng theo
`admin` / `admin_l2`. Gate nó bằng mã quyền thì ai được cấp mã đó tự cấp thêm cho mình —
quyền tự nhân bản, không còn ai chặn được. Đừng "sửa cho nhất quán".

Vai `admin` đi qua mọi cửa (`require_feature()` cho qua ngay ở dòng đầu) — đó là siêu quyền
cố ý, không tính là hard-code tính năng.

### Route công khai — chỉ `/` và `/health`

Mọi route khác đều có `Depends(...)`. Hai route này đăng ký thẳng trên `app` trong
`backend/main.py` (không qua `registry.py`) và không đòi đăng nhập:

- `/` — chuỗi tĩnh.
- `/health` — `{"status", "db_ok"}`, 200 hoặc 503. Cho script khởi động / người vận hành biết
  backend đã lên. Vì công khai nên **không** thêm trường nào khác (đường dẫn, phiên bản, backup,
  lệch giờ): backup và lệch giờ đã có ở màn Nhật ký hệ thống, sau `menu.logs`.

Rà "route nào thiếu Depends" mà đếm ra đúng hai cái này là đúng thiết kế, không phải lỗ.

### Phạm vi quyền ≠ phạm vi dữ liệu

Hai module của phòng Kế toán từng gate theo mã phòng `ACCT`, nay gate bằng mã quyền
(03/09/2026). Nhưng **dữ liệu** vẫn khoanh theo phòng và điều đó là đúng:

- Bảng công (`/api/attendance/*`) chỉ liệt kê nhân viên phòng `ACCT` — `WHERE d.code='ACCT'`
  trong `_acct_staff_rows()`. Người phòng khác được cấp `menu.attendance` sẽ **vào được màn
  hình** và thấy bảng công phòng Kế toán; đó là quyết định của admin khi tick ô, không phải lỗi.
- "Người kiểm soát" ký bảng công vẫn bắt buộc là trưởng/phó phòng `ACCT` đang active — đó là
  yêu cầu của **chứng từ**, không phải quyền truy cập.

Đừng nhân danh quy tắc "không hard-code quyền" đi gỡ hai chỗ trên.

### Khảo sát — trả lời theo danh sách người nhận, không theo mã quyền

`menu.surveys` / `surveys.create` / `surveys.view_all` là quyền (tạo, sửa, xem kết quả). Còn
**trả lời** chỉ cần có dòng trong `survey_recipients` — cùng loại với người được giao duyệt đơn.
Vì thế `_PENDING_DEFS` (shared.py) và `_KINDS` (pending_work.py) có mục feature `None`, và
`/surveys/fill` không kiểm `has_feature`. Gate bằng mã quyền thì gửi khảo sát cho nhóm chưa tick
menu là cả nhóm không trả lời được mà không ai hay. Đừng "sửa cho nhất quán".

`/api/surveys` nằm trong `_SKIP_PREFIXES` của `audit_middleware.py`: middleware ghi cả body, mà
body của lượt nộp là câu trả lời — khảo sát ẩn danh sẽ lộ nội dung trong Nhật ký hệ thống. Mọi
thao tác ghi đã tự `write_audit` không kèm nội dung.

Hai quy tắc ẩn danh khác, cùng lý do "khoá ở giao diện chưa đủ":
- Dòng kết quả ẩn danh xếp **theo nội dung**, không trộn bằng hạt giống cố định. Thứ tự nộp tra
  được trong Nhật ký (`survey.submit` ghi người + giờ) → hạt giống đoán được là đảo lại được.
- `PUT` chặn đổi `is_anonymous` khi đã có trả lời (cả hai chiều) và chặn tắt khi đã phát hành.

## RBAC — deps.py

| Dependency | Roles được phép |
|---|---|
| `get_current_staff` | Tất cả đã đăng nhập |
| `require_admin` | admin |
| `require_admin_any` | admin, admin_l2 — **chỉ dùng cho `/api/groups`** (màn Phân quyền chức năng); cấp 2 còn bị `_chan_l2_tu_cap_quyen()` chặn ghi lên nhóm chứa chính mình và chặn tự thêm mình vào nhóm |
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

> ⚠ **Bỏ `lambda` là đổi thời điểm tra tên.** `lambda: f()` chỉ tra `f` lúc bấm; `on_click=f` tra
> **ngay lúc dựng trang**. Nếu `async def f` nằm **bên dưới** nút trong cùng hàm trang thì `f` là biến
> cục bộ chưa gán → `UnboundLocalError`, cả trang không mở được. Hàm định nghĩa sau thì tạo nút trước
> rồi gắn sau: `btn = ui.button(...)` … `async def f(): …` … `btn.on_click(f)`.
> Đã xảy ra thật: `bundles.py` (30/08/2026), vá 11/09/2026. Xem mục *Lỗi tên chưa định nghĩa* dưới đây.

## Lỗi tên chưa định nghĩa — test xanh không chứng minh gì, chạy ruff F821

Python chỉ tra tên **lúc chạy tới dòng đó**. Tên sai / thiếu import / dùng trước khi định nghĩa nằm
trên nhánh không test nào đi qua thì cả bộ test vẫn xanh. Hai lỗi thật cùng lọt vào `develop`, cùng
qua review, cùng được `ruff check --select F821` bắt trong một lần chạy (11/09/2026):

| Lỗi | Sinh ra từ | Vì sao test không bắt |
|---|---|---|
| `ilo1000_service._run()` gọi `os.listdir`, file không `import os` → ILO1000 **không bao giờ trả kết quả** | Đổi `os.path.basename()` → `safe_filename()` lúc rebase PR#68; `import os` trông như thừa nên bị bỏ (suy luận — bản trước rebase không còn trong repo), `os.listdir` 60 dòng dưới còn dùng | Test đưa file giả → pipeline trả `None` → return trước dòng lỗi. `except Exception` trong luồng nền đổi `NameError` thành job `error` trông như lỗi dữ liệu |
| `bundles_page`: `on_click=load_groups` đứng trước `async def load_groups` → **trang không mở được** | Dọn `ensure_future` theo mục trên, làm **kèm** trong một commit sửa hiệu năng khác | Không test nào dựng trang; `test_kiem_nap_trang_frontend` chỉ kiểm import |

Điểm chung: cả hai là **sửa phụ, sửa máy móc** nằm trong một thay đổi lớn hơn. Người review đọc từng
khối diff — không thấy dòng `import` đã mất ở đầu file, không thấy dòng định nghĩa 50 dòng bên dưới.

**Quy tắc:** sau khi xoá import, đổi tên, đổi `lambda` thành tham chiếu thẳng, hay chuyển mã giữa các
hàm/file → chạy `ruff check . --select F821,F823,E9` và phải sạch. Từ 11/09/2026 CI chạy lệnh này
và báo **đỏ** (`.github/workflows/tests.yml`, cấu hình ở `ruff.toml`). Đỏ **không tự khoá** nút
Merge — repo riêng tư gói Free không bật được bảo vệ nhánh; `gh pr checks` phải xanh mới merge. Còn 48 lời gọi
`ensure_future`/`create_task` ở 10 trang (không tính chú thích) — dọn hàng loạt mà không chạy lệnh này là gặp lại lỗi thứ hai.

## Nuốt lỗi — ba lựa chọn, không có lựa chọn thứ tư

`except Exception: pass` trần là thứ bị cấm (SKILL.md). Gặp một khối như vậy, chọn ĐÚNG MỘT trong ba:

| Tình huống | Làm gì |
|---|---|
| Chỉ một loại lỗi cụ thể là bình thường (sai khuôn ngày, file đã xoá, ống đã đóng) | **Thu hẹp** `except (ValueError, TypeError)` / `OSError` / `sqlite3.Error`… — lỗi lập trình sẽ nổ ra thay vì bị nuốt |
| Bỏ qua được nhưng có mất mát (thiếu một dòng dữ liệu, một ngày lễ, một đơn trong lô) | **Ghi log** `_log.warning(..., exc_info=True)` kèm ngữ cảnh (id nào, năm nào) |
| Thật sự không quan trọng (dọn dẹp, hâm nóng, chờ WebSocket) | **Ghi lý do ngay tại dòng** `pass  # …` — người sau đọc là biết đây là chủ ý |

Rà 12/09/2026 (`backend/` + `frontend/`): 39 khối `except Exception: pass` → **15 thu hẹp, 10 thêm log,
10 giữ nguyên kèm lý do, 4 đổi thành cảnh báo cho người dùng**.

> Mức log: `root.setLevel(INFO)` trong `backend/main.py` → **`_log.debug()` không ra file nào**. Muốn thấy
> thì dùng `info` trở lên. Log của tiến trình **frontend** đi vào `logs/frontend.log`, KHÔNG vào
> `logs/app.log` và KHÔNG hiện ở màn Nhật ký hệ thống (màn đó chỉ đọc `app.log`).
Hai chỗ đang **mất dữ liệu âm thầm** (đổi ngày lễ âm lịch hỏng → thiếu hẳn một ngày lễ; duyệt hàng
loạt đơn nghỉ phép → mất lý do từng đơn lỗi) nay có log. Xem card *NL1* trong Implementation-notes.

## Trang Nghỉ phép là một GÓI, không phải một file

`frontend/pages/leaves/` — đang chẻ dần từ một file 6.473 dòng (một hàm 6.125 dòng):

| File | Chứa gì |
|---|---|
| `__init__.py` | `@ui.page("/leaves")` + phần trang chưa tách |
| `_chung.py` | Hằng số + helper cấp module (nguyên văn từ bản cũ) |
| `_chi_tiet_don.py` | Ngăn kéo chi tiết một đơn (728 dòng) + `ChiTietCtx` |

**Tách một phần ra thì state đi qua một `ctx` dataclass, KHÔNG qua tham số rời.** Lý do: vài thứ
(`leave_tabs`, `_nav_pending`, `_nav_pending_th`) được tạo **sau** chỗ định nghĩa hàm đã tách.
Closure cũ chạy được vì Python tra tên lúc **gọi**; truyền theo giá trị lúc định nghĩa là ba thứ
đó bằng `None` — hỏng đúng lúc người dùng bấm nút, không test nào bắt. `ctx` đọc thuộc tính lúc
gọi nên giữ nguyên hành vi đó. `tests/test_leaves_chi_tiet_ctx.py` canh mọi trường của `ctx` đều
được trang gán.

> Test nào cần đọc mã trang (kiểm chuỗi) thì nối **cả gói**, đừng trỏ vào một file —
> xem `_ma_trang_nghi_phep()` trong `tests/test_nghi_phep_buoc_th_va_gd.py`.

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
docx (docxtpl) → [Word thường trú qua PowerShell] → PDF gốc (cache RAM theo nội dung)
                                                     ├→ pypdfium2 render → PNG xem trước
                                                     └→ pypdfium2 dán ảnh chữ ký → PDF tải về
```
- **Một bản Word chạy nền, dùng lại giữa các lần gọi** (`_WordServer` + `docx_pdf_server.ps1`).
  Mở/đóng Word tốn ~3,6 giây còn chuyển một file chỉ ~0,25 giây — mở lại mỗi lần là tự trả
  giá 3,6 giây đó cho từng người dùng. Đo: 4,1–6,5 giây → **0,32–0,39 giây/lượt**.
- **Word chỉ chạy khi cache trượt.** Khoá cache = template + mtime + toàn bộ ctx → đổi người
  duyệt/số ngày là tự dựng lại. Dán chữ ký ~0,02 giây nên mỗi lần ký thêm KHÔNG gọi Word.
- `_word_lock` tuần tự hoá: hai request cùng lúc sẽ đẻ hai tiến trình WINWORD tranh nhau.
- Word tự tắt khi rảnh `WORD_IDLE_SECONDS` (mặc định 900) và được thay bản mới sau
  `WORD_MAX_JOBS` lượt (mặc định 100). `WORD_SERVER=0` quay về cách cũ (mở/đóng từng lần).
- `POST /api/leaves/preview/warmup` bật sẵn Word lúc người dùng mở màn Nghỉ phép; trả lời
  ngay, không đợi Word lên.
- PID của WINWORD do mình sinh ra ghi ở `data/word_server.pid`; lần khởi động sau diệt bản
  mồ côi (backend bị `taskkill /F` thì `atexit` không chạy). **Luôn kiểm tên chương trình
  bằng `_la_winword()` trước khi diệt** — Windows cấp lại PID cho tiến trình khác.

> Trong `docx_pdf_server.ps1` phải dùng `[Console]::Out.WriteLine()` + `Flush()`, **không**
> `Write-Output`: `Write-Output` đi qua bộ định dạng của PowerShell và nằm lại trong bộ đệm,
> Python đọc dòng sẽ chờ mãi — treo im lặng, không lỗi nào.

> ### ⚠ Không bao giờ `Quit()` một bản Word đang có cửa sổ
> Nếu bản Word ngầm là WINWORD **duy nhất** đang chạy trên máy, người vận hành double-click một
> file `.docx` thì Windows điều tài liệu đó vào **đúng tiến trình của mình**. Đo được: PID không
> đổi, `MainWindowHandle` từ `0` nhảy lên khác `0`, tiêu đề cửa sổ thành tên tài liệu của họ.
> `Quit()` lúc đó **đóng tài liệu của họ**, và nếu `DisplayAlerts=0` thì đóng luôn không hỏi
> "có lưu không" — mất bài đang gõ, không có cách lấy lại.
>
> Ba hàng rào, đừng gỡ cái nào:
> 1. `DisplayAlerts` chỉ tắt **quanh `Open`/`SaveAs` của mình**, xong trả lại `-1` (wdAlertsAll).
> 2. Lúc thoát chỉ `Quit()` khi `Documents.Count -eq 0` **và** `MainWindowHandle -eq 0`.
>    Giữ lại thì **xoá luôn `word_server.pid`** để lần khởi động sau không diệt nhầm.
> 3. `_kiem_truoc_khi_diet()` phía Python chặn mọi `taskkill` lên WINWORD có cửa sổ; tra không
>    được cũng **không** bắn.
>
> Lỗi khi có lỗi phải đóng **đúng tài liệu của mình** (`$doc`), không quét sạch `Documents`.

> ### ⚠ Word không làm việc ở phiên 0
> Máy chủ **phải có người đăng nhập**. Chạy backend bằng Windows Service hoặc Task Scheduler
> *"chạy cả khi không ai đăng nhập"* là rơi vào phiên 0 — đo được ở đó:
> `New-Object -ComObject Word.Application` **thành công** (0,59 s), nhưng `Documents.Open()`
> **trả `null` mà không ném lỗi**. Bước tạo COM chạy được nên nhìn qua tưởng Word ổn.
>
> `docx_pdf_server.ps1` bắt riêng trường hợp `$doc -eq $null` và ném thông báo nói thẳng
> nguyên nhân — không có nó thì lỗi hiện ra là "You cannot call a method on a null-valued
> expression", đọc xong không biết làm gì. Xem mục *Word đòi phiên đăng nhập trên máy chủ*
> trong README.
> Thứ tự ngược lại (người vận hành mở Word **trước**, backend bật sau) thì hai tiến trình tách
> rời — an toàn sẵn, nhưng đó không phải thứ tự thường gặp vì backend chạy suốt ngày.
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
