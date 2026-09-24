# Từ điển mã/lệnh thanh toán — TTTT

## Đây là gì

Từ điển các mã/lệnh/trường/trạng thái thanh toán xuất hiện trong 4 module đối chiếu của dự án
(ACH, ILO1000, Chấm 459901, Đối chiếu Song phương). **Không dựa trên tài liệu quy chuẩn chính thức** (không có spec từ
NHNN/Agribank/nhà cung cấp hệ thống lõi) — toàn bộ được **suy luận ngược** từ:

1. Code thực tế đang chạy (`backend/services/...`) — nguồn chính của tài liệu này.
2. Comment tiếng Việt do người viết code để lại, khi có.

**Đợt 2 đã bổ sung** — đối chiếu với dữ liệu thật (tần suất, miền giá trị mỗi mã trong file
MIS/GW/OSB/GL02 thật của ACH 31/07–03/08/2026, ILO1000 04-06/07/2026, 459901 tháng 7/2026), dùng để
*kiểm chứng*, không dùng để định nghĩa — xem chi tiết ghi chú "Xác nhận dữ liệu thật" trong từng
bảng và **Phần 5** ở cuối file.

**Vẫn chưa làm** — xác nhận với người/tài liệu quy trình nghiệp vụ nội bộ: nguồn duy nhất xác nhận
được *ý nghĩa nghiệp vụ gốc* của một mã, vì code + dữ liệu chỉ cho biết hệ thống *xử lý* mã đó thế
nào. Danh sách ưu tiên cần hỏi nằm ở Phần 5.

**Đợt 3 (2026-08-20)** — rà soát lại toàn bộ từ điển, đào sâu thêm bằng dữ liệu thật đã có sẵn trên
máy (không phải dữ liệu mới): giải mã thêm GL02 để tra 2 mã lạ liên quan nhau (`1000ITT.../
1000-553970732`, xem Phần 2.1/4.1), trace code + dữ liệu thật để giải thích cơ chế `PrcFlg` biến
mất (Phần 1.6), kiểm tra thêm 6 ngày ACH khác cho `TOPO`/`TXTF`, đối chiếu với tài liệu quy trình
459901 có sẵn (`G:\NGOC HA\Quy_trinh_cham_459901.docx`). Phát hiện thêm 1 vấn đề dữ liệu quan
trọng: 2 file `GL02_20260731_1000.zip` khác nhau cùng tên (xem Phần 5, ưu tiên cao).

**Module Đối chiếu Song phương** (Phần 4) mới chỉ có bước phân loại, chưa có bước đối chiếu thật —
xem ghi chú riêng đầu Phần 4.

**Nguồn 3 (mới, đang chờ) — tài liệu kỹ thuật/quy trình chính thức.** Business Owner sẽ cung cấp
dần tài liệu kỹ thuật + quy trình nghiệp vụ của các hệ thống liên quan. Khi nhận được, nội dung sẽ
được đối chiếu với 2 nguồn hiện có (code + dữ liệu thật) và gộp thẳng vào các bảng bên dưới — xem
mục "Nhật ký cập nhật từ tài liệu chính thức" ở cuối file để biết tài liệu nào đã xử lý.

## Sơ đồ hệ thống thanh toán (tổng hợp từ 4 module)

Sơ đồ dưới đây **suy ra thuần tuý từ những gì đã xác nhận** ở Phần 1-4 (code + dữ liệu thật) —
KHÔNG phải sơ đồ chính thức. Mục đích: khi tài liệu chính thức tới, biết ngay thông tin mới khớp
vào đâu trong bức tranh hiện có, và phần nào (đường nét đứt `❓`) đang là lỗ hổng thật sự cần tài
liệu lấp vào.

```mermaid
flowchart TB
    CORE["Core Banking / IPCAS<br/>(1 nguồn GL02 duy nhất, xác nhận<br/>bằng dữ liệu thật 31/07/2026)"]

    CORE -->|"LOCAC=502003<br/>CUSTOMER=1000-003526275"| ACH["Module ACH"]
    CORE -->|"LOCAC=459901<br/>CUSTOMER=1000-000007709"| M459["Module Chấm 459901"]
    CORE -->|"LOCAC=501202<br/>CUSTOMER=1000-000007709"| ILO["Module ILO1000"]
    CORE -->|"CUSTOMER ∈ 4 mã ngân hàng<br/>(không lọc LOCAC)"| SP["Module Đối chiếu<br/>Song phương"]
    CORE -.->|"CUSTOMER=1000-553970732<br/>LOCAC=502003, 53 dòng"| UNK["✅ Mobifone — khách hàng<br/>thuộc hệ thống thanh toán<br/>(xác nhận BO 2026-08-20)"]

    ACH --> ACH_MIS["MIS_đi / MIS_đến<br/>(kênh ACH/NAPAS)"]
    ACH --> ACH_GW["GW (gateway)"]
    ACH --> ACH_QT["QT (quyết toán OSB)"]

    ILO --> ILO_HUB["Hub (phub_*)"]
    ILO --> ILO_CITAD["Citad"]
    ILO --> ILO_EICP["EICP (tra cứu trung gian)"]
    ILO --> ILO_OSB["OSB<br/>(đã verify dữ liệu thật tháng 8/2026)"]

    M459 --> M459_HUB["Hub đi / Hub đến<br/>(Quay_..., Danh_sach_giao_dich_den)"]

    SP -.-> SP_CHANNEL["❓ Kênh song phương<br/>4 ngân hàng — CHƯA CÓ DỮ LIỆU"]
```

**Điểm đáng chú ý (suy từ dữ liệu, chưa xác nhận nghiệp vụ):**
- `Chấm 459901` và `ILO1000` dùng **chung 1 CUSTOMER** (`1000-000007709`) nhưng khác `LOCAC`
  (459901 vs 501202) — gợi ý đây là 2 sổ cái con (sub-ledger) khác nhau của cùng 1 khách hàng/đơn
  vị nội bộ trên Core. Chưa có tài liệu xác nhận ý nghĩa quan hệ này.
- 4 module đã biết đều lọc ra từ **cùng 1 nguồn GL02** — khác nhau ở tổ hợp LOCAC/CUSTOMER dùng để
  lọc. Nếu tài liệu chính thức có bảng "danh mục LOCAC/CUSTOMER toàn hệ thống", đó sẽ là mảnh còn
  thiếu quan trọng nhất để lấp đầy `UNK` và xác nhận các LOCAC/CUSTOMER hiện tại không phải trùng
  hợp ngẫu nhiên. **Đợt 3 (2026-08-20):** `UNK` (CUSTOMER=`1000-553970732`) có REMARK 100% là
  "Công ty Cổ phần Thanh toán số Mobifone" và REFERENCE cùng định dạng `1000ITT...` với 1 dòng lạ
  từng gặp ở ILO1000 (Phần 2.1). **Business Owner đã xác nhận (2026-08-20): Mobifone chỉ là khách
  hàng thuộc hệ thống thanh toán** — dùng chung LOCAC kênh ACH (502003), không phải ngân hàng thứ 5
  của Song phương. Câu hỏi kỹ thuật còn lại (không phải nghiệp vụ): vì sao dòng lẻ `1000ITT...` ở
  ILO1000 lọt qua filter `LOCAC=501202` — xem Phần 2.1.
- Kênh song phương (4 ngân hàng) là nhánh duy nhất hoàn toàn chưa có dữ liệu phía kênh — bất kỳ tài
  liệu nào về định dạng file/luồng dữ liệu 4 ngân hàng này đều ưu tiên cao nhất.

## Cách đọc bảng

Mỗi mã có 4 cột: **Mã** | **Ý nghĩa suy luận** | **Nguồn (file:line)** | **Độ tin cậy**.

Độ tin cậy:
- **Cao** — có comment tiếng Việt giải thích rõ ràng trong code, đã được Business Owner xác nhận
  trực tiếp (ghi rõ trong comment), hoặc **đã xác nhận bằng tài liệu chính thức** (ghi rõ tên tài
  liệu + ngày trong ô "Ý nghĩa suy luận", xem "Nhật ký cập nhật" cuối file).
- **Trung bình** — suy từ logic xử lý (if/else, cách ghép khoá) nhưng không có comment giải thích.
- **Thấp** — chỉ đoán từ tên biến, chưa có logic hay comment nào xác nhận.
- **Không biết** — chỉ thấy dùng để so khớp/phân loại hoặc liệt kê cột, không rõ ý nghĩa gì cả.

Khi tài liệu chính thức **mâu thuẫn** với code/dữ liệu thật (VD: tài liệu nói mã X nghĩa là A,
nhưng code lại xử lý như thể nghĩa là B) — ghi rõ CẢ HAI, gắn cờ "⚠️ mâu thuẫn với code/dữ liệu",
KHÔNG âm thầm ghi đè. Mâu thuẫn kiểu này tự nó là một phát hiện quan trọng (có thể là bug, có thể
là tài liệu lỗi thời) cần báo lại Business Owner, không phải lỗi cần "sửa cho khớp".

⚠️ **Không suy diễn thêm khi đọc bảng này.** Nếu một dòng ghi "chưa rõ" / "không biết", nghĩa là
code không thể hiện — đừng tự đoán tiếp theo hướng nào "nghe hợp lý". Đây đúng là bẫy đã từng gặp
trong dự án (suy diễn ý nghĩa cột từ tương quan quan sát được thay vì từ Business Rule đã xác nhận).

---

## Phần 1 — ACH

*Nguồn: `backend/services/ach/` (b1–b11, pipeline.py, validate.py, so_tien.py, osb_common.py,
zip_utils.py, config.py) và `backend/services/ach_service.py`.*

### 1.1 Mã trạng thái lệnh (TRANG_THAI_LENH)

**MIS_đi:**

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `CALD` | Bị loại hẳn khỏi MIS_đi ngay Bước 1, không dùng lại cho mục đích nào khác. Ý nghĩa viết tắt không được giải thích. Xác nhận dữ liệu thật 31/07–03/08/2026: có xuất hiện thật trên MIS_đi thô, 0 dòng còn lại trong `MIS_DI_THUA` (đúng — đã bị loại từ Bước 1). | `ach/b4_xu_ly_mis_di.py:23,286-287` | trung bình |
| `ERPO` | Cùng nhóm loại trừ với CALD/TPER. Xác nhận dữ liệu thật 31/07–03/08/2026. | `ach/b4_xu_ly_mis_di.py:23,286-287` | trung bình |
| `TPER` | Cùng nhóm loại trừ với CALD/ERPO. Xác nhận dữ liệu thật 31/07–03/08/2026. | `ach/b4_xu_ly_mis_di.py:23,286-287` | trung bình |
| `TPAY` | Lệnh "chưa được xử lý — cần theo dõi"; trong nhóm CN_TIỀN thừa được xét đại diện cho case "Timeout" (lệnh gửi đi nhưng chưa/không đi kênh). Xác nhận dữ liệu thật 31/07–03/08/2026. | `ach/b8_phan_tich.py:30-32,67-70,123`; `ach/b4_xu_ly_mis_di.py:441-446` | cao |
| `TXRT` | "Hoàn trả — cần kiểm tra". Xác nhận dữ liệu thật 31/07–03/08/2026. | `ach/b8_phan_tich.py:124` | cao |
| `SCNL` | "Đã thanh toán — có thể thuộc session khác, bình thường". Xác nhận dữ liệu thật 31/07–03/08/2026 — 100% dòng còn lại trong `MIS_DI_THUA_20260731.csv` (75.118 dòng) là SCNL, đúng như mô tả (CALD/ERPO/TPER đã bị loại từ Bước 1). | `ach/b8_phan_tich.py:123` | cao |
| `TXPR` | Chỉ được nêu như ví dụ "trạng thái khác ngoài TPAY phát sinh theo thời gian", không có logic phân loại riêng. Xác nhận dữ liệu thật: xuất hiện đúng 1 dòng (31/07/2026) trong 4 ngày mẫu — hiếm nhưng có thật. | `ach/b4_xu_ly_mis_di.py:445` | không biết |
| `TXCA` | Chỉ được nêu như ví dụ, không có logic phân loại riêng. **Không quan sát được** trong 6 ngày mẫu 31/07–03/08/2026 — không phủ nhận việc mã này tồn tại, chỉ chưa gặp trong dữ liệu đã kiểm tra. | `ach/b4_xu_ly_mis_di.py:445` | không biết |
| `TOPO` | ⚠️ **Mã thật ngoài từ điển, không có trong code/comment nào.** Xuất hiện đúng 1 dòng (31/07/2026) trong 6 ngày mẫu đợt 1. **Đợt 3 (2026-08-20) kiểm tra thêm 6 ngày khác** (05,06,07,08,09,12/08/2026, ~3,7 triệu dòng MIS_đi thô từ `doichieugd_*_DI_9999_N.zip`) — **không xuất hiện lại**, cũng không phát sinh mã lạ nào khác ngoài 6 mã đã biết. Củng cố khả năng là ca hiếm/lỗi gõ, không phải mã hệ thống thường dùng bị bỏ sót. Vẫn cần Business Owner xác nhận ý nghĩa. | Dữ liệu thật, không có trong code | không biết |
| `TXTF` | ⚠️ **Mã thật ngoài từ điển, không có trong code/comment nào.** Xuất hiện đúng 1 dòng (03/08/2026) trong 6 ngày mẫu đợt 1. **Đợt 3 (2026-08-20)**: cùng kết quả như `TOPO` — không xuất hiện lại trên 6 ngày kiểm tra thêm. Cần Business Owner xác nhận ý nghĩa. | Dữ liệu thật, không có trong code | không biết |

**MIS_đến:**

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `RJCT` | Bị loại khỏi MIS_đến (BR gốc mục 6.3, không tính vào đối chiếu). Ý nghĩa tên viết tắt không được giải thích. Xác nhận dữ liệu thật 31/07–03/08/2026: 56-108 dòng/ngày trên MIS_đến thô, **0 dòng** còn lại trong `MIS_DEN_THUA_20260731.csv` (84.330 dòng) — đúng logic bị loại trước khi ra file thừa. | `ach/b6_xu_ly_mis_den.py:132-137` | thấp cho tên, cao cho hành vi |
| `PYED` | ⚠️ **KHOẢNG TRỐNG LỚN NHẤT của từ điển.** Không có trong bất kỳ code/comment nào — code chỉ lọc riêng `RJCT`, mọi giá trị khác (kể cả PYED) đi thẳng qua không phân loại. Chiếm **~88-93% khối lượng** MIS_đến thô (534k-602k dòng/ngày, 6 ngày mẫu 31/07–03/08/2026). Chưa dùng được để phân tích nếu không hỏi Business Owner ý nghĩa. | Dữ liệu thật, không có trong code | không biết |
| `SBSC` | Cùng mức độ khoảng trống như PYED — chiếm ~7-8% khối lượng MIS_đến. Không có trong code/comment. | Dữ liệu thật, không có trong code | không biết |
| `SBFL`, `WBIL`, `WFPG`, `RFED` | Xuất hiện với tần suất nhỏ hơn PYED/SBSC nhưng vẫn hoàn toàn ngoài từ điển — không có trong code/comment nào. | Dữ liệu thật, không có trong code | không biết |
| `'ACH Từ chối'` (giá trị `PrcFlg`, không phải TRANG_THAI_LENH) | Trạng thái GW bị loại khỏi dữ liệu GW sạch trước khi so khớp. Xác nhận dữ liệu thật 31/07/2026: 316/1.077.333 dòng trên GW gốc, 0 dòng còn lại trong `RAW_GW_20260731.csv` (523.951 dòng) — đúng logic bị loại. | `ach/b3_xu_ly_gw.py:158-161` | cao |

