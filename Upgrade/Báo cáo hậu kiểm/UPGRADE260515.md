# UPGRADE260515 — Chức năng Báo cáo Hậu kiểm

**Ngày cập nhật:** 15/05/2026  
**Phiên bản:** 1.2.0  
**Thực hiện bởi:** KSNB System / Claude Code  

---

## Tóm tắt

Xây dựng hoàn chỉnh module báo cáo hậu kiểm: upload file IPCAS/Payment → parse dữ liệu → sinh báo cáo Excel per phòng (ZIP) + báo cáo Word tổng hợp trung tâm. Toàn bộ xử lý in-memory, không lưu file lên server.

| Hạng mục | Trạng thái |
|----------|-----------|
| Parse file IPCAS (GDV + HKV) | ✅ Hoàn thành |
| Parse file Payment (Teller + Backchecker) | ✅ Hoàn thành |
| Sinh báo cáo Excel per phòng → ZIP | ✅ Hoàn thành |
| Sinh báo cáo Word tổng hợp trung tâm | ✅ Hoàn thành |
| Kiểm tra GD HK sai ≠ 0 (blocking popup) | ✅ Hoàn thành |
| Tự động điền ngày tháng vào Word | ✅ Hoàn thành |
| Tổng hợp số liệu phòng (Table 4) | ✅ Hoàn thành |
| Fix parse số có dấu phẩy hàng nghìn | ✅ Hoàn thành |
| Fix lỗi startup crash khi DB bị lock | ✅ Hoàn thành |
| Fix lệch cột hàng Tổng (I/II/I+II) trong Word | ✅ Hoàn thành |

---

## Chi tiết thay đổi

---

### Tổng quan kiến trúc

```
[Frontend] Upload 4 file (GDV, HKV, Teller, Backchecker)
    ↓
POST /api/reports/parse-gdv   → JSON grouped by phòng (GDV + Teller)
POST /api/reports/parse-hkv   → JSON merged HKV list (HKV + Backchecker)
    ↓
[Frontend] Tính dept_summaries từ kết quả parse-gdv
    ↓
POST /api/reports/generate-dept-zip  → ZIP chứa Excel per phòng
POST /api/reports/generate-word      → Word tổng hợp (.docx)
```

Không ghi file lên disk — toàn bộ xử lý in-memory với `io.BytesIO`.

---

### `backend/services/report_service.py` *(tạo mới)*

Module chính xử lý parse và generate báo cáo.

#### Parse IPCAS
- `parse_ipcas_gdv(file_bytes)` / `parse_ipcas_hkv(file_bytes)`:
  - Đọc file `.xls` bằng `xlrd` engine
  - Ánh xạ cột theo tên: `col_tellerid`, `name_1` (ngày), `name_3` (tổng GD), `name_4` (HK đúng), `name_5` (HK sai), `name_7` (chưa HK), `name_10` (BT hủy)
  - Nếu bất kỳ user nào có `name_5 > 0` → trả `violations` list (blocking)
  - Lấy tháng/năm báo cáo từ cột `name_1`

#### Parse Payment
- `parse_payment_teller(file_bytes)` / `parse_payment_backchecker(file_bytes)`:
  - Teller: header ở row index 6; Backchecker: header ở row index 10
  - Cột: `HKV` (username), `Tổng GD`, `GD Hậu kiểm đúng`, `GD Hậu kiểm sai`, `GD chưa HK`, `Tổng số GD Hủy`
  - Nhiều dòng per user (per ngày) → `groupby('HKV').sum()` để lấy số cả tháng

#### Lookup phòng ban
- `enrich_and_group(rows, db, is_payment)`: tra `source_users` theo `user_code` (IPCAS) hoặc `payment_username` (Payment) → gắn `vn_name` + `dept_name`
- Dùng batch query `WHERE user_code IN (...)` để tránh N+1

#### Hàm helper `_to_int(val)`
```python
def _to_int(val) -> int:
    try:
        v = str(val).strip().replace(',', '')   # bỏ dấu phân cách hàng nghìn
        if v.lower() in ('', 'nan', 'none', '-'):
            return 0
        return int(float(v))
    except Exception:
        return 0
```
**Lý do:** File Excel Payment dùng dấu phẩy làm phân cách hàng nghìn (1,000 = 1000, không phải 1.0). `float("1,000")` ném ValueError → cần strip dấu phẩy trước.

