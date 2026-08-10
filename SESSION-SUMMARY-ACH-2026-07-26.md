# Session Summary — Module Chấm ACH (thay thế bản 2026-07-24)
**Ngày:** 2026-07-26 · **Trạng thái:** Milestone A→E đã VERIFY PASS. Chỉ còn 2 Business Rule
chờ Business Owner quyết định (mục 3) — không còn việc kỹ thuật nào có thể tự làm tiếp.

---

## 1. Milestone đã hoàn thành

| Milestone | Nội dung | Trạng thái |
|---|---|---|
| Chốt Rule mới SESSION=NULL | Thay khung giờ `[23h T-1, 23h T)` bằng tra GW gốc; xác minh case thật 22/07; commit `523608b` | ✅ VERIFY PASS 2026-07-25 |
| Milestone B | Checkpoint xác nhận thủ công: wiring Engine → API → Frontend; commit `23ee580` | ✅ VERIFY PASS — UI click-through thật chưa làm (không phải blocker, verify khi chạy dữ liệu thật) |
| Milestone C | Review "chọn thư mục server" (13 test) + fix `KEY_DEN`/`KEY_DEN_HUB` chiều MIS_đến (19 test) + sửa 1 bug crash GL02 rỗng; commit `1f5bf59` | ✅ VERIFY PASS 2026-07-26 |
| Milestone D | Chứng minh C.1a case 07/07 (3 nhóm lệch cũ) là hệ quả ĐÚNG của Rule mới, xác nhận bằng GW gốc thật; commit `bd9db45` | ✅ VERIFY PASS 2026-07-26 — **C.1a coi là hoàn thành** |
| Milestone E | Verify `KEY_DEN`/`KEY_DEN_HUB` bằng dữ liệu MIS_đến thật (12/07) — bất biến đúng, spot-check khớp 100% giữa GL02 và MIS_đến độc lập | ✅ VERIFY PASS 2026-07-26 |

ACH suite hiện tại: **106 test PASS** (`test_ach_algorithm.py`, `test_ach_gw_reading.py`,
`test_ach_excel_export.py`, `test_ach_checkpoint_api.py`, `test_ach_gl02_misden_algorithm.py`,
`test_ach_folder_mode.py`). Toàn bộ code liên quan đã commit qua 6 commit (`523608b` →
`d88c75a` → `23ee580` → `1f5bf59` → `bd9db45` → tài liệu Milestone E), không còn phần nào của
module ACH đang uncommitted (trừ mảng cố ý ngoài phạm vi — folder-mode đã review ở Milestone C).

Nền tảng trước đó (đã hoàn thành ở các phiên cũ hơn, vẫn đứng vững): BR-ACH-001 (C.1+C.2 —
nhóm CN_TIỀN + MSGREF, không cumcount), "Nguồn 1" đã gỡ hẳn, C.1a (GW-thừa) đã wiring vào
Excel, Checkpoint engine (Bước 1-3) code+verify từ 2026-07-24.

## 2. Business Rule đã CHÍNH THỨC CHỐT (không được tự ý thay đổi)

1. **BR-ACH-001** (`khop_voi_gw()`): xác định nhóm CN_TIỀN chênh lệch bằng so COUNT
   (không cumcount) → phân loại từng dòng TPAY trong nhóm đó bằng MSGREF (không PrcFlg).
2. **"Nguồn 1" (CALD/ERPO/TPER + khung giờ)**: đã gỡ hẳn, cấm khôi phục dưới mọi hình thức.
3. **Rule mới SESSION=NULL**: tra SessionId thật trên GW gốc thay khung giờ — **mặc định
   chính thức** từ 2026-07-25. "Khác session" (tìm thấy MSGREF nhưng SessionId khác phiên
   đối chiếu) → loại khỏi lần chạy này, không đưa vào Checkpoint, không tạo nhánh xử lý mới.
4. **Checkpoint xác nhận thủ công**: máy xử lý tối đa, người chỉ xác nhận nhánh Timeout;
   kiến trúc "chạy lại toàn bộ" cho lần chạy 2 (không resume state); không cần audit trail;
   **luôn bật mặc định** cho mọi lần chạy mới (cả mode upload lẫn mode thư mục server),
   không có toggle bỏ qua — chốt 2026-07-26.
5. **SO_TRACE** = 12 ký tự từ vị trí thứ 8 của REFERENCE, lstrip số 0 (giữ `'0'` nếu toàn số 0).
6. **KEY_DI/KEY_DEN/KEY_DEN_HUB**: ghép đủ 3 phần chi nhánh + SO_TRACE(hoặc TRACE) + số tiền.
7. **Filter `CUSTOMER='1000-003526275'`** ở `b2_xu_ly_gl02.py`: đây là tài khoản trung gian
   ACH — GL02 chứa dữ liệu của nhiều hệ thống thanh toán khác nhau (ACH, MDP...), điều kiện
   này dùng để NHẬN DIỆN đúng dữ liệu thuộc ACH giữa GL02 gộp chung. Không phải hardcode —
   **không được refactor hoặc loại bỏ**.

## 3. Business Rule còn TREO (cần quyết định trước khi coi liên quan là "xong")