### 1.2 Mã kênh / loại lệnh

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `LOAI_LENH_OSB = 'O'` | Lệnh OSB chiều **đi** trên MIS_đi (verify trên dữ liệu thật — chữ 'O', không phải số 0). | `ach/osb_common.py:5-16` | cao |
| `LOAI_LENH_OSB = '1'` | Lệnh OSB chiều **đến** trên MIS_đến (verify dữ liệu thật). | `ach/osb_common.py:5-11,19-21` | cao |
| `TRTP = 'Normal'` | Điện GL02 gốc dương (bình thường), nửa cặp đối ứng của "điện đi huỷ trong ngày". **Xác nhận trực tiếp từ GL02 gốc** (giải mã bằng `ZIP_PASSWORD`, `GL02_20260731_1000.zip`, 3.811.704 dòng): `Normal` = 3.810.098 dòng, đúng chỉ 2 giá trị tồn tại. | `ach/b10_xu_ly_npo_di_thua.py:18-19` | cao |
| `TRTP = 'Cancel'` | Điện GL02 huỷ (CRAMOUNT âm); bắt cặp cùng REFERENCE/nhóm tổng=0 với dòng Normal → "huỷ trong ngày", đứng riêng → "huỷ khác ngày". **Xác nhận trực tiếp từ GL02 gốc**: `Cancel` = 1.606 dòng. | `ach/b10_xu_ly_npo_di_thua.py:18-23,48` | cao |
| `'Kiểu giao dịch' = 'Cancel'` (file QT) | Lệnh huỷ trong file Quyết toán OSB — chỉ thấy ở QT đi, Số tiền âm, giữ nguyên không lọc riêng (BO xác nhận). | `ach/b9_doi_chieu_osb.py:71-73` | cao |
| `'Chiều giao dịch' = 'GD đi' / 'GD về'` | File QT là quyết toán chiều đi / chiều đến. | `ach/b9_doi_chieu_osb.py:84-93` | cao |

### 1.3 Khoá đối chiếu (tự tính trong code)

| Mã | Công thức / ý nghĩa | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `SO_TRACE` (GL02) | 12 ký tự từ vị trí thứ 8 của `REFERENCE`, bỏ số 0 đầu — theo "mục 4.1 tài liệu đối chiếu" (tài liệu ngoài code). | `ach/b2_xu_ly_gl02.py:131-134` | cao |
| `SO_TRACE` (MIS_đi) | `SE_TRACE` ưu tiên, fallback `TRACE` nếu rỗng, cả 2 bỏ số 0 đầu. | `ach/b4_xu_ly_mis_di.py:111-114` | trung bình |
| `KEY_DI` | `TRBRCD + SO_TRACE + CRAMOUNT` — khoá NPO_đi (GL02, CRAMOUNT≠0). | `ach/b2_xu_ly_gl02.py:136-141` | cao |
| `KEY_DEN` | `TRBRCD + SO_TRACE + DRAMOUNT` — khoá NPO_đến (GL02, CRAMOUNT=0). | `ach/b2_xu_ly_gl02.py:143-148` | cao |
| `KEY_HUB` | `CHI_NHANH + SO_TRACE + SO_TIEN` — khoá đối chiếu MIS_đi ↔ NPO. | `ach/b4_xu_ly_mis_di.py:156-164` | cao |
| `KEY_DEN_HUB` | `CHI_NHANH + TRACE(bỏ 0 đầu) + SO_TIEN` — khoá đối chiếu MIS_đến ↔ NPO. | `ach/b6_xu_ly_mis_den.py:139-144` | cao |
| `'CN tiền Hub'` | `CHI_NHANH + SO_TIEN` (không TRACE) — khoá đối chiếu MIS_đi ↔ GW. | `ach/b4_xu_ly_mis_di.py:156-164` | cao |
| `KEY_GW` | `BRCD + STTLMAMT` — "CN TIỀN" bên GW, đối ứng `'CN tiền Hub'`. | `ach/b3_xu_ly_gw.py:176-179` | cao |
| `CN_TRACE_TIEN` | `mã CN thực hiện + Mã giao dịch(bỏ 0 đầu) + Số tiền` — khoá QT, cùng công thức MIS (KEY_HUB/KEY_DEN_HUB). | `ach/b9_doi_chieu_osb.py:62-102` | cao |
| `MATCH_TYPE = 'TIMEOUT'` | Dòng MIS_đi thừa nhóm nhưng MSGREF đã tồn tại trên GW sạch — "Timeout thật, đã được kênh xác nhận, KHÔNG phải thừa" (BR-ACH-001 nhánh 1B). | `ach/b4_xu_ly_mis_di.py:419-470` | cao |
| `CHECK_TRUNG` | `TRBRCD + SO_TRACE` — nhóm tìm cặp Normal/Cancel cùng ngày (điện đi huỷ trong ngày). | `ach/b10_xu_ly_npo_di_thua.py:9-10,38` | cao |

### 1.4 Mã trường định danh giao dịch

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `MSGREF` | Định danh duy nhất 1 giao dịch trên GW/MIS — dùng loại trùng và tra tồn tại/không tồn tại để phân loại Timeout. Tên viết tắt không được giải thích. | `ach/b3_xu_ly_gw.py:45-54`; `ach/b4_xu_ly_mis_di.py:419-470` | trung bình |
| `REFHUB` | Định danh giao dịch MIS_đi thô — dùng cho checkpoint chấm tay. Trùng ≥2 dòng → raise lỗi, không tự chọn. | `ach/b4_xu_ly_mis_di.py:610-720` | trung bình |
| `SessionId` (GW) | Phiên xử lý dòng GW — phân loại 'thuần nhất'/'lận cận'/'không liên quan', tra SessionId thật cho MIS SESSION=NULL. | `ach/b3_xu_ly_gw.py:27-42`; `ach/b4_xu_ly_mis_di.py:167-257` | cao |
| `SESSION` (MIS) | Phiên xử lý giao dịch MIS — lọc đúng session, xử lý riêng khi rỗng. | `ach/b4_xu_ly_mis_di.py:282-308`; `ach/b6_xu_ly_mis_den.py:121-129` | cao |
| SessionId/SESSION rỗng | "SESSION = NULL" — luồng xử lý riêng, không lọc theo khung giờ (BR mới 2026-07-23). **Chưa quan sát được trong 6 ngày mẫu 31/07–03/08/2026** — SessionId (GW) không có dòng rỗng nào (0/1.077.333), SESSION (MIS_đi/đến raw) cũng rỗng = 0 dòng trong mọi ngày kiểm tra. Không phủ nhận việc case này tồn tại, chỉ chưa gặp trong dữ liệu đã kiểm tra — cần kiểm tra thêm ngày khác. | `ach/zip_utils.py:16`; `ach/b4_xu_ly_mis_di.py:283-284` | trung bình |
| `SessionId = '0000'` | Giá trị đặc biệt trên GW gốc khiến MIS SESSION=NULL được GIỮ lại (nhãn `GW_SESSION_0000`) — ý nghĩa nghiệp vụ của '0000' không được giải thích. Xác nhận dữ liệu thật 31/07/2026: **23/1.077.333 dòng** trên GW gốc mang SessionId='0000' (bên cạnh 3 giá trị session thường: 16446, 16448, 16450). | `ach/b4_xu_ly_mis_di.py:223,241-242` | thấp |
| `'__NHIEU__'` | Marker 1 MSGREF có ≥2 SessionId khác nhau trên GW gốc (dữ liệu chưa dedup) — không tự chọn theo vị trí. | `ach/b4_xu_ly_mis_di.py:167-179,232-233` | cao |
| session_id (từ tên file PDF, `_NRT_(\d+)_`) | Số phiên đối chiếu cả ngày, dùng lọc MIS_đi/đến/GW. | `ach/b1_doc_session.py:6-35` | cao |

### 1.5 Mã trường nguồn GL02 (NPO)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `LOCAC = '502003'` | "Mã đơn vị hạch toán kênh ACH trên GL02". **Xác nhận trực tiếp từ GL02 gốc** (giải mã bằng `ZIP_PASSWORD`, `GL02_20260731_1000.zip`, 3.811.704 dòng, chỉ 2 giá trị LOCAC tồn tại): `502003` = 976.930 dòng (26% tổng), `502001` = 2.834.774 dòng (kênh khác). | `ach/b2_xu_ly_gl02.py:20-23,79-83,112-116` | cao |
| `CUSTOMER = '1000-003526275'` | Mã khách hàng ACH — lọc thêm vì 1 LOCAC có thể có nhiều CUSTOMER. **Xác nhận trực tiếp từ GL02 gốc**: 976.877 dòng (khớp gần đúng với LOCAC=502003, chênh 53 dòng do CUSTOMER khác dùng chung LOCAC). | `ach/b2_xu_ly_gl02.py:21-24,81-83,114-116` | cao |
| `TRBRCD` | Mã chi nhánh GL02, ghép KEY_DI/KEY_DEN, đối ứng `CHI_NHANH` bên MIS. | `ach/b2_xu_ly_gl02.py:137-148` | trung bình |
| `CRAMOUNT ≠ 0` | Dòng GL02 là NPO_đi. | `ach/b2_xu_ly_gl02.py:126-136` | cao |
| `CRAMOUNT = 0` (dùng `DRAMOUNT`) | Dòng GL02 là NPO_đến. | `ach/b2_xu_ly_gl02.py:126-127,143-148` | cao |
| `TRDATE, USERID, JOURSEQ, DYTRSEQ, CCY, BUSCD, UNIT, TRCD, REMARK, CRTDTM` | Chỉ trong danh sách cột đọc (`COLS_NPO`), không có logic phân loại nào dùng. | `ach/config.py:6-10` | không biết |

### 1.6 Mã trường nguồn GW

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `BRCD` | Mã chi nhánh GW — ghép `KEY_GW`, đối ứng `TRBRCD`/`CHI_NHANH`; cũng dùng dò header row. | `ach/b3_xu_ly_gw.py:5-11,177` | trung bình |
| `STTLMAMT` | Số tiền GW (nghi "Settlement Amount") — làm sạch trước khi ghép khoá. | `ach/b3_xu_ly_gw.py:169-177` | trung bình |
| `PrcFlg` | Cờ trạng thái xử lý GW — code chỉ có logic loại rõ ràng cho `'ACH Từ chối'`; **không được dùng để quyết định phân loại Timeout** (chỉ MSGREF mới quyết định). | `ach/b3_xu_ly_gw.py:158-167`; `ach/b4_xu_ly_mis_di.py:438-439` | trung bình |
| `PrcFlg = 'Lệnh Hoàn thành'` | Đa số bản ghi GW (1.076.825/1.077.333 dòng gốc 31/07/2026). Còn lại đầy đủ trong GW sạch đã lọc (`RAW_GW_20260731.csv`: 523.802 dòng). | Dữ liệu thật, không có trong code | cao (hành vi: không bị lọc) |
| `PrcFlg = 'Lệnh Timeout'` | 158/1.077.333 dòng gốc. Vẫn còn 149 dòng trong GW sạch đã lọc — **không bị lọc** giống `ACH Từ chối`. | Dữ liệu thật, không có trong code | trung bình (hành vi rõ, ý nghĩa tên chưa xác nhận) |
| `PrcFlg = 'Đang sửa'` | 23/1.077.333 dòng gốc. **Đợt 3 (2026-08-20) đã xác định được cơ chế:** cả 23 dòng đều có `SessionId = '0000'` (giá trị đặc biệt, xem dòng "SessionId = '0000'" bên dưới) — khác session mục tiêu của ngày 31/07 (16448) — nên bị loại bởi chính bộ lọc session (`b3_xu_ly_gw.py:160-162`, `mask_sai_session`), **không phải bị lọc riêng theo PrcFlg** (code chỉ lọc rõ `'ACH Từ chối'`). Cơ chế biến mất đã rõ; lý do NGHIỆP VỤ vì sao các dòng này mang SessionId='0000' vẫn chưa xác nhận. | `ach/b3_xu_ly_gw.py:160-162`; xác nhận dữ liệu thật `đi GW 31.07.xlsx` | cao (cơ chế); không biết (lý do nghiệp vụ) |
| `PrcFlg = 'Chờ hoàn trả'` | 11/1.077.333 dòng gốc. **Đợt 3 (2026-08-20):** cả 11 dòng đều có `SessionId = '16446'` — session của một ngày TRƯỚC đó (khác 16448 của 31/07) — cùng cơ chế bị lọc bởi `mask_sai_session`, không phải PrcFlg. Có vẻ là các dòng còn sót của phiên trước xuất hiện lẫn trong file GW ngày sau; lý do nghiệp vụ cụ thể chưa xác nhận. | `ach/b3_xu_ly_gw.py:160-162`; xác nhận dữ liệu thật `đi GW 31.07.xlsx` | cao (cơ chế); không biết (lý do nghiệp vụ) |

### 1.7 Mã trường nguồn MIS (đi/đến)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `CHI_NHANH` | Mã chi nhánh MIS, ghép mọi khoá đối chiếu MIS. | `ach/b4_xu_ly_mis_di.py:156-164`; `ach/b6_xu_ly_mis_den.py:139-144` | cao |
| `SO_TIEN` | Số tiền giao dịch MIS — thành phần bắt buộc mọi khoá. | `ach/b4_xu_ly_mis_di.py:122,160-161` | cao |
| `NGAY_GIAO_DICH` | Ngày giá trị giao dịch — so với ngày T/T-1 để giữ/loại MIS SESSION=NULL. | `ach/b4_xu_ly_mis_di.py:213-218`; `ach/b6_xu_ly_mis_den.py:124-127` | cao |
| `NGAY_KENH_TRA` | Parse datetime, hiển thị báo cáo — không thấy logic phân loại dùng trực tiếp. | `ach/b4_xu_ly_mis_di.py:118-127` | thấp |
| `MSGSEQ, TXID, KENH_THANH_TOAN, MA_GIAO_DICH, NOI_DUNG` | Chỉ trong danh sách cột đọc/hiển thị, không có logic riêng. | `ach/b4_xu_ly_mis_di.py:25-30`; `ach/b6_xu_ly_mis_den.py:23-27` | không biết |
| `NH_NHAN` (MIS_đi), `NH_GUI` (MIS_đến) | Cột hiển thị, tên gợi ý "ngân hàng nhận/gửi", không có logic riêng. | `ach/b4_xu_ly_mis_di.py:26-30`; `ach/b6_xu_ly_mis_den.py:23-27` | thấp |

