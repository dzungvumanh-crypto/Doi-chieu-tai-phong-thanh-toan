"""
Synthetic tests cho pipeline Chấm 459901.
Bao phủ các quy tắc nghiệp vụ đã chốt sau nhiều vòng đối chiếu với dữ liệu thật
(xem Implementation-notes.html card 21): khóa TRACE cho 1000 Hoàn trả, ghép cặp
N:N theo số tiền cho Điện KO offline, cân bằng nhóm bắt buộc cho Chuyển chi nhánh,
và thứ tự waterfall (1000HT chạy trước CCN/KO để tránh bị cướp nhầm).

Chạy: python -m pytest tests/test_cham459901_algorithm.py -v
"""

import io

import pandas as pd
import pyzipper
import pytest

from backend.services import cham459901_service as svc


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tk_row(ref, dr=0, cr=0, trbrcd='1000', userid='1000API0', remark='',
            trdate='20260601', trtp='Normal', dytrseq='1'):
    """Tạo 1 dòng TK459 với DRAMOUNT/CRAMOUNT đã là số (giống sau _load_data)."""
    return {
        'TRDATE': trdate, 'TRBRCD': trbrcd, 'USERID': userid, 'JOURSEQ': '1',
        'DYTRSEQ': dytrseq, 'LOCAC': '459901', 'CCY': 'VND', 'BUSCD': 'EI', 'UNIT': 'AP',
        'TRCD': '', 'CUSTOMER': '1000-000007709', 'TRTP': trtp, 'REFERENCE': ref,
        'REMARK': remark, 'DRAMOUNT': float(dr), 'CRAMOUNT': float(cr), 'CRTDTM': '',
    }


def _hub_row(trace, amount, link, trace2=None):
    """Hub đi/đến đã ở dạng chuẩn hóa (giống output của _read_hub_di/_read_hub_den).
    `trace2` chỉ áp dụng cho hub_đến ACH-NAPAS có 2 dãy số trace (xem _trace_candidates)."""
    return {
        'AMOUNT': float(amount), 'TRACE': float(trace), 'LINK': link,
        'TRACE2': float(trace2) if trace2 is not None else float('nan'),
    }


# ── _trace_last9 (chuẩn hóa cột "Số trace" của hub_den) ────────────────────────

class TestTraceLast9:
    def test_exactly_9_digits_unchanged(self):
        result = svc._trace_last9(pd.Series(['095864367']))
        assert result.iloc[0] == 95864367

    def test_two_sequences_takes_first_then_last9(self):
        result = svc._trace_last9(pd.Series(['095864367;005869323']))
        assert result.iloc[0] == 95864367

    def test_longer_than_9_digits_truncated_to_last9(self):
        # '1234567890123' (13 ký tự) -> lấy 9 ký tự cuối -> '567890123'
        result = svc._trace_last9(pd.Series(['1234567890123']))
        assert result.iloc[0] == 567890123

    def test_shorter_than_9_digits_kept_as_is(self):
        result = svc._trace_last9(pd.Series(['12345']))
        assert result.iloc[0] == 12345

    def test_unparseable_becomes_nan(self):
        result = svc._trace_last9(pd.Series(['abc']))
        assert pd.isna(result.iloc[0])


class TestTraceCandidates:
    def test_single_sequence_seg2_is_nan(self):
        seg1, seg2 = svc._trace_candidates(pd.Series(['095864367']))
        assert seg1.iloc[0] == 95864367
        assert pd.isna(seg2.iloc[0])

    def test_two_sequences_both_returned_last9_each(self):
        """Dữ liệu thật Tháng 5 (ACH-NAPAS): '099419569;009423425' -> seg1=99419569,
        seg2=9423425 — REFERENCE của TK459 có thể khớp SEG2, không chỉ seg1."""
        seg1, seg2 = svc._trace_candidates(pd.Series(['099419569;009423425']))
        assert seg1.iloc[0] == 99419569
        assert seg2.iloc[0] == 9423425

    def test_trace_last9_is_seg1_only(self):
        result = svc._trace_last9(pd.Series(['099419569;009423425']))
        assert result.iloc[0] == 99419569


# ── classify_upload_filename ──────────────────────────────────────────────────

class TestClassifyUploadFilename:
    def test_gl02_zip(self):
        assert svc.classify_upload_filename('GL02_20260630_1000.zip') == 'zip'

    def test_case_insensitive(self):
        assert svc.classify_upload_filename('gl02_test.ZIP') == 'zip'

    def test_zip_without_gl02_not_recognized(self):
        assert svc.classify_upload_filename('random_backup.zip') is None

    def test_hub_di_quay_prefix(self):
        name = 'Quay_danh sach giao dich chuyen tien di_20260707105525.xlsx'
        assert svc.classify_upload_filename(name) == 'hub_di'

    def test_hub_den(self):
        name = 'Danh_sach_giao_dich_den_202607071050463.xlsx'
        assert svc.classify_upload_filename(name) == 'hub_den'

    def test_ton_file(self):
        assert svc.classify_upload_filename('459_TON_T6.xlsx') == 'ton'

    def test_ton_file_case_insensitive_and_variant_separators(self):
        assert svc.classify_upload_filename('459-Ton-T7.xlsx') == 'ton'
        assert svc.classify_upload_filename('459_ton_t12.XLSX') == 'ton'

    def test_unrelated_xlsx_not_recognized(self):
        assert svc.classify_upload_filename('bao_cao_thang_6.xlsx') is None

    def test_docx_not_recognized(self):
        assert svc.classify_upload_filename('note.docx') is None


# ── _mark_ccn ──────────────────────────────────────────────────────────────────

