# REVIEW TÀI LIỆU `RA_SOAT_TTTT_DEVELOP.md`

> Người review: Claude — 27/07/2026
> Phương pháp: đọc trực tiếp source tại `d:\System` (branch `develop`, HEAD `d5722f8`), đếm lại toàn bộ số liệu, không lấy con số trong tài liệu làm gốc.
> Phạm vi: kiểm chứng tính đúng đắn của phát hiện + phản biện đề xuất + đánh giá lộ trình.

---

## 0. KẾT LUẬN NGẮN

Tài liệu **có chất lượng tốt**: số liệu phần lớn chính xác, ưu tiên hợp lý, và phần khuyến nghị (bỏ Phương án 2, test trước khi tách `leaves.py`) là đúng.

Nhưng có **một vấn đề nghiêm trọng về quy trình** và **bốn sai sót kỹ thuật** cần sửa trước khi dùng tài liệu này làm cơ sở triển khai:

| # | Vấn đề | Mức độ | Độ tin cậy |
|---|---|---|---|
| R1 | **Tài liệu review một snapshot đã lỗi thời** — B1, B3 và một nửa B4 đã được fix bởi 3 commit cùng ngày 27/07 | 🔴 Nghiêm trọng | **Cao** — đối chiếu git log |
| R2 | C1 nêu rủi ro `ui.run_javascript(respond=…)` nhưng codebase **không dùng** tham số đó ở đâu cả | 🟡 Sai sự thật | **Cao** |
| R3 | C1 bỏ sót `leaves.py:219` cũng dùng `ui.right_drawer` (chỉ nêu `handovers.py`) | 🟡 Thiếu | **Cao** |
| R4 | Ba số liệu quy mô sai lệch: số service, số file nguồn, số chuỗi empty-state | 🔵 Nhỏ | **Cao** |
| R5 | Lộ trình **không có Pha nào sửa `CLAUDE.md` / `DESIGN.md`** — hai file này đang mô tả sai kiến trúc hiện tại | 🟡 Thiếu | **Cao** |

---

## 1. R1 — TÀI LIỆU ĐÃ LỖI THỜI NGAY KHI VIẾT XONG

Đây là phát hiện quan trọng nhất của review này.

Tài liệu ghi nguồn là `TTTT-develop.zip`. File zip đó được xuất **trước** 3 commit sau, tất cả đều thực hiện trong ngày 27/07/2026 — đúng ngày tài liệu ghi:

```
d5722f8 2026-07-27 docs: ghi nhận thay đổi chiều rộng vùng nội dung + auto-collapse sidebar
63c88a8 2026-07-27 fix: sidebar chỉ đóng/mở bằng nút góc trên trái
caa427f 2026-07-27 fix: ẩn mục phòng ban rỗng trên sidebar (Kế toán, Nostro, Ban Giám đốc)
```

### Đối chiếu từng mục

**B1 — "Ba mục menu chết" → ĐÃ SỬA**

