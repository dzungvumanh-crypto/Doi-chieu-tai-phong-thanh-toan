# Bối cảnh dự án — đọc trước khi làm bất cứ việc gì

> **File này tồn tại để làm gì:** ngữ cảnh dự án trước đây chỉ nằm trong bộ nhớ cục bộ trên
> một máy laptop. Phiên làm việc từ điện thoại hay từ cloud không đọc được, nên lần nào cũng
> phải kể lại từ đầu. File này nằm trong repo → mọi phiên ở mọi thiết bị đều đọc được.
>
> Cập nhật lần cuối: 2026-08-10. Khi trạng thái đổi, sửa mục 6 (Trạng thái hiện tại) trước khi kết thúc phiên.

---

## 1. Bối cảnh nghiệp vụ

Người dùng làm việc tại **Trung tâm Thanh toán Agribank Việt Nam**, phụ trách các quy trình
đối chiếu dữ liệu thủ công giữa nhiều hệ thống nguồn. Dự án gồm **nhiều module đối chiếu độc
lập** — ACH, ILO1000, Chấm 459901, Đối chiếu song phương, Citad–Hub.

### Từ vựng nguồn dữ liệu (dùng xuyên suốt mọi module)

| Thuật ngữ | Nghĩa |
|---|---|
| **Hub** | Trục thanh toán / kênh xử lý lệnh — switch nội bộ ngân hàng |
| **Core** | Dữ liệu hạch toán, sổ cái ngân hàng (GL02) |
| **Citad** | Kênh thanh toán liên ngân hàng với Ngân hàng Nhà nước |
| **GW** | Gateway — dữ liệu phía kênh, đối chiếu với Hub |
| **MIS_đi / MIS_đến** | Dữ liệu lệnh đi / đến dựng từ MIS_Hub |
| **NPO_đi / NPO_đến** | Dữ liệu đối ứng phía hạch toán, đối chiếu ở Phase 2 |

### Citad có hai loại — đừng dùng chung tham số

| | Citad **Thấp** | Citad **Cao** |
|---|---|---|
| Giá trị mỗi giao dịch | < 500 triệu | Không giới hạn |
| Cutoff (NHNN có thể đổi) | **16h** | **17h** |
| Cách hạch toán | Tất toán **theo lô** — 1 bút toán gộp | **Từng giao dịch riêng lẻ** |
| Tên kênh nội bộ | **ILO1000** | **HIO** / `1000HIO` |

- **ILO1000 = kênh Citad Thấp** → cutoff **16h**. Nếu sau này làm module Citad Cao, cutoff mặc
  định phải là **17h**, tuyệt đối không dùng lại 16h.
- `"1000"` = mã chi nhánh Trung tâm Thanh toán. `ILO1000` = tài khoản trung gian ILO của kênh
  giá trị thấp; `1000HIO` = tài khoản kênh giá trị cao.
- Trong `process_core()` ([backend/services/ilo1000/process.py](../backend/services/ilo1000/process.py)),
  REFERENCE chứa `"HI"` (vd `1000HIO000000006`) → Trace = `Quyết toán`. **Đây là giao dịch quyết
  toán hợp lệ giữa ILO và HIO, không phải lỗi hay case rác.**
- Citad chỉ chạy **giờ hành chính (8h → cutoff), không có phiên thứ 7/CN**, trong khi hệ thống
  nội bộ Agribank chạy 24/7. Lệnh phát sinh sau cutoff phải **"chờ đi kênh"** sang phiên kế
  tiếp → luôn cân nhắc khoảng lệch này khi gộp dữ liệu cuối tuần / ngày lễ.

---

## 2. Lý do gốc của module ACH — đọc kỹ, đây là xương sống

Đối chiếu chương-trình-với-chương-trình, với-đối-tác, với-kênh đều đã có nơi khác xử lý.
Riêng **"Timeout không đi kênh"** — giao dịch **không tường minh** (nếu tường minh thì hệ
thống gốc đã tự xử lý) — **không có công cụ nào khác phục vụ**. Đó chính là lý do dự án ACH
ra đời. Nó không phải một tính năng trong nhiều tính năng.

### Rủi ro hai chiều KHÔNG đối xứng

| Phân loại sai | Hậu quả | Mức độ |
|---|---|---|
| **Chọn THIẾU** — bỏ sót điện thật sự timeout | Khách hàng khiếu nại đòi hoàn tiền | Phiền, nhưng **sửa được**, tự lộ ra qua khiếu nại |
| **Chọn THỪA** — báo điện đã đi thành công là "timeout không đi kênh" | Chạy hoàn tiền trong khi lệnh **đã đi rồi** → **mất tiền thật, hoàn oan, khó thu hồi** | **Nghiêm trọng hơn hẳn — không có cơ chế tự phát hiện** |

