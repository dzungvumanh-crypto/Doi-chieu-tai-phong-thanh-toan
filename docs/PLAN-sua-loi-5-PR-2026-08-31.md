# Kế hoạch xử lý 5 PR đang mở — chốt ngày 31/08/2026

Phạm vi: PR #43, #54, #66, #68, #69. Tất cả đều có commit vá review mới trong
ngày 31/08, tất cả đều đang `CONFLICTING` với `develop`.

Tài liệu này chia việc theo thứ tự thực hiện, không theo số PR. Mỗi việc có mã
để tiện trao đổi (VD `P43-1`), file liên quan và tiêu chí nghiệm thu cụ thể.

---

## 0. Hai quyết định cần chốt trước khi code

Hai việc dưới đây không phải lỗi kỹ thuật mà là lựa chọn nghiệp vụ. Chưa chốt
thì `P43-2` và `P68-2` không có đáp án đúng.

### Q1 — Có giữ chế độ "chạy từ thư mục máy chủ" không?

Ba PR đang đi ba hướng khác nhau cho cùng một rủi ro:

| PR | Hiện trạng |
|---|---|
| #43 | Giữ `/process_folder`, nhận `folder_path` tuỳ ý từ client |
| #54 | **Gỡ hẳn** folder-mode khỏi ACH (mục A4) vì đúng rủi ro này |
| #68 | Giữ `/api/fs/browse` cho 4 module, siết quyền nhưng không giới hạn phạm vi |

Ba phương án:

- **A. Gỡ hết** — theo #54, mọi module chỉ nhận file upload. Đơn giản nhất,
  an toàn nhất, nhưng người vận hành phải kéo-thả file hàng trăm MB mỗi lần.
- **B. Giữ, có allowlist gốc** — thêm `FOLDER_PICKER_ROOTS` vào `.env`, liệt kê
  vài thư mục dữ liệu thật. Mọi endpoint duyệt/đọc thư mục từ chối path ngoài
  danh sách. Giữ được tiện lợi, đóng được lỗ hổng.
- **C. Giữ nguyên** — chấp nhận rủi ro, ghi vào Implementation-notes.

**Đề xuất: B.** Cần người vận hành cho biết đường dẫn thật trên máy chủ để điền
vào `.env.example`.

### Q2 — Module ILO1000 lâu nay ai dùng được?

`menu.cham_ilo1000` được dùng ở 6 chỗ trong code nhưng **không có trong**
`backend/core/features.py`. Nghĩa là chưa từng có ai cấp được quyền này.

Cần xác nhận với người vận hành: từ trước tới nay có **ai ngoài admin** chạy
được Chấm ILO1000 không?

- Nếu **không** → đúng như phân tích, và `P68-1` là sửa lỗi.
- Nếu **có** → đang có một đường cấp quyền khác mà tài liệu không ghi, phải tìm
  ra trước khi sửa, kẻo sửa xong lại chặn nhầm người đang dùng.

---

## 1. Thứ tự merge

