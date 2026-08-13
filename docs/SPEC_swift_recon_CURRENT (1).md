# SPEC — Module "Đối chiếu điện SWIFT" (trạng thái hiện tại, đã tích hợp vào TTTT)

> **Mục đích tài liệu này:** ghi lại ĐẦY ĐỦ hành vi hiện tại của module (đã
> qua nhiều đợt sửa) để bất kỳ ai — kể cả AI — sửa code sau này đều giữ đúng
> các quy tắc nghiệp vụ đã thống nhất, không vô tình làm hỏng hoặc bỏ sót.
> Khi đưa yêu cầu sửa đổi cho Claude/AI ở phiên làm việc mới, đính kèm NGUYÊN
> VĂN file này để AI hiểu đúng "luật chơi" hiện tại trước khi sửa.
>
> Tài liệu phản ánh trạng thái sau PR #13 (`swift/nhieu-file-va-xuat-bieu-mau`),
> ĐÃ cập nhật thêm sau khi xử lý review hiệu năng trên PR (xem mục 9 — MỚI).

---

## 0. Vị trí file trong repo

```
backend/services/swift_recon/
    __init__.py
    parsers.py             # BẤT BIẾN — copy nguyên văn từ bản gốc, KHÔNG sửa logic
    reconcile.py            # BẤT BIẾN — copy nguyên văn từ bản gốc, KHÔNG sửa logic
    exporters.py             # BẤT BIẾN — copy nguyên văn từ bản gốc, KHÔNG sửa logic
    upload_utils.py          # xử lý upload + giải nén zip
    history_service.py       # lưu/đọc bảng audit swift_recon_history
    template_exporters.py    # MỚI — xuất Excel theo biểu mẫu Mẫu 04/05
    templates/                # MỚI — 4 file .xlsx làm khung nền cho xuất theo biểu mẫu
        tonghop_den.xlsx
        tonghop_di.xlsx
        chitiet_den.xlsx
        chitiet_di.xlsx
backend/schemas/swift_recon.py
backend/api/swift_recon.py    # router, ĐÃ sửa nhiều đợt (xem mục 6)
frontend/pages/swift_recon.py  # trang NiceGUI, ĐÃ sửa (hỗ trợ nhiều file/1 ô upload)
```

**Nguyên tắc bất biến (giữ nguyên từ SPEC gốc):** `parsers.py`, `reconcile.py`,
`exporters.py` **KHÔNG được sửa logic**. Mọi hành vi mới (phân loại hệ thống,
tính lại "Chênh lệch" theo khoá, gộp nhiều file...) đều làm ở TẦNG TRÊN
(`backend/api/swift_recon.py`, `template_exporters.py`) — chỉ ĐỌC/gọi lại các
hàm có sẵn trong 3 file bất biến (đặc biệt là `reconcile.match_by_key()`),
không viết lại logic ghép khoá.

---

## 1. Giao diện — 5 tab (`frontend/pages/swift_recon.py`)

1. **"1. Điện đến"** — 2 ô upload: SAA điện đến, Quản lý điện đến + nút "Đối chiếu điện đến".
2. **"2. Điện đi"** — 2 ô upload, **đúng thứ tự Quản lý trước, SAA sau** + nút "Đối chiếu điện đi".
3. **"3. Kết quả đối chiếu điện đến"**.
4. **"4. Kết quả đối chiếu điện đi"**.
5. **"Lịch sử"** — HOÀN TOÀN ĐỘC LẬP, không đọc/ghi chung state với tab 3/4, không tự chuyển tab khi thao tác.

### 1.1 Upload & kiểm tra file (tab 1, 2)

- Chấp nhận `.xls`, `.xlsx`, `.zip` (zip chứa `.xls`/`.htm`/`.html` kèm thư
  mục `..._files` — trường hợp export "Web Page, Complete" — tự giải nén, tự
  tìm đúng file bên trong, ưu tiên file KHÔNG nằm trong thư mục `..._files`,
  ưu tiên độ sâu thư mục nông hơn).
- **Mỗi ô upload nhận NHIỀU FILE cùng lúc** (kéo-thả hoặc chọn nhiều) — vì 1
  bên (thường là SAA) có thể phải xuất nhiều lần trong ngày. Mỗi file được
  kiểm tra NGAY khi vừa chọn (gọi `/api/swift-recon/parse-preview` — vẫn
  parse TỪNG file 1, không đổi), hiện dòng riêng:
  - `✅ <tên file> (N dòng)` — file hợp lệ, dùng để đối chiếu.
  - `⏳ Đang kiểm tra <tên file>...` — đang gọi API kiểm tra.
  - `❌ <tên file> — lỗi, KHÔNG được dùng: <chi tiết lỗi>` — file lỗi, tự
    động KHÔNG được gộp vào lúc đối chiếu.
  - Dòng tổng: `✅ Đang dùng để đối chiếu: N file — tổng X dòng`.
  - Có nút ✕ xoá từng file khỏi danh sách trước khi đối chiếu.