class TestMarkCCN:
    def test_balanced_cross_branch_pair_matched(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, trbrcd='1000', remark='Chuyen khoan A'),
            _tk_row('REF2', cr=500000, trbrcd='6604', remark='Chuyen khoan A'),
        ])
        mask = svc._mark_ccn(df)
        assert mask.tolist() == [True, True]

    def test_unbalanced_group_excluded_entirely(self):
        """3 dòng cùng REMARK+số tiền nhưng Nợ != Có -> loại HẾT, không đoán/tách phần khớp."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, remark='X'),
            _tk_row('REF2', dr=500000, remark='X'),
            _tk_row('REF3', cr=500000, remark='X'),
        ])
        mask = svc._mark_ccn(df)
        assert not mask.any(), "Nhóm lệch Nợ/Có phải bị loại toàn bộ, không tách dòng khớp ra"

    def test_one_sided_group_not_marked(self):
        """Chỉ có phía Nợ, không có phía Có đối ứng -> không đánh dấu."""
        df = pd.DataFrame([_tk_row('REF1', dr=500000, remark='X')])
        mask = svc._mark_ccn(df)
        assert not mask.any()

    def test_different_remark_not_paired(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, remark='A'),
            _tk_row('REF2', cr=500000, remark='B'),
        ])
        mask = svc._mark_ccn(df)
        assert not mask.any()

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=['DRAMOUNT', 'CRAMOUNT', 'REMARK'])
        mask = svc._mark_ccn(df)
        assert len(mask) == 0

    def test_remark_case_insensitive_pairing(self):
        """Regression — dữ liệu thật Tháng 5: 2 chân cùng 1 giao dịch Chuyển chi nhánh do 2
        chi nhánh khác nhau gõ REMARK khác case ('chuyen tien' / 'CHUYEN TIEN') vẫn phải được
        nhận diện cùng 1 nhóm — trước đây rơi xuống Cân CN và bị ghép nhầm với giao dịch khác
        trùng số tiền tròn (xem Implementation-notes.html)."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=450000000, trbrcd='2122', remark='chuyen tien'),
            _tk_row('REF2', cr=450000000, trbrcd='3407', remark='CHUYEN TIEN'),
        ])
        mask = svc._mark_ccn(df)
        assert mask.tolist() == [True, True]

    def test_remark_leading_trailing_space_ignored(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, remark=' Chuyen khoan A '),
            _tk_row('REF2', cr=500000, remark='Chuyen khoan A'),
        ])
        mask = svc._mark_ccn(df)
        assert mask.tolist() == [True, True]


# ── _mark_can_cn ───────────────────────────────────────────────────────────────

class TestMarkCanCN:
    def test_balanced_same_branch_pair_matched(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, trbrcd='2000'),
            _tk_row('REF2', cr=500000, trbrcd='2000'),
        ])
        mask = svc._mark_can_cn(df)
        assert mask.tolist() == [True, True]

    def test_different_trbrcd_not_paired(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, trbrcd='2000'),
            _tk_row('REF2', cr=500000, trbrcd='3000'),
        ])
        mask = svc._mark_can_cn(df)
        assert not mask.any()

    def test_different_amount_not_paired(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=500000, trbrcd='2000'),
            _tk_row('REF2', cr=400000, trbrcd='2000'),
        ])
        mask = svc._mark_can_cn(df)
        assert not mask.any()

    def test_trbrcd_1000_small_amount_excluded_even_if_balanced(self):
        """DK3: nhánh 1000 chỉ được chấm Cân CN nếu tổng nhóm >5 tỷ — nhóm nhỏ để lại
        GD khác cho người dùng chấm tay."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=5_000_000, trbrcd='1000'),
            _tk_row('REF2', cr=5_000_000, trbrcd='1000'),
        ])
        mask = svc._mark_can_cn(df)
        assert not mask.any()

    def test_trbrcd_1000_large_amount_included(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=6_000_000_000, trbrcd='1000'),
            _tk_row('REF2', cr=6_000_000_000, trbrcd='1000'),
        ])
        mask = svc._mark_can_cn(df)
        assert mask.tolist() == [True, True]

    def test_threshold_only_applies_to_branch_1000(self):
        """Nhánh khác 1000 không bị áp ngưỡng 5 tỷ dù số tiền nhỏ."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=5_000_000, trbrcd='2000'),
            _tk_row('REF2', cr=5_000_000, trbrcd='2000'),
        ])
        mask = svc._mark_can_cn(df)
        assert mask.tolist() == [True, True]

    def test_one_sided_group_not_marked(self):
        df = pd.DataFrame([_tk_row('REF1', dr=500000, trbrcd='2000')])
        mask = svc._mark_can_cn(df)
        assert not mask.any()

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=['DRAMOUNT', 'CRAMOUNT', 'TRBRCD'])
        mask = svc._mark_can_cn(df)
        assert len(mask) == 0


# ── _mark_ko ───────────────────────────────────────────────────────────────────