### 1.8 File QT (Quyết toán OSB)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `'STT'` + `'Số tiền'` | Marker dò đúng header row / đúng sheet dữ liệu QT. | `ach/b9_doi_chieu_osb.py:13-21,40-59` | cao |
| `'CN thực hiện'` | `<mã CN> - <tên>`, trích mã số đầu chuỗi làm mã chi nhánh QT. | `ach/b9_doi_chieu_osb.py:96-98` | cao |
| `'Mã giao dịch'` | Số trace QT, bỏ số 0 đầu — đối ứng TRACE bên MIS. | `ach/b9_doi_chieu_osb.py:99` | cao |

### 1.9 Nhãn kết quả tự sinh (nội bộ hệ thống)

| Nhãn | Ý nghĩa | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `GHI_CHU_T2 = 'Hạch toán lệnh ngày T-2'` | Gắn lên dòng NPO_đi/đến thừa khi khớp với MIS thừa T-2. | `ach/b11_doi_chieu_cheo_ngay.py:8` | cao |
| `KETQUA_OSB_DI_KHOP/CHUA`, `KETQUA_OSB_DEN_KHOP/CHUA`, `KETQUA_KHONG_CO_QT`, `KETQUA_THUONG_KHOP/CHUA` | Nhãn `KET_QUA` trên file MIS thừa T-2, theo đúng mẫu docx "NGUYEN TAC DOI CHIEU DIEN MIS THUA NGAY T-1". ⚠️ Giá trị **thật xuất hiện trong dữ liệu** (`MIS_DI/DEN_THUA_T2_KETQUA_*.csv`) là chuỗi tiếng Việt hiển thị, không phải tên hằng số — mapping chính xác (đọc trực tiếp từ code): `KETQUA_OSB_DI_KHOP` = `"lệnh đi OSB ngày T-2 hạch toán QT ngày T-1"`; `KETQUA_OSB_DI_CHUA` = `"OSB đi chưa hạch toán"`; `KETQUA_OSB_DEN_KHOP` = `"lệnh đến OSB ngày T-2 hạch toán QT ngày T-1"`; `KETQUA_OSB_DEN_CHUA` = `"OSB đến chưa hạch toán"`; `KETQUA_KHONG_CO_QT` = `"Không có QT ngày T-1 để đối chiếu"`; `KETQUA_THUONG_KHOP` = `"lệnh ngày T-2 hạch toán ngày T-1"`; `KETQUA_THUONG_CHUA` = `"lệnh chưa hạch toán"`. Cả 4 chuỗi mẫu quan sát được trên dữ liệu 02/08/2026 đều khớp đúng nhóm này. | `ach/b11_doi_chieu_cheo_ngay.py:8,14-20` | cao |
| `LY_DO_GIU_SESSION_NULL` (8 giá trị: `NGAY_GIA_TRI_KHAC_T_VA_T-1`, `GW_GOC_NHIEU_SESSIONID_KHAC_NHAU`, `KHONG_TIM_THAY_TREN_GW`, `GW_SESSION_NULL`, `GW_SESSION_0000`, `GW_SESSION_DOI_CHIEU`, `GW_SESSION_KHAC`, `KHONG_TIM_THAY_TREN_GW_TAI_T-1`) | 8 lý do giữ/loại giao dịch MIS_đi SESSION=NULL, mỗi nhãn có docstring giải thích rõ. | `ach/b4_xu_ly_mis_di.py:182-257` | cao |

### 1.10 Định dạng số tiền

| Mẫu | Ý nghĩa | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `'180000'` | Số thuần, parse trực tiếp. | `ach/so_tien.py:20,24-37` | cao |
| `'180.000'` | Dấu chấm LUÔN là ngăn nghìn, không bao giờ thập phân (chốt với Business Owner 2026-08-10/11). | `ach/so_tien.py:8-21` | cao |
| Mẫu khác (VD `'1.5'`) | Raise lỗi, không đoán 15 hay 1,5. | `ach/so_tien.py:14,30-35` | cao |
| **Quy tắc chung VND — mọi module** | Tiền Việt Nam đồng (VND) LUÔN là số nguyên, không bao giờ có phần thập phân — số thập phân chỉ xuất hiện ở đồng tiền khác VND (áp dụng cho mọi cột tiền ở mọi module: ACH, ILO1000, 459901, Đối chiếu Song phương, không riêng `so_tien.py`). Hệ quả: dấu phẩy `,` xuất hiện trong cột tiền VND (VD `'180,000'`) an toàn để coi là ngăn-nghìn giống dấu chấm, KHÔNG cần lo là dấu thập phân kiểu châu Âu — vì VND không có thập phân. (Xác nhận trực tiếp Business Owner, chat, 2026-08-21 — xem `feedback_ach_so_tien_ngan_nghin` cho bối cảnh bug gốc.) | Xác nhận Business Owner 2026-08-21 | cao |

*Không có logic nghiệp vụ trong `validate.py` (chỉ quy ước đặt tên file) và `ach_service.py` (chỉ trạng thái job kỹ thuật: pending/running/awaiting_confirmation/done/error/cancelled).*

---

## Phần 2 — ILO1000

*Nguồn: `backend/services/ilo1000/` (process.py, config.py, detect.py, load_core.py, load_eicp.py, load_osb.py, export.py).*

### 2.1 Mã trong "Số giao dịch" / "REFERENCE" — quyết định cách tính Trace

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `'S'` trong "Số giao dịch" (Hub) | Giao dịch phải qua bước tra EICP/BFX để lấy Trace, thay vì dùng thẳng Số Trace 1/2. Xác nhận dữ liệu thật (bộ `4-6.7.2026`, ngày 06/07/2026, 88.483 dòng Hub): **49.316/88.483** dòng chứa 'S'. | `ilo1000/process.py:44-48` | cao |
| `'BFX'` trong "Nội dung chuyển tiền" (Hub) | Nhóm 'S': Trace = 16 ký tự cuối nội dung chuyển tiền. Ý nghĩa "BFX" cụ thể chưa rõ. Xác nhận dữ liệu thật: **30 dòng**. | `ilo1000/process.py:49,62-64` | trung bình |
| `'SMF'` trong "Số giao dịch" (Hub) | Loại trừ khỏi tra EICP/BFX dù thuộc nhóm 'S' — Trace lấy từ **"Số Trace 2"** của chính dòng đó, tức trace của GIAO DỊCH GỐC (cùng ý nghĩa "Số Trace 2" đã dùng cho nhóm OT). Xác nhận Business Owner **2026-08-25**, sửa lại quyết định cũ 2026-07-16 ("giữ nguyên Số Trace 1") vốn SAI — nguyên nhân 393 dòng CITAD lệch phát hiện 2026-08-22 (VD REFERENCE `1000API208409150`: Số Trace 1 dòng SMF = `'208275257'` khác hẳn Trace Core tự tính = `'208409150'`; đúng ra phải lấy Số Trace 2 của dòng đó). Danh sách 393 dòng cũ: `G:\Cham ILO1000\Danh_sach_188_lech_CITAD_can_xac_nhan.xlsx` — chờ chạy lại batch 22-24/8 để xác nhận giảm về 0. | `ilo1000/process.py:52-75` | cao |
| Không chứa `'S'` (chủ yếu "OT") | Hoàn trả lệnh gốc — dùng thẳng "Số Trace 2". | `ilo1000/process.py:42-45,58-60` | cao |
| `'API'` trong REFERENCE (Core) | Trace = `REFERENCE[7:23]` — không có comment giải thích "API". Xác nhận dữ liệu thật (44.569 dòng Core sau filter, ngày 06/07/2026): **23.200 dòng**. | `ilo1000/process.py:231,237` | thấp |
| `'OTT'` trong REFERENCE (Core) | Trace = TRBRCD + `REFERENCE[4:16]`. Trùng với literal `'OTT'` mà EICP dùng dựng `map_core` (mục 2.3) — gợi ý mã loại giao dịch nội bộ Core dùng chung với EICP. Xác nhận dữ liệu thật: **21.355 dòng**. | `ilo1000/process.py:232,238`; `ilo1000/load_eicp.py:49` | trung bình |
| `'BFX'` trong REFERENCE (Core) | Trace = TRBRCD + `REFERENCE[4:16]` — cùng công thức OTT. Xác nhận dữ liệu thật: **9 dòng**. | `ilo1000/process.py:233,239` | thấp |
| `'HI'` trong REFERENCE (Core) | Trace = `'Quyết toán'` → TT = `'quyết toán'`. Loại giao dịch quyết toán, không tra Hub/Citad. Xác nhận dữ liệu thật: **1 dòng**. | `ilo1000/process.py:234,240,262-263` | trung bình |
| `'IBPSILO'` trong REMARK (Core) | Giao dịch kênh OSB, ngoài phạm vi ILO1000 → TT = `'OSB'` (sẽ có module Chấm TK OSB riêng), xác nhận qua dữ liệu thật 04-06/7/2026: **3/3 dòng** khớp đúng (toàn bộ dòng REFERENCE dạng `1000OSB` phát hiện ở dòng dưới). | `ilo1000/process.py:265-272` | cao |
| `REFERENCE` dạng `1000ITT...` (VD thật: `1000ITT261005801`) | Trong 44.569 dòng Core (06/07/2026), có đúng **4 dòng** không rơi vào 4 nhóm API/OTT/BFX/HI: 3 dòng `1000OSB` (đã xác nhận thuộc nhóm OSB ở trên) và **1 dòng `1000ITT261005801`** — REMARK là tên công ty, không khớp bất kỳ mẫu nào đã biết. Không có logic xử lý riêng trong code. **Đợt 3 (2026-08-20):** giải mã thật `GL02_20260731_1000.zip` (bản ACH, LOCAC=502003) cho **53 dòng CUSTOMER=`1000-553970732`** (mã lạ, xem Phần 4.1) — REFERENCE **cùng định dạng `1000ITT2610072xx`**, REMARK **100% là "Công ty Cổ phần Thanh toán số Mobifone"**. **Business Owner đã xác nhận (2026-08-20): Mobifone chỉ là khách hàng thuộc hệ thống thanh toán** — cùng một khách hàng/đối tác với dòng `1000-553970732` ở Song phương (Phần 4.1), dùng chung kênh ACH. Câu hỏi kỹ thuật còn lại: vì sao dòng `1000ITT` lẻ này lọt qua filter `LOCAC=501202` của ILO1000 — chưa truy được nguyên nhân, không phải câu hỏi nghiệp vụ. | Dữ liệu thật (Core 06/07 + GL02 31/07 đã giải mã) | cao (danh tính); thấp (cơ chế lọt filter) |

### 2.2 Mã trạng thái xuất ra (cột TT)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `'Hủy'` | Net-zero (tổng Nợ = tổng Có cùng REFERENCE) và ngày lập = ngày hủy. Xác nhận Business Owner 2026-07-16: khác "Đã hủy", không phải lỗi gõ tay. | `ilo1000/process.py:178-206` | cao |
| `'Đã hủy'` | Khác ngày lập/hủy, hoặc thiếu vế gốc trong batch đang xử lý — bắt qua CRAMOUNT<0. | `ilo1000/process.py:178-206` | cao |
| `'quyết toán'` | Dòng Core có Trace = `'Quyết toán'` (loại "HI"), chưa có TT — không cần tra Hub/Citad. | `ilo1000/process.py:261-263` | trung bình |
| `'OSB'` | (a) Core REMARK chứa IBPSILO; (b) Citad thừa khớp trực tiếp khoá OSB. | `ilo1000/process.py:272,320-350` | cao |
| `'citad {day}.{month}'` | Core khớp trúng Map dc của Citad, TRX_DATE thực tế trong cửa sổ đã lọc chỉ có 1 ngày (T) — không có carryover T+1 thật. | `ilo1000/process.py:186-198` | cao |
| `'citad {D1}-{D2}.{M}'` (mới, 2026-08-22) | Cùng cơ chế trên nhưng TRX_DATE thực tế có ≥2 ngày (T + phiên Citad kế tiếp) — nhãn đổi sang dạng khoảng, khớp đúng quy ước người chấm tay quan sát được trên dữ liệu thật (100% dòng khớp Citad trong bài chấm tay `18-19.8.xlsx` dùng ĐÚNG 1 nhãn `'citad 18-19.8'`, không tách theo ngày). Nếu 2 ngày khác tháng → `'citad {D1}.{M1}-{D2}.{M2}'`. Xem mục 2.3a (cửa sổ mở rộng T+1) để biết vì sao giờ có ≥2 ngày. | `ilo1000/process.py:186-198` | cao |
| `'Chờ đi kênh'` (pipeline, cột Hub `Trạng thái`) | "Ngày giờ kênh trả" > ngày đang đối chiếu — Hub tự flag chưa đi kênh xong. **Khác** nhãn thủ công cùng tên người chấm tay tự gõ trực tiếp lên cột TT của Core (xem hàng dưới) — 2 cơ chế độc lập, trùng tên do cùng ý nghĩa nghiệp vụ nhưng khác nguồn sinh ra. | `ilo1000/process.py:91-94` | cao |
| `'OSB mới'` / `'OSB cũ'` | 'Ngày hạch toán' == ngày chấm (T) → mới; carryover ngày trước → cũ. | `ilo1000/load_osb.py:88-93` | cao |
| `''` (rỗng) | Không khớp Hủy/Quyết toán/OSB/Citad/Hub — để chấm tay, "không tự suy luận thêm". | `ilo1000/process.py:373` (map merge, biến `tt`) | cao |
| `'Chờ đi kênh'` (thủ công, cột TT của Core trong bài chấm tay) | ⚠️ Nhãn người chấm **tự gõ tay** lên Core, KHÔNG do pipeline sinh ra — pipeline để trống (`''`) cho các dòng này. Xác nhận dữ liệu thật 2026-08-22 (2 batch tháng 8): tập trung ở ngày CUỐI mỗi batch chấm — bản chất là hiệu ứng biên (dữ liệu Citad của ngày kế tiếp chưa có trong batch đang chấm), KHÔNG PHẢI bug — sẽ tự "biến mất" (được pipeline khớp đúng) khi chấm batch kế tiếp có đủ dữ liệu ngày đó. | Dữ liệu thật, không có trong code | cao (hiện tượng); không biết (quy ước gõ tay chính xác khi nào người chấm dùng nhãn này) |
| `'Đã gửi, chờ phản hồi'` (thủ công) | ⚠️ Nhãn người chấm tự gõ tay, KHÔNG có trong pipeline. **Business Owner xác nhận trực tiếp (chat, 2026-08-22): đây là quy trình thủ công thuần túy** (người chấm tự gửi yêu cầu tra soát/xác minh ở nơi khác và chờ phản hồi) — không suy ra được từ dữ liệu đầu vào hiện có, **không tìm cách tự động hoá**. Đã loại giả thuyết ban đầu "liên quan kênh OSB" — kiểm 2.000 mẫu dữ liệu thật, 0/2.000 dòng có REMARK chứa `IBPSILO`. | Xác nhận Business Owner 2026-08-22; dữ liệu thật không có trong code | cao |
| `'Chờ duyệt chi trả'` (thủ công) | Nhãn người chấm tự gõ tay, khối lượng nhỏ (~5-28 dòng/batch trên dữ liệu thật tháng 8/2026) — chưa điều tra, không có trong code. | Dữ liệu thật, không có trong code | không biết |