- Toàn bộ file HỢP LỆ trong CÙNG 1 ô được **gộp (concat)** thành 1 tập bản
  ghi duy nhất trước khi đối chiếu (xem mục 6.2). **KHÔNG tự động loại
  trùng** — nếu người dùng lỡ chọn trùng 1 file 2 lần, tổng số dòng sẽ tăng
  gấp đôi rõ ràng trên giao diện, người dùng tự phát hiện và xoá bớt bằng
  nút ✕, thay vì hệ thống âm thầm đoán và loại sai bản ghi hợp lệ.
- Ghi chú hướng dẫn xử lý lỗi "Không tìm thấy `<table>`" hiện ngay dưới 2 ô upload.

### 1.2 Đối chiếu

- Nút "Đối chiếu điện đến" / "Đối chiếu điện đi".
- Chặn bấm nếu chưa có ÍT NHẤT 1 file hợp lệ mỗi bên.
- Sau khi xong: tự chuyển sang đúng tab Kết quả tương ứng.
- Logic ACK riêng cho điện đi (không đổi, xem `reconcile.py::_ack_ok`): field
  `ACK/NAK` (bên QL, giá trị OK = `"ACK"`) HOẶC `Netw. Status` (bên SAA, giá
  trị OK = `"Network Ack"`) — chỉ cần 1 trong 2 bên báo OK là coi là đã Ack.

### 1.3 Tab Kết quả (3 & 4)

- Dòng tổng quan: tổng số điện, số khớp, số chênh lệch.
- **Chú thích trạng thái kèm SỐ LƯỢNG** từng loại, KHÁC NHAU giữa đến/đi:
  - Điện đến: `Khớp khoá`, `Chỉ có ở SAA (không có ở QL)`, `Chỉ có ở QL (không có ở SAA)`.
  - Điện đi: `Khớp khoá + đã Ack`, `Khớp khoá nhưng chưa Ack`, `Chỉ có ở QL (không có ở SAA)`, `Chỉ có ở SAA (không có ở QL)`.
- **2 bộ lọc multi-select ĐỘC LẬP, kết hợp AND**: theo Trạng thái, theo Loại
  điện (danh sách loại điện tự lấy từ dữ liệu vừa đối chiếu).
- Mỗi bộ lọc có nút "chọn tất cả" (`done_all`) + "bỏ chọn tất cả" (`remove_done`) riêng.
- Nút "Bỏ lọc" dùng chung — reset cả 2 ô về chọn hết.
- Hiệu ứng ⏳ → ✅ trên giá trị đang chọn ở CẢ 2 ô lọc mỗi khi đổi lựa chọn ở
  BẤT KỲ ô nào (giữ ⏳ ~0.3s rồi mới đổi ✅ sau khi bảng đã hiển thị đúng).
- Bảng kết quả: cột đầu "STT", cột 2 "Trạng thái" (nhãn tiếng Việt, KHÔNG
  hiện mã nội bộ `ONLY_A`/`ONLY_B`/`MATCHED`/`MATCHED_NOT_ACK`), sau đó toàn
  bộ cột gốc của cả 2 file (không có cột `_` nội bộ).
- **Header bảng LUÔN GHIM (sticky)** khi kéo thanh cuộn dọc, không tạo thêm
  khung cuộn phụ (CSS `.sticky-header-table`).
- **5 nút xuất Excel** mỗi tab (2 nút cuối là MỚI, xem mục 3):
  1. "Xuất Excel Tổng hợp"
  2. "Xuất Excel Chi tiết lệch"
  3. "Xuất Excel bản ghi đang lọc" — xuất ĐÚNG những dòng đang hiển thị sau
     lọc, đúng cột đang hiển thị (không phải toàn bộ dữ liệu).
  4. "Xuất Excel Tổng hợp theo biểu mẫu"
  5. "Xuất Excel Chi tiết lệch theo biểu mẫu"

### 1.4 Tab Lịch sử

- Danh sách: thời gian, chiều, người thực hiện, SL SAA, SL QL, khớp, lệch.
- **Tự làm mới ngay sau khi đối chiếu xong** (callback `history_refresh["fn"]`
  gọi lại `load_history()`, không cần F5).
- Mỗi dòng có: "Xem chi tiết" (mở/đóng bảng ngay tại chỗ, KHÔNG đụng state
  tab Kết quả), tải lại Excel Tổng hợp, tải lại Excel Chi tiết lệch, tải file
  dữ liệu gốc từng bên.
- **4 nút tải ở trên dùng dữ liệu SNAPSHOT đã lưu tại đúng thời điểm đối
  chiếu** — KHÔNG tính lại từ dữ liệu thô, đảm bảo tính audit (dù sau này
  logic đối chiếu đổi, dữ liệu lịch sử cũ vẫn giữ nguyên).

---

