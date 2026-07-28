# SPIKE B1 — Nâng cấp NiceGUI: kết quả đo thật

> Ngày: 28/07/2026 · Cơ sở: `develop` @ `d5722f8` + nhóm A đã áp dụng
>
> ## ✅ ĐÃ TRIỂN KHAI — không còn là spike
> Sau khi có kết quả đo, đã áp dụng lên môi trường thật:
> `nicegui 1.4.37 → 2.12.1` · `python-multipart 0.0.9 → >=0.0.31`
> **`fastapi`, `starlette`, `uvicorn` giữ nguyên.** Xem mục 8 để biết cách lùi.
>
> Mục 3 đã được cập nhật: rủi ro "70 card" hoá ra **bằng 0** — xem 3.3.

---

## 1. KẾT LUẬN

**Nâng lên NiceGUI 2.12.1 là drop-in.** Không cần sửa một dòng code frontend nào,
và **không cần soi mắt 70 card** — CSS hai bản đã chứng minh là tương đương (mục 3.3).

Điều kiện duy nhất: nới `python-multipart` từ `==0.0.9` lên `>=0.0.31` — mà việc đó
**phải làm dù có nâng NiceGUI hay không** (xem mục 4).

Đi xa hơn (2.24.2 hoặc 3.15.0) cũng chạy, nhưng kéo theo FastAPI và Starlette lên
major mới. Đã kiểm thử qua middleware thật: **cũng sạch**. Rủi ro thấp hơn dự đoán
của cả ba vòng rà soát trước.

| Phương án | nicegui | fastapi | starlette | Import 21 trang | Middleware | Render |
|---|---|---|---|---|---|---|
| Hiện tại | 1.4.37 | 0.109.1 | 0.35.1 | ✅ | ✅ 6/6 | ✅ |
| **A (khuyến nghị)** | **2.12.1** | **0.109.1** *(giữ nguyên)* | **0.35.1** *(giữ nguyên)* | ✅ | ✅ 6/6 | ✅ |
| B | 2.24.2 | 0.140.7 | 1.3.1 | ✅ | ✅ 6/6 | — |

---

## 2. NÚT THẮT THẬT: STARLETTE, KHÔNG PHẢI API GIAO DIỆN

Ba vòng rà soát đều tập trung vào breaking change của API giao diện (`ui.card`,
`ui.right_drawer`, `run_javascript`). **Không vòng nào nhận ra ràng buộc phiên bản.**

```
fastapi==0.109.1   cần  starlette >=0.35.0, <0.36.0
nicegui>=2.13.0    cần  starlette >=0.45.3
```

Hai điều kiện này không thoả đồng thời. Đã xác nhận bằng pip resolver:

| Tổ hợp | Kết quả |
|---|---|
| `nicegui==2.12.1` + `fastapi==0.109.1` | ✅ giải được |
| `nicegui==2.24.2` + `fastapi==0.109.1` | ❌ ResolutionImpossible |
| `nicegui==3.15.0` + `fastapi==0.109.1` | ❌ ResolutionImpossible |

`nicegui 2.12.1` là **bản 2.x cuối cùng chưa ép starlette** — nó cho ta vượt qua
ranh giới breaking change 2.0 mà không đụng vào backend.

---

## 3. API BREAKING CHANGE — QUÉT TOÀN BỘ CODEBASE

Đối chiếu với danh sách chính thức trong release notes NiceGUI 2.0.0:

| API bị gỡ / đổi ở 2.0 | Số lần dùng | Ảnh hưởng |
|---|---|---|
| `ui.run_javascript(respond=, check_interval=)` | **0** | Không |
| `ui.open()` → `ui.navigate.to()` | **0** | Không |
| `ui.add_style()` → `ui.add_css()` | **0** | Không |
| `ui.chart` → `ui.highchart` | **0** | Không |
| `context.get_slot_stack/get_slot/get_client` | **0** | Không |
| `aggrid.call_api_method/call_column_method` | **0** | Không |
| `libraries=` / `extra_libraries=` | **0** | Không |
| `ui.leaflet` (đổi hành vi vẽ) | **0** | Không |
| Input có `validation=` (chừa chỗ báo lỗi) | **0** | Không |
| Lồng layout element → `RuntimeError` | 2 drawer | **Đã test: không lỗi** |
| `ui.table` rows dạng list, columns tuỳ chọn | 4 | Cả 4 truyền `columns=` tường minh — vẫn hợp lệ |
| `ui.card` không còn gỡ border/shadow của con | 70 | **Không đổi ở 2.12.1** — xem 3.3 |

### Hai `right_drawer` — rủi ro thấp hơn giả định

Vòng rà soát trước cho rằng `handovers.py:47` và `leaves.py:219` cần sửa. Kiểm tra
thực tế: cả hai **là con trực tiếp của page**, không lồng trong element khác
(`leaves.py` còn có comment ghi rõ điều này). Đã dựng bản tái hiện đúng cấu trúc và
chạy trên cả hai phiên bản — không có `RuntimeError`.