→ Đây là lý do **Checkpoint (dừng chấm tay thủ công tại MIS_đi, trước khi so khớp GW)** là
**bắt buộc tuyệt đối**, không được tự động hoá bỏ bước xác nhận. Khác hẳn mọi bước khác trong
pipeline vốn có thể tối ưu/tự động.

### Quy tắc áp dụng cho MỌI đề xuất kỹ thuật ACH

Trước khi đề xuất bất kỳ thay đổi nào — kể cả thay đổi nhỏ, kể cả ở phần tưởng như không liên
quan — phải tự hỏi: **thay đổi này có làm yếu đi độ chính xác của Timeout, hoặc làm yếu vai trò
bắt buộc của Checkpoint không?** Nếu có nguy cơ dù nhỏ, nói rõ **trước** khi làm.

Khi trình bày phương án, luôn nêu một câu: phương án này **có / không** ảnh hưởng
Checkpoint–Timeout. Đừng để Business Owner phải tự hỏi.

> Ghi chú kiến trúc: Checkpoint (`_process_mis_di()` → dừng chờ xác nhận → `khop_voi_gw()`)
> nằm ở **Phase 1** của `main_from_dir()`, **hoàn toàn không phụ thuộc GL02**. GL02/NPO chỉ
> dùng ở **Phase 2**. Nên các ý tưởng kiểu "cho chạy khi thiếu GL02" về kiến trúc không đụng
> tới xương sống — nhưng vẫn phải bàn thiết kế trước khi code.

---

## 3. Mười nguyên tắc — nghiệp vụ trước kỹ thuật

Business Owner nêu tường minh (2026-07-31) là **triết lý xuyên suốt toàn dự án**, không gắn với
một yêu cầu cụ thể nào.

1. **Nghiệp vụ luôn đứng trước kỹ thuật.** Không đổi bản chất nghiệp vụ chỉ vì thiết kế kỹ
   thuật "đẹp hơn".
2. **Không dẫn Business Owner đi quá xa.** Hỏi A thì giải quyết A — không tự dẫn sang B/C/D.
3. **Không làm phình dự án.** Sửa ít nhất, đổi ít file nhất, giữ nguyên kiến trúc nếu được.
   Không thêm abstraction/layer mới nếu bài toán hiện tại không cần.
4. **Giải bài toán đơn giản nhất.** Không tối ưu sớm, không thiết kế cho nhu cầu chưa tồn tại.
5. **Business Rule là ưu tiên số 1** — đúng nghiệp vụ quan trọng hơn tốc độ / kiến trúc / code đẹp.
6. **Không suy diễn nghiệp vụ.** Code hiểu khác Business Owner → **không bảo vệ code**, phân
   tích đúng bản chất nghiệp vụ trước rồi mới đề xuất sửa.
7. **Phân biệt rõ 3 thứ, không trộn:** (a) người dùng muốn gì, (b) chương trình đang làm gì,
   (c) cần sửa gì.
8. **Không viết code quá sớm.** Chưa rõ nghiệp vụ thì tiếp tục phân tích, không code.
9. **Phản biện nhưng không chệch mục tiêu.** Được chỉ ra rủi ro, nhưng sau đó quay lại đúng
   mục tiêu — không biến trao đổi thành thiết kế kiến trúc lớn hơn yêu cầu.
10. **Mục tiêu cuối:** đúng nghiệp vụ, số liệu chính xác tuyệt đối, đơn giản, dễ bảo trì.

---

## 4. Bảy cái bẫy đã dính — đừng lặp lại

### 4.1 Không chọn bản ghi theo vị trí/thứ tự
Nhóm trùng khóa (chi nhánh+số tiền, ngày+session…) cần xác định bản ghi nào chênh lệch:
**cấm dùng `cumcount()`, `head()`, `tail()`, index vị trí.** Thứ tự trong file do hệ thống
nguồn export ra — **ngẫu nhiên đối với ý nghĩa nghiệp vụ**.

Tách **2 bước độc lập**: (a) xác định **NHÓM** nào lệch — thuần so tổng `COUNT`, không chọn
dòng nào; (b) trong nhóm đã lệch, phân loại **TỪNG DÒNG** bằng **định danh cấp-dòng chính
xác** (MSGREF). Không có định danh đáng tin → **xuất toàn bộ nhóm** cho người dùng chấm tay,
không tự suy luận chọn.

> Đây là dạng lỗi tinh vi nhất: code chạy được, tổng số khớp, nhưng **chọn sai đúng bản ghi**
> — chỉ lộ khi soi ngược từng MSGREF với dữ liệu tham chiếu thật.
>
> ⚠️ **Pattern 7** trong [`.claude/commands/doi-chieu.md`](../.claude/commands/doi-chieu.md)
> dùng `cumcount` — pattern đó **chỉ hợp lệ để ĐẾM**, không được dùng để **CHỌN** bản ghi.