## 2. Lưu trữ / Audit (bảng `swift_recon_history` trong DB chung)

Không tạo file/folder riêng, không dùng Google Drive/đường dẫn local. Mỗi
lần đối chiếu lưu ĐỦ (dạng JSON, không phải `.xlsx`):

| Cột | Nội dung |
|---|---|
| `recon_type` | `"den"` / `"di"` |
| `file_saa_name`, `file_ql_name` | Tên file — **nếu nhiều file, nối bằng `"; "`** (ví dụ `"DEN_P1.xls; DEN_P2.xls"`) — TEXT column, không cần ALTER TABLE khi thêm multi-file |
| `total_saa`, `total_ql`, `total_matched`, `total_diff` | Số liệu tổng quan |
| `raw_a_json`, `raw_b_json` | Dữ liệu THÔ đã import của cả 2 bên (đã GỘP nếu nhiều file) |
| `merged_json` | Kết quả đối chiếu đầy đủ (khớp + lệch) |
| `summary_json` | Snapshot Excel Tổng hợp |
| `diff_a_only_json`, `diff_b_only_json` | Snapshot Excel Chi tiết lệch |
| `di_not_ack_json` | (điện đi) phần "khớp khoá chưa Ack" |

- Lỗi lưu lịch sử **KHÔNG được làm hỏng việc trả kết quả đối chiếu** — vẫn
  trả kết quả bình thường, kèm cảnh báo rõ ràng (`history_saved: false`,
  `history_error: "..."` trong response JSON, hiển thị `ui.notify` cảnh báo
  ở frontend).

---

## 3. MỚI — Xuất Excel "theo biểu mẫu" (Mẫu 04 / Mẫu 05)

File: `backend/services/swift_recon/template_exporters.py` + 4 file
`.xlsx` mẫu trong `templates/`.

### 3.1 Cơ chế chung

- Mở ĐÚNG file `.xlsx` mẫu người dùng cung cấp làm khung nền (giữ nguyên
  quốc hiệu, tiêu đề, ký tên, định dạng ô/merge) bằng `openpyxl`.
- Tự tìm dòng mốc (header, dòng "Tổng số lượng điện", dòng "Lập bảng"...)
  bằng cách quét nội dung cột, KHÔNG hard-code số dòng cố định — vì số dòng
  dữ liệu (số loại điện, số bản ghi lệch) thay đổi mỗi lần đối chiếu.
- Tự **thêm/bớt dòng dữ liệu** (`ws.insert_rows`/`delete_rows`) cho khớp số
  lượng thực tế, đồng thời copy style + merge-cell pattern từ dòng mẫu đầu
  tiên sang các dòng mới (không làm vỡ định dạng).
- Tự cập nhật các ô ngày tháng dạng `"ngày D tháng M năm YYYY"` về ngày hiện tại.
- Không sửa `reconcile.py`/`parsers.py` — chỉ gọi lại `reconcile.match_by_key()`.

### 3.2 Phân loại hệ thống nguồn (SWIFT / IPCAS / P-HUB)

Biểu mẫu yêu cầu tách bên "Quản lý điện" thành 3 cột con: SWIFT (=toàn bộ
bên SAA) / IPCAS / P-HUB.

**Đã XÁC NHẬN bằng dữ liệu thật** (file mẫu `MSG_IN_..._QL_DEN.xls` và
`MSG_OUT_..._QL_DI.xls`): file Quản lý điện có sẵn cột **`Channel Process`**
chứa thẳng giá trị `"IPCAS"` hoặc `"PMHUB"` (hiển thị là "P-HUB" trong biểu
mẫu; nếu gặp giá trị `"ARS"` thì gộp chung vào cột "P-HUB" vì biểu mẫu Tổng
hợp chỉ có 3 cột hệ thống).

`classify_system(source, seq_raw, channel_raw)`:
1. Nếu `source` bắt đầu bằng `"SAA"` → luôn `"SWIFT"`.
2. Nếu có `channel_raw` và nằm trong `{"SWIFT","IPCAS","PMHUB","P-HUB","ARS"}` → dùng THẲNG giá trị đó (đáng tin cậy nhất).
3. **Dự phòng** (chỉ khi không có cột channel — trường hợp file nào đó về sau
   không có cột này): đoán qua hoa văn chuỗi SaSeq (QL_DEN) / Msg Key (QL_DI)
   THÔ theo mẫu `<4 số chi nhánh><chữ cái><...>`: chữ `O`→IPCAS, chữ `S`→PMHUB,
   chữ `R`+chi nhánh `"0000"`→ARS, chữ `R` khác→PMHUB, không khớp mẫu→IPCAS.
   **Cách dự phòng này CHƯA được kiểm chứng bằng dữ liệu thật** — chỉ tồn tại
   để không crash nếu thiếu cột channel.

Tên cột tìm channel: `CHANNEL_COL_CANDIDATES = ["Channel Process", "Channel", "System", "Source System"]`, dò cả không phân biệt hoa/thường.