### 2.3 Khoá ghép so khớp Hub ↔ Citad ↔ Core ↔ OSB

| Khoá | Công thức | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|---|
| `Trace` (Hub) | Tuỳ nhóm: Số Trace 2 nếu không chứa 'S' hoặc chứa 'SMF' / right(nội dung,16) nếu BFX / tra EICP nếu 'S' không BFX/SMF | Định danh dùng chung đối chiếu Citad và Core | `ilo1000/process.py:54-90` | cao |
| `STC` (Hub, "Số thành công") | Cột gốc đổi tên | Khoá tra `stc_to_trace` — nối SERIAL_NO Citad sang Trace Hub. Tên "STC" không giải thích. | `ilo1000/config.py:24`; `ilo1000/process.py:99,105,136-138` | trung bình |
| `Trace` (Citad) | `VLOOKUP(SERIAL_NO, hub.STC → Trace)` | Gán Trace cho Citad qua khoá SERIAL_NO khớp STC Hub | `ilo1000/process.py:135-138` | cao |
| `Map dc` (Citad) | `LEFT(RELATION_NO,4) + Trace + AMOUNT(int)` | Khoá đối chiếu Citad ↔ Core | `ilo1000/process.py:140-144` | cao |
| `Map dc` (Core) | `TRBRCD + Trace + CRAMOUNT(int)` | Khoá đối chiếu Core ↔ Citad | `ilo1000/process.py:245-247` | cao |
| Khoá OSB | `LEFT(CN thực hiện,4) + Mã giao dịch + Số tiền` | So trực tiếp với 'Map dc' Citad còn thừa — xác nhận dữ liệu thật 2026-08-19 (56/80, 54/84 dòng khớp) | `ilo1000/load_osb.py:78-85` | cao |
| `map chung hub` (EICP) | `BRCD + MSGKEY` | Khoá nối "Số giao dịch" Hub → Core qua trung gian EICP | `ilo1000/load_eicp.py:44-48,58` | cao |
| `Map chung core` (EICP) | `BRCD + 'OTT' + TRSEQ` | Trace tương ứng bên Core — literal `'OTT'` chèn cứng, gợi ý mã loại giao dịch cố định (xem 2.1) | `ilo1000/load_eicp.py:49,59` | trung bình |
| `trace_trangthai`, `trace_sotien` | `{Trace(Hub)→Trạng thái}`, `{Trace(Hub)→Số tiền}` | 2 lookup dự phòng cuối để Core tra TT khi không khớp Citad | `ilo1000/process.py:281-296` | cao |

### 2.3a Cửa sổ khớp Citad↔Core mở rộng sang T+1 ("chờ đi kênh", mới 2026-08-21/22)

**Phát hiện qua đối chiếu thật, không phải tài liệu:** so 74.301+71.613 REFERENCE (2 batch tháng
8/2026) với bài chấm tay VLOOKUP Excel — nhóm lệch lớn nhất (10.251 dòng) là do Core lập ngày T
nhưng thực tế "đi kênh" ở phiên Citad ngày **T+1** (lệnh vào hệ thống core SAU giờ cutoff Citad
ngày T). Pipeline trước đó chỉ so Citad đúng ngày T — 98,2% của nhóm lệch này biến mất sau khi sửa.

| Cơ chế | Công thức | Ý nghĩa | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|---|
| `_citad_forward_days(ngay_int)` | Thứ 2-5 → hôm sau (+1). Thứ 6 → Thứ 2 tuần sau (+3, nhảy T7+CN). Thứ 7/CN → không mở rộng, trả `{T}`. | Cửa sổ ngày nạp Citad cho ngày T đang chấm — đối xứng chiều XUÔI với `_osb_carryover_days()` (chiều NGƯỢC, dùng cho Hub/OSB, mục dưới). Nhánh Thứ 7/CN không mở rộng để không "nhặt nhầm" Citad thật của Thứ 2 kế tiếp vào nhóm carryover-only. | `ilo1000/pipeline.py:39-64` | cao |
| `hub_window = _osb_carryover_days(T) \| _citad_forward_days(T)` | Hợp 2 cửa sổ | **Hub PHẢI cùng cửa sổ với Citad** — Citad tính Trace qua `stc_to_trace` (map từ Hub), 1 dòng Citad dated T+1 có STC chỉ xuất hiện trong Hub CŨNG dated T+1. Thiếu dòng này, Trace resolve rỗng dù `citad_raw` đã đúng cửa sổ — phát hiện SAU khi code "đúng" theo unit test nhưng số liệu thật không cải thiện (1 lớp phụ thuộc dễ bị unit test tối giản che giấu). | `ilo1000/pipeline.py:139` | cao |
| `_osb_carryover_days(ngay_int)` | T + T-1 (ngày thường); T + T-1,T-2,T-3 nếu T là Thứ 2 (nhảy qua T7+CN chiều ngược) | Cửa sổ NGƯỢC cho Hub/OSB — có trước cửa sổ xuôi ở trên, tên hàm giữ nguyên dù giờ dùng chung cho cả 2 chiều | `ilo1000/pipeline.py:22-36` | cao |

**Rủi ro còn lại, đã đánh giá thấp:** nếu 2 giao dịch khác ngày (T và T+1) trong cùng cửa sổ vô
tình trùng khoá `Map dc`, `_first_match()` chỉ giữ dòng xuất hiện trước trong DataFrame — Core có
thể khớp nhầm đúng giao dịch cụ thể dù nhãn TT vẫn đúng dạng khoảng ngày (không lộ ra qua nhãn).
Đã kiểm 0 va chạm thực tế trên 10.251 dòng dữ liệu 18-19/8/2026 — chỉ log CẢNH BÁO, không chặn.

### 2.4 Mã lọc nguồn Core (GL02)

| Mã | Giá trị | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|---|
| `CORE_FILTER_LOCAC` | `'501202'` | Mã đơn vị hạch toán, lọc đúng bút toán kênh Citad/ILO1000 trong GL02 chi nhánh 1000 (ILO1000 chỉ ~2% bút toán). | `ilo1000/config.py:67-71`; `ilo1000/load_core.py:47-59` | cao |
| `CORE_FILTER_CUSTOMER` | `'1000-000007709'` | Mã khách hàng/tài khoản nội bộ, lọc kèm LOCAC. | `ilo1000/config.py:70-71`; `ilo1000/load_core.py:55-59` | trung bình |
| `DRAMOUNT == 0` | filter | Chỉ giữ dòng Core có Nợ = 0 — không rõ lý do nghiệp vụ. | `ilo1000/load_core.py:1,108-111` | thấp |
| `CRAMOUNT < 0` | tín hiệu Hủy | "Số tiền (-) thì là hủy lệnh ngày cũ" — dịch trực tiếp từ quy tắc docx gốc. | `ilo1000/process.py:171-176,200` | cao |

### 2.5 Nhận dạng loại file nguồn

| Loại file | Điều kiện | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `'hub'` | tên bắt đầu `phub_`, đuôi `.xlsx` | `ilo1000/detect.py:15-21` | cao |
| `'osb'` | tên bắt đầu `osb`, đuôi `.xlsx` — HOẶC (mới 2026-08-22, dự phòng) đuôi `.xlsx` bất kỳ có sheet `'Sheet 1'` với dòng tiêu đề chứa "DỮ LIỆU CHI TIẾT HẠCH TOÁN" | `ilo1000/detect.py:20-23,56-70` | cao |
| `'eicp'` | tên chứa `eicp`, đuôi `.xls`/`.xlsx` | `ilo1000/detect.py:24-25` | cao |
| `'core_zip'` / `'core_csv'` | tên chứa `gl02`, đuôi `.zip`/`.csv` | `ilo1000/detect.py:26-29` | cao |
| `'citad'` | đuôi `.csv`, header chứa `SERIAL_NO`, `RELATION_NO`, `TRX_STATUS` | `ilo1000/detect.py:30,35-42` | cao |

*Cột `TRCD, BUSCD, UNIT, CCY, JOURSEQ, DYTRSEQ, USERID, TRTP, CRTDTM` xuất hiện trong `CORE_HEADER`/export nhưng không dùng trong bất kỳ if/else phân loại nào — không đưa vào từ điển vì code không thể hiện ý nghĩa phân loại.*

