# Việc cần làm — sổ ghi nhớ

> Cập nhật: **2026-08-10**. Đọc được từ điện thoại qua phiên cloud.
> Xong việc nào thì gạch việc đó; phát sinh việc mới thì thêm vào đúng mục.
> Bối cảnh nghiệp vụ xem [BOI-CANH-DU-AN.md](BOI-CANH-DU-AN.md).

---

## 🔴 Ưu tiên 1 — hai lỗi thật, dễ thất lạc nhất

| # | Lỗi | Hậu quả | Cách sửa |
|---|---|---|---|
| **1** | **`menu.cham_ach` chưa khai báo** trong `backend/core/features.py` → `require_feature` tra bảng `group_features` không thấy | **Người chấm thật bị 403, chỉ admin dùng được ACH.** Bạn không gặp vì đang đăng nhập admin | Thêm `menu.cham_ach` + `cham_ach.process` vào nhóm Phòng Thanh toán, **kèm migration** `UPDATE group_features SET feature_code='menu.cham_ach' WHERE feature_code='menu.doi_chieu_ach'` để nhóm đang có quyền ACH cũ không mất menu sau merge |
| **2** | **`requirements.txt` trên `develop` thiếu `pdfplumber`** | ACH không tự nhận được ngày đối chiếu từ file PDF | Bổ sung vào `requirements.txt` trong cùng PR ACH |

## 🟠 Ưu tiên 2 — việc đang dở giữa chừng

| # | Việc | Trạng thái | Ai làm bước tiếp |
|---|---|---|---|
| 3 | **Tách module ACH thành PR riêng vào `develop`** — worktree `e:\Clause code\TTTT-ach`, nhánh `ach-module`. PR #19 (4 module gộp) **bạn đã chủ động đóng** 10/08 03:05Z để đi đường này. Toàn bộ ACH mới **chưa từng vào `develop`** (4.327 dòng thêm, 0 xoá). | ⚠️ **Đang lỗi nửa chừng:** `backend/api/registry.py` dòng 33 đã đổi sang `ach_router` nhưng **dòng 64 vẫn `doi_chieu_ach_router`** → backend không khởi động được | **Bạn báo "xong module ACH"** → phiên đó làm tiếp. Sửa dòng 64 trước tiên |
| 4 | **Chưa push `origin`.** Local lệch `origin/Cham_ILO1000` 1/9 commit (9 commit kia là Phân lịch trực), 12 file trùng việc đang sửa dở | Chờ bạn đồng ý | Tôi — **`git merge`, KHÔNG `rebase`** (rebase làm hỏng nhánh đã push lên `personal`) |
| 5 | **Gõ `/web-setup`** trong ô chat để bật `claude --cloud` (làm việc từ điện thoại) | Chưa làm | **Bạn** — lệnh của CLI, tôi không gọi thay được |

> **Quy ước đã chốt, đừng hỏi lại:** từ nay **1 module hoàn tất = 1 nhánh = 1 PR**, cắt từ
> `origin/develop`, dùng `git worktree` (cây chính luôn có file dirty của cửa sổ khác).
> Module ACH cũ `doi_chieu_ach` **thay thế hẳn**. Lịch sử **gộp 1 commit sạch**.
> Tài liệu kèm PR **chỉ** `Quy_trinh_nghiep_vu_Module_ACH_v2.docx`.

---

## Module ACH

### Cần người chấm xem
| # | Việc | Ghi chú |
|---|---|---|
| 4 | `SESSION_NULL_BI_LOAI` ngày **04/08 có 445 dòng**, ngày **05/08 chỉ 23 dòng** — chênh ~19 lần giữa 2 ngày liền kề, **chưa ai giải thích** | Kết quả chạy 2026-08-10 |
| 5 | Sheet `TIMEOUT_KHONG_KENH` hai ngày 04–05/08 cần người chấm đối chiếu | 04/08: 6 món / 11.679.000 · 05/08: 11 món / 21.177.000 |

### Còn treo
| # | Việc | Trạng thái |
|---|---|---|
| 6 | **2 file T-2 chép vào thư mục `05.08`** chưa dọn: `MIS_DI_THUA_20260804.csv`, `MIS_DEN_THUA_20260804.csv` | Bạn chưa nói dọn hay giữ |
| 7 | **Card 68 + 69** trong `Implementation-notes.html` đã viết, **cố ý chưa commit** | Chờ bạn quyết |
| 8 | `Implementation-notes.html` đã dựng lại đủ **111 card**, **chưa commit** | Đã gỡ nguy cơ xoá nhầm 41 card của đồng nghiệp |
| 9 | Lỗi **"đọc tiếng Việt"** khi chạy chương trình | Chờ bạn báo **nguyên văn** lỗi — đừng đoán là lỗi cũ `4cad7bc` |
| 10 | Checklist **UI test "REFHUB bổ sung tra ngày khác"** — 2 case bắt buộc click-through UI thật | Chưa làm |
| 11 | **Checkpoint UX** (popup, đếm giao dịch, auto-copy) — code + test 122/122 đạt nhưng **chưa click-through UI thật** | Chưa xác nhận trực quan |
| 12 | Xoá thư mục `_scratch_verify_167/` | Giữ làm tư liệu, **xoá khi dự án ACH hoàn thành** |