### 3.3 Tên cột thật đã xác nhận (`FIELD_CANDIDATES` trong `template_exporters.py`)

Dùng cho báo cáo "Chi tiết lệch theo biểu mẫu" (cột Số tham chiếu/Số
tiền/Loại tiền/Ngân hàng gửi phía Quản lý điện):

| | QL_DEN | QL_DI |
|---|---|---|
| Số tham chiếu | `RefNo` | `Refno` (chú ý khác hoa/thường so với QL_DEN — đã xử lý so khớp không phân biệt hoa/thường) |
| Số tiền | `Amount` | `Amount` |
| Loại tiền | `Curent` (đúng chính tả gốc trong file, không phải "Currency") | `Ccy` |
| Ngân hàng gửi | `Send Bic` | `Send Bic` |

Việc dò cột dùng danh sách candidate + so khớp không phân biệt hoa/thường
(`_first_present()`), để chịu được sai khác nhỏ về cách đặt tên cột giữa các
lần export từ hệ thống nguồn.

### 3.4 Cột "Chênh lệch" — CÙNG 1 công thức cho cả 2 kiểu Tổng hợp (xem mục 4)

---

## 4. Cách tính cột "Chênh lệch" trong báo cáo Tổng hợp — QUAN TRỌNG, đã sửa 2 lần

**Áp dụng cho CẢ 2 nút:** "Xuất Excel Tổng hợp" (thường) và "Xuất Excel Tổng
hợp theo biểu mẫu" — cả điện đến lẫn điện đi.

### 4.1 Công thức hiện tại (ĐÚNG, đã người dùng xác nhận)

