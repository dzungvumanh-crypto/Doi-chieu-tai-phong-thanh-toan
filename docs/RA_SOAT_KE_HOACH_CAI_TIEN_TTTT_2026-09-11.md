# RÀ SOÁT KẾ HOẠCH CẢI TIẾN HỆ THỐNG TTTT

**Ngày rà:** 11/09/2026
**Đối tượng:** `KE_HOACH_CAI_TIEN_TTTT_2026-09-11.md` (lập từ bản nén nhánh `TTTT-develop`)
**Cách kiểm:** đo lại trên cây làm việc hiện tại của `develop` (AST + grep), dẫn file:dòng. Nhãn độ tin cậy: **cao / trung bình / thấp / cần xem thêm**.

---

## 0. Kết luận

Hướng đi và thứ tự các đợt **đúng**. Phần lớn số liệu khớp mã nguồn. Nhưng có:

- **1 hạng mục báo lỗi sai** — mục 1.5, nên bỏ.
- **2 chỗ đếm thiếu** — mục 1.4 (`except Exception`) và mục 3 (số nơi giữ trạng thái job).
- **3 chỗ thiết kế sẽ gây hỏng nếu làm đúng như văn bản** — mục 2.1, 1.3, 3.1.
- **4 chỗ kế hoạch tự vi phạm nguyên tắc của chính nó** — mục 4.1, 1.2, 3.3, 4.4.

---

## 1. Chỗ sai — cần sửa trong kế hoạch

### 1.1 ❌ Mục 1.5 báo lỗi không có — độ tin cậy **cao**

Hai dòng `frontend/pages/leaves.py:786` và `:1583` **không** chặn event loop. Chúng truyền một `lambda` vào `_fetch_preview()`, và hàm này đã tự bọc `to_thread`:

```python
# frontend/pages/leaves.py:158-166
async def _fetch_preview(call):
    ...
    try:
        return await asyncio.to_thread(call)
```

Công cụ quét thấy chữ `api.get` nằm trong `async def` nên báo nhầm — lời gọi thực ra đã chạy ở luồng riêng.

Nếu "sửa" thành `lambda: asyncio.to_thread(...)` thì **tệ hơn**: `to_thread(call)` nhận về một coroutine không ai `await` → việc duyệt đơn hỏng mà không báo lỗi.

**→ Bỏ mục 1.5.**

### 1.2 ⚠ Mục 3 — trạng thái job trong RAM không phải 4 nơi mà ít nhất 6 — độ tin cậy **cao**

| File | Biến | Kiểu API |
|---|---|---|
| `backend/services/ach_service.py:78` | `_jobs` | start / poll / cancel / download |
| `backend/services/ilo1000_service.py:24` | `_jobs` | như trên |
| `backend/services/doi_chieu_song_phuong_kenh_core_service.py:44` | `_jobs` | như trên |
| `backend/services/doi_chieu_song_phuong_kenh_core_di_service.py:42` | `_jobs` | như trên |
| `backend/services/cham459901_service.py:110` | `_progress` | `task_token` / `progress` — **kế hoạch bỏ sót** |
| `backend/services/doi_chieu_song_phuong_service.py:79` | `_progress` | như trên — **kế hoạch bỏ sót** |

Ngoài ra CITAD và CITAD Nostro giữ `_citad_buffer` / `_ph_buffer` — bộ đệm upload, là một loại trạng thái khác, cần quyết có đưa vào `job_runner` hay không.

Hệ quả cho việc chọn module thí điểm: ILO1000 (`_jobs`) + Chấm 459901 (`_progress`) là **đúng mỗi con một kiểu** — chọn vậy là tốt. Nhưng lý do nên ghi là *"phủ đủ hai kiểu job"*, không phải *"nhỏ nhất"*.

### 1.3 ⚠ Mục 1.4 — đếm theo chuỗi ký tự, không theo cú pháp — độ tin cậy **cao**

| Chỉ số | Kế hoạch | Đo lại (AST) |
|---|---:|---:|
| `except Exception` (mọi dạng) | 134 | **511** — backend 123, frontend 388 |
| Khối chỉ có `pass` | ~33 | **39** — backend 16, frontend 23 |