Tài liệu trích [shared.py:218](frontend/shared.py#L218) là:
```python
if dept["items"] and not visible_items:
```
Code thực tế tại [shared.py:214-215](frontend/shared.py#L214-L215):
```python
if not visible_items:
    return  # gồm cả phòng chưa có chức năng (items rỗng) — không render header chết
```
Đúng chính xác cách sửa tài liệu đề xuất. **Pha 0 mất một nửa khối lượng.**

**B3 — "Click bất kỳ đâu trong sidebar mở rộng nó" → ĐÃ SỬA**

Tài liệu trích `shared.py:139-143`. Ở HEAD, dòng 139-147 không còn là handler click nữa mà là JS auto-collapse. Toàn bộ cơ chế đóng/mở giờ nằm ở **một nút duy nhất** [shared.py:304-314](frontend/shared.py#L304-L314) với `onclick="toggleSidebar()"`. Không còn hành vi mâu thuẫn.

Đáng chú ý: nút này **đã có `aria-label`** — nên con số "aria-*, tabindex: 0 lần" trong B7 nay là **1**, không phải 0.

**B4 — Đề xuất 2/2 → ĐÃ LÀM**

Tài liệu đề xuất hai việc. Việc thứ hai ("cho sidebar tự thu về chế độ chỉ-icon khi viewport < 1400px, tận dụng `sb-collapsed`") **đã có sẵn** tại [shared.py:139-147](frontend/shared.py#L139-L147), ngưỡng 1440px, còn khôn hơn đề xuất ở chỗ nó tôn trọng lựa chọn thủ công lưu trong `localStorage`.

Tài liệu cũng trích sai `.style("width: calc(100vw - 16rem)")`. Code thực tế là `calc(100% - 16rem)` ([shared.py:412](frontend/shared.py#L412)) — dùng `100%` chứ không phải `100vw`, tức lỗi tràn ngang do thanh cuộn dọc mà `100vw` gây ra **không tồn tại**.

→ **B4 chỉ còn đúng 1 việc: thêm `max-width` cho vùng nội dung.** Ước tính không còn là "2 ngày" mà là ~15 phút.

### Hệ quả với lộ trình

| Pha | Tài liệu ước tính | Sau khi trừ phần đã làm |
|---|---|---|
| **0 — Vá nhanh** | 0,5 ngày (B1 + A2 + C3) | **~2 giờ** (chỉ còn A2 + C3) |
| **2 — Vỏ ứng dụng** | 2 ngày (B2 + B3 + cỡ chữ + B7 + B4) | **~1 ngày** (B3 xong, B4 còn 1 dòng CSS) |

### Bài học quy trình

Đây không phải lỗi phân tích — người viết đọc đúng những gì có trong zip. Đây là **lỗi quy trình**: rà soát trên bản chụp tĩnh trong khi nhánh vẫn đang được commit.

**Khuyến nghị:** mọi tài liệu rà soát về sau phải ghi **commit hash** ở đầu file thay vì tên file zip. Một dòng `> Cơ sở: develop @ d5722f8` giải quyết triệt để vấn đề này và cho phép người đọc tự chạy `git diff d5722f8..HEAD` để biết phần nào đã lạc hậu.

---

## 2. BẢNG KIỂM CHỨNG SỐ LIỆU

Tôi đếm lại toàn bộ. Ký hiệu: ✅ khớp · ⚠️ lệch nhưng không đổi kết luận · ❌ sai đủ để đổi kết luận

| Chỉ số | Tài liệu | Thực tế | |
|---|---|---|---|
| Tổng LOC Python | 26.997 | **26.995** | ✅ |
| Backend API endpoint | 162 | **162** | ✅ |
| Trang frontend | 21 | **21** (22 file trừ `__init__.py`) | ✅ |
| `frontend/pages/leaves.py` | 5.018 dòng | **5.018** | ✅ |
| Service backend | 22 | **17** file `.py` | ⚠️ |
| File nguồn | 132 | **100** file `.py` trong git | ⚠️ |
| Thư mục `tests/` | Không có | **Không có** | ✅ |
| `storage_secret` hardcode | `main.py:48` | **`main.py:49`** | ✅ |
| `COLORS[...]` dùng ngoài `shared.py` | 2 | **2** | ✅ |
| Mã hex khác nhau trong `frontend/` | 58 | **57** | ✅ |
| Mã hex trong `handovers.py` | 47 | **47** | ✅ |
| `_card()` được gọi | 1 lần | **1 lần** | ✅ |
| `ui.notify` | 165 | **169** | ✅ |
| `ui.spinner` — số trang có | 5/21 | **5/21** | ✅ |
| `ui.skeleton` | 0 | **0** | ✅ |
| `text-xs` | 202 | **202** | ✅ |
| `text-sm` | 194 | **194** | ✅ |
| `text-gray-400` | 72 | **72** | ✅ |
| `aria-*` / `tabindex` | 0 | **1** (nút toggle mới) | ⚠️ |
| Chuỗi "Chưa có…" viết tay | 21 | **37** | ⚠️ *(tài liệu **nói nhẹ** hơn thực tế)* |
| Trang gọi `/api/departments` | 8 | **5** | ⚠️ |
| Tỷ lệ tương phản `#9CA3AF` trên nền trắng | 2,8:1 | **2,54:1** | ⚠️ *(thực tế **tệ hơn**)* |

**Nhận xét:** tỷ lệ chính xác rất cao — 14/22 khớp tuyệt đối, không có mục nào ❌. Các mục lệch đều theo hướng **tài liệu nói nhẹ đi**, không phóng đại. Đây là dấu hiệu của rà soát trung thực.

Riêng con số tương phản: tôi tính lại theo công thức WCAG 2.1 và ra **2,54:1** (không phải 2,8:1). Nếu nền là `bg-gray-50` (#F9FAFB — mà `_content_area()` đang dùng) thì còn thấp hơn nữa. Kết luận "không đạt AA" giữ nguyên, chỉ là mức độ vi phạm nặng hơn tài liệu mô tả. Độ tin cậy: **cao** (tính tay từ giá trị sRGB).

---

## 3. R2 — C1 NÊU MỘT RỦI RO KHÔNG TỒN TẠI

Tài liệu viết:

> 2.0: `ui.run_javascript()` bỏ tham số `respond`, `check_interval` → `shared.py:176` có dùng

Hai vấn đề:

1. **`shared.py:176` không có `run_javascript`.** Dòng 176 hiện là phần khai báo helper `_nav_item`.
2. **Không chỗ nào trong toàn bộ codebase dùng `respond=` hay `check_interval=`.** Tôi grep cả `frontend/` lẫn `backend/` — 0 kết quả.

Có 6 lời gọi `run_javascript` thật, tất cả đều dùng chữ ký hiện đại:

| File | Dòng |
|---|---|
| `frontend/pages/cham_459901.py` | 188 |
| `frontend/pages/storage.py` | 133, 257 |
| `frontend/pages/doi_chieu_song_phuong.py` | 197 |
| `frontend/pages/handovers.py` | 119, 508 |

→ **Rủi ro nâng cấp NiceGUI 2.x ở mục này bằng 0.** Nên xoá khỏi danh sách cảnh báo. Điều này làm cho spike nâng cấp **bớt đáng ngại hơn** tài liệu mô tả.

## 4. R3 — C1 BỎ SÓT MỘT `ui.right_drawer`

Tài liệu chỉ nêu `handovers.py:46`. Thực tế có **hai** chỗ:

- [frontend/pages/handovers.py:47](frontend/pages/handovers.py#L47) — `.props("width=360 overlay")`
- [frontend/pages/leaves.py:219](frontend/pages/leaves.py#L219) — `.props("width=440 overlay behavior=mobile")`

Chỗ thứ hai **quan trọng hơn** vì hai lý do:

1. Nó nằm trong file 5.018 dòng sắp bị tách (Pha 5) — nếu nâng NiceGUI song song với tách file, hai thay đổi rủi ro sẽ chồng lên nhau.
2. Nó dùng `behavior=mobile` — một prop **mâu thuẫn trực tiếp** với quyết định desktop-only vừa chốt. Mục 3.4 của tài liệu đề xuất "bỏ hẳn `ui.right_drawer` overlay" nhưng không nhắc rằng chính `leaves.py` đang ép drawer chạy ở chế độ mobile.

---

## 5. ĐÁNH GIÁ TỪNG PHÁT HIỆN

### 🔴 Nhóm A

| Mục | Đánh giá |
|---|---|
| **A1** — `leaves.py` 5.018 dòng | ✅ **Xác nhận đầy đủ.** Đây là vấn đề thật và lớn nhất trong repo. Bổ sung: `backend/api/leaves.py` cũng **2.716 dòng** — file backend lớn nhất, tài liệu không nhắc. Nghiệp vụ nghỉ phép đang phình ở **cả hai đầu**, không chỉ frontend. |
| **A2** — `storage_secret` hardcode | ✅ **Xác nhận.** Lập luận về xung đột cookie giữa 2 instance cùng `localhost` là **đúng về mặt kỹ thuật** — cookie scope theo domain, không theo port. Nhưng đây là hệ quả phụ; lý do chính đơn giản là secret ký cookie nằm trong Git. |
| **A3** — Không có test | ✅ **Xác nhận.** Ba file test đề xuất chọn đúng chỗ. |

**Phản biện A1 — thứ tự tách file:**

Tài liệu đề xuất cấu trúc 6 module (`_dashboard`, `_create`, `_approve`, `_quota`, `_stats`). Cấu trúc hợp lý, nhưng **thiếu một bước**: `leaves.py` chứa một `ui.right_drawer` và nhiều closure chia sẻ state. Tách theo *màn hình* mà không trước hết tách phần *state dùng chung* sẽ dẫn tới việc mỗi module phải nhận một `ctx` khổng lồ — đổi một đống closure lấy một God object.

**Đề xuất bổ sung:** thêm `_state.py` (dataclass giữ state dùng chung + các hàm load dữ liệu) làm **module đầu tiên** được tách, trước cả 5 module màn hình. Nếu bước này khó, đó là tín hiệu sớm cho biết ranh giới module đang chọn sai — biết sớm rẻ hơn nhiều so với biết ở module thứ tư.

### 🟡 Nhóm B

| Mục | Trạng thái |
|---|---|
| **B1** ba menu chết | ❌ **Đã fix ở `caa427f`** — bỏ khỏi backlog |
| **B2** flyout hover-only | ✅ **Vẫn đúng.** [shared.py:104,108](frontend/shared.py#L104-L108) còn nguyên `:hover`, không có `:focus-within`, không có `tabindex`. Handler JS [shared.py:154-167](frontend/shared.py#L154-L167) không có vùng đệm. |
| **B3** click sidebar mâu thuẫn | ❌ **Đã fix ở `63c88a8`** — bỏ khỏi backlog |
| **B4** bố cục đóng cứng | ⚠️ **Còn 1/2** — auto-collapse đã có; chỉ thiếu `max-width` |
| **B5** design token không dùng | ✅ **Xác nhận, số liệu chính xác tuyệt đối** |
| **B6** loading/empty state | ✅ **Xác nhận, và nặng hơn tài liệu nói** (37 chuỗi chứ không phải 21) |
| **B7** khả năng đọc | ✅ **Xác nhận.** Bổ sung: font Inter được nạp ở **3** trang (`login.py`, `dashboard.py`, `change_password.py`), không phải 1 — nhưng kết luận "không nhất quán" **mạnh hơn**, vì giờ là 3 trang một kiểu / 18 trang kiểu khác |
| **B8** không có tìm kiếm | ✅ **Xác nhận** |

**Phản biện B2 — đừng bỏ hover:**

Tài liệu đề xuất "đổi `:hover` sang click-to-open, có thể giữ hover làm cách mở phụ trợ". Tôi cho rằng thứ tự này **ngược**.

Vấn đề thật của B2 không phải là "hover xấu" — trên desktop hover là thao tác hợp lệ, và chính mục 3.4 của tài liệu công nhận điều đó. Vấn đề thật là **hai lỗ hổng cụ thể**: (a) không Tab tới được, (b) không có vùng đệm đường chéo.

Chuyển sang click-to-open sửa được (b) nhưng làm **chậm hơn** cho người dùng chuột đã quen — thêm một cú click cho mỗi lần điều hướng, nhân với hàng chục lần mỗi ngày.

**Đề xuất thay thế, rẻ hơn và ít rủi ro hơn:**

1. Giữ hover làm cách mở **chính**.
2. Thêm `:focus-within` vào cùng selector CSS — một dòng, giải quyết trọn (a) khi kèm `tabindex="0"` trên header phòng.
3. Sửa (b) bằng `transition-delay` ~120ms trên `display`/`visibility` thay vì implement safe-triangle bằng JS. Rẻ hơn nhiều, giải quyết ~90% trường hợp rê chéo.

Chi phí: ~2 giờ thay vì 1 ngày, và không đổi thói quen của người dùng hiện tại. Độ tin cậy: **trung bình** — cần thử thực tế mới biết 120ms có đủ không.

### 🔵 Nhóm C

| Mục | Đánh giá |
|---|---|
| **C1** NiceGUI 1.4.37 | ⚠️ **Đúng hướng, sai chi tiết.** Xem R2/R3. Con số "3.15.0 là bản mới nhất" tôi **không kiểm chứng được** (không truy cập PyPI) — cần xác minh lại trước khi trích dẫn. |
| **C2** khối lọc chép 8 lần | ⚠️ **Đúng bản chất, số liệu lệch.** Chỉ **5** trang gọi `/api/departments`. Nếu tính rộng ra khối lọc năm/tháng thì có 12 trang dùng `ui.select`. Con số 8 không khớp cách đếm nào. |
| **C3** `ALLOWED_ORIGINS` mặc định localhost | ✅ **Xác nhận chính xác.** [config.py:41-46](backend/core/config.py#L41-L46) đúng như mô tả, và không có cảnh báo nào khi `ENV=production`. |

**Bổ sung cho C3 — vấn đề nặng hơn tài liệu nêu:**

Tài liệu đề xuất "bổ sung cảnh báo khi `ENV=production` mà `ALLOWED_ORIGINS` vẫn chỉ có localhost". Nhưng đọc `config.py` thì thấy `ENV` **chỉ được đọc vào biến, không được dùng ở đâu để bật/tắt hành vi nào** ngoài giá trị mặc định của `ENABLE_API_DOCS`.

Nói cách khác: cảnh báo đề xuất sẽ dựa trên một biến mà **không ai đặt trong thực tế**. Nếu người vận hành quên set `ALLOWED_ORIGINS`, khả năng cao họ cũng quên set `ENV=production` — cảnh báo sẽ không bao giờ kích hoạt.

**Đề xuất chặt hơn:** cảnh báo dựa trên **sự thật quan sát được** thay vì cờ khai báo — nếu `BACKEND_HOST=0.0.0.0` (đang là mặc định cứng) mà `ALLOWED_ORIGINS` chỉ chứa `localhost`, log warning ngay lúc khởi động. Điều kiện này luôn đúng trong triển khai LAN thật.

---

## 6. R5 — TÀI LIỆU HƯỚNG DẪN DỰ ÁN ĐANG MÔ TẢ SAI KIẾN TRÚC

Tài liệu rà soát ghi nhận đúng ở mục 1.2:

> Session persist vào SQLite (PLAN 1.2) — ✅ đã xong — `backend/core/sessions.py` dùng bảng `login_sessions`

Tôi xác nhận: [sessions.py](backend/core/sessions.py) đúng là đang `INSERT OR REPLACE INTO login_sessions`.

**Nhưng `DESIGN.md` của chính dự án vẫn ghi:**

> Session lưu in-memory (`backend/core/sessions.py`) — mất khi restart

**Và `CLAUDE.md` cũng ghi:**

> `backend/core/` — … `sessions.py` (in-memory)

Đây là loại lỗi nguy hiểm hơn code bug: người mới vào dự án (hoặc một phiên Claude Code mới) sẽ đọc `CLAUDE.md`, tin rằng session mất khi restart, và thiết kế sai từ giả định đó.

**Tài liệu rà soát bắt được sự thật nhưng không đề xuất sửa nguồn sai.** Mục 6 chỉ đề xuất viết lại `Plan/PLAN.md`, không nhắc `CLAUDE.md` và `DESIGN.md`.

**Đề xuất: thêm vào Pha 0** — chi phí ~15 phút, giá trị cao:
- Sửa mô tả `sessions.py` trong cả `CLAUDE.md` và `DESIGN.md`
- Rà lại các mô tả kiến trúc khác trong hai file đó theo cùng cách

---

## 7. PHẢN BIỆN CÁC ĐỀ XUẤT LỚN

### 7.1 Bỏ Phương án 2 — ✅ Đồng ý, lập luận vững

Tôi không tìm được lý lẽ nào chống lại. Khi mục tiêu PWA/mobile bị loại, Phương án 2 chỉ còn khác biệt thẩm mỹ với chi phí sửa 21 trang. Ô tìm kiếm toàn cục — ưu điểm duy nhất còn lại — làm được trong Phương án 1. Quyết định đúng.

### 7.2 Test trước, tách `leaves.py` sau — ✅ Đồng ý, và nên mạnh hơn nữa

Tài liệu đặt đây là "Lưu ý thứ tự" ở cuối mục 4, nhưng vẫn đánh số Pha 5 (tách) trước Pha 6 (test) trong bảng. **Nên đổi số hẳn**, không chỉ ghi chú — người đọc bảng lộ trình thường không đọc phần lưu ý bên dưới.

Bổ sung: quy trình duyệt phép **đang chạy thật** trên hệ thống. Refactor 5.018 dòng logic duyệt 3 cấp mà không có lưới an toàn không phải "rủi ro cao" — đó là rủi ro **nghiệp vụ trực tiếp**. Nếu bước duyệt GĐ hỏng một ngày, hậu quả là đơn nghỉ phép thật của người thật bị treo.

### 7.3 `ui_kit.py` áp dụng dần — ⚠️ Đồng ý có điều kiện

Chiến lược "trang mới dùng ngay, trang cũ chuyển dần" là lựa chọn an toàn đúng. Nhưng nó có một rủi ro tài liệu không nêu: **giai đoạn quá độ có thể kéo dài vô hạn**, và khi đó hệ thống có *hai* phong cách giao diện thay vì một — tệ hơn tình trạng hiện tại về mặt nhất quán.

**Đề xuất bổ sung:** chọn trước **3 trang mốc** bắt buộc phải chuyển xong trong Pha 3 (gợi ý: `handovers.py` vì nó chứa 47/57 mã hex, `storage.py`, `bundles.py`). Không có mốc cụ thể thì "chuyển dần" trên thực tế nghĩa là "không chuyển".

### 7.4 Điều hướng bàn phím (mục 3.5) — ⚠️ Đồng ý phần lớn, phản đối một mục

`Ctrl+K`, `Esc`, `Tab`, `Alt+1…9` — không có ý kiến phản đối, giá trị rõ ràng, `ui.keyboard()` đủ dùng.

**Nhưng `Ctrl+S` để "lưu biểu mẫu đang mở" là lựa chọn tệ.** Lý do: trình duyệt bind `Ctrl+S` cho "Lưu trang". Chặn nó được về mặt kỹ thuật (`preventDefault`), nhưng:

- Nếu chặn sót ở một trang → hộp thoại "Save as…" của Windows bật ra giữa lúc người dùng nhập liệu
- Người dùng ngân hàng có phản xạ `Ctrl+S` từ Excel — họ sẽ bấm ở **mọi** trang, kể cả trang không có form. Khi đó phím tắt "im lặng không làm gì" và họ tưởng dữ liệu đã lưu.

Rủi ro thứ hai nguy hiểm hơn thứ nhất: **người dùng tin rằng đã lưu trong khi chưa**.

**Đề xuất:** dùng `Ctrl+Enter` để lưu (không xung đột trình duyệt, đã là quy ước phổ biến trong ứng dụng web), và nếu muốn giữ `Ctrl+S` thì bắt nó **ở tầng toàn cục** — có form thì lưu, không có form thì hiện notify "Trang này không có biểu mẫu để lưu". Im lặng là lựa chọn tệ nhất.

Tài liệu tự ghi mục `Enter` để lưu-và-nhảy-ô là "cần khảo sát trước" — đánh giá trung thực, tôi đồng ý. Cấu trúc lưới nhập liệu trong `handovers.py` cần đọc kỹ trước khi cam kết.

---

## 8. KHUYẾN NGHỊ CHO MỤC 5 (CẦN XÁC NHẬN)

| # | Quyết định | Khuyến nghị của tôi | Lý do |
|---|---|---|---|
| **1** | Vỏ ứng dụng | **(a) Phương án 1** | Đồng ý hoàn toàn với tài liệu |
| **1b** | Độ phân giải tối thiểu | **(a) 1366×768** — nhưng **cần đếm máy thật trước** | Đây là quyết định duy nhất trong danh sách **không thể đoán từ code**. Chọn sai theo hướng lạc quan (1920) thì cán bộ dùng laptop cũ phải cuộn ngang mọi bảng. Chi phí khảo sát: một buổi đi hỏi. |
| **1c** | Điều hướng bàn phím | **(a) Làm ở Pha 2b**, trừ `Ctrl+S` — xem 7.4 | Chi phí thấp, giá trị cao cho nhóm nhập liệu |
| **2** | Ba phòng chưa có tính năng | **Không cần quyết định nữa** | `caa427f` đã ẩn hẳn — tương đương phương án (a) |
| **3** | Cỡ chữ nền | **(b) 14px toàn hệ thống** | Nhưng lưu ý: nâng cỡ chữ **sẽ làm vỡ bố cục** ở các bảng nhiều cột đang vừa khít. Phải làm **cùng lúc** với `data_table` dày ở Pha 3, không tách rời. Tài liệu xếp cỡ chữ ở Pha 2 và `data_table` ở Pha 3 — **nên gộp**. |
| **4** | Nhóm "Việc của tôi" | **(a) Có** | Đồng ý — nguyên tắc "công việc trước, phòng ban sau" là đúng |
| **5** | Phạm vi `ui_kit.py` | **(a) Áp dụng dần** + 3 trang mốc bắt buộc — xem 7.3 | |
| **6** | Thứ tự Pha 5/6 | **(a) Test trước** — và **đổi số hẳn** | Xem 7.2 |
| **7** | Spike NiceGUI 2.x | **(a) Làm ngay** | Đảo ngược mức ưu tiên tài liệu ngụ ý: sau khi loại bỏ rủi ro `run_javascript` (R2), rào cản còn lại chỉ là padding của `ui.card` và 2 chỗ `right_drawer`. Spike rẻ hơn tài liệu ước tính. Quan trọng hơn: **biết kết quả trước Pha 1** giúp quyết định `ui_kit.py` nên viết theo API 1.x hay 2.x — viết theo 1.x rồi phải sửa lại là lãng phí kép. |

**Điểm bất đồng đáng chú ý duy nhất với tài liệu: câu #7.** Tài liệu xếp spike ở Pha 7 (cuối cùng). Tôi cho rằng nó nên là **Pha 0.5** — trước khi viết dòng code đầu tiên của `ui_kit.py`.

---

## 9. NHỮNG GÌ TÀI LIỆU BỎ SÓT

| # | Phát hiện | Mức độ |
|---|---|---|
| S1 | **`backend/api/leaves.py` — 2.716 dòng.** File backend lớn nhất, cùng nghiệp vụ với A1. Tài liệu chỉ soi frontend. | 🟡 Quan trọng |
| S2 | **`leaves.py:219` dùng `behavior=mobile`** trên `right_drawer` — mâu thuẫn trực tiếp với quyết định desktop-only vừa chốt | 🔵 Nhỏ |
| S3 | **`CLAUDE.md` và `DESIGN.md` mô tả sai `sessions.py`** — xem R5 | 🟡 Quan trọng |
| S4 | **`ENV` gần như không được dùng** — làm cho đề xuất cảnh báo ở C3 không hiệu quả trên thực tế | 🔵 Nhỏ |
| S5 | **`role_map` ở [shared.py:329-339](frontend/shared.py#L329-L339) map `controller` → "Phó phòng"** — vai trò đã deprecated theo `DESIGN.md` nhưng vẫn phải xử lý ở frontend. Nghĩa là **DB vẫn còn bản ghi `controller` chưa migrate**, hoặc code phòng thủ thừa. Cần xác định là cái nào. | 🔵 Nhỏ |
| S6 | **`__pycache__` còn `source_users.cpython-310.pyc`** nhưng không có `source_users.py` — dấu vết file đã xoá. Vô hại, nhưng gợi ý `.gitignore` chưa loại trừ `__pycache__` khỏi zip xuất bản. | 🔵 Nhỏ |

---

## 10. LỘ TRÌNH ĐỀ XUẤT SỬA LẠI

Giữ nguyên cấu trúc tài liệu, chỉ điều chỉnh theo các phát hiện trên:

| Pha | Nội dung | Ước tính | Thay đổi so với tài liệu |
|---|---|---|---|
| **0 — Vá nhanh** | A2 (`storage_secret` → env), C3 (cảnh báo CORS theo `BACKEND_HOST`), **S3 (sửa `CLAUDE.md`/`DESIGN.md`)** | **2 giờ** | ↓ từ 0,5 ngày — B1 đã xong |
| **0,5 — Spike NiceGUI 2.x** | C1 trên nhánh riêng, ghi lại danh sách lỗi thật | 1 ngày | **↑ chuyển từ Pha 7 lên đây** |
| **1 — Nền tảng UI** | `ui_kit.py`: TOKENS, STATUS, `status_chip`, `empty_state`, `skeleton` | 2 ngày | Không đổi |
| **2 — Vỏ ứng dụng** | B2 (`:focus-within` + `tabindex` + delay 120ms), B4 (`max-width`), B7 (tương phản) | **1 ngày** | ↓ từ 2 ngày — B3 xong, B4 còn 1 dòng |
| **2b — Bàn phím** | `Ctrl+K`, `Alt+1…9`, `Esc`, `Tab`; **`Ctrl+Enter` thay `Ctrl+S`** | 1–1,5 ngày | Đổi phím lưu |
| **3 — Áp dụng** | `filter_bar` + `data_table` dày cho 5 trang có khối lọc; **gộp việc nâng cỡ chữ 14px vào đây**; 3 trang mốc bắt buộc | 3 ngày | Gộp cỡ chữ từ Pha 2 |
| **4 — Test tối thiểu** | A3 — 3 file test ưu tiên | 2 ngày | **↑ đổi số, lên trước tách file** |
| **5 — Trang chủ** | Bố cục 4 vùng | 2 ngày | |
| **6 — Tách `leaves.py`** | A1 — **`_state.py` trước**, rồi 5 module màn hình | 3–4 ngày | Thêm bước tách state |
| **7 — Tách `backend/api/leaves.py`** | **S1 — mục mới** | 2 ngày | **Mới** |

**Tổng ước tính: ~18 ngày công** (tài liệu gốc: ~17 ngày). Khối lượng gần như không đổi — phần tiết kiệm được ở Pha 0/2 nhờ 3 commit đã làm được bù lại bằng Pha 7 mới và bước tách state.

---

## 11. ĐÁNH GIÁ TỔNG THỂ TÀI LIỆU

| Tiêu chí | Điểm | Nhận xét |
|---|---|---|
| Độ chính xác số liệu | **9/10** | 14/22 chỉ số khớp tuyệt đối; các mục lệch đều theo hướng dè dặt |
| Xác định vấn đề | **8/10** | Bắt đúng vấn đề lớn; bỏ sót `backend/api/leaves.py` và mâu thuẫn tài liệu dự án |
| Chất lượng đề xuất | **8/10** | Phần lớn đúng; `Ctrl+S` và "chuyển dần không mốc" là hai điểm yếu |
| Tính trung thực | **10/10** | Tự ghi rõ chỗ chưa chắc ("chưa đọc kỹ phần này"), không phóng đại số liệu, ghi nhận việc đã làm tốt trước khi nêu vấn đề |
| Tính khả dụng ngay | **5/10** | ⬅️ **Điểm yếu chính** — 3 mục đã lỗi thời, 1 rủi ro không tồn tại |

**Kết luận:** đây là tài liệu rà soát chất lượng tốt, đáng dùng làm cơ sở triển khai **sau khi cập nhật theo mục 1, 3, 4 và 6 của review này**. Điểm mạnh nhất là tính trung thực; điểm yếu duy nhất đáng kể là quy trình chụp snapshot thay vì bám commit — một lỗi dễ sửa và không lặp lại nếu áp dụng khuyến nghị ghi commit hash.

---

*Review — 27/07/2026 · Cơ sở kiểm chứng: `develop` @ `d5722f8`*
