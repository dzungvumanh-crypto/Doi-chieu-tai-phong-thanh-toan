# Tóm tắt phiên ACH 2026-08-07 — mở phiên mới đọc file này trước

## Trạng thái: TẤT CẢ VIỆC KỸ THUẬT ĐÃ XONG, ĐÃ COMMIT + PUSH + VÀO PR

- **Commit:** `3cfa612` — `feat(ach): báo cáo KẾT QUẢ MIS thừa T-2 + viết lại TONG_KET theo mẫu nghiệp vụ`
- **Push:** cả 2 remote — `origin` (khanhbq693/TTTT) và `personal` (dzungvumanh-crypto/Doi-chieu-tai-phong-thanh-toan)
- **PR:** #19 (`Cham_ILO1000` → `develop`) — **MERGEABLE / CLEAN**, 30 commit, đã có comment mô tả phần bổ sung hôm nay.
  https://github.com/khanhbq693/TTTT/pull/19
- **Test:** 420 passed. 1 fail `test_ilo1000_algorithm.py::TestExportTongHop::test_tong_hop_so_mon_so_tien`
  — **có sẵn từ trước, KHÔNG liên quan ACH**, đừng mất thời gian điều tra.

## Việc CÒN NỢ duy nhất (user dặn nhắc lại)

**Bổ sung mục mới vào `Implementation-notes.html`** cho đợt cập nhật này (CLAUDE.md yêu cầu bắt buộc).
Hoãn vì file đang bị sửa dở rất nhiều bởi **việc khác** (diff ~2.900 dòng — ILO1000/459901/duty_scheduler,
có phiên khác đang làm song song). User nói: *"bạn nhắc lại tôi sau vì tôi đang chéo việc vào nhau"*.
→ **Đầu phiên sau hỏi lại xem việc kia xong chưa để bổ sung notes.**

## 2 hạng mục đã làm (theo tài liệu nghiệp vụ Business Owner cung cấp trong ngày)

### 1. Báo cáo KẾT QUẢ đối chiếu MIS thừa T-2
Nguồn: `<Ổ DỮ LIỆU>\ACH CHUA DOI CHIEU NGAY 31.07-02.08\NGUYEN TAC DOI CHIEU DIEN MIS THUA NGAY T-1.docx`

- Hàm mới `ket_qua_mis_di_thua_t2()` / `ket_qua_mis_den_thua_t2()` trong `b11_doi_chieu_cheo_ngay.py`.
- Gắn cột `KET_QUA` lên chính file MIS thừa T-2, tách theo `LOAI_LENH_OSB`: dòng OSB (`'O'`/`'1'`) đối
  chiếu **QT ngày T-1**, dòng thường (rỗng) đối chiếu **NPO thừa ngày T-1**.
- Xuất file riêng `<ngày>_ACH_MISThuaT2.xlsx` (không đụng `doi_chieu_<ngày>.xlsx`), có ngưỡng CSV.
- Thiếu file QT T-1 → nhãn riêng `"Không có QT ngày T-1 để đối chiếu"` (không gộp nhầm "chưa hạch toán").

### 2. Viết lại sheet TONG_KET theo mẫu mới
Nguồn: `<Ổ DỮ LIỆU>\NGUYEN TAC DOI CHIEU ACH\Copy of chinh sua man hinh tong hop doi chieu ACH hang ngay.xlsx`

- Layout song song **Chiều Đi (cột A-C) | Chiều Đến (cột E-G)**, nhãn dùng **NGÀY THẬT** (không phải chữ
  "t-1"/"t-2" tĩnh như trong mẫu — user xác nhận rõ).
- **Bỏ hẳn khỏi TONG_KET** (user chốt): GW thừa x2, NPO_DI thừa, MIS_DI thừa, SESSION_NULL_BI_LOAI —
  dữ liệu KHÔNG mất, vẫn xem đủ ở các sheet riêng cùng tên.