Con số 134 khớp với số lần xuất hiện của chuỗi `except Exception:` (grep ra 135) — tức là đã bỏ qua dạng `except Exception as e:`. Việc vẫn nhỏ (39 chỗ), chỉ cần sửa số.

---

## 2. Chỗ thiết kế sẽ vỡ nếu làm đúng như văn bản

### 2.1 Mục 2.1 — "chuyển nguyên văn, không sửa logic" là không làm được — độ tin cậy **cao**

Đo trên `leaves_page`:

| Chỉ số | Giá trị |
|---|---:|
| Hàm lồng nhau | **193** |
| Tên cục bộ ở cấp trang | **719** |
| `nonlocal` | 0 — state chia sẻ qua closure đọc biến cha (dict, element UI) |

Các hàm con "mượn" biến của hàm cha. Đưa một tab sang file khác thì mọi biến mượn phải truyền vào tường minh — **đó chính là sửa logic**.

Nguy hiểm ở chỗ: Python chỉ tra tên lúc **chạy**. Quên một biến → `NameError` chỉ khi có người bấm đúng nút đó. `tests/test_kiem_nap_trang_frontend.py` chỉ kiểm được trang **import** được, không bắt loại lỗi này.

**→ Đề xuất:** ruff luật `F821` (tên chưa định nghĩa) bắt đúng loại lỗi trên bằng quét tĩnh. Vì vậy **mục 1.3 là lưới an toàn bắt buộc của mục 2.1**, không chỉ là "nên có". Mỗi PR tách tab phải qua `ruff check --select F821` sạch.

Ghi chú kỹ thuật: `frontend/main.py` tự nạp trang bằng `pkgutil.iter_modules`. Tách thành **package** `frontend/pages/leaves/` là an toàn (chỉ `__init__.py` được nạp tự động). Nhưng đừng để file `_tab_*.py` nằm thẳng trong `frontend/pages/` — chúng sẽ bị nạp như một trang.

### 2.2 Mục 1.3 — bật nhóm `B` sẽ ra ~509 cảnh báo sai ngay lần đầu — độ tin cậy **cao**

Luật `B008` cấm gọi hàm trong giá trị mặc định của tham số. Cách viết `x = Depends(...)` của FastAPI chính là như vậy — mã hiện có **509** chỗ trong `backend/api/`.

**→ Phải khai `ignore = ["B008"]` từ đầu.** Không thì câu hỏi 5.5 ("chấp nhận vài trăm cảnh báo không?") bị trả lời dựa trên nhiễu.

Cấu hình tối thiểu đề xuất:

```toml
[tool.ruff.lint]
select = ["F", "E9", "B"]
ignore = ["B008"]   # Depends() trong tham số mặc định — cách viết chuẩn của FastAPI
```

### 2.3 Mục 3.1 — lưu job vào CSDL không làm job "sống qua restart" — độ tin cậy **cao**

Job chạy bằng `threading.Thread` **trong chính tiến trình backend** (xem `backend/api/cham459901.py:189`). Restart → luồng chết. CSDL chỉ giữ được **bản ghi**, không giữ được **công việc**.

Ghi đúng phải là: *"bản ghi còn lại; job đang chạy dở được đánh dấu `interrupted` khi khởi động"*.

Thêm một rủi ro: nếu ghi tiến độ (%) vào SQLite mỗi vài trăm ms thì tranh khoá ghi với người dùng thật — hệ thống đã có log `db.contention` vì đúng chuyện này.

| Cách | Được | Mất |
|---|---|---|
| Ghi mọi cập nhật tiến độ vào CSDL | Màn "Tác vụ đang chạy" đọc 1 nguồn | Tranh khoá ghi WAL, `database is locked` |
| **Tiến độ ở RAM, CSDL chỉ ghi mốc** (bắt đầu / xong / lỗi / huỷ) | Không tranh khoá; vẫn tra được lịch sử | Màn 3.3 phải ghép 2 nguồn |

**→ Đề xuất cách thứ hai.**

---

## 3. Chỗ kế hoạch tự vi phạm nguyên tắc của chính nó

Kế hoạch tự đặt nguyên tắc *"không xếp hạng ưu tiên dựa trên phỏng đoán"*, nhưng:

### 3.1 Mục 4.1 — gộp baseline migration: rủi ro **Cao**, lợi ích **chưa đo**

