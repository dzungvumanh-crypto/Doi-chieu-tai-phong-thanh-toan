# Plan: Chức năng Báo cáo Hậu kiểm (v3 — Final)

## Context

Xây dựng chức năng sinh báo cáo hậu kiểm từ dữ liệu xuất từ IPCAS và Payment.
Gồm 2 loại báo cáo:
1. **Báo cáo tổng hợp hậu kiểm phòng** — Excel, hiển thị trên UI, người dùng điền tay một số ô, download + print
2. **Thư công tác + Báo cáo HK** — Word, gom từ 4 báo cáo phòng + dữ liệu HKV

---

## Column Mapping

### File GDV (IPCAS) + Teller (Payment) → báo cáo phòng

| Khái niệm | IPCAS col name | Payment col name |
|---|---|---|
| Mã user | `col_tellerid` | `HKV` |
| Ngày GD (lấy tháng BC) | `name_1` | `Ngày` |
| Tổng số GD | `name_3` | `Tổng GD` |
| GD HK đúng | `name_4` | `GD Hậu kiểm đúng` |
| GD HK sai ⚠️ | `name_5` | `GD Hậu kiểm sai` |
| GD chưa HK | `name_7` | `GD chưa HK` |
| Số BT hủy | `name_10` | `Tổng số GD Hủy` |

**Tổng GD thủ công đã HK = GD HK đúng (name_4)**

**Validation**: `name_5 ≠ 0` → popup blocking: "GD Hậu kiểm sai đang lớn hơn 0. Đề nghị kiểm tra lại"

IPCAS: header row 0 (row 1 Excel), đọc theo tên cột (`df['name_4']`)
Payment teller: header row 6 (0-indexed) = Excel row 7 → `pd.read_excel(header=6)`
Payment: có nhiều dòng per user per ngày → `groupby('HKV').sum()`

### File HKV (IPCAS) + Backchecker (Payment) → thư công tác / Word

Cùng cột name_3/4/5/7/10 như trên.
Payment backchecker: header row 10 (0-indexed) → `pd.read_excel(header=10)`
Ghép: `col_tellerid` (IPCAS) ↔ `HKV` (Payment) = cùng Cán bộ HK
Lấy tất cả user (không lọc theo role).

### Mapping user → phòng ban
```
source_users.user_code = col_tellerid (IPCAS)
source_users.full_name = HKV username (Payment, lowercase)
source_users.vn_name   = Tên hiển thị
source_users.department_id → Department.name
```

---

## Workflow

### Tab 1 — Báo cáo phòng (Excel)
```
1. Upload 2 file: GDV (.xls) + Teller (.xlsx)
   → parse + validate name_5 == 0
   → lookup source_users → group by department
2. User chọn phòng → hiển thị báo cáo trên UI
   Cột readonly: User | Tên | Tổng GD đã HK | Chưa HK | BT hủy
   Cột editable: HKV thực hiện | Hủy KQ | Hủy CQ | Nguyên nhân
   % = Hủy CQ / Tổng GD đã HK * 100 (auto, 2 số thập phân)
3. Click "Lưu" → download Excel
4. Click "In" → ui.run_javascript('window.print()')
```

### Tab 2 — Báo cáo tổng hợp (Word)
```
1. Upload 2 file: HKV (.xls) + Backchecker (.xlsx)
   → parse + validate name_5 == 0
   → merge IPCAS + Payment theo user
2. Nhập dept summaries từ 4 báo cáo phòng (stored trong app.storage.user sau khi lưu Tab 1)
3. Click "Tạo báo cáo HK" → download Word
```

---

## File Template

- **Excel output**: generate từ scratch bằng openpyxl (dynamic rows, matching template structure)
- **Word output**: generate từ scratch bằng python-docx (2 tables: HKV table + dept summary table)
- Template mẫu tham chiếu:
  - `templates/Báo cáo Tổng hợp hậu kiểm theo phòng.xlsx`
  - `templates/Báo cáo hậu kiểm tháng.docx`

---

## Files thực thi

### Tạo mới
- `backend/services/report_service.py`
- `backend/api/reports.py`
- `frontend/pages/reports.py`

### Chỉnh sửa
- `requirements.txt` — thêm `pandas`, `xlrd`
- `backend/main.py` — register router
- `frontend/api_client.py` — thêm `post_upload()`
- `frontend/shared.py` — thêm menu item
- `frontend/main.py` — thêm import

---

## API Endpoints

```
POST /api/reports/parse-gdv    multipart(gdv_file, teller_file) → JSON grouped by dept
POST /api/reports/parse-hkv    multipart(hkv_file, checker_file) → JSON merged HKV list
POST /api/reports/generate-dept JSON body → Excel bytes (StreamingResponse)
POST /api/reports/generate-word JSON body → Word bytes (StreamingResponse)
```

RBAC: `require_hkv_or_above` cho tất cả.