| # | Nội dung | Ghi chú |
|---|---|---|
| 1 | Nhánh `NGAY_GIA_TRI_KHAC_T_VA_T-1` (SESSION=NULL, ngày giao dịch khác cả T và T-1) | Đang "giữ tạm", chưa có quy tắc chính thức — chưa từng phát sinh trên dữ liệu thật đã verify (17-21/07, 22/07, 07-09/07) |
| 2 | Case MSGREF rỗng tại ngày T-1 (7 giao dịch, phát hiện 17/07) | Đã ghi nhận 2026-07-23, chưa hỏi riêng |

## 3b. Verify còn lại / Backlog Verify

**KHÔNG CÒN HẠNG MỤC NÀO MỞ.** Cả 2 mục từng nằm ở đây đã đóng:

- **C.1a (GW-thừa) — HOÀN THÀNH (Milestone D, 2026-07-26).** Re-verify case 07/07 trên code
  hiện tại cho 0 nhóm lệch (trước đây 3 nhóm). Đã chứng minh bằng GW gốc thật: cả 3 giao dịch
  của 3 nhóm cũ thực sự đã đi kênh đúng phiên đối chiếu (SessionId=16302, PrcFlg="Lệnh Hoàn
  thành") — Rule cũ bỏ sót chỉ vì lệch vài giây quanh mốc khung giờ 23h, Rule mới tra GW gốc
  phục hồi đúng. Xác nhận không phát sinh lệch mới ở 07/07 hay 2 ngày lân cận (08/07, 09/07).
  Chi tiết: Implementation-notes.html mục 48.
- **`KEY_DEN`/`KEY_DEN_HUB` — HOÀN THÀNH (Milestone E, 2026-07-26).** Dữ liệu MIS_đến thật hoá
  ra đã có sẵn trong repo (không cần chờ cung cấp thêm) — chạy thật B2+B6+B7 trên 12/07: bất
  biến số học đúng cả 2 chiều, spot-check 1 cặp khớp cho thấy chi nhánh/số tiền/SO_TRACE khớp
  tuyệt đối giữa 2 nguồn dữ liệu độc lập (GL02 lõi ngân hàng vs MIS_đến kênh). Chi tiết:
  Implementation-notes.html mục 49.

## 4. Việc còn lại của toàn dự án ACH

- **Cố ý ngoài phạm vi kỹ thuật**: 2 mục Business Rule còn treo ở phần 3 — cần quyết định của
  Business Owner, không phải việc code.
- **UI Checkpoint**: chưa có ai click-through thật trên browser (thiếu credential admin
  thật trong môi trường dev của Claude) — theo xác nhận của Business Owner, sẽ verify khi
  chạy dữ liệu thật, không phải việc cần chủ động làm thêm.
- **Backlog kỹ thuật đã ghi nhận, chưa xử lý** (không khẩn cấp, không ảnh hưởng số liệu hiện tại):
  - `_tim_ngay_tu_pdf()` chọn sai ngày khi 1 thư mục có nhiều PDF (gửi lại kênh nhiều lần).
  - `xuat_excel_xac_nhan()` chưa áp `CSV_THRESHOLD` cho sheet `MIS_DI_CHUAN` (file xác nhận
    có thể rất nặng — đã thấy 72MB/562K dòng).
  - Module "đối chiếu tuyệt đối theo MSGREF" (Reconciliation độc lập, tách khỏi C.1/C.2) —
    mới chỉ có trong backlog ý tưởng, chưa thiết kế.
- **Dọn dẹp**: các thư mục `_scratch_verify_*` (167, 1112, 22_07, dien_rong, session_null_br)
  đang giữ lại làm tư liệu theo yêu cầu trước đây — nhắc dọn khi dự án ACH hoàn thành hẳn.

---

## 5. Roadmap còn lại (Milestone D, E đã xong — xem mục 1)

- **Milestone F — Quyết định 2 nhánh mở SESSION=NULL**: `NGAY_GIA_TRI_KHAC_T_VA_T-1` và
  MSGREF rỗng T-1 — **cần Business Owner quyết định quy tắc**, không phải việc kỹ thuật; chưa
  từng phát sinh trên dữ liệu thật đã verify nên không khẩn cấp.
- **Milestone G — Test UI Checkpoint bằng dữ liệu thật**: theo đúng ý Business Owner
  ("verify khi chạy dữ liệu thật"), không cần chủ động đặt lịch riêng.
- **Milestone H (dài hạn, không gấp, không tạo mới hôm nay)**: sửa bug `_tim_ngay_tu_pdf()`;
  áp `CSV_THRESHOLD` cho `MIS_DI_CHUAN`; thiết kế module đối chiếu tuyệt đối theo MSGREF.

## 6. Chờ lệnh

**STATUS: KHÔNG CÒN VIỆC KỸ THUẬT NÀO CÓ THỂ TỰ LÀM TIẾP.** Toàn bộ hạng mục kỹ thuật đã có
thể tự thực hiện (Milestone A→E) đã xong và VERIFY PASS. Việc còn lại (Milestone F) cần
Business Owner quyết định quy tắc cho 2 nhánh mở SESSION=NULL; Milestone G chờ tự nhiên khi
chạy dữ liệu thật; Milestone H là backlog dài hạn không khẩn cấp. Dự án ACH ở trạng thái sẵn
sàng nghiệm thu cho toàn bộ phần đã chốt Business Rule.