Không có số nào cho thời gian `_ensure_indexes()` (hiện 1.682 dòng, `backend/db/migrations.py:698`) mất mỗi lần khởi động. Nếu dưới 1 giây thì lợi ích chỉ còn là dễ đọc — không đáng rủi ro chạm vào chỗ nhạy cảm nhất hệ thống.

**→ Đo trước, quyết sau.** Độ tin cậy rằng nên hoãn: **trung bình**.

### 3.2 Mục 1.2 — ngưỡng 1500 ms sẽ báo liên tục cho việc chậm có chủ đích

- Dựng bản xem trước qua Word: 5–7 giây ở lần đầu (`docs/DESIGN.md`, mục đơn nghỉ phép PDF)
- Tải file, upload file đối chiếu, chạy đối chiếu

**→ Cần danh sách đường dẫn loại trừ hoặc ngưỡng riêng theo đường dẫn**, không thì log toàn nhiễu và mất đúng tác dụng "xếp ưu tiên bằng số liệu".

### 3.3 Mục 3.3 — màn "Tác vụ đang chạy" không nhắc quy tắc phân quyền

Theo `CLAUDE.md` và `docs/DESIGN.md` mục *Phân quyền*, cần đi đủ 4 chỗ:

| # | Việc |
|---|---|
| 1 | Khai `menu.jobs` và `jobs.cancel_any` trong `FEATURES` (`backend/core/features.py`) |
| 2 | Thêm vào `FEATURE_GROUPS` |
| 3 | `Depends(require_feature(...))` ở route |
| 4 | `api.has_feature(...)` ở frontend |

Người **tự huỷ job của mình** là dữ liệu của hồ sơ (so id), không phải quyền — cùng loại với người duyệt đơn.

### 3.4 Mục 4.4 — tách tài liệu kéo theo sửa quy trình

`docs/Implementation-notes.html` hiện 1,46 MB / 16.723 dòng — con số của kế hoạch đúng. Nhưng đổi cấu trúc file này và `Logs_update.md` kéo theo phải sửa:

- `CLAUDE.md` — mục *Implementation Notes*
- memory `feedback_push_readme` — quy tắc cập nhật khi push/merge
- `deploy.bat` — đang chép `Logs_update.md` sang máy chính

---

## 4. Chỗ kế hoạch đúng — đã kiểm lại

| Khẳng định | Kết quả |
|---|---|
| Không có `/health`, không đo thời gian request | **Đúng** — `backend/main.py` chỉ có `@app.get("/")`; không middleware đo thời gian |
| `leaves_page` 6.122 dòng, `open_detail` 728 dòng | **Đúng** |
| Năm hàm dài nhất | **Đúng** thứ tự; số dòng lệch 1–3 do mã đã đổi |
| Helper lặp giữa các trang | **Đúng** — riêng `_confirm` lặp 6 trang (kế hoạch ghi 5) |
| SQL f-string ở `hr.py` không phải lỗ hổng | **Đúng** — tên cột lấy qua `hr.chuan_hoa(PROFILE_FIELDS_…)` = danh sách trắng; tên bảng từ `spec` nội bộ |
| Không có file cấu hình lint; chưa có `frontend/components/` | **Đúng** |
| `log_cleanup_service` chỉ dọn `login_logs` + `audit_logs` (365 ngày) | **Đúng** |
| CI chỉ chạy `pytest -q` trên `windows-latest` | **Đúng** |
| `duty_stats` chưa có test | **Đúng** |
| `handover_reports`, `th_reports` chưa có test | **Cần xem thêm** — grep thấy xuất hiện trong 4 và 2 file test, có thể chỉ là nhắc gián tiếp |
| `python-jose` có CVE 2024 | Dự án chỉ dùng HS256, `jwt.decode(..., algorithms=[settings.ALGORITHM])` khoá thuật toán (`backend/core/security.py:30`). CVE 2024 chủ yếu nhắm khoá ECDSA và giải nén JWE → mức ảnh hưởng **thấp** (độ tin cậy: trung bình). Vẫn nên chuyển PyJWT theo lịch rà 6 tháng, không gấp |

### Số liệu trôi so với bản nén