**Đã verify (2026-08-21/22) — logic "Ngày hạch toán" của OSB (mục 2.2 `'OSB mới'`/`'OSB cũ'`):**
chạy pipeline thật trên 2 batch tháng 8/2026 (`G:\Cham ILO1000\18-19.8.2026\`,
`20-21.8.2026\`), mỗi batch đều có file OSB thật (tên không theo quy ước "osb...", phải nhận diện
qua nội dung — xem mục 2.5) — khớp Citad-thừa qua khoá `LEFT(CN,4)+Mã GD+Số tiền` cho kết quả hợp
lý (45+72 và 50+69 dòng khớp thêm/2 ngày mỗi batch). Không còn là việc treo. Ghi chú lịch sử: 3
file gắn nhãn tháng 7 tại `G:\Cham ILO1000\OSB\` (`OSB n 10.7.xlsx` v.v.) thực chất chứa dữ liệu
tháng 8/2026 — tên file KHÔNG đáng tin về ngày, chỉ đáng tin về ĐỊNH DẠNG file OSB.

---

## Phần 3 — Chấm 459901

*Nguồn: `backend/services/cham459901_service.py`, `backend/api/cham459901.py`. Không có schema riêng trong `backend/schemas/`.*

### 3.1 Bộ lọc đầu vào (chọn dòng thuộc TK 459901)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `LOCAC = "459901"` | Mã tài khoản 459901 — lọc dòng thuộc TK này. Xác nhận dữ liệu thật tháng 7/2026 (`GL02_20260731_1000.zip`, 5.168.865 dòng, chỉ 3 giá trị LOCAC tồn tại: 502001/459901/502003): `459901` = **1.357.161 dòng** (~26,3%). | `cham459901_service.py:32, 331-335` | trung bình |
| `CUSTOMER = "1000-000007709"` | Mã khách hàng/đối tượng cố định, lọc cùng LOCAC/CCY. Xác nhận dữ liệu thật: **1.355.285 dòng** (chênh 1.876 dòng với LOCAC=459901, hợp lý vì còn điều kiện CCY=VND). | `cham459901_service.py:33, 331-335` | thấp |
| `CCY = "VND"` | Loại tiền tệ, điều kiện lọc. | `cham459901_service.py:34, 331-335` | trung bình |

### 3.2 Mã cột dữ liệu gốc (GL02/IPCAS)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `TRDATE` | Ngày giao dịch — chưa rõ, chỉ liệt kê cột. | `cham459901_service.py:39, 49` | thấp |
| `TRBRCD` | Mã chi nhánh — khoá ghép nhóm bước "Chuyển chi nhánh"/"Cân CN"; TRBRCD=1000 nhận diện riêng nhánh Hội sở. | `cham459901_service.py:39, 380, 619, 627` | trung bình |
| `USERID` | Tên đăng nhập giao dịch viên — nhận diện Điện KO offline qua mẫu `<4 số>KO`. | `cham459901_service.py:39, 646` | cao |
| `JOURSEQ` | Số thứ tự bút toán — chưa rõ, không dùng trong phân loại. | `cham459901_service.py:39, 49` | không biết |
| `DYTRSEQ` | Số thứ tự giao dịch — 1 phần khoá xác định cặp Hủy/Normal (`_huy_key`). | `cham459901_service.py:39, 380-381` | trung bình |
| `BUSCD`, `UNIT`, `TRCD` | Chưa rõ, chỉ liệt kê cột, không dùng trong phân loại. | `cham459901_service.py:39` | không biết |
| `TRTP` | Loại giao dịch: `Cancel` / `Normal`, dùng tìm cặp lệnh hủy. **Xác nhận trực tiếp từ GL02 gốc tháng 7/2026** (5.168.865 dòng): đúng chỉ 2 giá trị — `Normal` = 5.163.225, `Cancel` = 5.640, không có giá trị thứ 3. | `cham459901_service.py:39, 383-384` | cao |
| `REFERENCE` | Số tham chiếu — với dòng 1000 Hoàn trả, phần số từ ký tự thứ 8 chính là số Trace của hub. | `cham459901_service.py:39, 542-546, 559` | cao |
| `REMARK` | Nội dung diễn giải — 1 phần khoá "Chuyển chi nhánh" và nhận diện marker `'Remitting Amount:VND'` (Điện KO offline). | `cham459901_service.py:39, 592-598, 637, 647` | cao |
| `DRAMOUNT` / `CRAMOUNT` | Số tiền bên Nợ / bên Có. | `cham459901_service.py:39, 327-328` | cao |
| `CRTDTM` | Thời điểm tạo bút toán — không có trong file "tồn" (comment dòng 46). | `cham459901_service.py:41, 46` | thấp |
| `GHI_CHU` | Cột tự sinh: "Nghi ngờ 1000HT" / "Nghi ngờ Điện KO offline — chưa khớp đủ cặp, cần chấm tay". | `cham459901_service.py:41, 444-450` | cao |

### 3.3 Mã 7 nhóm phân loại kết quả

*Thứ tự phân loại "thác nước" (comment dòng 376-377): Hủy → Đi → 1000 Hoàn trả → Chuyển chi nhánh → Điện KO offline → Cân CN → Khác.*

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `huy` — "Lệnh Hủy" | Cặp `TRTP=Cancel` + `TRTP=Normal` cùng khoá (REFERENCE+TRBRCD+DYTRSEQ+số tiền tuyệt đối). | `cham459901_service.py:227-228, 378-388` | cao |
| `di` — "Lệnh Đi" | Nhóm (TRBRCD + số tiền lớn nhất Nợ/Có + REMARK) có Tổng Nợ = Tổng Có. | `cham459901_service.py:230-231, 390-403` | trung bình |
| `ht1000` — "1000 Hoàn trả" | Khớp cặp Trace hub đi/đến qua REFERENCE TK459 = số Trace hub. | `cham459901_service.py:233-234, 410-423, 541-554` | cao |
| `ccn` — "Chuyển chi nhánh" | Nhóm (số tiền + REMARK không phân biệt hoa/thường) có Tổng Nợ = Tổng Có — 2 chân do 2 chi nhánh ghi. | `cham459901_service.py:236-237, 591-609` | cao |
| `ko` — "Điện KO offline" | Ghép cặp N:N theo số tiền giữa dòng Nợ (REMARK chứa "Remitting Amount:VND") và dòng Có (USERID mẫu `<4số>KO`). | `cham459901_service.py:239-240, 632-666` | cao |
| `can_cn` — "Cân CN" | Nhóm (TRBRCD + số tiền) Tổng Nợ = Tổng Có; TRBRCD=1000 chỉ nhận nếu tổng nhóm >5 tỷ. | `cham459901_service.py:242-243, 612-629` | cao |
| `khac` — "GD khác" | Phần dư không khớp 6 nhóm trên — chấm thủ công. | `cham459901_service.py:245-246, 442-450` | cao |

### 3.4 Nhận dạng file upload

| Mã | Điều kiện | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `'zip'` | `.zip` chứa `'gl02'` | `cham459901_service.py:126-131` | cao |
| `'hub_di'` | `.xlsx` chứa `'quay'` hoặc `'chuyen tien di'` | `cham459901_service.py:135-136, 461` | cao |
| `'hub_den'` | `.xlsx` chứa `'giao dich den'` hoặc `'danh_sach'`+`'den'` | `cham459901_service.py:137-140, 501` | cao |
| `'ton'` | `.xlsx` chứa `'459'` và `'ton'` | `cham459901_service.py:132-134, 339` | cao |

### 3.5 Mã trường trung gian đối chiếu hub đi/đến

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `AMOUNT` | Chuẩn hóa từ "Số tiền thực chuyển" (hub đi) / "Số tiền lệnh gốc" (hub đến). | `cham459901_service.py:467, 475, 508, 516` | cao |
| `TRACE` / `TRACE2` | Chuẩn hóa từ "Số Trace 1"/"Số trace"; TRACE2 = dãy trace thứ 2 khi có 2 dãy cách nhau bởi `;` (kênh ACH-NAPAS). | `cham459901_service.py:468,475,479-498,509,516` | cao |
| `LINK` | Khoá liên kết hub đi↔đến = "Số tham chiếu lệnh gốc" / "Số REF HUB"; override riêng cho ACH-NAPAS. | `cham459901_service.py:472-475, 513-516, 522-538` | cao |
| `'ACH-NAPAS'` | Kênh thanh toán — khi khớp, LINK/TRACE override vì quy tắc chuẩn không áp dụng được. | `cham459901_service.py:469-473, 510-514` | cao |
| `'Remitting Amount:VND'` (marker REMARK) | Đánh dấu dòng Nợ ứng viên Điện KO offline. Xác nhận dữ liệu thật tháng 7/2026: **677 dòng**. | `cham459901_service.py:637, 647` | cao |
| `r'^\d{4}KO$'` (mẫu USERID) | Ứng viên chân Có Điện KO offline. Xác nhận dữ liệu thật tháng 7/2026: **861 dòng**. | `cham459901_service.py:633-636, 646` | cao |

### 3.6 Mã khoá `file_type` (download kết quả)

| Mã | Ý nghĩa | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `VALID_TYPES = {"huy","di","ht1000","ccn","ko","can_cn","khac"}` | Khoá định danh 7 file kết quả — trùng khớp trực tiếp 7 nhóm mục 3.3. | `backend/api/cham459901.py:14, 110-125` | cao |

### 3.7 Golden sample sẵn có (tháng 7/2026)

Có sẵn 7 file kết quả đã chạy pipeline thật tại
`G:\NGOC HA\459 file chấm gửi a Dũng\KetQuaCT\Tháng 7\` (bản trùng ở thư mục
`...\dữ liệu đã chạy chương trình chấm 459901\`) — dùng làm tham chiếu cho các lần kiểm chứng sau:

| File | Nhóm | Số dòng dữ liệu |
|---|---|---|
| `459901_huy_20260805.xlsx` | Lệnh Hủy | 7.994 |
| `459901_di_20260805.xlsx` | Lệnh Đi | 1.294.464 |
| `459901_ht1000_20260805.xlsx` | 1000 Hoàn trả | 42.931 |
| `459901_ccn_20260805.xlsx` | Chuyển chi nhánh | 584 |
| `459901_ko_20260805.xlsx` | Điện KO offline | 370 |
| `459901_can_cn_20260805.xlsx` | Cân CN | 7.930 |
| `459901_khac_20260805.xlsx` | GD khác | 642 |

Kèm `BaoCao_DoiChieu_Tháng7.md` — đối chiếu chương trình vs người chấm tay: 52.623 dòng đối chiếu,
khớp 51.783 (98,4%), lệch nhóm 839, chương trình có nhưng người chấm không có 1 dòng.

---

## Phần 4 — Đối chiếu Song phương

*Nguồn: `backend/services/doi_chieu_song_phuong_service.py`, `backend/api/doi_chieu_song_phuong.py`.*

⚠️ **Module này hiện chỉ có bước PHÂN LOẠI** (nhận zip IPCAS → định tuyến theo ngân hàng + chiều
→ xuất 8 file CSV). **Chưa có bước đối chiếu thật** (so khớp với dữ liệu phía kênh song phương của
từng ngân hàng) — đúng như Business Owner xác nhận 2026-08-20: phần dữ liệu phía kênh song phương
còn thiếu, dự kiến làm trong thời gian tới. Vì vậy phần dưới đây **chỉ có mã/lệnh của bước phân
loại**, chưa có gì để suy luận cho bước đối chiếu (chưa tồn tại trong code).

### 4.1 Mã ngân hàng đối chiếu (`BANK_MAP` / `BANK_NAME`)

| CUSTOMER (mã TK nội bộ) | Mã ngân hàng | Tên ngân hàng | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|---|
| `1000-003046287` | `201` | Vietinbank | `doi_chieu_song_phuong_service.py:39-49` | cao (tên biến `BANK_NAME` đặt tường minh) |
| `1000-003046328` | `202` | BIDV | `doi_chieu_song_phuong_service.py:39-49` | cao |
| `1000-000035720` | `203` | Vietcombank | `doi_chieu_song_phuong_service.py:39-49` | cao |
| `1000-003398630` | `311` | MBBank | `doi_chieu_song_phuong_service.py:39-49` | cao |

**Xác nhận trực tiếp từ dữ liệu GL02 thật** — 4 mã CUSTOMER trên trùng khớp chính xác với 4 giá
trị (ngoài CUSTOMER của module ACH) đã quan sát được khi giải mã `GL02_20260731_1000.zip` (31/07/
2026, đợt kiểm chứng ACH ở Phần 1): `1000-003398630` = 860.987 dòng, `1000-000035720` = 769.973
dòng, `1000-003046328` = 654.928 dòng, `1000-003046287` = 548.886 dòng. Nghĩa là **dữ liệu nguồn
IPCAS phía Song phương đã có thật trong cùng file GL02 mà module ACH đang dùng** — chỉ khác
CUSTOMER filter. Tổng 6 giá trị CUSTOMER quan sát được trong file này (4 mã trên + `1000-003526275`
của ACH + 1 mã lạ) khớp đúng 100% tổng số dòng (3.811.704) — không có CUSTOMER nào bị bỏ sót.

| Mã lạ | Ghi chú | Độ tin cậy |
|---|---|---|
| `1000-553970732` | 53/3.811.704 dòng trong GL02 31/07/2026 (bản ACH), không khớp CUSTOMER của ACH (`1000-003526275`) lẫn 4 mã trong `BANK_MAP`. Không có trong code. **Đợt 3 (2026-08-20):** cả 53 dòng có `LOCAC='502003'` (trùng kênh ACH), `TRBRCD` chủ yếu `1462` (41 dòng) + `1000` (12 dòng), **REMARK 100% là "Công ty Cổ phần Thanh toán số Mobifone"**, `REFERENCE` dạng `1000ITT261007279` — trùng khớp định dạng dòng lạ `1000ITT...` mà ILO1000 gặp (xem Phần 2.1). **Business Owner đã xác nhận (2026-08-20): Mobifone chỉ là khách hàng thuộc hệ thống thanh toán** — dùng chung LOCAC kênh ACH nhưng khác CUSTOMER với ACH gốc, **không phải "ngân hàng thứ 5"** theo nghĩa Song phương (không nằm trong `BANK_MAP` 4 ngân hàng đối chiếu song phương hiện có). | cao |

### 4.2 Quy tắc định tuyến chiều (DEN/DI)

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `CRAMOUNT ∈ {"0","0.0","0.00",""}` (`ZERO_AMOUNTS`) | Dòng vào file **ĐẾN** — "tiền ghi Có = 0 → lệnh nhận về" (comment đầu file). | `doi_chieu_song_phuong_service.py:8,52,245-247` | cao |
| `DRAMOUNT ∈ ZERO_AMOUNTS` | Dòng vào file **ĐI** — "tiền ghi Nợ = 0 → lệnh chuyển đi" (comment đầu file). | `doi_chieu_song_phuong_service.py:9,52,248-250` | cao |
| Cả DRAMOUNT và CRAMOUNT đều thuộc `ZERO_AMOUNTS` | Dòng xuất hiện ở **cả 2 file** ĐẾN và ĐI — "giữ nguyên bản gốc" (comment đầu file, port từ app desktop cũ `Doi_Chieu_Song_Phuong`, không tự thêm logic loại trừ). | `doi_chieu_song_phuong_service.py:10` | cao |
| `file_key` dạng `{ma_nh}_{chieu}` (VD `201_DEN`, `311_DI`) | Khoá định danh 8 file kết quả — 4 ngân hàng × 2 chiều. | `doi_chieu_song_phuong.py:15` | cao |

### 4.3 Mã trường IPCAS dùng trong module này

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| `CUSTOMER` | Khoá định tuyến chính — tra `BANK_MAP`, dòng không khớp mã nào trong 4 ngân hàng bị bỏ qua hoàn toàn (không lỗi, không log). | `doi_chieu_song_phuong_service.py:38-44,240-243` | cao |
| `COLS` (`BUSCD, UNIT, TRCD, CUSTOMER, TRTP, REFERENCE, REMARK, DRAMOUNT, CRAMOUNT, CRTDTM`) | Bộ cột chuẩn IPCAS đảm bảo luôn đủ khi xuất file — **khác với `COLS_NPO` của ACH** (`ach/config.py:6-10`): module này KHÔNG có `TRDATE, TRBRCD, USERID, JOURSEQ, DYTRSEQ, LOCAC, CCY`. Không lọc theo LOCAC (khác ACH/459901 vốn lọc LOCAC trước) — chỉ lọc theo CUSTOMER. | `doi_chieu_song_phuong_service.py:34-36` | cao |
| `REQUIRED_COLS = {"CUSTOMER","CRAMOUNT","DRAMOUNT"}` | 3 cột bắt buộc phải có trong file nguồn, thiếu 1 trong 3 → raise lỗi ngay, không đoán/bỏ qua. | `doi_chieu_song_phuong_service.py:53,224-232` | cao |
| `ZIP_PASSWORD = 'DACwLdHi'` | **Trùng với `ZIP_PASSWORD` của ACH và 459901** (`ach/config.py:4`) — cùng 1 mật khẩu giải nén cho cả 3 module, phù hợp với việc cả 3 đều đọc từ cùng nguồn GL02/IPCAS. | `doi_chieu_song_phuong_service.py:31` | cao |

### 4.4 IPCAS/GL02 (module Phân loại) và Kênh↔Hub (mục 4.5) là 2 pipeline khác nhau

Không giống 3 module kia (ACH/ILO1000/459901 đã có đủ 2 vế để đối chiếu), module Phân loại (4.1-4.3)
**chỉ có vế IPCAS** (định tuyến theo NH+chiều, xuất 8 file CSV) — không tự đối chiếu với bên nào.
Bước đối chiếu song phương thật (mục 4.5) hoá ra dùng **nguồn dữ liệu hoàn toàn khác** — không phải
"vế kênh còn thiếu của IPCAS" như suy đoán ban đầu (2026-08-24), mà là 2 file riêng: HUB
(`doichieugd_*.zip`) và kênh Excel do ngân hàng đối tác gửi trực tiếp cho nghiệp vụ đối chiếu song
phương — xem 4.5.

### 4.5 Đối chiếu Song phương — Kênh↔Hub chiều ĐẾN

*Nguồn: tài liệu quy trình chính thức `đối chiếu kênh hub Song phương.docx` (Business Owner cung
cấp 2026-08-22) + kiểm chứng bằng dữ liệu thật 3 ngày (21-23/08/2026, 2 vòng khảo sát read-only +
join thật 100% dữ liệu, không lấy mẫu) + code
`backend/services/doi_chieu_song_phuong_kenh/` (triển khai + chủ dự án duyệt 2026-08-25).*

⚠️ Bản thiết kế đầu tiên (2026-08-24, dựa trên module Phân loại IPCAS + khoá "Ngày+Số tiền") **sai
gốc rễ** — đã xoá toàn bộ code cũ (`doi_chieu_song_phuong_den*`). Mục này viết lại hoàn toàn theo
tài liệu + dữ liệu thật, không còn dấu vết thiết kế cũ.

**Đầu vào — 2 nguồn, định tuyến theo mã ngân hàng, KHÔNG phải 2 nguồn gộp chung:**

| Mã trong tên file HUB | Ngân hàng | Đợt này có dữ liệu? |
|---|---|---|
| `04` | 201 (Vietinbank) | Không (để dành mở rộng) |
| `05` | 202 (BIDV) | Có |
| `06` | 203 (Vietcombank) | Có |
| `07` | 311 (MBBank) | Không (để dành mở rộng) |

File HUB: `doichieugd_YYYYMMDD__{mã}_DEN_9999_N.zip`, 1 CSV bên trong, UTF-8 BOM, 14 cột:
`NGAY_GIAO_DICH, CHI_NHANH, REFHUB, MSGREF, MSGSEQ, TXID, KENH_THANH_TOAN, TRANG_THAI_LENH,
SO_TIEN, TRACE, SESSION, LOAI_LENH_OSB, NH_GUI, NOI_DUNG`. `MSGREF`/`TXID` luôn có dấu nháy đơn `'`
đầu giá trị (Excel text-prefix), phải strip trước khi dùng làm khoá — độ tin cậy cao, xác nhận 100%
trên toàn bộ dữ liệu 3 ngày.

File kênh: đã quan sát **3 quy ước đặt tên khác nhau** trên 3 đợt dữ liệu — `kênh đến {SPRT|SPT}
{mã_nh}.xlsx` (chuẩn, 21-23.8), `kênh đến {mã_nh} {SPRT|SPT}.xlsx` (đảo thứ tự, 25.8), `kenh
{SPRT|SPT} den {mã_nh} {ngày}.xlsx` (không dấu + kèm ngày, bộ dữ liệu 201/311 `TRANG/`,
2026-08-27). **Từ 2026-08-27, `find_kenh_path()` chuyển sang so khớp theo TỪ KHOÁ trong tên file**
(bỏ dấu + hạ chữ thường + tách token, cần đủ {`kenh`, mã NH, loại}) thay vì thử từng chuỗi cố định
— chịu được biến thể đặt tên tiếp theo mà không cần sửa code. Cấu trúc nội dung luôn đúng 5 cột
`STT, Ngày GD, Giờ truyền nhận, MtId/MsgId, Số tiền`.

**SP THƯỜNG — ĐÍNH CHÍNH 2026-08-27: KHÔNG phải "chỉ 202".** Dữ liệu thật `kenh SPT den 201
24.8.xlsx` (15.781 dòng, đúng cấu trúc) xác nhận **NH 201 CŨNG CÓ nghiệp vụ SPT** — nhận định cũ
"SPT chỉ áp dụng NH 202" (2026-08-25) ngoại suy quá rộng vì lúc đó chỉ mới có dữ liệu 202/203.
**NH 203 và 311 xác nhận KHÔNG có nghiệp vụ SPT** (203: chủ dự án xác nhận trực tiếp 2026-08-25 +
file HUB `06` luôn 0 dòng `SP THUONG`; 311: không có file `kenh SPT ... 311` trong bộ dữ liệu đầy
đủ cung cấp 2026-08-27, xử lý bằng đúng 1 cơ chế với 203 — không có mặt trong `RECONCILE_UNITS`).

**Khoá đối chiếu — existence-check, không dung sai:**

| Loại | Khoá HUB | Khoá kênh | Tỉ lệ khớp thật (3 ngày, full data) |
|---|---|---|---|
| SP REALTIME (202) | `MSGREF` (strip `'`) | `MtId/MsgId` (SPRT 202.xlsx) | 99,99% |
| SP REALTIME (203) | `MSGREF` (strip `'`) | `MtId/MsgId` (SPRT 203.xlsx) | 99,99% |
| SP THUONG (202) | `TXID` (strip `'`) | `MtId/MsgId` (SPT 202.xlsx) | 100,00% |

Độ tin cậy **cao** — không chỉ suy luận định dạng, đã xác nhận bằng join thật trên toàn bộ 3 ngày
(2.576.053 dòng HUB), kèm đối chiếu tuyệt đối số tiền (`doc_so_tien()`, 0 cặp lệch/873.189+ cặp
khớp mỗi ngày).

**Tiền xử lý bắt buộc trước khi đối chiếu** (`load_hub.filter_before_reconcile()`, dùng chung cho
cả Bảng 1 và đối chiếu chi tiết vì cùng 1 điểm lọc):
1. Loại dòng HUB có `-` trong `TXID` — bản ghi huỷ/đảo (trạng thái `WFPG`/`CGBR`) tham chiếu ngược
   bản ghi gốc (`WTSC`/`RTSC`) qua `TXID` dạng ghép `<txid_gốc>-<chuỗi khác>`, không phải giao dịch
   độc lập. Tỉ lệ thật rất nhỏ (~0,001-0,002% dòng HUB).
2. Loại cặp dòng có **cùng `TXID` và cùng `TRACE`** — cũng là giao dịch huỷ (xác nhận Business Owner
   2026-08-26). Xác nhận bằng dữ liệu thật 25.8: NH 202 có đúng 2 cặp/4 dòng (trạng thái `RFED`,
   cùng số tiền), NH 203 không có. TXID/TRACE rỗng bị loại khỏi bước gom nhóm trước (nhiều dòng
   `RJCT` có `TRACE` rỗng, nếu không loại sẽ ra cặp "trùng" giả). Nhóm >2 dòng cùng cặp bị coi là
   bất thường, log cảnh báo riêng thay vì âm thầm loại.

**Trạng thái `TRANG_THAI_LENH`** — tài liệu liệt kê 13 mã; dữ liệu thật 3 ngày quan sát 10/13
(`PYED, SBSC, WFPG, RFED, SBFL, RJCT, SDEB, WBIL, PYEK, WTSC`) + 3 mã lạ đã xác nhận là hợp lệ
(`RTSC, CGBR, WTBR`, chỉ SP THUONG, ~10 dòng/2,58 triệu). `RJCT` là trạng thái **duy nhất** được coi
"đương nhiên một phía" (hub-only hợp lệ, không cảnh báo) — xác nhận bằng dữ liệu thật: 100% dòng
"chỉ-hub" trong toàn bộ 3 ngày (277+ dòng) đều là `RJCT`. Mọi trạng thái khác lọt vào nhóm chỉ-hub là
tín hiệu cảnh báo (guard `process.check_unexpected_one_sided()`).

**Cut-off 17h (ngày giá trị)** — cột `Ngày GD` phía kênh gán ngày kế tiếp (D+1) cho giao dịch nhận
sau 17:00:00 cùng ngày — chủ dự án xác nhận đây đúng là quy tắc nghiệp vụ (2026-08-25). Hệ quả thiết
kế: đối chiếu nhóm theo **thư mục/tên file ngày** (ngày trong tên file HUB), KHÔNG lọc theo cột
`Ngày GD` — đã xác nhận 0% rò rỉ xuyên ngày trên toàn bộ 2.575.767+ cặp khớp 3 ngày.

**Output** — 2 phần, tách file riêng (2026-08-27, theo tài liệu `đối chiếu Song phương v3.docx`,
**thay hẳn** thiết kế "Bảng 3" cũ đã duyệt Phase 9, xem nhật ký cập nhật cuối file):
1. **Bảng 1 tổng hợp** (`doi_chieu_song_phuong_kenh_tonghop.xlsx`, sheet `Bang1_TongHop`) — không
   đổi: 1 dòng/ngày/đơn vị, số món + số tiền HUB so kênh, chênh lệch (cột 1-6 theo tài liệu).
2. **Chi tiết row-level** (`process.classify_kenh_hub_den()`) — thay "Bảng 3" (tổng hợp theo
   `TRANG_THAI_LENH`) bằng gắn cột trạng thái vào **từng dòng** của chính file kênh/hub gốc, xuất
   riêng mỗi đơn vị: `hub_{ma_nh}_{loai}_{ngay}.csv` (nguyên file HUB, **chưa** qua
   `filter_before_reconcile` — khác Bảng 1) + `kenh_{ma_nh}_{loai}_{ngay}.xlsx`. 5 nhãn theo đúng
   Bước 1/2 tài liệu, thứ tự waterfall trên-xuống (dừng ở bước đầu khớp):
   - File kênh, cột `TRẠNG THÁI TẠI HUB`: khớp khoá → `TRANG_THAI_LENH` của hub; không khớp →
     `"KÊNH THỪA"` (Bước 1.2).
   - File hub, cột `TRẠNG THÁI KÊNH`: `(TXID,TRACE)` trùng dòng khác → `"GD có trace hủy"` (Bước
     2.1); `-` trong TXID → `"GD chuyển tiếp"` (Bước 2.2); RJCT + không khớp → `"GD Đã từ chối-kênh
     không thành công"` (Bước 2.3); khớp → `"KÊNH THÀNH CÔNG"` (Bước 2.4); còn lại → `"HUB THỪA"`
     (Bước 2.5).

   ⚠️ **Chưa rõ/giả định cần verify** — Bước 2.3 trong tài liệu chỉ ghi "không trùng với MSGREF"
   (không nhắc lại "TXID đối với SP THƯỜNG" như các bước 1.1/2.4 khác). Code hiểu đây là viết tắt,
   dùng khoá **nhất quán theo loại** (MSGREF cho SPRT, TXID cho SPT) — độ tin cậy trung bình, cần
   verify với dữ liệu SPT thật (đơn vị 202-SPT) khi có.

Tài liệu còn mô tả đầy đủ **chiều ĐI** (Bảng 1 cột 1-6 theo trạng thái `SCNL`, đối chiếu chi tiết 2
bước đơn giản hơn — không cần lọc trace-hủy/`-` trước) — quyết định 2026-08-27: **vẫn chưa làm**,
giữ nguyên quyết định hoãn 2026-08-25, chỉ backlog. Tính năng "Nguyên nhân chênh lệch nhập tay + lưu
lịch sử" (có trong tài liệu từ v1, đè lên Bảng 1) — **vẫn chưa làm**, cũng backlog (cần bảng DB +
API + UI riêng, không phải thay đổi nhỏ).