Riêng `behavior=mobile` ở `leaves.py:219` vẫn nên bỏ, nhưng vì lý do **thiết kế**
(nó ép drawer luôn chạy chế độ overlay, phí chỗ trên màn rộng) chứ không phải vì
tương thích.

### 3.3 `ui.card` — rủi ro hoá ra bằng 0 với 2.12.1

Đây là hạng mục duy nhất còn lại sau 4 tài liệu rà soát, và bị đánh giá cao hơn thực tế.
Đã giải bằng cách **so trực tiếp CSS và mã nguồn hai bản** thay vì soi mắt 70 card.

**Bước 1 — `nicegui.css` gần như y hệt.** Chỉ 2 khác biệt: thêm luật cho
`.nicegui-scene` (đồ hoạ 3D, hệ thống không dùng) và `#popup` đổi `z-index` 1000 → 10000.
Luật padding của card **không đổi**: `.nicegui-card { padding: var(--nicegui-default-padding) }` = 1rem ở cả hai.

**Bước 2 — luật Quasar được viết lại thành opt-out, không phải bị gỡ.**

```css
/* 1.4.37 */  .q-card > div                                { border-left:0; border-right:0; box-shadow:none }
/* 2.12.1 */  .q-card > div:not(.q--avoid-card-border)     { border-left:0; border-right:0; box-shadow:none }
```

**Bước 3 — không có gì thêm class opt-out đó.** `grep -rn "avoid-card-border"` trên
toàn bộ package chỉ khớp trong `quasar.css`. NiceGUI không tự gắn nó vào đâu cả.

**Bước 4 — `card.py` hai bản giống hệt về hành vi.** Cùng gắn class `nicegui-card`,
cùng có `tight()`. Khác biệt duy nhất là cú pháp khai báo (`default_classes=` thay cho
`self._classes.append`) — một lần dọn code, không đổi kết quả.

> Docstring của `Card` ở 2.12.1 ghi *"Updated in version 2.0.0: Don't hide outer borders
> and shadows of nested elements anymore"*, và release notes 2.0.0 cũng nói vậy. **Nhưng
> cơ chế không được nối dây:** class opt-out tồn tại mà không ai gắn. Với 2.12.1, card
> hiển thị **y hệt** 1.4.37. Tài liệu của thư viện mô tả sai trạng thái bản này.

**Cảnh báo nhỏ còn lại — trình duyệt cũ.** Luật mới dùng cú pháp
`:nth-child(1 of :not(...))`, cần Chrome/Edge 111+ (03/2023) hoặc Firefox 113+.
Trên trình duyệt cũ hơn, hai luật bo góc trên/dưới cho phần tử con đầu/cuối sẽ không
áp dụng. Tác động thực tế **rất nhỏ** vì `_card()` và `ui_kit.card()` đều dùng
`overflow-hidden` — việc cắt viền đã tự bo góc. Chỉ cần lưu ý nếu máy trạm còn chạy
trình duyệt trước 2023.

**Đã giảm thêm ở B2:** `ui_kit.card()` đặt padding tường minh thay vì dựa vào mặc định,
nên card dựng qua nó miễn nhiễm với mọi thay đổi kiểu này về sau.

---

## 4. PHÁT HIỆN NGOÀI PHẠM VI — QUAN TRỌNG HƠN CHÍNH SPIKE

`python-multipart==0.0.9` đang chạy có **16 lỗ hổng đã biết**, trong đó 4 mức HIGH:

| Mã | Mức | Sửa ở bản | Nội dung |
|---|---|---|---|
| GHSA-wp53-j4wj-2cfg | HIGH | 0.0.22 | **Ghi file tuỳ ý** (cấu hình không mặc định) |
| GHSA-59g5-xgcq-4qw3 | HIGH | 0.0.18 | DoS qua boundary `multipart/form-data` dị dạng |
| GHSA-pp6c-gr5w-3c5g | HIGH | 0.0.27 | DoS qua header phần multipart không giới hạn |
| GHSA-5rvq-cxj2-64vf | HIGH | 0.0.30 | DoS: phân tích querystring thời gian bậc hai |
| +12 mã khác | MODERATE/LOW | ≤0.0.31 | Buôn lậu tham số, đệm toàn bộ body vào RAM… |

Đây là thư viện xử lý **mọi upload file**. Hệ thống có 9 chỗ `ui.upload` và các
endpoint nạp ZIP (SWIFT recon, chấm 459901).

> **Đính chính khuyến nghị ban đầu.** Tôi từng đề nghị `>=0.0.18` — đó là mức tối thiểu
> NiceGUI đòi, **không phải mức an toàn**. Kiểm lại bằng OSV: `0.0.18` vẫn còn **14 lỗ hổng**,
> phải `>=0.0.31` mới sạch. Đã áp dụng `>=0.0.31` (thực cài 0.0.32, 0 lỗ hổng).