Thứ tự này **không phải chuyện dễ/khó mà là chuyện đúng/sai**. Ba file dưới đây
là xung đột `add/add` giữa nhánh `Cham_ILO1000` (#68, #69) và `develop`:

- `backend/services/ach/so_tien.py`
- `frontend/pages/cham_ach.py`
- `backend/core/features.py`

Với `add/add`, git không có tổ tiên chung để hoà — người giải xung đột phải chọn
một bên. Chọn nhầm bên là **lặng lẽ lùi lại các fix vừa làm, mà test vẫn xanh**
vì file test cũng bị lấy theo bản cũ.

Hai ca cụ thể phải tránh:

| Lấy nhầm bên | Hậu quả |
|---|---|
| `so_tien.py` bản #68 | Mất luật dấu phẩy + xử lý ô trống + `LoiDinhDangSoTien` của #66/#69 → tái phát lỗi "sai 1000 lần, im lặng" |
| `cham_ach.py` bản #68 | Hồi sinh folder-mode mà #54 vừa gỡ vì lý do bảo mật |

**Thứ tự thực hiện:**

```
#66  →  #54  →  #43  →  (rebase #68)  →  #68  →  #69
```

- **#66 trước tiên**: chỉ 12 commit behind, 1 file xung đột (docs). Merge xong
  là `so_tien.py` trên develop thành bản chuẩn, mọi nhánh sau phải theo.
- **#68 và #69 bắt buộc rebase, không merge thẳng**: 203 commit behind, 39 file
  xung đột. Merge thẳng là đọc không nổi và giải không kiểm soát được.

---

## 2. Việc theo từng PR

### PR #66 — `fix/ach-so-tien-ngan-nghin-2026-08-28`

Sạch nhất. Làm trước, merge trước.

| Mã | Việc | File | Nghiệm thu |
|---|---|---|---|
| `P66-1` | Thêm test cho `pd.NA` (dtype `string`) và `pd.NaT` | `tests/test_so_tien.py` | Test đỏ nếu ai đó xoá dòng `trong_nan = sr.isna()` |
| `P66-2` | Hỏi Business Owner: ô chứa dấu gạch ngang có phải là 0 không. Nếu đúng, thêm vào `_O_TRONG` + test | `backend/services/ach/so_tien.py` | Có câu trả lời bằng văn bản, ghi vào Implementation-notes |
| `P66-3` | Rebase lên develop, giải 1 xung đột `docs/Implementation-notes.html` | — | `git merge-tree` không còn báo xung đột |

**Lý do `P66-1`:** hiện `pd.NA` không lọt vì `sr.isna()` bắt trước. Nhưng vì thế
dòng đó **trông như thừa** và sẽ có người dọn đi trong một đợt refactor. Test là
thứ duy nhất giữ được lý do tồn tại của nó.

---

### PR #54 — `ach-chi-tim-timeout-2026-08-22`

Chất lượng code tốt. Rủi ro nằm ở lúc deploy chứ không ở code.

| Mã | Việc | File | Nghiệm thu |
|---|---|---|---|
| `P54-1` | 🔴 Migration cấp `cham_ach.process` cho mọi nhóm đang có `menu.cham_ach` | `backend/db/migrations.py` | Trên bản sao DB thật: chạy migration xong, user không phải admin vẫn bấm được nút Chạy |
| `P54-2` | Ghi vào `Logs_update.md` việc phải kiểm tra quyền sau deploy | `Logs_update.md` | Người vận hành đọc là biết phải làm gì |
| `P54-3` | Đổi `except HTTPException` thành bắt theo `e.status_code == 413` | `backend/api/ach.py::start_job` | Lỗi không phải 413 từ `read_limited()` không còn bị báo nhầm là "vượt 500 MB" |
| `P54-4` | Ghi chú deploy: xoá tay `data/temp_ach` cũ ở đường dẫn tương đối | `Logs_update.md` | — |

**Lý do `P54-1` là 🔴:** mã `cham_ach.process` đã nằm trong `features.py` từ
trước nhưng **chưa từng được enforce**. Nghĩa là các nhóm trong DB thật rất có
thể chỉ được cấp `menu.cham_ach`. Merge xong mà không có migration thì sáng hôm
sau cả phòng mất nút Chạy ACH, và triệu chứng ("bấm không có gì xảy ra") không
chỉ về nguyên nhân.

Cách kiểm tra trước khi merge, trên bản sao DB thật:

```sql
SELECT g.name
FROM user_groups g
JOIN group_features gf ON gf.group_id = g.id AND gf.feature_code = 'menu.cham_ach'
WHERE NOT EXISTS (
    SELECT 1 FROM group_features x
    WHERE x.group_id = g.id AND x.feature_code = 'cham_ach.process'
);
```

Ra dòng nào là nhóm đó sẽ mất nút Chạy.

---

### PR #43 — `fix/cham459901-3bugs`

| Mã | Việc | File | Nghiệm thu |
|---|---|---|---|
| `P43-1` | 🔴 Mang kèm `backend/api/fs.py` + đăng ký `fs_router`, **hoặc** tạm ẩn nút chọn thư mục | `backend/api/fs.py`, `backend/api/registry.py` | Bấm nút chọn thư mục mở được dialog và liệt kê được thư mục thật |
| `P43-2` | 🔴 Xử lý `/process_folder` theo quyết định Q1 | `backend/api/cham459901.py` | Nếu chọn B: trỏ path ngoài allowlist trả 400, có test |
| `P43-3` | Test so khớp `_classify_upload_filename` (frontend) với `classify_upload_filename` (backend) | `tests/` | Sửa luật một bên mà quên bên kia → test đỏ |
| `P43-4` | Mục 10: `BackgroundTasks` → `threading.Thread` | `backend/api/cham459901.py` | Job dài không còn giữ worker của thread pool |
| `P43-5` | Nit: thêm 2 dòng trống trước `async def open_folder_picker` | `frontend/shared.py:703` | — |
| `P43-6` | Rebase lên develop, giải 6 xung đột | — | — |

**Lý do `P43-1` là 🔴:** commit mới đã vá đúng lỗi ImportError (import một hàm
không tồn tại làm sập cả 27 trang). Nhưng chỉ nửa frontend được mang sang từ
nhánh song phương — `open_folder_picker()` gọi `GET /api/fs/browse`, mà endpoint
đó không có trên nhánh này lẫn trên develop:

```
$ git ls-tree origin/fix/cham459901-3bugs backend/api/fs.py
(rỗng)
```

Kết quả: trang không sập nữa, nhưng bấm nút chọn thư mục thì dialog hiện lỗi rồi
thôi. Tính năng vẫn chết, chỉ là chết êm hơn.

**`P43-4` giải thích thêm:** `BackgroundTasks` của FastAPI chạy **sau khi
response đã trả** nhưng vẫn nằm trong thread pool của server. Một job 459901
chạy vài phút là chiếm một worker suốt thời gian đó; vài người chạy cùng lúc là
cả backend chậm theo, kể cả các trang không liên quan.

---

### PR #68 — `feat/doi-chieu-song-phuong-den-2026-08-30`

PR lớn nhất và rủi ro nhất. **Rebase trước, review sau.**

| Mã | Việc | File | Nghiệm thu |
|---|---|---|---|
| `P68-0` | 🔴 Rebase lên develop (203 behind, 39 xung đột) trước mọi việc khác | — | `git merge-tree` sạch; xem mục 1 về `add/add` |
| `P68-1` | 🔴 Thêm `menu.cham_ilo1000` (+ `cham_ilo1000.process` nếu tách quyền) vào `FEATURES` **và** cây phân cấp | `backend/core/features.py` | Màn Phân quyền chức năng hiện mục Chấm ILO1000; cấp cho 1 nhóm test thì user nhóm đó vào được |
| `P68-2` | 🔴 Giới hạn phạm vi `/api/fs/browse` theo quyết định Q1 | `backend/api/fs.py` | Path ngoài allowlist trả 400/403, có test |
| `P68-3` | Đổi `os.path.basename()` sang `safe_filename()` sau khi rebase | `backend/services/ilo1000_service.py` | Tên file `NUL`, `COM1`, tên kết thúc bằng dấu phân cách đều xử lý đúng |
| `P68-4` | Chuyển nội dung card mới từ `Implementation-notes.html` (gốc) sang `docs/Implementation-notes.html` | — | File ở gốc bị xoá, nội dung không mất dòng nào |
| `P68-5` | RAM read-limit cho `/api/ilo1000/start` bằng `read_limited()` | `backend/api/ilo1000.py` | File quá trần trả 413, không nạp hết vào RAM |

**Lý do `P68-1` là 🔴 nặng nhất trong cả đợt:**

```
$ git show origin/feat/doi-chieu-song-phuong-den-2026-08-30:backend/core/features.py | grep -n "ilo"
(không có kết quả)
```

Mã `menu.cham_ilo1000` được dùng ở:

- `backend/api/ilo1000.py` — 5 endpoint, đều `Depends(require_feature('menu.cham_ilo1000'))`
- `frontend/pages/cham_ilo1000.py:23` — `api.has_feature('menu.cham_ilo1000')`
- `backend/api/fs.py` — trong `require_any_feature(...)` vừa thêm

Vì không có trong catalog, mã này **không hiện trên màn Phân quyền chức năng**,
nên QTV không có cách nào cấp cho ai. Toàn bộ module ILO1000 chỉ `admin` dùng
được; người khác thấy menu bị ẩn và nhận 403 nếu gọi thẳng API. Không lỗi, không
log — chỉ là "menu tự nhiên không có". Xem Q2.

**`P68-2` giải thích thêm:** commit mới siết *ai được vào* (`require_any_feature`)
nhưng chưa siết *xem được gì*. `_list_drives()` liệt kê mọi ổ đĩa; `_list_dir()`
nhận `path` tuỳ ý rồi `os.path.abspath()` + `scandir`, không có gốc giới hạn. Một
chuyên viên chỉ có `menu.cham_ach` vẫn duyệt được thư mục cá nhân của người khác,
ổ mạng đã map, toàn bộ cây thư mục máy chủ.

---

### PR #69 — `fix/cham459901-ccy-filter-order-2026-08-30`

| Mã | Việc | File | Nghiệm thu |
|---|---|---|---|
| `P69-1` | Quyết định: đóng PR, chuyển 2 phần test sang #66 — **hoặc** rebase như #68 | — | — |
| `P69-2` | Nếu giữ: chuyển card mới sang `docs/Implementation-notes.html` | — | Giống `P68-4` |

**Lý do đề nghị đóng:** phần `so_tien.py` và `ach_service.py` của #69 **giống hệt
#66 từng byte** (đã kiểm bằng `git diff` giữa hai nhánh, không có khác biệt). Chỉ
khác hai thứ:

1. Test ô trống cho 4 cửa vào của 459901 (`tests/test_cham459901_algorithm.py`)
2. Sửa `test_ilo1000_algorithm.py::test_raises_on_unknown_amount_format`

Chuyển hai phần đó sang #66 thì bớt được một PR 39-xung-đột phải giải mà không
mất gì. Nếu giữ #69 thì phải rebase và giải xung đột lần thứ hai cho cùng một
nội dung.

---

## 3. Việc chung — làm một lần, chặn vĩnh viễn một lớp lỗi

| Mã | Việc | Nghiệm thu |
|---|---|---|
| `PC-1` | Test quét toàn bộ `require_feature(...)`, `require_any_feature(...)`, `has_feature(...)` trong code và khẳng định mọi mã đều nằm trong `FEATURES` | Cố tình đổi một mã thành `menu.khong_ton_tai` → test đỏ và nêu đúng tên file |

Cách làm: đọc source bằng `ast` hoặc regex, gom mọi chuỗi truyền vào ba hàm trên,
so với `set(FEATURES)`. Khoảng 15 dòng.

`menu.cham_ilo1000` là ca thật đã xảy ra và không ai phát hiện cho tới đợt review
này. Đây là loại lỗi tệ nhất trong hệ thống phân quyền: không exception, không
log, chỉ là một nhóm người dùng lặng lẽ không thấy chức năng của mình.

---

## 4. Checklist trước khi deploy lên máy chính

- [ ] Q1 và Q2 đã có câu trả lời bằng văn bản
- [ ] `python -m pytest -q` xanh trên `develop` **sau khi** merge đủ 5 PR
- [ ] Chạy câu SQL ở `P54-1` trên bản sao DB thật — không còn nhóm nào thiếu quyền
- [ ] Đăng nhập thử bằng 1 tài khoản chuyên viên: vào được ACH, 459901, ILO1000
      đúng như quyền đã cấp
- [ ] Xoá thư mục `data/temp_ach` cũ (đường dẫn tương đối) trên máy chính
- [ ] `docs/Implementation-notes.html` có card cho cả 5 đợt vá; không còn
      `Implementation-notes.html` ở gốc
- [ ] `README.md` và `Logs_update.md` đã cập nhật

---

## 5. Bảng tổng hợp mức độ

| Mã | PR | Mức | Tóm tắt |
|---|---|---|---|
| `P68-1` | #68 | 🔴 | `menu.cham_ilo1000` không có trong `FEATURES` — cả module chỉ admin dùng được |
| `P68-2` | #68 | 🔴 | `/api/fs/browse` duyệt được toàn bộ ổ đĩa máy chủ |
| `P68-0` | #68 | 🔴 | Phải rebase trước khi review được |
| `P43-1` | #43 | 🔴 | `/api/fs/browse` không tồn tại — nút chọn thư mục chết |
| `P43-2` | #43 | 🔴 | `/process_folder` đọc thư mục tuỳ ý, không có trần RAM |
| `P54-1` | #54 | 🔴 | Thiếu migration → cả phòng mất nút Chạy ACH sau deploy |
| `P66-1` | #66 | 🔴 | Thứ tự merge: `so_tien.py` là `add/add`, giải sai là lùi fix âm thầm |
| `P69-1` | #69 | 🔴 | Trùng #66; nên đóng hoặc rebase |
| `PC-1` | chung | 🟡 | Test chặn feature-code không khai báo |
| `P68-3` `P68-4` `P68-5` | #68 | 🟡 | `safe_filename`, vị trí Implementation-notes, read-limit |
| `P54-3` `P54-4` | #54 | 🟡 | Bắt lỗi 413 đúng cách, dọn temp cũ |
| `P43-3` `P43-4` | #43 | 🟡 | Test chống trôi luật phân loại, bỏ `BackgroundTasks` |
| `P66-2` | #66 | 🟡 | Luật cho ô chứa dấu gạch ngang |
| `P43-5` | #43 | ⚪ | Dòng trống PEP8 |

---

*Cơ sở: đọc 5 commit vá review ngày 31/08 (`bc8f960f`, `9c669296`, `5d89c0ae`,
`5d51fe93`, `124abcfb`) và đối chiếu với `origin/develop`. Số liệu xung đột lấy
từ `git merge-tree --write-tree`. Các claim về số test pass trong commit message
chưa được chạy lại để xác minh.*