## 3 bài học thật trong phiên — ĐỪNG LẶP LẠI

1. **Mục "Điện thường T-2" = 1 dòng mang cả nhãn lẫn số liệu, RỒI lặp lại y hệt dòng "khớp NPO cùng
   ngày" ngay sau** (đối xứng đúng mục OSB). Tôi sai 2 lần liên tiếp ở đây: lần 1 tách thành dòng tiêu đề
   + dòng phụ trùng nhãn; lần 2 sửa quá tay, xoá luôn dòng lặp lại. **File mẫu CỐ Ý có 2 dòng trùng
   nhãn + trùng số** (dòng 21 lặp dòng 10, dòng 30 lặp dòng 12) làm mốc so sánh — không phải lỗi
   copy-paste như tôi suy đoán ban đầu.
2. **File `.csv` chương trình xuất có thể bị người chấm mở/lưu lại bằng Excel** → dấu phẩy đổi thành tab
   (hoặc chấm phẩy ở locale vi-VN), mất dấu tiếng Việt ở cột không bắt buộc. Đã sửa `_doc_file_thua_t2()`
   dùng `sep=None, engine='python'` tự dò. Áp dụng cho MỌI chỗ đọc file người dùng có thể mở lại bằng Excel.
3. **Thư mục output đặt trong thư mục dữ liệu phải LỒNG trong `Output\`** (đúng tên segment "output" để
   `_tim_file_ngoai_output()` loại trừ) — nếu không, file `MIS_DI_THUA*.csv` mới ghi ra sẽ bị lần chạy sau
   nhặt nhầm làm file T-2.

## Verify dữ liệu thật 03.08 — khớp tuyệt đối với mẫu

Chạy qua Checkpoint thật (có 2 REFHUB bổ sung `260731000000004616351608`, `260731000000004617750314`
tra tự động từ thư mục anh em `31.07\`):

| Chỉ tiêu | Mẫu | Kết quả |
|---|---|---|
| GW đi | 587.811 / 2.997.972.684.461 | khớp tuyệt đối |
| Mis đi | 587.825 / 2.997.987.656.461 | khớp tuyệt đối |
| Lệnh đi khớp NPO | 526.172 / 2.888.686.495.217 | khớp tuyệt đối |
| Lệnh OSB đi khớp QT | 31.399 / 37.301.025.722 | khớp tuyệt đối |
| huỷ trong/khác ngày, TO | 402/0, 74/-155.078.000, 14/14.972.000 | khớp tuyệt đối |
| Điện thường T-2→T-1 (đi/đến) | (mẫu để công thức) | 26.914 / 21.741 |
| Điện OSB T-2→T-1 (đi/đến) | (mẫu để công thức) | 2.730 / 868 |

**File kết quả:**
- `<Ổ DỮ LIỆU>\ACH CHUA DOI CHIEU NGAY 31.07-02.08\03.08\doi_chieu_20260803.xlsx` — bản xuất riêng cho user.
- `<Ổ DỮ LIỆU>\...\03.08\Output\verify_TONGKET_moi_v3\` — bản chạy đầy đủ mới nhất (v1/v2 là bản cũ hơn cùng phiên,
  xoá được nếu user đồng ý — CHƯA hỏi).

## Lưu ý môi trường

- Ổ dữ liệu ngoài từng rớt kết nối giữa phiên, sau đó báo **"Full Repair Needed"** (exFAT) — đọc/ghi
  vẫn bình thường, chưa chạy `chkdsk` (chưa xin phép user).
- File `MIS_DI_THUA_20260802.csv` trong `03.08\` đã bị Excel đổi định dạng (tab-delimited) — user chốt
  **"để nguyên"**, code đã đọc được.
- Có **phiên/cửa sổ khác đang làm song song** (ILO1000, 459901, duty_scheduler đang dirty) — **không đụng
  các file đó**.