### 4.2 Lọc TRẠNG THÁI trước, SESSION/ngày sau
Luôn theo thứ tự thác nước, không chạy song song. Ngày/session không được che khuất trạng thái.

### 4.3 Không suy diễn ý nghĩa cột dữ liệu
Chỉ dùng điều kiện Business Rule đã quy định rõ cho cột đó (vd `PrcFlg`, `SessionId`). BR chưa
nói tới → **dừng và hỏi**, không suy ra từ tương quan quan sát được.

### 4.4 Lệch số liệu → nghi lỗi ĐỌC FILE trước, đừng đổ cho thuật toán
Tỷ lệ bất thường đều đặn (vd đúng 2.0x) hầu như luôn là **file nhiều sheet bị đọc gộp trùng
lặp**, không phải lỗi Business Rule.

### 4.5 Báo cáo đối chiếu chỉ có 2 trạng thái
**"Đã cân khớp"** / **"Chưa cân khớp cần hoàn thiện"**. Không dùng khung phần trăm để giảm nhẹ
sai lệch tài chính.

### 4.6 Chép file thừa T-2 sang thư mục ngày sau
Pattern `MIS_DI_THUA*` khớp **cả** file báo cáo `MIS_DI_THUA_T2_KETQUA_*.csv` → thư mục có 2
file trùng mẫu → pipeline dừng với `FileNotFoundError: Có nhiều hơn 1 file MIS_đi thừa T-2`.
**Chỉ chép đúng `MIS_DI_THUA_<ngày>.csv` và `MIS_DEN_THUA_<ngày>.csv`**, loại trừ tên chứa
`T2_KETQUA`.

### 4.7 Nhiều cửa sổ Claude Code chạy song song trên cùng thư mục
Người dùng thường mở nhiều phiên, mỗi phiên một module. **Trước khi `git stash` / `merge` /
`checkout`**, kiểm tra file dirty nằm ngoài phạm vi việc đang làm. Nghi ngờ thì hỏi thẳng,
không tự ghi đè.

---

## 5. Luật nghiệp vụ ACH — tra ở đâu

**Không tóm tắt luật vào đây.** Bản tóm tắt luôn lạc hậu so với code — đã xảy ra thật: bộ nhớ
còn ghi quy tắc *TPAY-only* trong khi quy tắc đó đã bị thay từ 2026-08-03.

Nguồn đáng tin, theo thứ tự:

| Nguồn | Nội dung |
|---|---|
| docstring `khop_voi_gw()` trong [`backend/services/ach/b4_xu_ly_mis_di.py`](../backend/services/ach/b4_xu_ly_mis_di.py) | **BR-ACH-001** đầy đủ — thứ tự C.1 (xác định NHÓM chênh lệch) → C.2 (tra MSGREF từng dòng), kèm lý do từng quyết định |
| `_process_mis_di()` cùng file | Mục 2 — dựng MIS_đi: lọc TRẠNG THÁI trước, SESSION sau (thác nước, không đảo) |
| `b3_xu_ly_gw.py` | Mục 3.1 — lọc GW, dựng khoá CN_TIỀN |
| `b2_xu_ly_gl02.py` | Mục 4 — SO_TRACE của NPO_đi |
| Tài liệu `DOI CHIEU ACH_v2.docx` (5 mục, 47 dòng) | Nguồn nghiệp vụ gốc |

**Đọc thẳng docstring trước khi đề xuất bất kỳ thay đổi nào** — nó ghi rõ vì sao từng bước phải
theo đúng thứ tự đó, và các cách làm đã thử rồi bỏ. Đừng suy luận lại từ code cũ hay golden
sample cũ: golden sample cũ đã từng dùng nhầm thuật toán.


---

## 6. Trạng thái hiện tại (2026-08-10)

### Git
- Nhánh làm việc: **`Cham_ILO1000`**, đồng bộ cả `origin` (khanhbq693/TTTT, **private**) và
  `personal` (dzungvumanh-crypto/Doi-chieu-tai-phong-thanh-toan, **public**).
- **PR #19** (`Cham_ILO1000` → `develop`) — `OPEN`, `MERGEABLE`. Chờ **khanhbq693** review +
  bấm Merge. **Không tự merge** — không có quyền admin, chỉ có `push`.