#### Generate Excel per phòng
- `generate_dept_excel(dept_name, month, year, ipcas_rows, payment_rows)` → bytes
- Dùng `openpyxl` ghi vào `io.BytesIO`
- Hai section: **I. HỆ THỐNG IPCAS** và **II. HỆ THỐNG THANH TOÁN TẬP TRUNG**
- Cột: STT | User | Họ tên | HKV thực hiện | Tổng GD thủ công đã HK | Chưa HK | BT hủy | Hủy KQ | Hủy CQ | % (CQ/Tổng HK) | Nguyên nhân

#### Generate Word tổng hợp
- `generate_center_word(month, year, hkv_ipcas, hkv_payment, dept_summaries)` → bytes
- Dùng `python-docx` đọc template `templates/Báo cáo hậu kiểm tháng.docx`
- Clone row XML để chèn dòng dữ liệu vào bảng (tránh mất style)
- **Table 1**: Bảng HKV — section IPCAS + Payment + hàng Tổng
- **Table 4**: Bảng số liệu phòng (b — Số liệu thực hiện) — điền từ `dept_summaries`

#### `_replace_date_runs(para, month, year)` *(mới)*
Xử lý vấn đề Word tách text thành nhiều `run` (run fragmentation). Ví dụ: "03/2026" có thể bị split thành `["0", "3", "/202", "6"]`.

```
- Ghép toàn bộ text của paragraph
- Tìm pattern bằng regex (tháng XX/YYYY và THÁNG XX NĂM YYYY)
- Xây dựng span-map vị trí từng run
- Ghi replacement vào run đầu tiên, xóa trắng các run còn lại trong match
```

Áp dụng cho tất cả `doc.paragraphs` trước khi điền bảng.

#### `_set_date_cell(cell, text)` *(mới)*
Xóa nội dung tất cả run trong paragraph trước khi set text, tránh hiện tượng ngày tháng bị nhân đôi khi cell có nhiều run cũ.

#### `_dept_label(name)` *(mới)*
```python
def _dept_label(name: str) -> str:
    return name.removeprefix('Phòng ').strip()
```
Bảng số liệu chỉ ghi tên ngắn ("Kế toán", "Thanh Toán") không ghi đầy đủ ("Phòng Kế toán").

---

### `backend/api/reports.py` *(tạo mới)*

4 endpoints, tất cả yêu cầu quyền `require_hkv_or_above`:

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/api/reports/parse-gdv` | POST multipart | Parse GDV + Teller → JSON grouped by phòng |
| `/api/reports/parse-hkv` | POST multipart | Parse HKV + Backchecker → JSON merged HKV list |
| `/api/reports/generate-dept-zip` | POST multipart | Sinh ZIP chứa Excel per phòng |
| `/api/reports/generate-word` | POST JSON | Sinh Word tổng hợp → `.docx` bytes |

- `parse-gdv` / `parse-hkv`: Nếu có `violations` → HTTP 422 với `detail = {"message": "...", "violations": [...]}`
- `generate-dept-zip`: nhận file trực tiếp → parse + sinh ZIP trong 1 request

---

### `frontend/pages/reports.py` *(tạo mới)*

Trang `/reports`, chỉ hiển thị với `hau_kiem_vien` trở lên (ẩn với `chuyen_vien`).

**Khu vực upload:** 4 file (GDV, HKV, Teller, Backchecker) — grid 4 cột.

**Nút "Tạo báo cáo hậu kiểm theo phòng":**
- Upload GDV + Teller → `POST /api/reports/generate-dept-zip`
- Nếu violations → hiện bảng cảnh báo user có GD HK sai > 0
- Nếu thành công → `ui.download(zip_bytes, "BC_HK_phong.zip")`

**Nút "Tạo thư công tác + BC HK":**
- Parse HKV + Backchecker song song với GDV + Teller bằng `asyncio.gather(..., return_exceptions=True)`
- GDV optional: lỗi parse GDV không chặn luồng chính, `dept_summaries` sẽ rỗng
- Tính `dept_summaries` từ kết quả GDV inline (hàm `_build_dept_summaries`)
- Gửi `POST /api/reports/generate-word` với JSON body
- Nếu thành công → `ui.download(word_bytes, f"BC_HK_T{month:02d}{year}.docx")`

**`_show_violations(violations, file_map)`:** Hiển thị bảng cảnh báo phân theo hệ thống (IPCAS / Payment), hiện tên file + số dòng trong file.

**`_build_dept_summaries(ipcas_grouped, payment_grouped)`:** Gom số liệu GDV+Teller theo phòng để truyền vào `generate-word`.

---

### `backend/main.py` — Fix startup crash khi DB bị lock

**Vấn đề:** Sau khi restart, backup scheduler của process cũ vẫn giữ DB lock trong vài giây. `_ensure_indexes()` gặp `OperationalError: database is locked` → raise → app crash.

**Fix:** Tolerate lỗi `locked` với warning log thay vì raise:
```python
if "database is locked" in msg or "locked" in msg:
    _mig_log.warning("Migration skipped (DB locked, sẽ thử lại lần sau): %.80s", s)