| Bản | Lỗ hổng còn lại |
|---|---|
| 0.0.9 *(cũ)* | 16 |
| 0.0.18 | 14 |
| **0.0.31+** | **0** |

✅ **Đã triển khai.** Kiểm thử: parser multipart xử lý đúng body thật; 3 endpoint
`UploadFile` nhận request và trả 401 (tới được RBAC, không lỗi phân tích).

---

## 5. ĐÃ KIỂM THỬ NHỮNG GÌ

| Kiểm thử | 1.4.37 | 2.12.1 | 2.24.2 |
|---|---|---|---|
| Import `backend.main` | ✅ | ✅ | ✅ |
| Import 21 trang frontend | ✅ | ✅ | ✅ |
| `GET /` qua `AuditMiddleware` | ✅ 200 | ✅ 200 | ✅ 200 |
| Preflight CORS | ✅ 200 | ✅ 200 | ✅ 200 |
| `/openapi.json` — 144 endpoint | ✅ | ✅ | ✅ |
| RBAC không token → 401 | ✅ | ✅ | ✅ |
| Đăng nhập sai → 422 | ✅ | ✅ | ✅ |
| Render `/login` HTTP 200 | ✅ | ✅ | — |
| right_drawer sau nội dung page | ✅ | ✅ | — |
| `ui.table` (2 kiểu dùng) | ✅ | ✅ | — |
| `ui.card` lồng nhau | ✅ | ✅ | — |
| `ui.upload`, `app.storage.user` | ✅ | ✅ | — |

**Chưa kiểm được:** các trang cần đăng nhập (không có tài khoản test — cố ý không tạo).
Hình dạng card đã giải bằng so CSS thay vì nhìn (mục 3.3).

---

## 6. TRẠNG THÁI TRIỂN KHAI

| # | Việc | Trạng thái |
|---|---|---|
| 1 | `python-multipart` → `>=0.0.31` | ✅ **Đã làm** — xem đính chính ở mục 4 |
| 2 | `nicegui` → `2.12.1`, giữ nguyên fastapi/starlette/uvicorn | ✅ **Đã làm** |
| 3 | Soi mắt 70 card | ❎ **Không cần** — giải bằng so CSS, xem 3.3 |
| 4 | Bỏ `behavior=mobile` ở `leaves.py:219` | ⏳ Gộp vào B5 |
| 5 | Đi tiếp 2.24.2 / 3.x | ⛔ **Hoãn** |

**Không khuyến nghị nhảy thẳng 3.15.0.** Nó chạy được, nhưng đổi 3 thư viện nền
cùng lúc để đổi lấy tính năng ta chưa cần thì không đáng.

---

## 7. VIỆC CÒN LẠI SAU KHI NÂNG CẤP

Không có việc bắt buộc. Hai việc tuỳ chọn:

- Xác nhận trình duyệt trên máy trạm ≥ Chrome/Edge 111 (xem cảnh báo ở 3.3).
  Nếu là Edge bản đi kèm Windows 10/11 còn cập nhật thì đương nhiên đạt.
- Mở vài trang nhiều card (`leaves`, `storage`, `groups`, `duty_schedule`) nhìn qua
  một lượt. Không bắt buộc — CSS đã chứng minh là tương đương — nhưng rẻ.

---

## 8. CÁCH LÙI NẾU CẦN

```bash
# Lùi thư viện
.venv/Scripts/python.exe -m pip install "nicegui==1.4.37" "python-multipart==0.0.9"
# Lùi khai báo
git checkout requirements.txt
```

Bản `pip freeze` đầy đủ trước khi nâng đã lưu trong thư mục tạm của phiên làm việc.
Lưu ý: lùi `python-multipart` về 0.0.9 là **mở lại 16 lỗ hổng** — chỉ lùi `nicegui`
nếu có thể, hai gói này độc lập với nhau.

---

## 9. CÁI GIÁ ĐÃ TRẢ CHO SPIKE NÀY

Mỗi lần boot backend để kiểm thử, backup scheduler tự chạy và tạo một bản backup.
3 lần boot → **3 backup cũ nhất (21/07, 22/07 ×2) bị xoay vòng đẩy ra** (giới hạn 7 bản).
Dữ liệu nguyên vẹn, nhưng chiều sâu lịch sử backup mất khoảng 6 ngày.

Đã bù bằng `data/backups/ksnb_truoc_nhomA_20260728.db` — ảnh chụp trước mọi thay đổi
nhóm A, 78 dòng, `integrity_check = ok`.

**Bài học:** lần sau spike phải trỏ `DB_PATH` vào bản sao, không dùng DB thật —
kể cả khi migration đã chứng minh là idempotent.

---

*Spike B1 — 28/07/2026 · Không merge. `requirements.txt` giữ nguyên `nicegui==1.4.37`.*