Với **mỗi loại điện**, "Chênh lệch" = **số bản ghi THỰC SỰ KHÔNG KHỚP KHOÁ**
(tức là số bản ghi rơi vào `ONLY_A` + `ONLY_B` của loại điện đó, lấy từ
`reconcile.match_by_key(df_a, df_b)` — ĐÚNG cơ chế khoá dùng ở tab "Kết quả
đối chiếu" và file "Chi tiết lệch"). Dòng "TỔNG"/"Tổng chênh lệch..." =
**tổng CỘNG DỒN** (không trừ bù, không có số âm) của cột này.

Cài đặt tại:
- `backend/api/swift_recon.py::_key_match_summary()` — dùng cho "Xuất Excel Tổng hợp" thường.
- `backend/services/swift_recon/template_exporters.py::build_system_summary()` — dùng cho bản theo biểu mẫu.

### 4.2 Lịch sử thay đổi công thức (để hiểu TẠI SAO, tránh quay lại cách cũ)

1. **Bản đầu tiên** (kế thừa nguyên hàm có sẵn `reconcile.summarize_counts()`
   của module gốc): `Chênh lệch = count(A) − count(B)` theo từng loại điện —
   **hiệu SỐ LƯỢNG thô**, có thể ÂM, và tổng dòng "TỔNG" là tổng có dấu (số
   dương/âm bù trừ nhau).
2. **Sửa lần 1**: đổi sang trị tuyệt đối `|count(A) − count(B)|` ở từng dòng
   và ở tổng — để tổng không bị bù trừ dương/âm.
3. **Sửa lần 2 (hiện tại)**: nhận ra hiệu SỐ LƯỢNG — dù đã lấy trị tuyệt đối
   — vẫn có lỗ hổng nghiêm trọng: nếu 1 loại điện có SỐ LƯỢNG bằng nhau ở 2
   bên (ví dụ 5 và 5) nhưng đó là **5 giao dịch hoàn toàn khác nhau** (không
   cùng khoá), công thức số lượng vẫn báo "Chênh lệch = 0" — SAI, che giấu
   vấn đề thật. Đổi hẳn sang đếm theo **kết quả khớp khoá thật sự**
   (`match_by_key`), đúng bản chất "đối chiếu". Từ nay 2 báo cáo Tổng hợp và
   Chi tiết lệch LUÔN khớp nhau: tổng cột "Chênh lệch" ở Tổng hợp = đúng
   tổng số dòng liệt kê trong Chi tiết lệch.

**=> Khi sửa code sau này: TUYỆT ĐỐI không quay lại công thức hiệu số lượng
thô (`count_a - count_b`) cho cột "Chênh lệch", kể cả khi có vẻ "đơn giản
hơn" — đã bị bác bỏ vì lý do nghiệp vụ ở trên.**

---

## 5. Đa file import (SAA có thể xuất nhiều lần/ngày)

- Áp dụng cho CẢ 4 loại file: SAA điện đến, QL điện đến, QL điện đi, SAA điện đi.
- Cơ chế: mỗi file trong 1 ô upload được `parsers.load_file()` parse RIÊNG
  (giữ nguyên hàm parse gốc, không đổi), sau đó `pd.concat` toàn bộ kết quả
  thành 1 DataFrame trước khi đưa vào `reconcile`.
- **KHÔNG dedupe tự động** (xem lý do ở mục 1.1).
- Đã kiểm chứng bằng dữ liệu thật: 2 file SAA cùng ngày (999 + 200 dòng)
  không trùng khoá nhau (`overlap keys = 0`), gộp đúng thành 1199 dòng.
- Hàm liên quan: `backend/api/swift_recon.py::_load_many()`.

---

## 6. API endpoints (`backend/api/swift_recon.py`)

Tất cả yêu cầu `Depends(require_feature("menu.swift_recon"))` (admin bypass).

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/swift-recon/parse-preview` | Kiểm tra 1 file ngay khi chọn (✅/❌ + số dòng) |
| POST | `/api/swift-recon/reconcile-den` | Đối chiếu điện đến — nhận `saa_files[]`, `ql_files[]` (nhiều file, BẮT BUỘC) |
| POST | `/api/swift-recon/reconcile-di` | Đối chiếu điện đi — nhận `ql_files[]`, `saa_files[]` |
| POST | `/api/swift-recon/export-summary` | Xuất Excel Tổng hợp (thường) |
| POST | `/api/swift-recon/export-diff` | Xuất Excel Chi tiết lệch (thường) |
| POST | `/api/swift-recon/export-summary-template` | **MỚI** — Tổng hợp theo biểu mẫu |
| POST | `/api/swift-recon/export-diff-template` | **MỚI** — Chi tiết lệch theo biểu mẫu |
| POST | `/api/swift-recon/export-filtered` | Xuất đúng bản ghi đang lọc trên UI |
| GET | `/api/swift-recon/history` | Danh sách lịch sử |
| GET | `/api/swift-recon/history/{id}` | Chi tiết 1 lần đối chiếu (merged_records đầy đủ) |
| GET | `/api/swift-recon/history/{id}/export-summary` | Xuất lại Excel Tổng hợp TỪ SNAPSHOT |
| GET | `/api/swift-recon/history/{id}/export-diff` | Xuất lại Excel Chi tiết lệch TỪ SNAPSHOT |
| GET | `/api/swift-recon/history/{id}/export-raw?side=a\|b` | Tải dữ liệu thô đã import 1 bên TỪ SNAPSHOT |

4 endpoint xuất Excel (`export-summary`, `export-diff`, `export-summary-template`,
`export-diff-template`) nhận **CÙNG 1 bộ field name tuỳ chọn**:
`saa_den[]`, `ql_den[]`, `ql_di[]`, `saa_di[]` — chỉ cần điền đúng 1 cặp
tương ứng chiều đang xuất, cặp còn lại để trống.

---

## 7. Cạm bẫy kỹ thuật đã gặp — TRÁNH LẶP LẠI

1. **FastAPI 0.109.1** (bản đang pin trong `requirements.txt`) có bug: khai
   báo `list[UploadFile] | None = File(None)` (Optional list) sẽ báo lỗi 422
   `"Input should be a valid list"` nếu client chỉ gửi ĐÚNG 1 file cho field
   đó (không gửi 2+ file) — đây là trường hợp PHỔ BIẾN NHẤT thực tế. Bắt buộc
   dùng `list[UploadFile] = File(default_factory=list)` (KHÔNG dùng
   `Optional`/`None` làm mặc định) cho mọi field kiểu "nhiều file không bắt
   buộc". Field BẮT BUỘC (`File(...)`) không bị lỗi này.
2. **FastAPI + multipart form**: field scalar khác gửi kèm `UploadFile` PHẢI
   khai `= Form(...)`, không được để `str = "default"` — nếu không, FastAPI
   hiểu nhầm thành query param.
3. **NiceGUI**: `on_upload`/`on_click` gọi hàm `async def` có thao tác tạo UI
   bên trong (`ui.notify(...)`) — KHÔNG bọc `asyncio.create_task(...)`, gọi
   trực tiếp `on_upload=lambda e: async_fn(e, ...)`. Bọc `create_task` có thể
   gây lỗi "slot stack is empty".
4. **SQLite migration**: `CREATE TABLE IF NOT EXISTS` không tự thêm cột mới
   vào bảng đã tồn tại — đổi schema phải dùng `ALTER TABLE` thật.
5. **openpyxl `insert_rows`/`delete_rows` KHÔNG dịch đúng vùng gộp ô (merge)**
   — đây là lỗi đã tự kiểm chứng trực tiếp (không phải suy đoán): 2 hàm này
   dịch chuyển ĐÚNG nội dung ô (value) nằm dưới điểm chèn/xoá, nhưng KHÔNG
   dịch chuyển toạ độ các vùng gộp tương ứng — merge đứng yên ở toạ độ CŨ dù
   nội dung đã "trôi" đến vị trí mới. Từng gây lỗi thật: dòng chữ ký cuối
   biểu mẫu "Tổng hợp" bị mất/lệch sau khi tối ưu tốc độ (xem mục 9.2).
   PHẢI tự gọi `_shift_merges()` (trong `template_exporters.py`) ngay sau
   MỌI lần `insert_rows`/`delete_rows` để bù lại — không có cách nào khác an
   toàn hơn ngoài tự dịch tay.
6. Style copy sang dòng mới chèn KHÔNG tự động — phải tự làm
   (`_capture_row_style`/`_apply_row_style`), và nên GÁN THẲNG mảng chỉ số
   `cell._style` đã có sẵn từ dòng mẫu thay vì đi qua `cell.font = ...` (rất
   chậm khi lặp lại hàng nghìn lần — xem mục 9.1).
7. **Tên cột file nguồn có thể khác hoa/thường** giữa các lần export khác
   nhau của cùng hệ thống (ví dụ `RefNo` ở QL_DEN nhưng `Refno` ở QL_DI) —
   luôn so khớp tên cột không phân biệt hoa/thường khi dò cột động.
8. PowerShell không tự chạy file `.bat` trong thư mục hiện tại nếu chỉ gõ tên
   suông — cần `.\ten_file.bat`.
9. **Endpoint FastAPI trong backend TTTT phải khai `def`, KHÔNG `async def`**
   trừ khi thực sự có `await` một I/O bất đồng bộ thật bên trong. Backend
   chạy 1 tiến trình/1 luồng (uvicorn không kèm `--workers`); nếu khai
   `async def` mà bên trong chạy code chặn (đọc file, `openpyxl`...), request
   đó chạy THẲNG trên event loop duy nhất, đóng băng TOÀN BỘ hệ thống (mọi
   trang khác) trong lúc xử lý — đã đo được 10-12 giây/lần trước khi sửa.
   Khai `def` để FastAPI tự đẩy sang thread pool phụ.
10. **Không để bộ nhớ phiên (session state) trong NiceGUI cộng dồn không giới
    hạn** — tiến trình NiceGUI (cổng 8080) phục vụ CHUNG mọi trang khác
    (dashboard, nghỉ phép...), không riêng 1 tính năng. Danh sách file/bản
    ghi giữ trong `state` phải có trần rõ ràng (xem `MAX_FILES_PER_SLOT`/
    `MAX_TOTAL_BYTES_PER_SLOT` trong `frontend/pages/swift_recon.py`).

---

## 8. Checklist kiểm thử đầy đủ (dùng lại mỗi khi sửa code)

- [ ] Nạp **nhiều file** vào 1 ô upload (SAA đến) → mỗi file có dòng ✅/❌
      riêng, dòng tổng đúng số file + tổng dòng, nút ✕ xoá được từng file.
- [ ] Nạp file lỗi (sai định dạng) → hiện ❌ kèm lý do, KHÔNG được tính vào
      lúc đối chiếu, không chặn các file hợp lệ khác.
- [ ] Đối chiếu điện đến + điện đi với dữ liệu thật → tự chuyển đúng tab kết quả.
- [ ] Tab Kết quả: lọc theo Trạng thái + Loại điện (AND), chọn/bỏ chọn tất
      cả, nút Bỏ lọc, hiệu ứng ⏳→✅, header sticky khi cuộn.
- [ ] Bấm đủ 5 nút xuất Excel mỗi tab — không lỗi, file tải về mở được.
- [ ] File "Tổng hợp theo biểu mẫu": giữ nguyên định dạng/quốc hiệu, cột
      IPCAS/P-HUB đúng số liệu thật (đối chiếu bằng cột `Channel Process`
      trong file QL gốc).
- [ ] **Tổng cột "Chênh lệch" ở file Tổng hợp = đúng tổng số dòng trong file
      Chi tiết lệch tương ứng** (kiểm tra bắt buộc sau mỗi lần sửa công thức).
- [ ] Tab Lịch sử: tự làm mới sau khi đối chiếu xong (không cần F5); "Xem
      chi tiết" mở/đóng đúng dòng, không đụng tab Kết quả; 4 nút tải dùng
      đúng snapshot cũ (không đổi dù sửa logic đối chiếu sau này).
- [ ] Tắt DB tạm thời (giả lập lỗi lưu lịch sử) → vẫn trả kết quả đối chiếu
      bình thường, có cảnh báo rõ ràng, không crash toàn bộ request.
- [ ] **File "theo biểu mẫu" xuất ra phải còn ĐỦ dòng chữ ký cuối trang**
      ("Lập bảng"/"Kiểm soát" + 2 dòng "(Ký và ghi rõ họ tên)") — kiểm tra
      bắt buộc sau MỌI lần đụng vào `_ensure_data_rows`/`_shift_merges`
      trong `template_exporters.py` (từng có lỗi mất dòng này — xem mục 9.2).
- [ ] Xuất "Chi tiết lệch theo biểu mẫu" với dữ liệu lệch NHIỀU (~1000+ dòng)
      → phải xong trong vài giây, không phải hàng chục giây (kiểm tra hồi quy
      hiệu năng — xem mục 9.1).
- [ ] Trong lúc 1 người đang bấm xuất Excel theo biểu mẫu, thử mở 1 trang
      KHÁC (không liên quan Swift) ở tab/trình duyệt khác → phải vẫn dùng
      được bình thường, không bị treo theo.
- [ ] Nạp vượt quá 10 file hoặc tổng >100MB vào 1 ô upload → bị chặn ngay,
      có thông báo rõ lý do, không thêm được vào danh sách.

---

## 9. MỚI — Sửa theo review hiệu năng trên PR #13 (đọc kỹ trước khi đụng vào `_ensure_data_rows`/endpoint nào)

Sau khi PR #13 được đăng, reviewer (Tech Lead) để lại review chỉ ra 2 vấn đề
hiệu năng/tài nguyên thật — cả 2 đã tự đo lại và xác nhận đúng trước khi sửa.

### 9.1 🔴 Backend đóng băng 10-12s/lần xuất "theo biểu mẫu" — ĐÃ SỬA

**Nguyên nhân 1 — sai kiểu endpoint:** toàn bộ endpoint trong
`backend/api/swift_recon.py` khai `async def` nhưng bên trong toàn code
CHẶN (`pd.read_excel`, `load_workbook`, `wb.save`...), không có `await` nào
thật sự. Backend chạy 1 tiến trình/1 luồng (`run.py` khởi động uvicorn
không kèm `--workers`) — `async def` chạy thẳng trên event loop DUY NHẤT
phục vụ TOÀN BỘ hệ thống, nên request nặng của 1 người làm ĐÓNG BĂNG mọi
trang khác của mọi người khác trong lúc xử lý.
**Sửa:** đổi tất cả 13 endpoint từ `async def` → `def` (xem mục 7.9).
`get_db()` đã tạo connection mới mỗi request với `check_same_thread=False`
nên an toàn khi chạy trong thread pool, không cần sửa gì thêm ở đó.

**Nguyên nhân 2 — file mẫu .xlsx quá nặng:** 4 file mẫu ban đầu còn giữ
nguyên dữ liệu MẪU THẬT (2612/1279 dòng + hàng nghìn vùng gộp ô) từ file
người dùng gửi — `load_workbook()` một file như vậy mất 10-12 giây MỖI LẦN
gọi, dù chỉ cần đúng 1 dòng làm khuôn.
**Sửa:** cắt gọn cả 4 file về đúng khung (header + 1 dòng mẫu + footer) —
xem script build lại 4 file này (chạy 1 lần, không phải code chạy lúc
runtime) dùng chung logic `_shift_merges()` với mục 9.2 bên dưới.

**Nguyên nhân 3 — chi phí per-row khi số bản ghi lệch lớn:** sau khi sửa 2
điểm trên, xuất báo cáo có NHIỀU bản ghi lệch (ví dụ >1000 dòng) vẫn chậm
(~46 giây), do cách `openpyxl` xử lý style + vùng gộp ô rất tốn khi lặp lại
hàng nghìn lần:
- `ws.merge_cells()` mặc định làm kiểm tra chồng lấn (overlap check) quét
  TOÀN BỘ vùng gộp đã có mỗi lần gọi → O(n²) khi gọi hàng nghìn lần.
- `cell.font = ...`/`cell.border = ...` mỗi lần gán phải băm (hash) + so
  sánh TOÀN BỘ nội dung style để gộp trùng vào bảng style dùng chung — tốn
  dù style hệt nhau.
- Dựng lại đường viền (border) cho vùng gộp (`MergedCellRange.format()`) —
  tốn tương tự nếu gọi lại cho MỌI dòng thay vì học 1 lần rồi tái dùng.

**Sửa (trong `template_exporters.py`):**
- `_fast_merge()` — thêm merge trực tiếp vào `ws.merged_cells.ranges` (set),
  bỏ qua bước kiểm tra chồng lấn chậm của `ws.merge_cells()`. AN TOÀN vì các
  vùng gộp ở đây luôn nằm trong đúng 1 dòng, các dòng không bao giờ chồng
  lấn nhau.
- `_capture_row_style()`/`_apply_row_style()` — lấy `cell._style` (mảng CHỈ
  SỐ style đã gộp trùng sẵn từ lúc mở file) của dòng mẫu ĐÚNG 1 LẦN, gán
  THẲNG mảng đó cho ô mới — không đi qua `cell.font = ...` (tránh băm/so
  sánh lặp lại).
- `_register_merge_no_format()` — xử lý ĐẦY ĐỦ (kể cả dựng viền) cho DÒNG
  ĐẦU TIÊN chèn thêm, "học" lại style kết quả, rồi TÁI DÙNG cho mọi dòng
  sau — không gọi lại bước dựng viền (chậm nhất) cho từng dòng.

Kết quả đo lại (dữ liệu thật, 1349-1673 dòng lệch tuỳ file):
| Thao tác | Trước | Sau |
|---|---|---|
| Mở file mẫu `chitiet_den.xlsx` | 12,13s | 0,06s |
| Xuất Chi tiết lệch theo biểu mẫu (~1350-1670 dòng lệch) | ~46s | 1,7-2,5s |
| Xuất Tổng hợp theo biểu mẫu | 0,26s | 0,1-0,3s |

### 9.2 🐞 Lỗi hồi quy do chính việc sửa 9.1 gây ra — ĐÃ SỬA: dòng chữ ký bị mất

Sau khi tối ưu theo 10.1, phát hiện (qua chính người dùng test) file "Tổng
hợp theo biểu mẫu" xuất ra **mất hẳn dòng "(Ký và ghi rõ họ tên)"** ở cuối.

**Nguyên nhân (đã tự viết test kiểm chứng trực tiếp, không suy đoán):**
`ws.insert_rows()`/`ws.delete_rows()` của `openpyxl` dịch chuyển ĐÚNG nội
dung Ô (value) nằm dưới điểm chèn/xoá, nhưng **KHÔNG dịch chuyển toạ độ các
VÙNG GỘP Ô (merge) tương ứng** — vùng gộp đứng yên ở toạ độ CŨ dù nội dung
đã "trôi" đến vị trí mới. Dòng chữ ký nằm trong 1 vùng gộp nên bị lộ đúng
lỗi này: chữ text dịch đúng chỗ, nhưng khung gộp bọc quanh nó thì không,
khiến hiển thị sai/mất.

**Sửa:** thêm hàm `_shift_merges(ws, from_row, delta)` trong
`template_exporters.py` — TỰ dịch toạ độ mọi vùng gộp có `min_row >=
from_row` thêm `delta` dòng, gọi NGAY sau MỌI lần `insert_rows`/
`delete_rows` (cả trong `_ensure_data_rows()` lúc chạy thật, LẪN trong
script build lại 4 file mẫu — đã build lại cả 4 file từ đúng bản GỐC người
dùng gửi, không dựa trên bản đã lỡ hỏng trước đó).

**Bài học rút ra — áp dụng cho MỌI lần sửa code sau này liên quan
`openpyxl`:** không bao giờ tin `insert_rows`/`delete_rows` tự xử lý đúng
TOÀN BỘ cấu trúc sheet (kể cả khi tài liệu/StackOverflow nói là "đã hỗ trợ
merged cells") — PHẢI tự kiểm tra bằng cách viết 1 đoạn test nhỏ in ra toạ
độ merge THẬT SỰ sau khi gọi, so với toạ độ mong đợi, trước khi tin tưởng.

### 9.3 🟠 Bộ nhớ phiên không giới hạn trên — ĐÃ SỬA (1 phần)

Trước bản sửa này, danh sách file mỗi ô upload (`a_files`/`b_files` trong
`state`) cộng dồn KHÔNG giới hạn số lượng hay tổng dung lượng — chỉ chặn
từng file riêng lẻ ≤20MB. Vì `state` sống trong tiến trình NiceGUI (cổng
8080) — CHUNG cho mọi trang khác (dashboard, nghỉ phép, bàn giao chứng
từ...) — 1 phiên giữ vài trăm MB có thể làm chậm/crash cả hệ thống, không
riêng người đang dùng màn hình Swift.

**Sửa:** chặn ngay tại `_on_file_upload` (frontend) — `MAX_FILES_PER_SLOT =
10`, `MAX_TOTAL_BYTES_PER_SLOT = 100MB` mỗi ô, báo rõ lý do khi vượt, không
thêm được file vào state nếu vượt trần.

**CHƯA làm** (đề xuất phụ, có điều kiện, của reviewer): giải phóng
`a_files`/`b_files` ngay sau khi đối chiếu xong hoặc khi rời tab — quyết
định KHÔNG làm vì sẽ phá UX hiện tại (4/5 nút xuất Excel cần gửi lại đúng
những file đã upload). Nếu sau này đổi ý theo hướng này, cần thiết kế lại:
cache file ở phía SERVER (không phải giữ nguyên bytes ở session frontend)
để không bắt người dùng chọn lại file mỗi lần xuất.

---

## 10. Việc CHƯA hoàn thiện / cần xác nhận thêm

- Công thức tính dòng "Tổng chênh lệch" tổng quát đã đổi sang key-match nên
  không còn phụ thuộc giả định cũ — coi như đã chốt, không còn caveat treo.
- Nếu sau này có thêm giá trị `Channel Process` mới ngoài
  `SWIFT/IPCAS/PMHUB/ARS`, cần thêm vào `_KNOWN_SYSTEM_VALUES` trong
  `template_exporters.py`, nếu không sẽ rơi về nhánh dự phòng (đoán qua hoa
  văn — chưa kiểm chứng).