class TestMarkKO:
    def test_paired_dr_cr_matched(self):
        df = pd.DataFrame([
            _tk_row('REF1', dr=1000000, userid='HNHUYENLN', remark='Remitting Amount:VND1000000.000'),
            _tk_row('REF2', cr=1000000, userid='1000KO'),
        ])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert mask_confirmed.tolist() == [True, True]
        assert not mask_candidate.any()

    def test_unpaired_amount_becomes_candidate_not_confirmed(self):
        """DR có marker nhưng không có CR cùng số tiền -> candidate (chờ chấm tay), KHÔNG confirmed."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=1000000, remark='Remitting Amount:VND1000000.000'),
            _tk_row('REF2', cr=999999, userid='1000KO'),
        ])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert not mask_confirmed.any()
        assert mask_candidate.tolist() == [True, True]

    def test_ko_userid_alone_without_dr_partner_is_candidate(self):
        df = pd.DataFrame([_tk_row('REF1', cr=500000, userid='1000KO')])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert not mask_confirmed.any()
        assert mask_candidate.tolist() == [True]

    def test_unrelated_row_untouched(self):
        df = pd.DataFrame([_tk_row('REF1', dr=1000, userid='1000API0', remark='hoa don')])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert not mask_confirmed.any()
        assert not mask_candidate.any()

    def test_nn_matching_multiple_pairs_same_amount(self):
        """2 dòng Nợ + 2 dòng Có cùng số tiền -> ghép đủ N:N cả 2 cặp."""
        df = pd.DataFrame([
            _tk_row('D1', dr=200000, remark='Remitting Amount:VND200000.000'),
            _tk_row('D2', dr=200000, remark='Remitting Amount:VND200000.000'),
            _tk_row('C1', cr=200000, userid='1000KO'),
            _tk_row('C2', cr=200000, userid='1000KO'),
        ])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert mask_confirmed.sum() == 4
        assert not mask_candidate.any()

    def test_surplus_side_falls_back_to_candidate(self):
        """3 Nợ vs 2 Có cùng số tiền -> chỉ ghép được 2 cặp, 1 dòng Nợ dư -> candidate."""
        df = pd.DataFrame([
            _tk_row('D1', dr=300000, remark='Remitting Amount:VND300000.000'),
            _tk_row('D2', dr=300000, remark='Remitting Amount:VND300000.000'),
            _tk_row('D3', dr=300000, remark='Remitting Amount:VND300000.000'),
            _tk_row('C1', cr=300000, userid='1000KO'),
            _tk_row('C2', cr=300000, userid='1000KO'),
        ])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert mask_confirmed.sum() == 4
        assert mask_candidate.sum() == 1

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=['DRAMOUNT', 'CRAMOUNT', 'USERID', 'REMARK'])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert len(mask_confirmed) == 0 and len(mask_candidate) == 0

    def test_userid_with_ko_substring_not_branch_pattern_not_marked(self):
        """Regression — dữ liệu thật Tháng 5: USERID 'DTRLTKO' (tên đăng nhập giao dịch viên,
        'KO' chỉ là hậu tố ngẫu nhiên) từng bị nhận nhầm Điện KO offline dù không phải mã chi
        nhánh 4 số + 'KO'. Dù CRAMOUNT khớp đúng 1 dòng Nợ có marker Remitting Amount:VND,
        vẫn KHÔNG được đánh dấu — vì USERID không đúng mẫu."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=1000000, remark='Remitting Amount:VND1000000.000'),
            _tk_row('REF2', cr=1000000, userid='DTRLTKO'),
        ])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert not mask_confirmed.any()

    def test_branch_code_ko_userid_other_than_1000_still_matched(self):
        """Đối chứng: mã chi nhánh 4 số + 'KO' (VD '3511KO') vẫn phải hoạt động bình thường."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=1000000, remark='Remitting Amount:VND1000000.000'),
            _tk_row('REF2', cr=1000000, userid='3511KO'),
        ])
        mask_confirmed, mask_candidate = svc._mark_ko(df)
        assert mask_confirmed.tolist() == [True, True]


# ── _match_hub_1000ht (DK1: khớp hub đi ↔ hub đến) ──────────────────────────────

class TestMatchHub1000HT:
    def test_matched_link_equal_totals(self):
        hub_di  = pd.DataFrame([_hub_row(111, 500000, 'LINK_A')])
        hub_den = pd.DataFrame([_hub_row(222, 500000, 'LINK_A')])
        mask_di, mask_den = svc._match_hub_1000ht(hub_di, hub_den)
        assert mask_di.tolist() == [True]
        assert mask_den.tolist() == [True]

    def test_unequal_totals_not_matched(self):
        hub_di  = pd.DataFrame([_hub_row(111, 500000, 'LINK_A')])
        hub_den = pd.DataFrame([_hub_row(222, 400000, 'LINK_A')])
        mask_di, mask_den = svc._match_hub_1000ht(hub_di, hub_den)
        assert not mask_di.any()
        assert not mask_den.any()

    def test_no_common_link(self):
        hub_di  = pd.DataFrame([_hub_row(111, 500000, 'LINK_A')])
        hub_den = pd.DataFrame([_hub_row(222, 500000, 'LINK_B')])
        mask_di, mask_den = svc._match_hub_1000ht(hub_di, hub_den)
        assert not mask_di.any()
        assert not mask_den.any()

    def test_split_group_sums_still_match(self):
        """1 LINK có 2 dòng phía đi cộng lại bằng tổng phía đến -> vẫn khớp (N:N theo tổng)."""
        hub_di = pd.DataFrame([
            _hub_row(111, 300000, 'LINK_A'),
            _hub_row(112, 200000, 'LINK_A'),
        ])
        hub_den = pd.DataFrame([_hub_row(222, 500000, 'LINK_A')])
        mask_di, mask_den = svc._match_hub_1000ht(hub_di, hub_den)
        assert mask_di.tolist() == [True, True]
        assert mask_den.tolist() == [True]

    def test_blank_link_not_matched_even_if_totals_coincide(self):
        """LINK rỗng/'nan' của nhiều dòng KHÔNG LIÊN QUAN không được ghép nhóm với nhau
        dù tổng tiền trùng ngẫu nhiên — tránh khớp giả (false-positive 1000HT)."""
        hub_di = pd.DataFrame([
            _hub_row(111, 300000, ''),      # LINK rỗng — không có Số tham chiếu lệnh gốc
            _hub_row(112, 200000, 'nan'),    # LINK 'nan' — cell Excel trống bị ép thành chuỗi
        ])
        hub_den = pd.DataFrame([
            _hub_row(222, 500000, ''),       # Tổng trùng ngẫu nhiên với 2 dòng trên (300k+200k)
        ])
        mask_di, mask_den = svc._match_hub_1000ht(hub_di, hub_den)
        assert not mask_di.any(), "LINK rỗng không được xem là cùng 1 giao dịch"
        assert not mask_den.any()

    def test_real_link_still_matches_when_blank_links_present_elsewhere(self):
        """Có lẫn LINK rỗng trong dữ liệu không được làm hỏng việc khớp các LINK thật."""
        hub_di = pd.DataFrame([
            _hub_row(111, 300000, ''),
            _hub_row(999, 700000, 'LINK_REAL'),
        ])
        hub_den = pd.DataFrame([
            _hub_row(222, 500000, ''),
            _hub_row(888, 700000, 'LINK_REAL'),
        ])
        mask_di, mask_den = svc._match_hub_1000ht(hub_di, hub_den)
        assert mask_di.tolist() == [False, True]
        assert mask_den.tolist() == [False, True]


# ── _mark_1000ht (khóa TRACE đầy đủ + bắt buộc đủ cặp) ─────────────────────────

class TestMark1000HT:
    def test_full_pair_confirmed(self):
        """REFERENCE (bỏ 7 ký tự tiền tố) khớp TRACE hub đi (chân Nợ) và hub đến (chân Có)
        của CÙNG 1 LINK đã xác nhận DK1 -> cả 2 dòng TK459 được đánh dấu 1000HT."""
        df = pd.DataFrame([
            _tk_row('1000API0006922690', dr=500000),   # REFERENCE[7:] = '0006922690' -> 6922690
            _tk_row('1000API0003247962', cr=500000),   # REFERENCE[7:] = '0003247962' -> 3247962
        ])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_X')])
        hub_den = pd.DataFrame([_hub_row(3247962, 500000, 'LINK_X')])

        mask_confirmed, mask_candidate = svc._mark_1000ht(df, hub_di, hub_den)
        assert mask_confirmed.tolist() == [True, True]
        assert not mask_candidate.any()

    def test_reference_prefix_stripped_at_position_8(self):
        """Chỉ 7 ký tự đầu bị bỏ — REFERENCE 'AAAAAAA1234567' -> suffix numeric 1234567."""
        df = pd.DataFrame([_tk_row('AAAAAAA1234567', dr=90000)])
        hub_di  = pd.DataFrame([_hub_row(1234567, 90000, 'LINK_P')])
        hub_den = pd.DataFrame([_hub_row(9999999, 90000, 'LINK_P')])
        # chỉ chân Nợ có mặt trong df -> candidate, không confirmed (thiếu chân Có)
        mask_confirmed, mask_candidate = svc._mark_1000ht(df, hub_di, hub_den)
        assert not mask_confirmed.any()
        assert mask_candidate.tolist() == [True]

    def test_only_one_leg_present_becomes_candidate_not_confirmed(self):
        """Chân Có rơi ngoài kỳ dữ liệu TK459 đang chấm -> không xác nhận (rule 18: Nợ=Có
        bắt buộc theo cặp), chỉ đánh dấu candidate để chấm tay, KHÔNG tự ý đánh dấu 1000HT."""
        df = pd.DataFrame([_tk_row('1000API0006922690', dr=500000)])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_X')])
        hub_den = pd.DataFrame([_hub_row(3247962, 500000, 'LINK_X')])
        mask_confirmed, mask_candidate = svc._mark_1000ht(df, hub_di, hub_den)
        assert not mask_confirmed.any()
        assert mask_candidate.tolist() == [True]

    def test_unrelated_amount_not_matched_at_all(self):
        """Không trùng LINK/TRACE nào đã xác nhận -> không confirmed, không candidate."""
        df = pd.DataFrame([_tk_row('1000API0009999999', dr=700000)])
        hub_di  = pd.DataFrame([_hub_row(1234567, 700000, 'LINK_Z')])
        hub_den = pd.DataFrame([_hub_row(7654321, 700000, 'LINK_Z')])
        mask_confirmed, mask_candidate = svc._mark_1000ht(df, hub_di, hub_den)
        assert not mask_confirmed.any()
        assert not mask_candidate.any()

    def test_dr_cr_totals_balance_exactly_when_confirmed(self):
        """Bất biến bắt buộc (rule 18): Tổng DRAMOUNT = Tổng CRAMOUNT trong tập confirmed."""
        df = pd.DataFrame([
            _tk_row('1000API0001111111', dr=250000),
            _tk_row('1000API0002222222', cr=250000),
            _tk_row('1000API0003333333', dr=999999),   # không match hub -> phải bị loại
        ])
        hub_di  = pd.DataFrame([_hub_row(1111111, 250000, 'LINK_B')])
        hub_den = pd.DataFrame([_hub_row(2222222, 250000, 'LINK_B')])
        mask_confirmed, _ = svc._mark_1000ht(df, hub_di, hub_den)
        confirmed = df[mask_confirmed]
        assert confirmed['DRAMOUNT'].sum() == confirmed['CRAMOUNT'].sum() == 250000
        assert mask_confirmed.sum() == 2

    def test_ach_napas_matches_via_second_trace_segment(self):
        """Regression — dữ liệu thật Tháng 5 (REFERENCE=1000API9423425, chân Có): hub_đến
        ACH-NAPAS có 'Số trace' 2 dãy số ('099419569;009423425') -> seg1=99419569,
        seg2=9423425. REFERENCE[7:] của chân Có chỉ khớp SEG2, không khớp seg1 — trước đây bị
        bỏ sót hoàn toàn (rơi vào GD khác không cả candidate). Nay phải được xác nhận 1000HT."""
        df = pd.DataFrame([
            _tk_row('1000API0006922690', dr=500000),   # chân Nợ, khớp hub_di TRACE=6922690
            _tk_row('1000API9423425', cr=500000),       # chân Có, REFERENCE[7:]=9423425 = seg2
        ])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_ACH')])
        hub_den = pd.DataFrame([_hub_row(99419569, 500000, 'LINK_ACH', trace2=9423425)])

        mask_confirmed, mask_candidate = svc._mark_1000ht(df, hub_di, hub_den)
        assert mask_confirmed.tolist() == [True, True]
        assert not mask_candidate.any()

    def test_ach_napas_first_segment_match_still_works(self):
        """Regression đối chứng: dòng khớp qua SEG1 (như trước khi có sửa) vẫn phải hoạt động
        — không được để việc thêm khớp seg2 làm vỡ 49/97 dòng đang khớp đúng qua seg1."""
        df = pd.DataFrame([
            _tk_row('1000API0006922690', dr=500000),
            _tk_row('1000API0099419569', cr=500000),   # REFERENCE[7:] -> 99419569 (= seg1)
        ])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_ACH')])
        hub_den = pd.DataFrame([_hub_row(99419569, 500000, 'LINK_ACH', trace2=9423425)])

        mask_confirmed, mask_candidate = svc._mark_1000ht(df, hub_di, hub_den)
        assert mask_confirmed.tolist() == [True, True]


# ── _classify — tích hợp toàn bộ waterfall ──────────────────────────────────────

class TestClassifyIntegration:
    def test_row_conservation_no_hub(self):
        """Không có file HUB -> bỏ qua 1000HT, các dòng còn lại vẫn được bảo toàn đầy đủ."""
        df = pd.DataFrame([
            _tk_row('REF1', dr=100000, cr=0, trtp='Normal'),
            _tk_row('REF1', dr=0, cr=100000, trtp='Cancel'),   # cặp Hủy
            _tk_row('REF2', dr=500000, trbrcd='1000', remark='CN đi'),
            _tk_row('REF3', cr=500000, trbrcd='1000', remark='CN đi'),
            _tk_row('REF4', dr=1000000, remark='Remitting Amount:VND1000000.000'),
            _tk_row('REF5', cr=1000000, userid='1000KO'),
            _tk_row('REF6', dr=9999, remark='hoa don khac'),   # rơi vào GD khác
        ])
        df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac = svc._classify(df.copy())
        total = (len(df_huy) + len(df_di) + len(df_1000ht) + len(df_ccn) + len(df_ko)
                 + len(df_can_cn) + len(df_khac))
        assert total == len(df)
        assert len(df_1000ht) == 0, "Không có HUB thì không được tự đánh dấu 1000HT"
        assert len(df_ko) == 2
        assert len(df_di) == 2

    def test_row_and_money_conservation_with_hub(self):
        # Nợ và Có ở khác chi nhánh để không vô tình bị Bước 2 "Lệnh Đi" (cùng chi nhánh
        # + cùng số tiền + cùng REMARK) bắt trước khi tới lượt 1000HT.
        df = pd.DataFrame([
            _tk_row('1000API0006922690', dr=500000, trbrcd='1000'),
            _tk_row('1000API0003247962', cr=500000, trbrcd='2000'),
            _tk_row('REFX', dr=9999, remark='khac'),
        ])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_X')])
        hub_den = pd.DataFrame([_hub_row(3247962, 500000, 'LINK_X')])

        df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac = svc._classify(
            df.copy(), hub_di=hub_di, hub_den=hub_den,
        )
        total = (len(df_huy) + len(df_di) + len(df_1000ht) + len(df_ccn) + len(df_ko)
                 + len(df_can_cn) + len(df_khac))
        assert total == len(df)
        assert len(df_1000ht) == 2
        assert df_1000ht['DRAMOUNT'].sum() == df_1000ht['CRAMOUNT'].sum() == 500000

    def test_1000ht_runs_before_ccn_to_avoid_being_stolen(self):
        """Regression test cho lỗi thứ tự waterfall đã fix (REFERENCE=1000API845335):
        1 dòng vừa khớp khóa TRACE 1000HT, vừa TRÙNG số tiền+REMARK với 1 dòng khác
        (điều kiện CCN) -> phải được xếp vào 1000HT (chạy trước), không rơi vào CCN."""
        df = pd.DataFrame([
            _tk_row('1000API0006922690', dr=500000, trbrcd='1000', remark='Chuyen khoan'),
            _tk_row('1000API0003247962', cr=500000, trbrcd='2000', remark='Chuyen khoan'),
            # 1 dòng khác cùng REMARK+số tiền để hình thành "bẫy" CCN nếu chạy trước
            _tk_row('OTHERREF00', cr=500000, trbrcd='6604', remark='Chuyen khoan'),
        ])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_X')])
        hub_den = pd.DataFrame([_hub_row(3247962, 500000, 'LINK_X')])

        df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac = svc._classify(
            df.copy(), hub_di=hub_di, hub_den=hub_den,
        )
        assert '1000API0006922690' in set(df_1000ht['REFERENCE'])
        assert '1000API0003247962' in set(df_1000ht['REFERENCE'])
        assert '1000API0006922690' not in set(df_ccn['REFERENCE'])

    def test_ghi_chu_flags_candidates_in_khac(self):
        df = pd.DataFrame([
            _tk_row('1000API0006922690', dr=500000),  # 1000HT candidate (thiếu chân Có)
            _tk_row('REFKO', dr=1000000, remark='Remitting Amount:VND1000000.000'),  # KO candidate
        ])
        hub_di  = pd.DataFrame([_hub_row(6922690, 500000, 'LINK_X')])
        hub_den = pd.DataFrame([_hub_row(9999999, 500000, 'LINK_X')])

        *_, df_khac = svc._classify(df.copy(), hub_di=hub_di, hub_den=hub_den)
        assert 'GHI_CHU' in df_khac.columns
        notes = set(df_khac['GHI_CHU'])
        assert any('1000HT' in n for n in notes if n)
        assert any('KO' in n for n in notes if n)

    def test_huy_pair_removed_and_di_balanced(self):
        df = pd.DataFrame([
            _tk_row('REFH', dr=200000, trtp='Normal'),
            _tk_row('REFH', cr=200000, trtp='Cancel'),
            _tk_row('REFD1', dr=300000, trbrcd='2000', remark='CN'),
            _tk_row('REFD2', cr=300000, trbrcd='2000', remark='CN'),
        ])
        df_huy, df_di, *_rest = svc._classify(df.copy())
        assert len(df_huy) == 2
        assert len(df_di) == 2
        assert df_di['DRAMOUNT'].sum() == df_di['CRAMOUNT'].sum()

    def test_can_cn_runs_after_ko_before_khac(self):
        """Bước 6: cặp khớp TRBRCD+số tiền (không cùng REMARK nên không bị Đi/CCN bắt trước,
        USERID/REMARK không dính KO) phải rơi vào Cân CN, không phải GD khác."""
        df = pd.DataFrame([
            _tk_row('REFA', dr=500000, trbrcd='2000', remark='A'),
            _tk_row('REFB', cr=500000, trbrcd='2000', remark='B'),
            _tk_row('REFC', dr=9999,   trbrcd='9999', remark='khong khop'),
        ])
        df_huy, df_di, df_1000ht, df_ccn, df_ko, df_can_cn, df_khac = svc._classify(df.copy())
        total = (len(df_huy) + len(df_di) + len(df_1000ht) + len(df_ccn) + len(df_ko)
                 + len(df_can_cn) + len(df_khac))
        assert total == len(df)
        assert set(df_can_cn['REFERENCE']) == {'REFA', 'REFB'}
        assert 'REFC' in set(df_khac['REFERENCE'])


# ── Job lifecycle: init_progress / cancel_progress / delete_result ─────────────

class TestJobLifecycle:
    def test_init_progress_creates_entry(self):
        token = svc.init_progress()
        prog = svc.get_progress(token)
        assert prog is not None
        assert prog['done'] is False
        assert prog['cancelled'] is False
        assert 'cancel_event' not in prog, "cancel_event là nội bộ, không được lộ ra ngoài API"

    def test_get_progress_unknown_token(self):
        assert svc.get_progress('token-khong-ton-tai') is None

    def test_cancel_progress_sets_event(self):
        token = svc.init_progress()
        assert svc.cancel_progress(token) is True
        assert svc._progress[token]['cancel_event'].is_set()

    def test_cancel_progress_unknown_token_returns_false(self):
        assert svc.cancel_progress('token-khong-ton-tai') is False

    def test_cancel_progress_already_done_returns_false(self):
        token = svc.init_progress()
        svc._progress[token]['done'] = True
        assert svc.cancel_progress(token) is False

    def test_set_prog_raises_after_cancel(self):
        token = svc.init_progress()
        svc.cancel_progress(token)
        with pytest.raises(svc._Cancelled):
            svc._set_prog(token, 50, 'đang chạy...')

    def test_delete_result_removes_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        result_token = svc.init_progress()   # token thật luôn là str(uuid.uuid4())
        out_dir = tmp_path / result_token
        out_dir.mkdir(parents=True)
        (out_dir / 'huy.xlsx').write_text('x')

        assert svc.delete_result(result_token) is True
        assert not out_dir.exists()

    def test_delete_result_missing_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        assert svc.delete_result(svc.init_progress()) is False


# ── resolve_result_dir() — chốt chặn hồi quy path traversal (review PR#43) ─────
# Trước fix: delete_result()/download_result ghép token từ URL thẳng vào path rồi
# rmtree/read_bytes, không kiểm gì. Token '..\\..\\data' (dấu \\ — %2F bị chặn
# nhưng %5C thì không, và pathlib trên Windows hiểu \\ là dấu phân cách) xoá được
# thư mục data/ chứa SQLite. Token luôn là str(uuid.uuid4()) nên chặn ngay từ
# bước kiểm định dạng UUID là đủ, không cần đợi tới is_relative_to().

class TestResolveResultDir:
    def test_token_khong_phai_uuid_bi_tu_choi(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        assert svc.resolve_result_dir(r'..\..\data') is None
        assert svc.resolve_result_dir('../../data') is None
        assert svc.resolve_result_dir('') is None
        assert svc.resolve_result_dir('khong-phai-uuid') is None

    def test_token_uuid_hop_le_tra_ve_dung_thu_muc(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        token = svc.init_progress()
        out_dir = svc.resolve_result_dir(token)
        assert out_dir == (tmp_path / token).resolve()

    def test_delete_result_chan_token_thoat_thu_muc(self, tmp_path, monkeypatch):
        """Dựng đúng nạn nhân + gọi đúng hàm public (delete_result), không chỉ test
        resolve_result_dir() đơn lẻ — verify rmtree thật sự không chạm tới nạn nhân."""
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path / 'temp_cham459901')
        (tmp_path / 'temp_cham459901').mkdir()
        victim = tmp_path / 'du_lieu_quan_trong'
        victim.mkdir()
        (victim / 'data.db').write_text('khong duoc xoa')

        assert svc.delete_result(r'..\du_lieu_quan_trong') is False
        assert victim.exists()
        assert (victim / 'data.db').exists()


# ── _write_excel — smoke test cấu trúc file xuất ra ────────────────────────────

class TestWriteExcel:
    def test_output_readable_and_matches_row_count(self, tmp_path):
        df = pd.DataFrame([
            _tk_row('REF1', dr=100000, cr=0),
            _tk_row('REF2', dr=0, cr=100000),
        ])
        df['GHI_CHU'] = ''
        out_path = tmp_path / 'test.xlsx'
        svc._write_excel(df, out_path, 'Test Sheet', 'FF0000')

        assert out_path.exists()
        # engine='calamine' — khớp engine dùng thật trong service (openpyxl trong requirements.txt
        # hiện bị pandas coi là quá cũ cho pd.read_excel mặc định, không liên quan đến code test).
        read_back = pd.read_excel(out_path, skiprows=1, engine='calamine')
        # +1 vì có dòng "TỔNG CỘNG" ở cuối
        assert len(read_back) == len(df) + 1
        assert list(read_back.columns) == svc.OUTPUT_COLS

    def test_empty_dataframe_does_not_crash(self, tmp_path):
        df = pd.DataFrame(columns=svc.OUTPUT_COLS)
        out_path = tmp_path / 'empty.xlsx'
        svc._write_excel(df, out_path, 'Empty', '00FF00')
        assert out_path.exists()


# ── _load_data — đọc + giải mã + lọc theo LOCAC/CUSTOMER/CCY ───────────────────

def _make_gl02_zip(rows: list[dict]) -> bytes:
    """Đóng gói CSV thành zip mã hóa AES giống định dạng GL02 thật (test không mock I/O
    — dùng file zip thật, chỉ thu nhỏ, theo đúng khuyến nghị trong doi-chieu skill)."""
    cols = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
            'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
            'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']
    df = pd.DataFrame(rows)[cols]
    csv_bytes = df.to_csv(index=False).encode('utf-8-sig')

    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                              encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(svc.ZIP_PASSWORD)
        zf.writestr('data.csv', csv_bytes)
    return buf.getvalue()


def _gl02_row(ref, dr='0', cr='0', locac='459901', customer='1000-000007709', ccy='VND'):
    return {
        'TRDATE': '20260601', 'TRBRCD': '1000', 'USERID': '1000API0', 'JOURSEQ': '1',
        'DYTRSEQ': '1', 'LOCAC': locac, 'CCY': ccy, 'BUSCD': 'EI', 'UNIT': 'AP',
        'TRCD': '', 'CUSTOMER': customer, 'TRTP': 'Normal', 'REFERENCE': ref,
        'REMARK': '', 'DRAMOUNT': dr, 'CRAMOUNT': cr, 'CRTDTM': '',
    }


def _make_ton_xlsx(rows: list[dict]) -> bytes:
    """Đóng gói xlsx giống định dạng file '459_TON_Tx.xlsx' thật (header ngay dòng 1,
    có thêm 3 cột ghi chú thủ công 'chấm'/'Phong ban'/'refhub' mà _read_ton_file phải bỏ)."""
    cols = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
            'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
            'DRAMOUNT', 'CRAMOUNT', 'chấm', 'Phong ban', 'refhub']
    df = pd.DataFrame(rows)[cols]
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    return buf.getvalue()


def _ton_row(ref, dr=0, cr=0, trdate=20260601, trbrcd=1000, journseq=1, dytrseq=1,
             locac=459901, customer='1000-000007709', ccy='VND', remark=''):
    return {
        'TRDATE': trdate, 'TRBRCD': trbrcd, 'USERID': '1000API1', 'JOURSEQ': journseq,
        'DYTRSEQ': dytrseq, 'LOCAC': locac, 'CCY': ccy, 'BUSCD': 'EI', 'UNIT': 'AP',
        'TRCD': None, 'CUSTOMER': customer, 'TRTP': 'Normal', 'REFERENCE': ref,
        'REMARK': remark, 'DRAMOUNT': dr, 'CRAMOUNT': cr,
        'chấm': None, 'Phong ban': 'TTTT', 'refhub': None,
    }


class TestReadTonFile:
    def test_reads_16_common_columns_only(self):
        xlsx_bytes = _make_ton_xlsx([_ton_row('REF1', dr=100000)])
        df = svc._read_ton_file(xlsx_bytes)
        assert list(df.columns) == svc._TON_COLS
        assert 'refhub' not in df.columns

    def test_integer_columns_no_dot_zero_suffix(self):
        xlsx_bytes = _make_ton_xlsx([_ton_row('REF1', dr=100000, trdate=20251231)])
        df = svc._read_ton_file(xlsx_bytes)
        assert df.iloc[0]['TRDATE'] == '20251231'

    def test_amounts_numeric(self):
        xlsx_bytes = _make_ton_xlsx([_ton_row('REF1', dr=100000, cr=0)])
        df = svc._read_ton_file(xlsx_bytes)
        assert df.iloc[0]['DRAMOUNT'] == 100000.0
        assert isinstance(df.iloc[0]['DRAMOUNT'], float)

    def test_filters_by_locac_customer_ccy(self):
        xlsx_bytes = _make_ton_xlsx([
            _ton_row('REF1', dr=100000),                     # khớp filter
            _ton_row('REF2', dr=200000, locac=999999),       # sai LOCAC -> bị lọc
            _ton_row('REF3', dr=300000, customer='khac'),    # sai CUSTOMER -> bị lọc
            _ton_row('REF4', dr=400000, ccy='USD'),          # sai CCY -> bị lọc
        ])
        df = svc._read_ton_file(xlsx_bytes)
        assert len(df) == 1
        assert df.iloc[0]['REFERENCE'] == 'REF1'

    def test_blank_trcd_becomes_empty_string_not_none_literal(self):
        xlsx_bytes = _make_ton_xlsx([_ton_row('REF1', dr=100000)])
        df = svc._read_ton_file(xlsx_bytes)
        assert df.iloc[0]['TRCD'] == ''

    def test_thieu_cot_bat_buoc_raise_input_error_khong_phai_key_error(self):
        """Review PR#43 (khanhbq693) mục 6/9: nhận diện file theo tên rất lỏng
        ('459' in name and 'ton' in name) — thả nhầm file khác định dạng vào là
        dễ xảy ra. Trước fix: thiếu cột -> KeyError -> 500 'Lỗi hệ thống'. Nay
        phải là InputError với tên cột thiếu, giống hệt cách _load_data() đã làm
        cho GL02 gốc."""
        df = pd.DataFrame([{'TRDATE': '20260601', 'REFERENCE': 'REF1'}])  # thiếu hầu hết cột
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine='openpyxl')
        with pytest.raises(svc.InputError, match='thiếu cột bắt buộc'):
            svc._read_ton_file(buf.getvalue())


def _make_hub_di_xlsx(so_tien_thuc_chuyen='500000', thieu_cot=False) -> bytes:
    """Header ở dòng Excel thứ 2 (index 1), dữ liệu từ dòng thứ 3 (index 2) —
    đúng layout _read_hub_di() kỳ vọng."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Tiêu đề báo cáo'])
    cols = ['Số Trace 1', 'Số tiền thực chuyển', 'Hệ thống thanh toán',
            'Nội dung chuyển tiền', 'Số tham chiếu lệnh gốc']
    if thieu_cot:
        cols = cols[:-1]   # bỏ 'Số tham chiếu lệnh gốc'
    ws.append(cols)
    row = ['123456789', so_tien_thuc_chuyen, 'ACH-NAPAS', 'noi dung', 'REFGOC1']
    ws.append(row[:len(cols)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_hub_den_xlsx(so_tien_lenh_goc='500000', thieu_cot=False) -> bytes:
    """Header ở dòng Excel thứ 3 (index 2), dữ liệu từ dòng thứ 4 (index 3) —
    đúng layout _read_hub_den() kỳ vọng."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Tiêu đề báo cáo'])
    ws.append([''])
    cols = ['Số trace', 'Số tiền lệnh gốc', 'Hệ thống thanh toán',
            'Số thành công/MSGID', 'Số REF HUB']
    if thieu_cot:
        cols = cols[:-1]   # bỏ 'Số REF HUB'
    ws.append(cols)
    row = ['987654321', so_tien_lenh_goc, 'ACH-NAPAS', 'MSG123456', 'REFHUB1']
    ws.append(row[:len(cols)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestReadHubDiHubDen:
    def test_hub_di_doc_dung_khi_du_cot(self):
        df = svc._read_hub_di(_make_hub_di_xlsx('500000'))
        assert df.iloc[0]['AMOUNT'] == 500_000

    def test_hub_di_thieu_cot_raise_input_error(self):
        with pytest.raises(svc.InputError, match='thiếu cột bắt buộc'):
            svc._read_hub_di(_make_hub_di_xlsx(thieu_cot=True))

    def test_hub_den_doc_dung_khi_du_cot(self):
        df = svc._read_hub_den(_make_hub_den_xlsx('500000'))
        assert df.iloc[0]['AMOUNT'] == 500_000

    def test_hub_den_thieu_cot_raise_input_error(self):
        with pytest.raises(svc.InputError, match='thiếu cột bắt buộc'):
            svc._read_hub_den(_make_hub_den_xlsx(thieu_cot=True))


class TestLoadData:
    def test_filters_by_locac_customer_ccy(self):
        zip_bytes = _make_gl02_zip([
            _gl02_row('REF1', dr='100000'),                      # khớp filter
            _gl02_row('REF2', dr='200000', locac='999999'),      # sai LOCAC -> bị lọc
            _gl02_row('REF3', dr='300000', customer='khac'),     # sai CUSTOMER -> bị lọc
            _gl02_row('REF4', dr='400000', ccy='USD'),           # sai CCY -> bị lọc
        ])
        df, filtered_rows = svc._load_data(zip_bytes)
        assert len(df) == 1
        assert filtered_rows == 3
        assert df.iloc[0]['REFERENCE'] == 'REF1'

    def test_amounts_converted_to_numeric(self):
        zip_bytes = _make_gl02_zip([_gl02_row('REF1', dr='150000.5', cr='0')])
        df, _ = svc._load_data(zip_bytes)
        assert df.iloc[0]['DRAMOUNT'] == 150000.5
        assert isinstance(df.iloc[0]['DRAMOUNT'], float)

    def test_wrong_password_raises(self):
        """File zip không đúng mật khẩu GL02 phải báo lỗi rõ ràng (InputError), không âm thầm
        trả rỗng và không lộ lỗi hệ thống chung chung."""
        buf = io.BytesIO()
        with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                                  encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(b'sai-mat-khau')
            zf.writestr('data.csv', 'a,b\n1,2\n')
        with pytest.raises(svc.InputError, match='mật khẩu'):
            svc._load_data(buf.getvalue())

    def test_not_a_zip_file_raises_input_error(self):
        with pytest.raises(svc.InputError, match=r'\.zip hợp lệ'):
            svc._load_data(b'day khong phai file zip')

    def test_zip_without_csv_raises_input_error(self):
        buf = io.BytesIO()
        with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                                  encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(svc.ZIP_PASSWORD)
            zf.writestr('readme.txt', 'khong co file csv nao')
        with pytest.raises(svc.InputError, match='csv'):
            svc._load_data(buf.getvalue())

    def test_missing_required_column_raises_input_error(self):
        buf = io.BytesIO()
        with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                                  encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(svc.ZIP_PASSWORD)
            # thiếu cột CCY và DRAMOUNT bắt buộc
            zf.writestr('data.csv', 'LOCAC,CUSTOMER,REMARK,CRAMOUNT\n459901,1000-000007709,x,0\n')
        with pytest.raises(svc.InputError, match='CCY') as exc_info:
            svc._load_data(buf.getvalue())
        assert 'DRAMOUNT' in str(exc_info.value)


class TestRunProcessInputError:
    def test_input_error_stored_as_friendly_message_not_generic_500(self, tmp_path, monkeypatch):
        """run_process phải bắt InputError TRƯỚC nhánh Exception chung — người dùng thấy đúng
        lý do (file sai), không phải 'Lỗi xử lý — xem log server'."""
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        token = svc.init_progress()
        svc.run_process(b'day khong phai file zip', token)
        prog = svc.get_progress(token)
        assert prog['done'] is True
        assert prog['error'] is not None
        assert 'xem log server' not in prog['msg']
        assert '.zip hợp lệ' in prog['msg']


# ── process_zip — bytes rỗng (b'') phải được coi là "có cung cấp" chứ không phải
#    "không cung cấp" (regression test cho fix truthy-check ngày hôm nay) ────────

class TestProcessZipHubBytesEdgeCase:
    def test_empty_bytes_hub_file_is_not_silently_skipped(self):
        """b'' (file 0 byte) khác None — không được lặng lẽ coi là 'không có file HUB',
        phải cố đọc và báo lỗi rõ ràng (file hỏng/rỗng) thay vì bỏ qua trong im lặng."""
        zip_bytes = _make_gl02_zip([_gl02_row('REF1', dr='100000')])
        with pytest.raises(Exception):
            svc.process_zip(zip_bytes, hub_di_bytes=b'', hub_den_bytes=b'')

    def test_none_hub_bytes_skips_1000ht_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row('REF1', dr='100000')])
        result = svc.process_zip(zip_bytes, hub_di_bytes=None, hub_den_bytes=None)
        assert result['hub_provided'] is False
        assert result['ht1000_rows'] == 0


# ── process_zip — ghép file tồn tháng trước (ton_bytes) trước khi phân loại ────

def _group_row_sum(result: dict) -> int:
    return (result['huy_rows'] + result['di_rows'] + result['ht1000_rows']
            + result['ccn_rows'] + result['ko_rows'] + result['can_cn_rows']
            + result['khac_rows'])


class TestProcessZipTonFile:
    def test_ton_rows_added_and_included_in_classification(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row('REF1', dr='100000')])
        ton_bytes = _make_ton_xlsx([_ton_row('TONREF1', dr=50000, remark='tồn cũ')])

        result = svc.process_zip(zip_bytes, ton_bytes=ton_bytes)
        assert result['ton_rows_added'] == 1
        # 1 dòng GL02 + 1 dòng tồn -> cả 2 phải được phân loại (bảo toàn dòng)
        assert _group_row_sum(result) == 2
        # Review PR#43 mục 5/8: total_before tính TRƯỚC khi ghép dòng tồn — "Tổng
        # số dòng" hiển thị nhỏ hơn tổng 7 ô cộng lại. total_rows PHẢI bằng đúng
        # số dòng đã thật sự phân loại (không tính filtered_rows vì đã bị lọc ra).
        assert result['total_rows'] == _group_row_sum(result) + result['filtered_rows']

    def test_missing_ton_bytes_behaves_like_before(self, tmp_path, monkeypatch):
        """Bước 2 trong yêu cầu: không có file tồn -> chạy y hệt trước khi có tham số mới."""
        monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)
        zip_bytes = _make_gl02_zip([_gl02_row('REF1', dr='100000')])
        result = svc.process_zip(zip_bytes)
        assert result['ton_rows_added'] == 0
        assert _group_row_sum(result) == 1