else:
    _mig_log.error("Migration failed: %s — %s", s, exc)
    raise
```

Migration idempotent nên bỏ qua lần này không ảnh hưởng — lần restart tiếp theo sẽ chạy lại.

---

### Fix lệch cột hàng Tổng trong Word Table 1

**Vấn đề:** Hàng dữ liệu thường có 9 ô riêng biệt (cột 2 và 3 là 2 ô). Hàng Tổng (I), Tổng (II), Tổng (I+II) có cột 2+3 merged thành 1 ô → chỉ 8 ô. Code truyền 9 giá trị → lệch 1 cột sang phải.

**Fix:** Bỏ `''` thừa ở vị trí 3 cho 3 hàng tổng:
```python
# Trước (9 giá trị — sai):
_append_data_row(t1, total_xml, ['', 'Tổng (I):', str(ti_gd), '', str(ti_dung), ...])

# Sau (8 giá trị — đúng):
_append_data_row(t1, total_xml, ['', 'Tổng (I):', str(ti_gd), str(ti_dung), ...])
```

---

### Templates *(tạo mới)*

| File | Mô tả |
|------|-------|
| `templates/Báo cáo hậu kiểm tháng.docx` | Template Word tổng hợp trung tâm |
| `templates/Báo cáo Tổng hợp hậu kiểm theo phòng.xlsx` | Template Excel báo cáo per phòng |

---

## Danh sách file thay đổi

### File mới tạo
| File | Mô tả |
|------|-------|
| `backend/api/reports.py` | 4 API endpoints báo cáo hậu kiểm |
| `backend/services/report_service.py` | Core parse + generate logic |
| `frontend/pages/reports.py` | Trang `/reports` |
| `templates/Báo cáo hậu kiểm tháng.docx` | Template Word tổng hợp |
| `templates/Báo cáo Tổng hợp hậu kiểm theo phòng.xlsx` | Template Excel phòng |

### File sửa đổi
| File | Nội dung thay đổi |
|------|------------------|
| `backend/main.py` | Tolerate DB lock trong `_ensure_indexes()`; đăng ký `reports_router` |
| `frontend/shared.py` | Thêm menu item "Báo cáo" (ẩn với `chuyen_vien`) |
| `frontend/main.py` | Import `frontend.pages.reports` |
| `frontend/api_client.py` | Thêm `post_upload`, `post_upload_bytes`, `post_download` |

---

## Mapping dữ liệu

### IPCAS (file .xls, xlrd engine)
| Cột file | Ý nghĩa |
|----------|---------|
| `col_tellerid` | Mã user IPCAS → lookup `source_users.user_code` |
| `name_1` | Ngày GD (lấy tháng/năm báo cáo) |
| `name_3` | Tổng số GD |
| `name_4` | GD HK đúng |
| `name_5` | GD HK sai (≠ 0 → blocking) |
| `name_7` | GD chưa HK |
| `name_10` | Số BT hủy |

### Payment (file .xlsx, openpyxl engine)
| Cột file | Ý nghĩa |
|----------|---------|
| `HKV` | Username Payment → lookup `source_users.payment_username` |
| `Tổng GD` | Tổng GD thủ công |
| `GD Hậu kiểm đúng` | GD HK đúng |
| `GD Hậu kiểm sai` | GD HK sai (≠ 0 → blocking) |
| `GD chưa HK` | GD chưa HK |
| `Tổng số GD Hủy` | GD hủy |

Header row: Teller → index 6, Backchecker → index 10 (0-indexed).

---

## Hướng dẫn sử dụng

1. Đăng nhập tài khoản `hau_kiem_vien` trở lên
2. Vào menu **Báo cáo**
3. Upload file theo đúng loại (GDV/HKV → IPCAS `.xls`; Teller/Backchecker → Payment `.xlsx`)
4. **Báo cáo phòng**: cần GDV hoặc Teller → nhấn "Tạo báo cáo hậu kiểm theo phòng" → tải về ZIP
5. **Báo cáo tổng hợp**: cần HKV hoặc Backchecker (GDV+Teller tùy chọn để điền Table 4) → nhấn "Tạo thư công tác + BC HK" → tải về `.docx`
6. Nếu có user vi phạm (GD HK sai > 0) → hệ thống hiển thị bảng cảnh báo, không sinh báo cáo

---

*Tài liệu tạo ngày 15/05/2026.*