### Backlog — đã hoãn, không tự ý làm
| # | Việc | Quyết định |
|---|---|---|
| 13 | Module Reconciliation độc lập đối chiếu tuyệt đối theo **MSGREF** (MATCH / Chỉ-MIS / Chỉ-GW) | Chỉ làm **sau** khi xong toàn bộ Requirement hiện tại |
| 14 | **GL02 / MIS_đến tuỳ chọn** khi thiếu file (bảng tầng phụ thuộc) | Hoãn 2026-08-03, phương án đã lưu sẵn |

---

## Module ILO1000

| # | Việc | Trạng thái |
|---|---|---|
| 15 | 🔴 **Test đang HỎNG:** `test_ilo1000_algorithm.py::TestExportTongHop::test_tong_hop_so_mon_so_tien` — sheet TONG_HOP ra `('Hub', None, None, None)`, đáng lẽ `('Hub', 2, …, 1.500.000)` | Phát hiện 2026-08-10; 489 test còn lại đạt |
| 16 | **2 bộ golden sample tháng 7/2026** (4–6.7 và 11–13.7) — **chưa cân khớp cả hai** | Không dùng lại dữ liệu tháng 5/2026 |
| 17 | 10 file đang sửa dở chưa commit — **chưa rõ nội dung đang sửa gì** | Cần bạn nói rõ trước khi ai đó đụng vào |

---

## Module Chấm 459901

| # | Việc | Trạng thái |
|---|---|---|
| 18 | Tính năng **ghép file "tồn tháng trước"** (`459_TON_Tx.xlsx`) vào GL02 tháng hiện tại — đã có `classify_upload_filename()` loại `'ton'`, `_read_ton_file()`, `_TON_COLS` | **Chưa rõ đã xong hay còn dở** — phải hỏi, không tự đoán |
| 19 | 3 tháng (5, 6, 7) đã đối chiếu với bản chấm tay — **chờ phản hồi người chấm** | 97–99% khớp |

---

## Module Phân lịch trực

| # | Việc | Trạng thái |
|---|---|---|
| 20 | PR **#24, #26, #28 đều đã MERGE** ngày 2026-08-10; data test đã dọn, worktree đã gỡ | Có vẻ đã xong — **xác nhận lại** xem còn tồn gì không |

---

## Trạng thái nhánh (kiểm tra 2026-08-10)

| Nhánh / PR | Tình trạng |
|---|---|
| `develop` | Đã nhận **duty** (PR #26) và **CITAD** (PR #25) |
| `Cham_ILO1000` | Còn **40 commit chưa vào `develop`** — ACH + ILO1000 + 459901. Giữ nguyên làm lịch sử chi tiết |
| PR #19 | **CLOSED, không merge** — bạn chủ động đóng để tách theo module |
| PR #22 `chamcong/chamcongpkt` | Đang mở, không phải việc của bạn |
| Nhánh `ach-module` (worktree `TTTT-ach`) | Chưa commit gì, đang lỗi nửa chừng — xem mục 3 |

---

## Hạ tầng / repo

| # | Việc | Ghi chú |
|---|---|---|
| 21 | ⚠️ Repo **`personal` đang PUBLIC** — toàn bộ code TTTT-Agribank công khai. `README.md` ghi mật khẩu mặc định `admin / Admin@2024!` | Bạn đã cân nhắc và quyết giữ Public. Việc **đổi mật khẩu mặc định trong README** vẫn nên làm riêng |
| 22 | Phiên cloud gói Pro/Max chỉ có **Private / Public** — không có mức "chỉ nhóm" | **Giữ Private, đừng bật share** |
| 23 | 1 thẻ `</div>` thừa cuối `Implementation-notes.html` — có sẵn trong bản đã commit, dấu vết merge cũ | Trình duyệt tự bỏ qua, ưu tiên thấp |
| 24 | Skill `doi-chieu` tồn tại 2 bản (`~/.claude/commands/` và `.claude/commands/`) — có thể lệch theo thời gian | Chấp nhận; nhớ sửa cả hai khi cập nhật |

---

## Nguyên tắc đang áp dụng

- **Lập kế hoạch xong, được duyệt, rồi mới code** (2026-08-10). Đang làm mà gặp tình huống ngoài
  kế hoạch → dừng, báo, lập lại kế hoạch.
- Nhiều cửa sổ Claude Code chạy song song cùng thư mục → **luôn `git fetch` trước**, không
  `git add -A`, không `git stash`, kiểm tra file dirty ngoài phạm vi trước khi merge/checkout.
- Báo cáo đối chiếu chỉ có **2 trạng thái**: "Đã cân khớp" / "Chưa cân khớp cần hoàn thiện".