**Nhận diện ngân hàng từ nội dung `MtId/MsgId`, không chỉ tên file** (nguồn:
`G:\ĐỐI CHIẾU SONG PHƯƠNG\ĐỐI CHIẾU SONG PHƯƠNG\lyxink.txt`, Business Owner cung cấp 2026-08-25) —
10 ký tự đầu của `MtId/MsgId` là mã cố định theo ngân hàng, **chỉ áp dụng SP REALTIME**: `0200970415`
→ 201, `0200970488` → 202, `0200970436` → 203, `0200970422` → 311. Độ tin cậy **cao** — verify 100%
trên 4 file thật (202+203 × ngày 21.8+24.8, 1.736.063 dòng, 0 dòng lệch prefix). Vì `MSGREF` (HUB SP
REALTIME) = `MtId/MsgId` (kênh) khi khớp tuyệt đối (xem bảng khoá đối chiếu trên), quy tắc prefix
này áp dụng được cho cả 2 phía. **Chưa verify được cho SP THUONG** (khoá SPT là số tuần tự 16 chữ
số, không quan sát được cấu trúc prefix theo NH) và **chưa verify được cho NH 201/311** (chưa có file
kênh SPRT thật của 2 NH này). Giá trị sử dụng: guard validate file kênh đúng NH đã khai báo qua tên
file (đề xuất, chưa triển khai — xem plan `vast-mapping-tome.md` mục "Bổ sung — nhận diện NH").

**Quyết định nghiệp vụ đã chốt (2026-08-25, không suy luận thêm):**
- Không lưu lịch sử DB (khác yêu cầu "lưu lại lịch sử các lần chấm trước" trong docx — chủ dự án
  chốt bỏ yêu cầu này, theo pattern 459901: chạy nền → tải kết quả → tự dọn).
- Chỉ làm chiều ĐẾN; `config.py` tham số hoá mã NH↔file + chiều để mở rộng chiều ĐI/NH 201,311 sau
  mà không cần đổi kiến trúc — chưa code logic chiều ĐI.
- Route/feature-code: `doi_chieu_song_phuong_kenh` (menu + action riêng), độc lập route
  `doi_chieu_song_phuong` (module Phân loại, 4.1-4.4) — 2 module không liên quan nhau.

**Bổ sung 2026-08-26** (đối chiếu lại tài liệu Word gốc, phát hiện thiếu 1 điều kiện):
- Mục 1.2/2.2 tài liệu còn yêu cầu loại thêm cặp dòng HUB có **cùng TXID và cùng TRACE** (giao dịch
  huỷ) — `filter_before_reconcile()` đã bổ sung, verify dữ liệu thật 25.8: NH 202 có đúng 2 cặp/4
  dòng (trạng thái `RFED`), NH 203 không có.
- Tên file kênh 25.8 đảo thứ tự (`kênh đến {mã_nh} {loại}.xlsx` thay vì `{loại} {mã_nh}`) —
  `load_kenh.find_kenh_path()` chấp nhận cả 2 thứ tự. Độ tin cậy trung bình (mới quan sát 1 ngày).
- Bỏ dòng "N/A" cho (203, SPT) khỏi Bảng 1 (quyết định chủ dự án — quy luật cấu trúc đã chắc chắn,
  không cần hiển thị tường minh nữa) — xoá `FULL_MATRIX_NOTE`.

### 4.6 Đối chiếu Song phương — Hub↔Core chiều ĐẾN (chân thứ 3)

*Nguồn: `G:\ĐỐI CHIẾU SONG PHƯƠNG\ĐỐI CHIẾU SONG PHƯƠNG\đối chiếu Song phương.docx` mục "Đối chiếu
kênh – core" (tên mục lệch — nội dung thực chất HUB↔CORE, không dùng file kênh) + verify dữ liệu
thật 21-25/08/2026 + code `backend/services/doi_chieu_song_phuong_core/` (2026-08-26).*

Chân thứ 3 của mô hình kênh-hub-core, khác hẳn 2 chân đã có: đối chiếu theo **cửa sổ nhiều ngày**
(core T so hub T/T-1/T-2/T-3; hub T so core T/T+1/T+2/T+3), có thêm nguồn dữ liệu thứ 3 (**file
OSB**, `osb {mã_nh}.xlsx`) cho các dòng hub còn thừa sau khi so hết với core.

**Khoá đối chiếu chính (Bước 1.4/2.2):** `TRBRCD + SO_TRACE + DRAMOUNT` (core) so
`CHI_NHANH + TRACE(lstrip '0') + SO_TIEN` (hub). `SO_TRACE` = `REFERENCE` bỏ tiền tố `1000API`,
**bỏ số 0 đầu** — tài liệu không nói rõ bước lstrip này nhưng dữ liệu thật xác nhận bắt buộc (raw
so khớp 0/18.952, sau lstrip 18.029/18.952). Độ tin cậy cao (có dữ liệu thật kiểm chứng).

**Khoá đối chiếu OSB (Bước 2.6) — khác khoá core, không lstrip:** `CHI_NHANH + TRACE` (hub,
nguyên bản) so `4 ký tự đầu "CN thực hiện" + "Mã giao dịch"` (OSB). Verify: khớp RAW 100%
(8.117/8.117, NH 202 21.8). Kết quả gán nhãn `"OSB & {Ngày hạch toán}"`.

**3 nhóm core không cần khớp hub:**
| Nhóm | Điều kiện | Nhãn KETQUADOICHIEU |
|---|---|---|
| Huỷ cùng ngày | `TRBRCD+REFERENCE` trùng ≥2 dòng, tổng DRAMOUNT=0 | `core T hủy T` |
| Quyết toán OSB hàng ngày | `REFERENCE == "1000OSB"` — BO xác nhận: thường 1 điện/ngày | `GD QT OSB` |
| Quyết toán vốn | `TRBRCD=="1000"` và `REMARK` chứa "Quyet toan von" (không phân biệt hoa/thường) | `GD QT vốn` |

Độ tin cậy cao cho cả 3 — verify dữ liệu thật 21.8 (nhóm QT vốn: 3 dòng thật, gồm đúng dòng
`1000API3901984` 180 tỷ từng bị coi là bất thường ở khảo sát trước module này).

**Kiến trúc code:** module mới `backend/services/doi_chieu_song_phuong_core/` (không sửa module
phân loại IPCAS hay module kênh↔hub, chỉ thêm 2 hàm tái dùng vào `load_hub.py`:
`filter_before_reconcile_core` — như `filter_before_reconcile` + loại thêm RJCT; `build_key_hub_core`).
`pipeline.py` dò file HUB/CORE theo ngày ở **cả thư mục ngày lẫn thư mục cha** (quyết định người
dùng 2026-08-26, vì 1 số ngày dữ liệu được cấp rời không có thư mục riêng). Output: 3 sheet
(TongHop + Core_ChiTiet + Hub_ChiTiet, quyết định người dùng — cần cả chi tiết lẫn tổng hợp).

**Test:** 34 test mới (27 thuật toán + 7 API), 71/71 test toàn nhóm song phương pass. Chạy thật
ngày 24.8 đang tiến hành khi viết mục này — xem `Implementation-notes.html` card 86 để biết kết
quả cuối.

### 4.7 Đối chiếu Song phương — chiều ĐI (Kênh↔Hub + Hub↔Core)

*Nguồn: `Đối chiếu SP chiều đi.docx` (bản đầu) → `Đối chiếu SP chiều đi V2.docx` (Hương Ly — người
chấm thủ công phía Business — cung cấp 2026-09-04, sửa 2 điểm so bản đầu) + verify dữ liệu thật
NH 201/311 (01-02/09) + NH 202/203 (27/8-2/9, 8 ngày) + đối chứng chéo với file người soát tự chấm
tay ngày 28/8 (2 ngân hàng) + code `backend/services/doi_chieu_song_phuong_core_di/` +
`doi_chieu_song_phuong_kenh/` (tham số `chieu`).*