### Việc đang dang dở, CHƯA COMMIT
| Module | File | Tình trạng |
|---|---|---|
| **Chấm 459901** | `backend/api/cham459901.py`, `backend/services/cham459901_service.py`, `frontend/pages/cham_459901.py`, `tests/test_cham459901_algorithm.py` | Tính năng **ghép file "tồn tháng trước"** (`459_TON_Tx.xlsx`) vào GL02 tháng hiện tại. Đã có `classify_upload_filename()` loại `'ton'`, `_read_ton_file()`, `_TON_COLS`. **Chưa rõ đã xong hay còn dở — phải hỏi lại, không tự đoán.** |
| **ILO1000** | `backend/services/ilo1000/*.py` (8 file), `frontend/pages/cham_ilo1000.py`, `tests/test_ilo1000_algorithm.py` | **Chưa rõ đang sửa gì.** |

### ACH — kết quả gần nhất (chạy 2026-08-10, dữ liệu 04–05/08/2026)
- Chế độ **chạy thẳng không Checkpoint** (`dung_sau_mis_di=False`). 04/08 mất 453s, 05/08 mất 424s.
- **Đã cân khớp cả 2 ngày.** Bất biến số học tự kiểm: `MIS đi − GW đi` = đúng dòng "TO không đi
  kênh" — 04/08: **6 món / 11.679.000**; 05/08: **11 món / 21.177.000**. `GW_CAN_DOI_CHIEU` = 0
  dòng cả hai ngày.
- **Cần người chấm xem:** `SESSION_NULL_BI_LOAI` ngày 04/08 có **445 dòng** so với 05/08 chỉ
  **23 dòng** — chênh ~19 lần giữa 2 ngày liền kề, **chưa ai giải thích**.

### Dữ liệu test
- **ILO1000:** chỉ dùng golden sample **tháng 7/2026** (bộ 4–6.7 và 11–13.7). **Cả 2 bộ chưa
  cân khớp.** Không dùng lại dữ liệu tháng 5/2026.
- **Chấm 459901:** 3 tháng (5, 6, 7) đã đối chiếu với bản chấm tay bằng code mới nhất — đang
  **chờ phản hồi người chấm**.

### Backlog đã hoãn — không tự ý làm
| Việc | Trạng thái |
|---|---|
| Module Reconciliation độc lập đối chiếu tuyệt đối theo **MSGREF** (MATCH / Chỉ-MIS / Chỉ-GW), tách khỏi C.1–C.2 | Chỉ làm **sau** khi xong toàn bộ Requirement hiện tại |
| **GL02 / MIS_đến tuỳ chọn** khi thiếu file (bảng tầng phụ thuộc) | Hoãn 2026-08-03. Phương án đầy đủ đã lưu, **không code đợt này** |
| Lỗi **"đọc tiếng Việt"** khi chạy chương trình | Business Owner sẽ báo lại nguyên văn khi gặp. **Hỏi nội dung lỗi trước, không suy đoán** là cùng lỗi đã sửa ở `4cad7bc` |

---

## 7. Cách làm việc

- **Bước cực nhỏ.** Tính năng lớn → bám đúng phạm vi từng Bước người dùng liệt kê, không tự mở
  rộng. Phản biện trước, nhưng **rà code kỹ trước khi kết luận là bug**.
- **Bàn giao = "Ready for User Experience", không phải "Ready for Developer Test".** Tự chạy đủ
  checklist trước; người dùng chỉ trải nghiệm, **không làm tester**.
- **Quyền đã cấp rộng thì đừng hỏi lại từng thao tác.** Chỉ dừng khi có **quyết định nghiệp vụ**
  thật sự, hoặc hành động rủi ro cao/khó đảo ngược.
- **Dọn data test** sau khi test xong, trước khi báo hoàn thành — không chờ nhắc.
- **Ghi Implementation-notes liên tục.** Mọi quyết định kỹ thuật không hiển nhiên, mọi đánh đổi
  → [`Implementation-notes.html`](../Implementation-notes.html), không để sau.

---

## 8. Giới hạn của phiên cloud / điện thoại

Máy ảo cloud clone repo từ GitHub. **Toàn bộ dữ liệu thật (~50GB) đã gitignore và KHÔNG có ở
đó.**

| Làm được | Không làm được |
|---|---|
| Đọc, sửa, refactor code | Chạy pipeline đối chiếu ACH / ILO1000 / 459901 trên dữ liệu thật |
| Viết và chạy test (dữ liệu tổng hợp nhỏ) | Đối chiếu với golden sample thật |
| Viết tài liệu, phân tích nghiệp vụ, lập kế hoạch | Xác minh kết quả bằng file nguồn thật |
| Rà soát logic, tìm bug bằng đọc code | Kiểm thử UI click-through |

→ Nếu phiên cloud định đề xuất "chạy thử để xác nhận": **không được**, phải để dành cho phiên
trên laptop có ổ dữ liệu.