| Chỉ số | Kế hoạch | Hiện tại |
|---|---:|---:|
| `backend/db/migrations.py` | 2.303 dòng | 2.379 dòng |
| `_ensure_indexes` bắt đầu ở | dòng 624 | dòng 698 |
| `frontend/shared.py` | 797 dòng | 803 dòng |
| File trong `tests/` | 101 | 103 |

Ngoài lề: `CLAUDE.md` ghi `backend/main.py ~80 LOC`, thực tế **191 dòng** — tài liệu dự án cũ, không phải lỗi của kế hoạch.

---

## 5. Góp ý bổ sung cho mục 1.1 (`/health`)

Endpoint không cần đăng nhập, trên LAN. Đề xuất tách hai tầng:

| Tầng | Trả gì | Đăng nhập |
|---|---|---|
| `GET /health` | `{status, db_ok}` — đủ cho `deploy.bat` kiểm backend đã lên | Không |
| `GET /api/health/detail` | `pool_free`, `backup_moi_nhat`, `lech_gio_giay` | Có — qua mã quyền, theo quy tắc 4 chỗ |

Lý do: thời điểm backup mới nhất và độ lệch giờ là thông tin vận hành, không cần lộ cho mọi máy trong LAN. `backup_moi_nhat` còn phải quét thư mục — giữ `/health` rẻ để gọi dồn dập không sao.

---

## 6. Trả lời các câu hỏi ở mục 5 của kế hoạch

| # | Câu hỏi | Ý kiến |
|---|---|---|
| 1 | Thứ tự | Đợt 1 (**bỏ 1.5, đưa 1.3 lên đầu**) → 2.1. **Chưa gộp 2.2**: helper cùng tên ở 7 trang có thể chạy khác nhau, gộp = sửa logic, phải so khác biệt từng bản trước |
| 2 | Lưu trữ kết quả đối chiếu | Quyết định nghiệp vụ — không có cơ sở kỹ thuật để trả lời thay |
| 3 | Tách `leaves.py` | Đồng ý tách từng tab, deploy giãn. Thêm điều kiện: mỗi PR qua `ruff F821` sạch |
| 4 | Khung job | Đồng ý thí điểm 2 module (ILO1000 + 459901 — phủ đủ hai kiểu job) |
| 5 | CI / ruff | Chạy toàn mã, `ignore B008`, chế độ báo cáo, không chặn merge |
| 6 | `python-jose` | Không gấp (xem mục 4) — nhưng ràng buộc của đơn vị thì người dùng phải xác nhận |

---

## 7. Điều kiện trước khi bắt đầu

Cây làm việc `develop` đang có tính năng **Khảo sát** chưa commit, sửa `backend/api/registry.py`, `backend/core/features.py`, `backend/db/migrations.py`, `frontend/shared.py`. Đợt 1 chạm đúng các file đó.

**→ Merge Khảo sát xong rồi mới bắt đầu Đợt 1**, tránh xung đột hai nhánh cùng sửa một chỗ.

---

## 8. Danh sách sửa cho bản kế hoạch

- [ ] Bỏ mục 1.5
- [ ] Mục 1.4: sửa số (511 / 39)
- [ ] Mục 1.3: thêm `ignore = ["B008"]`; ghi rõ là tiền đề của 2.1 (`F821`)
- [ ] Mục 1.2: thêm danh sách đường dẫn loại trừ / ngưỡng theo đường dẫn
- [ ] Mục 1.1: tách `/health` công khai và `/api/health/detail` có đăng nhập
- [ ] Mục 2.1: bỏ chữ "nguyên văn"; ghi rõ phải truyền state tường minh + dùng package
- [ ] Mục 3: sửa "4 nơi" thành 6 nơi (+ 2 bộ đệm CITAD); đổi lý do chọn module thí điểm
- [ ] Mục 3.1: bỏ "job không mất khi restart"; tiến độ ở RAM, CSDL chỉ ghi mốc
- [ ] Mục 3.3: thêm mã quyền theo quy tắc 4 chỗ
- [ ] Mục 4.1: thêm bước đo thời gian khởi động trước khi quyết
- [ ] Mục 4.4: liệt kê các quy trình/tài liệu phải sửa theo
- [ ] Mục 4.5: xem lại `handover_reports` / `th_reports`
- [ ] Thêm điều kiện: merge Khảo sát trước Đợt 1