**Khoá Kênh↔Hub — khác chiều đến ở đúng 1 điểm (SPT):**

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| SPRT (SP REALTIME) — khoá `MSGREF` | Giống hệt chiều đến, không tranh cãi. | `kenh/config.py::LOAI_KHOA_HUB` | cao |
| SPT (SP THƯỜNG) chiều **ĐẾN** — khoá `TXID` | Verify dữ liệu thật NH 202 21.8: `TXID` khớp `kênh.MtId/MsgId`, `MSGREF` cùng dòng khác hẳn dạng. | `kenh/config.py::LOAI_KHOA_HUB` | cao |
| SPT (SP THƯỜNG) chiều **ĐI** — khoá `MSGREF` (KHÁC đến) | ⚠️ V1 docx-đi ghi TXID (copy nguyên câu từ mẫu đến, không cập nhật) — dùng TXID cho khớp 0/X mọi ngày trên dữ liệu thật NH 202 (7 ngày); dùng MSGREF khớp 93-99%. **V2 docx sửa thẳng thành MSGREF, và Hương Ly xác nhận trực tiếp** — đã chốt bằng cả văn bản chính thức lẫn dữ liệu thật, không còn là suy luận. | `kenh/config.py::LOAI_KHOA_HUB_DI` | cao — xác nhận tài liệu chính thức (`Đối chiếu SP chiều đi V2.docx`, 2026-09-04) |

**Khoá Hub↔Core — cấu trúc giống hệt chiều đến (`TRBRCD+SO_TRACE+DRAMOUNT` ↔
`CHI_NHANH+SE_TRACE+SO_TIEN`), khác ở 3 điểm:**

| Mã | Ý nghĩa suy luận | Nguồn (file:line) | Độ tin cậy |
|---|---|---|---|
| Cửa sổ CORE rộng gấp đôi đến (T-3..T+3 thay vì T..T+3) | Phục vụ nhánh "hủy chéo ngày" (6 nhãn `core T±N hủy T`) mà chiều đến không có (đến chỉ có `core T hủy T` cùng ngày). | `core_di/config.py::OFFSET_CORE_CAN_DOC` | cao (đúng câu chữ docx Bước 2.11-2.16) |
| `TRANG_THAI_HUB_DOI_CHIEU = ("SCNL", "TPAY")` — phạm vi HUB đưa vào Hub↔Core | Docx chỉ nói SCNL (Bước 1.1) — **không nhắc TPAY** (đã grep toàn văn V1 lẫn V2, không có). Verify 4 ngày dữ liệu thật NH 311 (28-31/8) đối chứng với file "chấm" tay người soát: dòng HUB `TPAY` được coi khớp bình thường như SCNL, không bị loại. | `core_di/config.py` | ⚠️ trung bình — dựa dữ liệu thật + đối chứng người soát, KHÔNG có xác nhận bằng câu chữ văn bản (docx im lặng về TPAY) |
| Khoá OSB (Bước 1.7) — `CHI_NHANH+SE_TRACE+SO_TIEN` (hub) ↔ `4 ký tự CN thực hiện+Mã giao dịch+Số tiền` (OSB) | V1 docx CHỈ 2 phần (không có SO_TIEN) — verify công thức 2 phần khớp ~99,9% dữ liệu thật nhưng để lại 22-35 khoá trùng/ngày (cặp giao dịch gốc+đảo/huỷ, số tiền +X/-X). **V2 docx thêm SO_TIEN vào cả 2 phía** — vì `HUB.SO_TIEN` LUÔN DƯƠNG (verify 100%, 0 dòng âm cả NH 202/203), ghép SO_TIEN tự động chỉ khớp được dòng OSB dương (đúng dòng gốc) mà không cần rule riêng. Hương Ly xác nhận trực tiếp: "lấy giao dịch có số tiền dương". Số tiền OSB parse qua `doc_so_tien()` — bỏ dấu `.`/`,` ngăn nghìn, GIỮ NGUYÊN dấu `-` (không ép `abs()`, vì dấu `-` là bút toán đảo/huỷ có ý nghĩa thật). | `core/load_osb.py::build_key_osb_di()`, `build_key_hub_osb_di()` | cao — xác nhận tài liệu chính thức (V2, 2026-09-04) + verify dữ liệu thật (0 khoá trùng còn lại) |

**`TRANG_THAI_LENH` — bộ giá trị đầy đủ quan sát được + ý nghĩa (từ bảng tra cứu nội bộ
`Status-Hub.xls`, không phải docx đối chiếu):**

| Mã | Ý nghĩa (Status-Hub) | Ghi chú đối chiếu | Độ tin cậy |
|---|---|---|---|
| `SCNL` | Hoàn thành | Trạng thái chính, luôn vào Hub↔Core | cao |
| `ERPO` | Hạch toán lỗi | Loại khỏi Hub↔Core, không có nhãn riêng | cao (ý nghĩa) / trung bình (loại đúng không) |
| `CALD` | Đã hủy | Loại khỏi Hub↔Core, không có nhãn riêng | cao (ý nghĩa) / trung bình (loại đúng không) |
| `TPAY` | TT Timeout | Coi như SCNL trong Hub↔Core-đi (xem bảng trên) — ý nghĩa "timeout xác nhận", không phải "hỏng/từ chối", củng cố lý do hợp lý cho việc coi là khớp được | trung bình (ý nghĩa cao, việc gộp SCNL vẫn chưa có xác nhận văn bản) |
| `WTPA` | Chờ duyệt chi trả | Tra ngược HUB gốc (Bước 2.17), nhãn `"core T hub Chờ duyệt chi trả"` — chưa có ca thật để verify | cao (đúng câu chữ docx) |
| `TPER` | TT Lệnh lỗi | Tra ngược HUB gốc (Bước 2.18), nhãn `"core T hub TT lệnh lỗi"` — CÓ ca thật (28/8, NH 311, 1 dòng, khớp đúng ghi chú tay của người soát) | cao |

**Kết quả verify (tham khảo nhanh, chi tiết đầy đủ ở `Implementation-notes.html` card 118):** NH
201/311 (mẫu đầu) Kênh↔Hub cân bằng tuyệt đối; NH 311 4 ngày đối chứng người soát khớp gần tuyệt
đối sau khi thêm TPAY; NH 202/203 8 ngày (27/8-2/9) đối chứng người soát ngày 28/8: core khớp
99,97-99,999%, hub khớp ~100% (sau khi quy đổi ký hiệu ngày "T"/"T±N" ↔ ngày cụ thể — 2 nguồn dùng
2 quy ước khác nhau, phải quy đổi trước khi so mới ra đúng số lệch thật).

---

## Phần 5 — Khoảng trống & việc cần Business Owner xác nhận

**Đợt 2 (kiểm chứng dữ liệu thật) đã hoàn thành** cho cả 3 module — ACH (6 ngày, 31/07–03/08/2026),
ILO1000 (bộ `4-6.7.2026`), 459901 (tháng 7/2026, gồm cả verify trực tiếp GL02 gốc bằng
`ZIP_PASSWORD`). Phần lớn từ điển đợt 1 đã được xác nhận đúng bằng số liệu thật. Các khoảng trống
còn lại xếp theo mức ưu tiên:

### Ưu tiên cao — cần hỏi Business Owner trước khi dùng để phân tích

- **`PYED` / `SBSC`** (ACH, `TRANG_THAI_LENH` trên MIS_đến) — chiếm **>95% khối lượng** MIS_đến
  (PYED ~88-93%, SBSC ~7-8%) nhưng hoàn toàn không có trong code/comment nào. Code chỉ lọc riêng
  `RJCT`, mọi giá trị khác (kể cả 2 mã chiếm đa số này) đi thẳng qua không phân loại. Đây là
  khoảng trống lớn nhất của toàn bộ từ điển.
- **⚠️ 2 file `GL02_20260731_1000.zip` khác nhau, cùng tên (phát hiện đợt 3, 2026-08-20).**
  Tồn tại ở 2 nơi: `G:\ACH CHUA DOI CHIEU NGAY 31.07-02.08\31.07\` (131,8MB, sửa 03/08, MD5
  `739f5956...`) và `G:\NGOC HA\459 file chấm gửi a Dũng\Tháng 7\Dữ liệu chấm\` (171,8MB, sửa
  04/08, MD5 `c84e78e6...`) — **kích thước, ngày sửa, MD5 đều khác nhau, chắc chắn là 2 file vật
  lý riêng biệt** dù cùng tên. Giải mã bản ACH ra 3.811.704 dòng (LOCAC=459901 → **0 dòng**);
  trong khi Phần 3.1 (459901) ghi nhận "GL02_20260731_1000.zip, 5.168.865 dòng" (LOCAC=459901 →
  1.357.161 dòng) — chắc chắn đợt xác minh 459901 đã dùng **bản khác** (nhiều khả năng bản NGOC
  HA) chứ không phải bản dùng cho xác minh ACH/Song phương ở Phần 1/Phần 4. **Cần Business Owner
  xác nhận bản nào là chuẩn / vì sao có 2 bản khác nhau cùng tên** — chưa tự chọn bản nào để verify
  lại số liệu 459901.

### Ưu tiên trung bình

- **4 giá trị `PrcFlg` khác `'ACH Từ chối'`** (ACH, GW) — **đợt 3 (2026-08-20) đã làm rõ cơ chế
  kỹ thuật** cho 2/4 giá trị: `Đang sửa` (SessionId='0000') và `Chờ hoàn trả` (SessionId='16446',
  session trước đó) đều biến mất khỏi GW sạch do bị lọc bởi điều kiện SESSION SAI
  (`b3_xu_ly_gw.py:160-162`), **không phải lọc theo PrcFlg** như nghi ngờ trước đó. `Lệnh Timeout`
  vẫn không bị lọc (còn nguyên trong GW sạch). Còn lại cần hỏi: **vì sao** các dòng `Đang sửa`
  mang SessionId đặc biệt `'0000'`, và vì sao dòng `Chờ hoàn trả` của phiên trước lại xuất hiện
  trong file GW của phiên sau — đây là câu hỏi nghiệp vụ, không còn là bí ẩn kỹ thuật.
- **459901 — "58 + 4 dòng lạ"** chưa khớp nhóm nào trong 7 nhóm phân loại, ghi nhận sẵn trong tài
  liệu chính thức `G:\NGOC HA\Quy_trinh_cham_459901.docx` (mục 7) và
  `Quy_trinh_thuat_toan_Cham_459901.md` (mục 7, nguồn 3 — xem Nhật ký cập nhật cuối file) — Business
  Owner (chị Hà) cần xem lại xem có phải 1 loại nghiệp vụ mới ngoài 7 nhóm hiện có hay không.

### Ưu tiên thấp — hiếm gặp, có thể là lỗi gõ nhưng chưa chắc

- `TOPO`, `TXTF` (ACH, MIS_đi) — đợt 1 mỗi mã chỉ 1 dòng/6 ngày mẫu; **đợt 3 (2026-08-20) kiểm tra
  thêm 6 ngày khác** (~3,7 triệu dòng), không xuất hiện lại — củng cố khả năng là ca hiếm/lỗi gõ.
- Các mã "không biết"/"thấp" đã liệt kê ở đợt 1 mà đợt 2 không đụng tới, VD `CALD/ERPO/TPER` (ý
  nghĩa tên, không phải hành vi), `DRAMOUNT==0` filter (ILO1000 Core) — chỉ xác nhận được qua
  người/tài liệu quy trình nghiệp vụ nội bộ, không suy ra thêm được từ code hay dữ liệu.

### Việc kỹ thuật còn treo

- **OSB tháng 7/2026 (ILO1000)**: chưa có dữ liệu thật hợp lệ trên đĩa để verify logic
  "Ngày hạch toán" (`'OSB mới'`/`'OSB cũ'`, mục 2.2) — 3 file gắn nhãn tháng 7 thực chất là dữ
  liệu tháng 8 (xem ghi chú ở cuối Phần 2).
- **GL02 (ACH)**: đã verify trực tiếp thành công bằng `ZIP_PASSWORD` có sẵn trong
  `ach/config.py:4` (đọc stream qua `pyzipper`, không cần công cụ ngoài) — không còn là việc treo.
- **Đối chiếu Song phương (Phần 4)**: chưa phải khoảng trống trong từ điển — là khoảng trống trong
  hệ thống (chưa có code đối chiếu, chưa có dữ liệu kênh). Xem mục 4.4. **Đợt 3 đã tìm thêm** ở
  `G:\dữ liệu SP\` (chỉ có 8 file IPCAS đã phân loại — sản phẩm ĐẦU RA của module, không phải dữ
  liệu kênh ĐẦU VÀO) — xác nhận lại vẫn là khoảng trống thật, không phải khoảng trống tài liệu.
  (Ghi chú thêm, ngoài phạm vi từ điển: có 1 dự án ĐỘC LẬP khác ở
  `G:\Phân loại dữ liệu đối chiếu song phương\phan loại du lieu ipcas\` — web app FastAPI riêng,
  GitHub `dzungvumanh-crypto/-i-chi-u-t-i-ph-ng-thanh-to-n`, làm đúng bước phân loại IPCAS nhanh
  hơn — nhưng là codebase khác, không thuộc repo này, không liên quan tới khoảng trống dữ liệu
  kênh song phương.)

---

## Nhật ký cập nhật từ tài liệu chính thức

Mỗi khi Business Owner cung cấp tài liệu kỹ thuật/quy trình chính thức, ghi lại ở đây: ngày nhận,
tên/loại tài liệu, phần nào trong từ điển được cập nhật (mã nào từ "chưa rõ" → "cao", mã mới nào
được thêm, mâu thuẫn nào phát hiện với code/dữ liệu). Mục đích: biết tài liệu nào đã xử lý, tránh
hỏi lại hoặc xử lý trùng khi nhận thêm tài liệu sau.

| Ngày | Tài liệu | Phạm vi cập nhật | Mã/mục thay đổi |
|---|---|---|---|
| 2026-08-20 | `G:\NGOC HA\Quy_trinh_cham_459901.docx` + `Quy_trinh_thuat_toan_Cham_459901.md` (đã có sẵn trên đĩa, không phải BO gửi mới trong phiên này — tìm thấy khi rà soát) | Phần 3 (459901) — xác nhận khớp đúng thứ tự 7 cửa + lý do thứ tự đã ghi trong từ điển; không có mâu thuẫn. Bổ sung câu hỏi mới vào Phần 5: "58+4 dòng lạ" (mục 7 của tài liệu) chưa có trong từ điển đợt 1/2. | Không đổi mã nào (chỉ xác nhận), thêm 1 câu hỏi Phần 5 |
| 2026-08-20 | Xác nhận trực tiếp từ Business Owner (chat) | Phần 2.1 (`1000ITT...`), Phần 4.1 (`1000-553970732`), Phần 5 (bỏ câu hỏi đã trả lời), sơ đồ mermaid (node `UNK`) — xác nhận Mobifone chỉ là khách hàng thuộc hệ thống thanh toán, dùng chung LOCAC kênh ACH, không phải "ngân hàng thứ 5" Song phương. | `1000ITT...` và `1000-553970732`: trung bình → cao (danh tính); câu hỏi "lọt filter ILO1000 thế nào" vẫn mở (thấp, kỹ thuật) |
| 2026-08-21 | Xác nhận trực tiếp từ Business Owner (chat) | Mục 1.10 (Định dạng số tiền) — bổ sung quy tắc chung: VND luôn là số nguyên, không có thập phân, áp dụng mọi module không riêng ACH. Phát sinh từ vụ 3 giá trị dùng dấu phẩy trong `MIS_DI_THUA_20260819.csv` bị `doc_so_tien()` raise (đúng thiết kế "mẫu lạ → raise, không đoán") — quy tắc mới này gỡ mối lo dấu phẩy có thể là thập phân kiểu châu Âu. | Thêm 1 dòng mục 1.10, độ tin cậy cao |
| 2026-08-21/22 | Kết quả kỹ thuật từ 2 phiên sửa code + đối chiếu dữ liệu thật tháng 8/2026 (`18-19.8.2026`, `20-21.8.2026`) — không phải tài liệu bên ngoài, ghi lại vì làm rõ đáng kể nhiều mã trong Phần 2 | Phần 2 (ILO1000): mục 2.2 — nhãn `'citad {D1}-{D2}.{M}'` mới (thay `'citad {day}.{month}'` khi cửa sổ có ≥2 ngày thật), phân biệt rõ 2 nguồn khác nhau của `'Chờ đi kênh'` (pipeline flag vs nhãn thủ công), thêm `'Đã gửi, chờ phản hồi'` (BO xác nhận thủ công thuần, không tự động hoá) và `'Chờ duyệt chi trả'`; mục 2.3a mới — cơ chế cửa sổ khớp Citad/Hub mở rộng T+1 (`_citad_forward_days`, hợp cửa sổ Hub); mục 2.5 — OSB nhận diện thêm qua nội dung; ghi chú cuối Phần 2 — OSB đã verify xong bằng dữ liệu thật tháng 8 (không còn treo) | Nhiều mã mới độ tin cậy cao (có code + dữ liệu thật kiểm chứng); 1 mã cũ (`'SMF'`, mục 2.1) gắn cờ ⚠️ mâu thuẫn, chờ Business Owner xác nhận qua người chấm |
| 2026-08-24 | Kế hoạch triển khai module mới (không phải tài liệu bên ngoài — mô tả bằng lời của người dùng khi bắt đầu code module "Đối chiếu Song phương Đến") | Phần 4 — thêm mục 4.5 mô tả thiết kế module đối chiếu ĐẾN (route/feature-code `doi_chieu_song_phuong_den` riêng biệt, column-mapping động cho vế kênh chưa biết cấu trúc, khoá so khớp giả định Ngày+Số tiền, 3 trạng thái output KHOP/CHI_IPCAS/CHI_KENH); mục 4.4 thêm dòng trỏ sang 4.5 | Toàn bộ mục 4.5 gắn nhãn "thiết kế — chưa triển khai xong" / "giả định — chưa có dữ liệu thật", KHÔNG dùng thang độ tin cậy chuẩn vì đây là code chưa viết, cần xác minh lại khi có dữ liệu kênh thật — **⚠️ ĐÃ XÁC NHẬN SAI, xem dòng 2026-08-25 bên dưới** |
| 2026-08-25 | `G:\ĐỐI CHIẾU SONG PHƯƠNG\ĐỐI CHIẾU SONG PHƯƠNG\đối chiếu kênh hub Song phương.docx` (Business Owner cung cấp 2026-08-22, đọc read-only trong khảo sát) + dữ liệu thật 3 ngày (21-23/08/2026, join 100% dữ liệu, không lấy mẫu) + code `backend/services/doi_chieu_song_phuong_kenh/` (chủ dự án duyệt Checkpoint 1 + Phase 9) | Viết lại HOÀN TOÀN mục 4.4/4.5 — bản 2026-08-24 sai gốc rễ (nhầm module Phân loại IPCAS là "vế thiếu" của đối chiếu song phương; thực tế đối chiếu dùng 2 nguồn khác hẳn: HUB `doichieugd_*.zip` 14 cột và kênh Excel 5 cột). Xác nhận bằng dữ liệu thật: khoá `MSGREF`/`TXID` (hub, strip nháy đơn) ↔ `MtId/MsgId` (kênh) khớp 99,99-100%; số trong tên file HUB (`04/05/06/07`) là MÃ NGÂN HÀNG (201/202/203/311), không phải 2 nguồn gộp chung; cut-off 17h xác nhận đúng là quy tắc ngày giá trị; `RJCT` là trạng thái một-phía đương nhiên duy nhất (100% dòng chỉ-hub thật). Đã xoá code cũ `doi_chieu_song_phuong_den*` (thiết kế sai). | Toàn bộ mục 4.5 viết lại, độ tin cậy CAO cho công thức khoá + quy tắc cut-off + RJCT (có code + dữ liệu thật kiểm chứng bằng join toàn bộ, không phải mẫu) |
| 2026-08-25 | Xác nhận trực tiếp từ Business Owner (chat) — chốt lại quy tắc SMF đã gắn cờ ⚠️ mâu thuẫn từ 2026-08-21/22 | Phần 2, mục 2.1 (`'SMF'`) và mục 2.3 (khoá `Trace` Hub) — Trace của dòng SMF lấy từ "Số Trace 2" (trace giao dịch gốc), không còn giữ nguyên Số Trace 1. Sửa `ilo1000/process.py::process_hub()`, viết lại test khoá quy tắc cũ (187/187 pass), thêm card 83 Implementation-notes.html. Còn treo: chạy lại dữ liệu 22-24/8 để xác nhận 393 dòng CITAD lệch giảm về 0 — chưa làm được ở phiên không có ổ dữ liệu thật. | `'SMF'` mục 2.1: ⚠️ trung bình → cao; `Trace` (Hub) mục 2.3: cao |
| 2026-08-25 | `G:\ĐỐI CHIẾU SONG PHƯƠNG\ĐỐI CHIẾU SONG PHƯƠNG\lyxink.txt` (Business Owner cung cấp, ghi chú kỹ thuật ngắn, không phải docx chính thức) | Mục 4.5 — thêm quy tắc nhận diện ngân hàng qua 10 ký tự đầu `MtId/MsgId` (chỉ SP REALTIME): 0200970415→201, 0200970488→202, 0200970436→203, 0200970422→311. Verify 100% trên 4 file thật (202+203 × 21.8+24.8, 1.736.063 dòng). | Thêm 1 đoạn mục 4.5, độ tin cậy cao (202/203, có dữ liệu thật); 201/311 chưa verify được (chưa có dữ liệu) |
| 2026-08-25 | Xác nhận trực tiếp từ chủ dự án (chat) | Mục 4.5 — đính chính: NH 203 không có nghiệp vụ SPT là quy luật nghiệp vụ CẤU TRÚC (đúng cho cả chiều đến lẫn chiều đi), không phải khoảng trống dữ liệu tạm thời như câu chữ cũ ngụ ý ("kênh đến SPT 203.xlsx không tồn tại"). Bổ sung: NH 311 cũng không có nghiệp vụ SPT (trước đó chưa từng nói rõ, chỉ suy đoán do chưa có dữ liệu). | `FULL_MATRIX_NOTE`/`RECONCILE_UNITS` (`config.py`) cập nhật comment theo đúng quy luật này — độ tin cậy cao (203) / cao (311, dù chưa có dữ liệu để tự kiểm chứng, do BO xác nhận trực tiếp) |
| 2026-08-26 | Đối chiếu lại `đối chiếu kênh hub Song phương.docx` mục 1.2/2.2 (đọc lại bằng python-docx) + xác nhận trực tiếp Business Owner (chat) + dữ liệu thật 25.8 | Mục 4.5 — code Phase 9 còn thiếu 1 điều kiện tài liệu mô tả: loại thêm cặp dòng HUB có cùng `TXID` VÀ cùng `TRACE` (giao dịch huỷ), áp dụng cả Bảng 1 lẫn đối chiếu chi tiết (`filter_before_reconcile()`). Verify dữ liệu thật: 21.8/23.8 có 0 trường hợp; 25.8 có đúng 2 cặp/4 dòng (NH 202, trạng thái `RFED`) — khớp giả thuyết, không có nhóm >2 bất thường. Phát hiện thêm (không phải từ tài liệu, từ chạy thật 25.8): tên file kênh 25.8 đảo thứ tự (`kênh đến {mã_nh} {loại}.xlsx` thay vì `{loại} {mã_nh}`) — code đã sửa chấp nhận cả 2 thứ tự (`find_kenh_path()`), chưa rõ là quy ước mới lâu dài hay 1 lần. Đã chạy thật ngày 25.8 sau khi sửa: 3 đơn vị (202-SPRT/203-SPRT/202-SPT) đều chênh số món/số tiền = 0, tỉ lệ khớp 99,98-100%, không cảnh báo trạng thái bất thường. | Thêm đoạn "Tiền xử lý bắt buộc" bước 2 (cặp TXID+TRACE) — độ tin cậy cao (có xác nhận BO + dữ liệu thật cả 2 ngày không-có và có case). Tên file kênh đảo thứ tự — độ tin cậy trung bình (mới quan sát 1 ngày, chưa biết có lặp lại) |
| 2026-08-27 | Dữ liệu thật đầy đủ NH 201+311 (thư mục `dữ liệu/TRANG/`, 21-24.8.2026: HUB, GL02, OSB, kênh) do người dùng cung cấp | Mục 4.5 — ĐÍNH CHÍNH "SPT chỉ áp dụng NH 202" thành "203 và 311 không có SPT, 201 CÓ" (dữ liệu thật `kenh SPT den 201 24.8.xlsx` 15.781 dòng); ghi nhận quy ước đặt tên file thứ 3 (không dấu, kèm ngày, thư mục ngày có hậu tố năm `D.M.YYYY`) — code chuyển từ so khớp chuỗi cố định sang so khớp từ khoá (`find_kenh_path`, `_tim_file_osb`, `_thu_muc_ngay_ung_vien`); phát hiện + xử lý lỗi CSV thật (dòng `NOI_DUNG` NH 311 chứa dấu `"` chưa escape, `load_hub._doc_csv_hub_thu_cong()` phục hồi không mất dòng). Chạy thật xác nhận: guard `KENH_MTID_PREFIX` cho 201/311 đúng (trước đó "chưa verify"); Kênh↔Hub 4 ngày NH 201 + 3/4 ngày NH 311 khớp 99,97-100%; Hub↔Core 1 ngày (23.8) cả 2 NH: CORE THỪA=0, HUB THỪA còn 0,11-0,23% (khác 202/203 vốn 0 tuyệt đối, chưa rõ nguyên nhân — có thể cần core T+2/T+3 chưa có dữ liệu). Chi tiết đầy đủ: `Implementation-notes.html` card 87. | SPT 201: độ tin cậy cao (dữ liệu thật rõ ràng). Guard MtId prefix 201/311: trung bình → cao. HUB THỪA còn lại 201/311: chưa giải thích được, độ tin cậy thấp về nguyên nhân |
| 2026-08-27 | `G:\ĐỐI CHIẾU SONG PHƯƠNG\ĐỐI CHIẾU SONG PHƯƠNG\đối chiếu Song phương v3.docx` (Business Owner cung cấp, rà soát toàn bộ codebase Đối chiếu Song phương cho khớp). Đối chiếu v1 (22.8)→v2 (26.8)→v3 (27.8) bằng diff từng đoạn để xác định chính xác phần mới/đổi. | Mục 4.5, đoạn "Output" — v3 THAY HẲN thiết kế "Bảng 3" cũ (tổng hợp theo `TRANG_THAI_LENH`, đã duyệt Phase 9) bằng gắn cột trạng thái vào TỪNG DÒNG file kênh/hub gốc (5 nhãn, waterfall Bước 1/2), xuất riêng file/đơn vị thay vì 1 sheet gộp — quyết định người dùng chốt 2026-08-27 là thay hẳn, không giữ song song. Bảng 1 tổng hợp không đổi (v1→v2→v3 giống nhau). Mục 4.6 (Hub↔Core) đối chiếu v2→v3: **không đổi gì** — xác nhận bằng diff, không cần sửa tài liệu/code. Chiều ĐI (đặc tả đủ từ v1, dùng trạng thái `SCNL`) và tính năng "Nguyên nhân chênh lệch nhập tay + lưu lịch sử" (có từ v1): quyết định người dùng — vẫn KHÔNG làm đợt này, giữ backlog. Code: `process.classify_kenh_hub_den()` mới, xoá hẳn `build_bang_chi_tiet()`/`build_bang3_rows()` cũ. | Thiết kế chi tiết mới: độ tin cậy cao (đúng câu chữ tài liệu, có code + test). Khoá Bước 2.3 (dùng nhất quán theo loại thay vì chỉ MSGREF như câu chữ) — độ tin cậy trung bình, chưa verify dữ liệu thật |
| 2026-09-04 | `Đối chiếu SP chiều đi.docx` (bản đầu, đọc toàn văn bằng python-docx) → `Đối chiếu SP chiều đi V2.docx` (Hương Ly cung cấp cùng ngày, sửa 2 điểm so bản đầu) + verify dữ liệu thật NH 201/311/202/203 (nhiều đợt) + đối chứng chéo file người soát tự chấm tay ngày 28/8 (NH 202+203) | Thêm mới Phần 4.7 (Đối chiếu Song phương chiều ĐI — Kênh↔Hub + Hub↔Core), toàn bộ chi tiết nằm ở mục đó. Tóm tắt 3 phát hiện chính: (1) khoá SPT-đi ban đầu suy luận sai là "tài liệu im lặng" — thực ra V1 ghi rõ TXID, mâu thuẫn thật với dữ liệu (khớp 0%); V2 sửa thành MSGREF + Ly xác nhận trực tiếp → đã chốt bằng cả văn bản lẫn dữ liệu; (2) khoá OSB V1 (2 phần) để lại 22-35 khoá trùng/ngày là cặp gốc+đảo/huỷ, V2 thêm SO_TIEN giải quyết dứt điểm (0 còn trùng), đúng ý Ly "lấy giao dịch số tiền dương"; (3) TPAY được coi khớp bình thường trong Hub↔Core — dựa dữ liệu thật, docx (cả V1 lẫn V2) vẫn hoàn toàn im lặng, CHƯA có xác nhận bằng văn bản. | Phần 4.7 hoàn toàn mới. Bài học quy trình: đã có 1 lần tự kết luận sai "TXID là bug" mà chưa đọc lại toàn văn tài liệu gốc trước — xem `feedback_doc_lai_toan_van_truoc_khi_ket_luan_mau_thuan` (bộ nhớ agent, không phải file repo) |
