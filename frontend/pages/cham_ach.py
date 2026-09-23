"""Trang Chấm đối chiếu ACH — chọn file từ máy người dùng, chạy pipeline, download kết quả.

D (23/09/2026) — tách 3 tab chạy ĐỘC LẬP thay cho 1 luồng chạy duy nhất:
- Tab "Timeout + Đối chiếu đi" — GỘP CHUNG cố ý (D0): cả hai đi qua đúng một
  bước khớp_voi_gw() ở backend, tách ra là phải tính lại từ đầu.
- Tab "Đối chiếu đến" — độc lập thật, không cần GW đi (D1 backend đã gỡ khỏi
  sàn bắt buộc chung).
- Tab "Báo cáo" — nơi liệt kê file kết quả THẬT SỰ được xuất (_BAO_CAO_REGISTRY)
  và (sau này, Luồng C) khối "Gộp kết quả pHub nhiều ngày".

D-3 (đã chốt): chỉ 1 lượt/lần cho CẢ TRANG — khi 1 tab đang chạy, khoá nút Chạy
của cả 2 tab còn lại (Báo cáo chưa có nút Chạy ở đợt này). Dùng CHUNG 1 bộ state
chạy (`run_state`) + progress/log/checkpoint — tách trạng thái FILE theo tab,
không tách logic poll/cancel/show kết quả (tránh lệch pha giữa các tab).
"""

import re
import asyncio

from nicegui import ui
import frontend.api_client as api
import frontend.ui_kit as ui_kit
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

# ─── Hằng số ──────────────────────────────────────────────────────────────────
_POLL_INTERVAL = 1.5   # giây

# Sức chịu đựng khi máy chủ im lặng = _MAX_POLL_FAILS × _POLL_TIMEOUT, KHÔNG phải
# × _POLL_INTERVAL: NiceGUI Timer gọi callback tuần tự rồi mới ngủ, nên một lần
# poll lỗi ngốn trọn timeout của nó. Bản cũ (4 lần × 10s mặc định của api_client)
# bỏ cuộc sau 40 giây và ghi nhầm trong comment là "~6s".
#
# 40 giây là quá ngắn: bước B4 giải nén 2 file MIS_DI rồi đọc CSV, và trong suốt
# quãng đó pipeline KHÔNG in dòng log nào — một lần giải nén nặng trông y hệt
# máy chủ đã chết. Nay chịu tới 10 × 30s = 5 phút, ngang các trang chấm khác
# (cham_459901, doi_chieu_song_phuong đều để trần 900 giây).
_POLL_TIMEOUT   = 30.0
_MAX_POLL_FAILS = 10

# Bấm "Dừng" chỉ ĐẶT CỜ. Pipeline ngó tới cờ đó ở ranh giới giữa các bước, nên
# đang giải nén 2 file MIS_DI thì phải xong chỗ đó mới dừng — cùng lý do khiến
# _MAX_POLL_FAILS phải chịu tới 5 phút. Chờ ngắn hơn là báo "chưa dừng được" oan.
_HAN_CHO_DUNG  = 300   # giây — tối đa chờ phiên cũ thật sự kết thúc
_NHIP_CHO_DUNG = 2.0   # giây — nhịp hỏi lại

# 2 tab CÓ nút Chạy (D-3 khoá lẫn nhau) — "baocao" chưa có nút Chạy ở đợt này,
# nút "Gộp" của Luồng C (sau này) CỐ Ý không dùng chung khoá này (C-K).
_TAB_LABELS = {
    'di':  'Timeout + Đối chiếu đi',
    'den': 'Đối chiếu đến',
}

_FILE_HINT_DI = (
    'PDF (session) · GW*.xlsx (đủ để tính Timeout) · 2× *_DI_*.zip · '
    'GL02*.zip (để đối chiếu Chiều đi với NPO) · '
    '(tùy chọn) MIS_DI_THUA*.csv / NPO_đi thừa T-2 / QT*.xlsx (Quyết toán OSB đi) / '
    'TIMEOUT_KHONG_KENH_*.csv ("TO ko đi kênh ngày cũ", Mục 8) / báo cáo Napas PDF hoặc CSV ISS'
)
_FILE_HINT_DEN = (
    'PDF (session) · GL02*.zip · 2× *_DEN_*.zip · '
    '(tùy chọn) MIS_DEN_THUA*.csv (T-2) / QT*.xlsx (Quyết toán OSB đến) / '
    'GW đến*.xlsx (Mục 4) / báo cáo Napas PDF hoặc CSV BEN'
)

# Nhãn hiển thị ở validate_card — chỉ hiện các mục LIÊN QUAN tới tab đang xem.
# Tab 1 gồm cả GL02 (Chiều đi cần NPO) dù D2 chỉ nói tắt "PDF + GW đi (+MIS_đi
# để ra số)" — quyết định tự chọn: không hiện GL02 sẽ khiến người dùng không
# hiểu vì sao nhóm "Chiều đi" báo CHƯA ĐỐI CHIẾU ĐƯỢC dù đã đủ GW+MIS_đi.
_CHECKS_TAB_DI  = {'File PDF (session)', 'GW (.xlsx)', 'MIS_DI (cần 2 file .zip)', 'GL02 (.zip)'}
_CHECKS_TAB_DEN = {'File PDF (session)', 'GL02 (.zip)', 'MIS_DEN (cần 2 file .zip)'}

# Mốc log → % tiến trình (tăng dần, không lùi lại)
_PROGRESS_MARKERS = [
    (re.compile(r'^Ngày đối chiếu:'),               0.05),
    (re.compile(r'^\[B1\] Session:'),                0.10),
    (re.compile(r'^Tìm thấy: GL02='),                0.15),
    (re.compile(r'\[TIMING\] Phase 1 IO:'),          0.45),
    (re.compile(r'^\[JOB\] Đang chờ xác nhận'),      0.50),
    (re.compile(r'\[TIMING\] Phase 2 đối chiếu:'),   0.65),
    (re.compile(r'\[TIMING\] Phase 3 Excel:'),       0.97),
    (re.compile(r'^Hoàn thành:'),                    1.0),
]
_EXCEL_STEP_RE = re.compile(r'\[EXCEL\] \((\d+)/(\d+)\)')


def _bump_progress(current: float, line: str) -> float:
    m = _EXCEL_STEP_RE.search(line)
    if m:
        i, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            current = max(current, 0.65 + 0.30 * (i / total))
    for pattern, pct in _PROGRESS_MARKERS:
        if pattern.search(line):
            current = max(current, pct)
    return current


# Khớp đúng thứ tự backend/services/ach_service.py::STAGE_LABELS — stage/% tiến
# trình tính ở server, trang này chỉ hiển thị.
_STAGE_LABELS = [
    'Đọc dữ liệu',
    'Chuẩn hoá & xử lý',
    'Đối chiếu & phân loại',
    'Tổng hợp báo cáo',
    'Hoàn tất',
]

# "Kết quả tạm thời" — nhóm nghiệp vụ ACH thật (khớp đúng dict summary_callback
# ở backend/services/ach/pipeline.py::xuat_excel), không dùng nhãn đối chiếu
# ngân hàng chung chung. (n_key, s_key, nhãn, icon, class khung, class chữ)
# D-4 (23/09/2026, đã chốt) — BỎ lớp tab con trong card "Kết quả tạm thời": mỗi
# tab lớn (Tab 1/Tab 2) chỉ hiện đúng bộ thẻ của mình, không còn 3 sub-tab
# Đi/Đến/Timeout lồng bên trong 1 tab lớn.
_SUMMARY_CARDS_DI = [
    ('khop_npo_di',    'tien_khop_npo_di',    'Khớp NPO — đi',  'call_made', 'bg-green-50 border-green-200', 'text-green-700'),
    ('khop_osb_di',    'tien_khop_osb_di',    'Khớp OSB — đi',  'call_made', 'bg-blue-50 border-blue-200',   'text-blue-700'),
    ('huy_trong_ngay', 'tien_huy_trong_ngay', 'Huỷ trong ngày', 'block',     'bg-gray-50 border-gray-200',   'text-gray-700'),
    ('huy_khac_ngay',  'tien_huy_khac_ngay',  'Huỷ khác ngày',  'block',     'bg-gray-50 border-gray-200',   'text-gray-700'),
    ('thua_di',        'tien_thua_di',        'Thừa chưa khớp — đi', 'warning', 'bg-red-50 border-red-200', 'text-red-700'),
]
_SUMMARY_CARDS_DEN = [
    ('khop_npo_den',   'tien_khop_npo_den',   'Khớp NPO — đến', 'call_received', 'bg-green-50 border-green-200', 'text-green-700'),
    ('khop_osb_den',   'tien_khop_osb_den',   'Khớp OSB — đến', 'call_received', 'bg-blue-50 border-blue-200',   'text-blue-700'),
    ('thua_den',       'tien_thua_den',       'Thừa chưa khớp — đến', 'warning', 'bg-red-50 border-red-200',    'text-red-700'),
]
_SUMMARY_CARDS_TIMEOUT = [
    ('timeout', 'tien_timeout', 'Timeout không đi kênh', 'schedule', 'bg-orange-50 border-orange-200', 'text-orange-700'),
]

# ─── D3 — Tab Báo cáo: registry các file THẬT SỰ được xuất ───────────────────
# Đọc trực tiếp `xuat_excel()` + khối xuất file cuối `main_from_dir()`
# (backend/services/ach/pipeline.py) để liệt kê — KHÔNG chép registry bản cũ
# (từng có mục `_ACH_PHUBLOI.xlsx` trỏ file không còn được xuất từ 18/09/2026).
# (regex tên file, tên nghiệp vụ, mô tả)
_BAO_CAO_REGISTRY: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'^doi_chieu_\d{8}\.xlsx$'),
     'Báo cáo tổng hợp',
     'File chính — các sheet Chiều đi/Chiều đến/Timeout của lượt chạy này.'),
    (re.compile(r'^TIMEOUT_KHONG_KENH_\d{8}\.csv$'),
     'Timeout không đi kênh (mang sang ngày sau)',
     'Input "TO ko đi kênh ngày cũ" (Mục 8) cho lượt chạy kế tiếp — cũng là '
     'nguyên liệu cho màn Gộp kết quả pHub (Luồng C).'),
    (re.compile(r'^GW_CHO_PHUB_\d{8}\.csv$'),
     'GW-cho-pHub (A4, chỉ xuất khi tick)',
     'Chỉ xuất khi tick "Tạo file GW-cho-pHub" ở Tab 1 — nguyên liệu cho màn '
     'Gộp kết quả pHub (Luồng C). Máy chủ không giữ bản sao, tải về ngay.'),
    (re.compile(r'^NPO_DI_THUA_\d{8}\.csv$'),
     'NPO_đi thừa (mang sang ngày sau)',
     'Input đối chiếu chéo ngày (Mục 5) cho lượt chạy kế tiếp.'),
    (re.compile(r'^QT_DI_THUA_\d{8}\.csv$'),
     'QT đi thừa (mang sang ngày sau)',
     'Input đối chiếu chéo ngày (Mục 5.1) cho lượt chạy kế tiếp.'),
    (re.compile(r'^\d{8}_ACH_OSB\.xlsx$'),
     'Đối chiếu OSB / Quyết toán (Điểm 2)',
     'Chỉ xuất khi có file QT*.xlsx (Quyết toán OSB đi và/hoặc đến).'),
    (re.compile(r'^\d{8}_ACH_GWDEN\.xlsx$'),
     'Đối chiếu GW đến (Mục 4)',
     'Chỉ xuất khi có file GW đến (tuỳ chọn) và MIS_đến.'),
    (re.compile(r'^\d{8}_ACH_Napas\.xlsx$'),
     'Đối chiếu Napas BC.03 (Mục 6/7)',
     'Chỉ xuất khi có báo cáo Napas PDF hoặc CSV chi tiết ISS/BEN.'),
    (re.compile(r'^\d{8}_ACH_MISThuaT2\.xlsx$'),
     'Đối chiếu chéo ngày MIS thừa T-2 (Điểm 4)',
     'Chỉ xuất khi có file MIS_DI_THUA*/MIS_DEN_THUA*.csv của ngày trước.'),
    (re.compile(r'^\d{8}_ACH_HuyCheoNgay\.xlsx$'),
     'Đối chiếu chéo ngày huỷ khác ngày (Mục 5/5.1)',
     'So NPO_đi thừa T-2 / QT đi thừa T-2 với huỷ khác ngày của ngày đang chạy.'),
    (re.compile(r'^\d{8}_ACH_TimeoutCu\.xlsx$'),
     'Đối chiếu Timeout ngày cũ (Mục 8)',
     'Chỉ xuất khi có đính kèm file "TO ko đi kênh ngày cũ".'),
]


def _phan_loai_bao_cao(files: list[str]) -> list[tuple[str, str, list[str]]]:
    """[(tên_nghiệp_vụ, mô_tả, [file...])] theo `_BAO_CAO_REGISTRY`. File KHÔNG
    khớp mục nào rơi vào nhóm "Khác" — không được để file biến mất khỏi màn hình
    chỉ vì registry thiếu (đúng tinh thần dự án: thiếu sót phải LỘ RA)."""
    nhom: dict[str, list[str]] = {}
    mo_ta: dict[str, str] = {}
    khac: list[str] = []
    for f in sorted(files):
        for pattern, ten, mota in _BAO_CAO_REGISTRY:
            if pattern.match(f):
                nhom.setdefault(ten, []).append(f)
                mo_ta[ten] = mota
                break
        else:
            khac.append(f)
    ket_qua = [(ten, mo_ta[ten], fs) for ten, fs in nhom.items()]
    if khac:
        ket_qua.append((
            'Khác (chưa có trong danh mục)',
            'File này chưa khớp mục nào ở trên — vẫn tải được bình thường, '
            'báo người phát triển bổ sung vào _BAO_CAO_REGISTRY.',
            khac,
        ))
    return ket_qua


@ui.page('/cham_ach')
async def cham_ach_page():
    if not _require_auth():
        return
    if not api.has_feature('menu.cham_ach'):
        ui.navigate.to('/home')
        return

    # Quyền chạy tách khỏi quyền xem — người chỉ có menu.cham_ach vẫn theo dõi
    # tiến độ và tải kết quả được, nhưng không khởi động/tiếp tục được lần chạy.
    co_quyen_chay = api.has_feature('cham_ach.process')

    # ── State CHUNG cho cả trang (chạy/poll/checkpoint) ─────────────────────
    # D-3: 1 lượt/lần cho CẢ TRANG — không phải 1 lượt/tab. `active_tab` cho
    # biết tab nào đang giữ job hiện tại, dùng để khoá 2 nút Chạy còn lại.
    run_state = {
        'job_id':      None,
        'log_pos':     0,
        'timer':       None,
        'running':     False,
        # job_open — CÓ job đang chiếm slot (đang chạy HOẶC đang chờ xác nhận
        # Checkpoint) — khác `running` (chỉ True lúc pipeline thật sự đang
        # chạy). Khoá 2 nút Chạy (D-3) phải dựa vào job_open: lúc Checkpoint
        # tạm dừng, `running` = False nhưng job vẫn CHIẾM SLOT trên máy chủ —
        # khoá theo `running` sẽ mở khoá nhầm, cho bấm Chạy tab kia trong khi
        # tab này còn đang chờ xác nhận (đặc biệt ở chế độ Checkpoint "deferred"
        # — không có dialog modal nào chặn thao tác nền).
        'job_open':    False,
        'active_tab':  None,          # 'di' | 'den'
        'progress':    0.0,
        'poll_fails':  0,
        'stage':       0,
        'dang_cho_dung': False,
        'xac_nhan_upload': None,
        'checkpoint_mode': 'inline',   # Tab 'di' — 'inline' | 'deferred'
        'pending_checkpoint_res': None,
        'bo_qua_checkpoint': False,    # Tab 'di' — chạy thẳng, bỏ qua Checkpoint
        'tao_gw_cho_phub': False,      # Tab 'di' — ô tick A4, xuất GW_CHO_PHUB_*.csv, mặc định TẮT
        'max_total_mb': None,
        'mis_di_thieu': False,         # Tab 'di' — hint nút Chạy
        'last_files': [],              # file kết quả job GẦN NHẤT — hiện ở tab Báo cáo
    }

    # ── State FILE riêng từng tab (D2) ───────────────────────────────────────
    state_di  = {'files': {}, 'tang0_ok': False}
    state_den = {'files': {}, 'tang0_ok': False}

    with ui.row().classes('w-full'):
        await _sidebar('cham_ach')
        with _content_area():
            _page_header('Chấm đối chiếu ACH', 'Đối chiếu GL02 (NPO) với MIS — Phòng Thanh toán')

            # ── Banner "đang chạy" CHUNG — hiện bất kể đang xem tab nào ──────
            with ui.row().classes(
                'w-full items-center gap-3 p-3 mb-4 rounded bg-blue-50 border border-blue-200'
            ) as running_bar:
                spinner = ui.spinner('dots', size='sm', color='blue')
                running_label = ui.label('').classes('text-sm text-blue-800 flex-grow')
                btn_cancel = ui.button('Dừng', icon='stop_circle', color='grey-6').props('dense')
            running_bar.set_visibility(False)

            # ── 3 tab cấp cao nhất (D2) ───────────────────────────────────────
            with ui.tabs().props(
                'active-color=red-800 indicator-color=red-800 align=left'
            ).classes('w-full border-b border-gray-200 mb-4') as top_tabs:
                tab_di     = ui.tab('di', label='Timeout + Đối chiếu đi')
                tab_den    = ui.tab('den', label='Đối chiếu đến')
                tab_baocao = ui.tab('baocao', label='Báo cáo')

            with ui.tab_panels(top_tabs, value=tab_di).classes('w-full'):

                # ══════════════════════════ TAB 1 ═══════════════════════════
                with ui.tab_panel(tab_di):
                    with ui.card().classes('w-full p-5 mb-4'):
                        ui.label('Nguồn dữ liệu — Timeout + Đối chiếu đi').classes(
                            'text-base font-semibold text-red-800 mb-3')

                        file_list_label_di = ui.label('Chưa chọn file nào').classes(
                            'text-xs text-gray-400 italic mb-2')
                        ui.label(_FILE_HINT_DI).classes('text-xs text-gray-400 mb-1')

                        async def on_upload_di(e):
                            data = e.content.read()
                            state_di['files'][e.name] = data
                            names = ', '.join(state_di['files'].keys())
                            file_list_label_di.set_text(
                                f'Đã chọn ({len(state_di["files"])} file, '
                                f'{_tong_mb(state_di):.0f} MB): {names}')
                            file_list_label_di.classes(
                                remove='text-gray-400 italic', add='text-green-700 font-medium')
                            await _validate_now('di', state_di, validate_card_di, _CHECKS_TAB_DI)

                        async def on_clear_di():
                            state_di['files'].clear()
                            file_list_label_di.set_text('Chưa chọn file nào')
                            file_list_label_di.classes(
                                remove='text-green-700 font-medium', add='text-gray-400 italic')
                            await _validate_now('di', state_di, validate_card_di, _CHECKS_TAB_DI)

                        ui.upload(
                            on_upload=on_upload_di, auto_upload=True, multiple=True,
                        ).props(
                            'accept=".zip,.xlsx,.pdf,.csv" flat dense label="Chọn file (có thể chọn nhiều)..."'
                        ).classes('w-full mb-1')
                        ui.button('Xóa tất cả file', icon='delete_outline', color='grey-6',
                                  on_click=on_clear_di).props('flat dense').classes('text-xs')

                        with ui.row().classes('items-center gap-3 mt-3'):
                            ui.label('Ngày đối chiếu:').classes('text-sm text-gray-600')
                            ngay_input_di = _ngay_input()
                            ui.label('Bỏ trống → tự động lấy từ tên file PDF').classes(
                                'text-xs text-gray-400')

                        validate_card_di = ui.column().classes(
                            'w-full mt-3 gap-1 p-3 rounded bg-gray-50 border')
                        validate_card_di.set_visibility(False)

                        # ── Chế độ xử lý Checkpoint (chỉ có ý nghĩa khi có MIS_đi) ──
                        checkpoint_section = ui.column().classes('w-full gap-1 mt-4')
                        with checkpoint_section:
                            ui.label('Chế độ xử lý Checkpoint').classes(
                                'text-sm font-medium text-gray-700')
                            checkpoint_mode_radio = ui.radio(
                                {
                                    'inline':   'Xác nhận ngay khi MIS_đi vừa tạo xong (quy trình hiện tại)',
                                    'deferred': 'Chạy hết phần tự động, sau đó mới xác nhận MIS_đi rồi tiếp tục chạy',
                                },
                                value='inline',
                            ).props('dense')

                        with ui.row().classes(
                            'w-full items-start gap-2 mt-3 p-3 rounded bg-orange-50 border border-orange-200'
                        ):
                            ui.icon('warning').classes('text-orange-700 mt-1')
                            with ui.column().classes('gap-0'):
                                bo_qua_checkbox = ui.checkbox(
                                    'Chạy thẳng — bỏ qua xác nhận thủ công MIS_đi'
                                ).props('dense').classes('text-orange-900 font-medium')
                                ui.label(
                                    'Coi TOÀN BỘ MIS_đi là đúng 100% (không loại dòng nào, không bổ sung REFHUB), '
                                    'chạy một mạch tới báo cáo cuối — KHÔNG dừng lại chờ xác nhận. Chỉ dùng khi '
                                    'chắc chắn không nghi ngờ dữ liệu.'
                                ).classes('text-xs text-orange-700')

                        with ui.row().classes('gap-3 mt-4 items-center'):
                            btn_run_di = ui.button('Chạy Timeout + Đối chiếu đi', icon='play_arrow',
                                                    color='red-8').classes('font-semibold')
                            if not co_quyen_chay:
                                btn_run_di.props('disable')
                                btn_run_di.tooltip('Bạn không có quyền thực hiện thao tác này')
                            hint_chay_label = ui.label(
                                'Pipeline sẽ dừng lại ngay sau khi tạo xong MIS_đi để bạn xác nhận, '
                                'rồi mới chạy tiếp tới báo cáo cuối.'
                            ).classes('text-xs text-gray-400')

                        def _cap_nhat_hint_chay():
                            if run_state['bo_qua_checkpoint']:
                                hint_chay_label.set_text(
                                    'Sẽ CHẠY THẲNG tới báo cáo cuối — KHÔNG dừng lại chờ xác nhận MIS_đi.')
                                hint_chay_label.classes(
                                    remove='text-gray-400', add='text-orange-700 font-semibold')
                            elif run_state['mis_di_thieu']:
                                # 2026-09-16 — thiếu MIS_đi thì không có gì để Checkpoint
                                # xác nhận, pipeline tự động chạy thẳng dù chưa tick.
                                hint_chay_label.set_text(
                                    'Đang thiếu MIS_đi — không có gì để xác nhận, pipeline sẽ '
                                    'CHẠY THẲNG tới báo cáo cuối dù không tick "chạy thẳng" ở trên.')
                                hint_chay_label.classes(
                                    remove='text-gray-400', add='text-orange-700 font-semibold')
                            else:
                                hint_chay_label.set_text(
                                    'Pipeline sẽ dừng lại ngay sau khi tạo xong MIS_đi để bạn xác nhận, '
                                    'rồi mới chạy tiếp tới báo cáo cuối.')
                                hint_chay_label.classes(
                                    remove='text-orange-700 font-semibold', add='text-gray-400')

                        def _on_bo_qua_change(val: bool):
                            run_state['bo_qua_checkpoint'] = val
                            checkpoint_section.set_visibility(not val)
                            _cap_nhat_hint_chay()

                        bo_qua_checkbox.on_value_change(lambda e: _on_bo_qua_change(e.value))

                        # ── Ô tick A4 (23.09.2026) — xuất GW-cho-pHub, mặc định TẮT ──
                        # C1 đã chốt: server KHÔNG lưu gì (C-S) — quên tick nghĩa là
                        # ngày hôm nay VĨNH VIỄN không có file để gộp pHub sau này. Nhãn
                        # phải nói rõ hậu quả (rủi ro #6, PLAN.md), không viết chung
                        # chung kiểu "Tạo file phụ".
                        with ui.row().classes(
                            'w-full items-start gap-2 mt-3 p-3 rounded bg-amber-50 border border-amber-200'
                        ):
                            ui.icon('info').classes('text-amber-700 mt-1')
                            with ui.column().classes('gap-0'):
                                gw_cho_phub_checkbox = ui.checkbox(
                                    'Tạo file GW-cho-pHub (dùng cho màn Gộp pHub sau này)'
                                ).props('dense').classes('text-amber-900 font-medium')
                                ui.label(
                                    'KHÔNG tick thì hôm nay KHÔNG có file GW-cho-pHub để gộp pHub sau này, '
                                    'và KHÔNG lấy lại được (máy chủ không lưu bản sao — muốn có lại phải chạy '
                                    'lại toàn bộ đối chiếu ngày này). Bật thêm khoảng 1 phút vào lượt chạy.'
                                ).classes('text-xs text-amber-700')

                        def _on_gw_cho_phub_change(val: bool):
                            run_state['tao_gw_cho_phub'] = val

                        gw_cho_phub_checkbox.on_value_change(lambda e: _on_gw_cho_phub_change(e.value))

                        bo_qua_confirm_dialog = ui.dialog()
                        with bo_qua_confirm_dialog, ui.card().classes('p-5').style('min-width: 420px'):
                            ui.label('Xác nhận chạy thẳng, bỏ qua Checkpoint').classes(
                                'text-base font-semibold text-orange-800 mb-2')
                            ui.label(
                                'Pipeline sẽ KHÔNG dừng lại để bạn xác nhận MIS_đi — toàn bộ được coi là đúng 100% '
                                'và đi thẳng vào báo cáo cuối. Nếu sau này phát hiện sai sót, bạn cần chạy lại '
                                '(bỏ tick) để đi qua Checkpoint như bình thường.'
                            ).classes('text-sm text-gray-700 mb-4')
                            with ui.row().classes('gap-2 justify-end w-full'):
                                ui.button('Hủy', color='grey-6').props('flat').on(
                                    'click', bo_qua_confirm_dialog.close)
                                btn_xac_nhan_chay_thang = ui.button(
                                    'Tôi hiểu, chạy thẳng luôn', icon='play_arrow', color='orange-8',
                                ).classes('font-semibold')

                    # "Kết quả tạm thời" Tab 1 — D-4: KHÔNG có sub-tab, hiện thẳng
                    # 2 bộ thẻ (Chiều đi + Timeout) trong cùng 1 card.
                    summary_card_di = ui.card().classes('w-full p-4 mb-4')
                    summary_card_di.set_visibility(False)
                    with summary_card_di:
                        ui.label('Kết quả tạm thời — Chiều đi').classes(
                            'text-base font-semibold text-red-800 mb-2')
                        summary_body_di = ui.row().classes('w-full gap-3 flex-wrap mb-3')
                        ui.label('Kết quả tạm thời — Timeout không đi kênh').classes(
                            'text-base font-semibold text-red-800 mb-2')
                        summary_body_timeout = ui.row().classes('w-full gap-3 flex-wrap')

                # ══════════════════════════ TAB 2 ═══════════════════════════
                with ui.tab_panel(tab_den):
                    with ui.card().classes('w-full p-5 mb-4'):
                        ui.label('Nguồn dữ liệu — Đối chiếu đến').classes(
                            'text-base font-semibold text-red-800 mb-3')

                        file_list_label_den = ui.label('Chưa chọn file nào').classes(
                            'text-xs text-gray-400 italic mb-2')
                        ui.label(_FILE_HINT_DEN).classes('text-xs text-gray-400 mb-1')

                        async def on_upload_den(e):
                            data = e.content.read()
                            state_den['files'][e.name] = data
                            names = ', '.join(state_den['files'].keys())
                            file_list_label_den.set_text(
                                f'Đã chọn ({len(state_den["files"])} file, '
                                f'{_tong_mb(state_den):.0f} MB): {names}')
                            file_list_label_den.classes(
                                remove='text-gray-400 italic', add='text-green-700 font-medium')
                            await _validate_now('den', state_den, validate_card_den, _CHECKS_TAB_DEN)

                        async def on_clear_den():
                            state_den['files'].clear()
                            file_list_label_den.set_text('Chưa chọn file nào')
                            file_list_label_den.classes(
                                remove='text-green-700 font-medium', add='text-gray-400 italic')
                            await _validate_now('den', state_den, validate_card_den, _CHECKS_TAB_DEN)

                        ui.upload(
                            on_upload=on_upload_den, auto_upload=True, multiple=True,
                        ).props(
                            'accept=".zip,.xlsx,.pdf,.csv" flat dense label="Chọn file (có thể chọn nhiều)..."'
                        ).classes('w-full mb-1')
                        ui.button('Xóa tất cả file', icon='delete_outline', color='grey-6',
                                  on_click=on_clear_den).props('flat dense').classes('text-xs')

                        with ui.row().classes('items-center gap-3 mt-3'):
                            ui.label('Ngày đối chiếu:').classes('text-sm text-gray-600')
                            ngay_input_den = _ngay_input()
                            ui.label('Bỏ trống → tự động lấy từ tên file PDF').classes(
                                'text-xs text-gray-400')

                        validate_card_den = ui.column().classes(
                            'w-full mt-3 gap-1 p-3 rounded bg-gray-50 border')
                        validate_card_den.set_visibility(False)

                        with ui.row().classes('gap-3 mt-4 items-center'):
                            btn_run_den = ui.button('Chạy đối chiếu đến', icon='play_arrow',
                                                     color='red-8').classes('font-semibold')
                            if not co_quyen_chay:
                                btn_run_den.props('disable')
                                btn_run_den.tooltip('Bạn không có quyền thực hiện thao tác này')

                    summary_card_den = ui.card().classes('w-full p-4 mb-4')
                    summary_card_den.set_visibility(False)
                    with summary_card_den:
                        ui.label('Kết quả tạm thời — Chiều đến').classes(
                            'text-base font-semibold text-red-800 mb-2')
                        summary_body_den = ui.row().classes('w-full gap-3 flex-wrap')

                # ══════════════════════════ TAB 3 — BÁO CÁO ═════════════════
                with ui.tab_panel(tab_baocao):
                    with ui.card().classes('w-full p-5 mb-4'):
                        ui.label('Kết quả — lượt chạy gần nhất').classes(
                            'text-base font-semibold text-red-800 mb-3')
                        bao_cao_container = ui.column().classes('w-full gap-2')
                        with bao_cao_container:
                            ui.label(
                                'Chưa có kết quả — chạy đối chiếu ở tab "Timeout + Đối chiếu đi" '
                                'hoặc "Đối chiếu đến" trước.'
                            ).classes('text-sm text-gray-400 italic')

                    # ── D4/D-5 (23/09/2026) — kết quả CŨ còn sống trên máy chủ ──────
                    # Khác card phía trên (chỉ nhớ job của phiên trình duyệt HIỆN TẠI,
                    # mất khi F5): đây là các lượt chạy TRƯỚC ĐÓ (kể cả tab/máy khác,
                    # kể cả sau F5) mà server còn giữ (chưa tới mốc dọn 23h). Lọc theo
                    # CHÍNH người đang đăng nhập ở BACKEND (`GET /api/ach/ket-qua`) —
                    # đây là phạm vi DỮ LIỆU, không phải quyền (docs/DESIGN.md).
                    with ui.card().classes('w-full p-5 mb-4'):
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.label('Kết quả khác của bạn còn trên máy chủ').classes(
                                'text-base font-semibold text-red-800')
                            btn_lam_moi_ket_qua_cu = ui.button(
                                icon='refresh', color='grey-6').props('flat dense round')
                        ui.label(
                            'Các lượt chạy TRƯỚC ĐÓ của chính bạn (kể cả sau khi tải lại trang) '
                            'mà máy chủ chưa dọn — kết quả bị dọn tự động sau 23h mỗi ngày.'
                        ).classes('text-xs text-gray-500 mb-2')
                        ket_qua_cu_container = ui.column().classes('w-full gap-2')
                        with ket_qua_cu_container:
                            ui.label('Đang tải...').classes('text-xs text-gray-400 italic')

                    # ── Luồng C (23/09/2026) — Gộp kết quả pHub nhiều ngày ──────────
                    # Bản-2 "kho 30 ngày" đã gỡ (Luồng A). Bản-3: server KHÔNG lưu gì
                    # ngoài kết quả cuối — nạp N file TIMEOUT_KHONG_KENH_*.csv + N file
                    # GW_CHO_PHUB_*.csv (chị Thảo tự giữ trên máy mình) + 1 file pHub
                    # trong CÙNG 1 request. CỐ Ý dùng state RIÊNG (`phub_state`), KHÔNG
                    # dùng chung `run_state`/khoá `gianh_cho('ach')` (C-K đã chốt —
                    # rủi ro chồng RAM đã được người dùng chấp nhận CÓ Ý THỨC, xem
                    # docs/Implementation-notes.html + pipeline/PLAN.md mục 4 C-K —
                    # KHÔNG tự ý "sửa cho đúng" bằng cách bọc khoá vào đây).
                    phub_state = {'files': {}}

                    with ui.card().classes('w-full p-5 mb-4'):
                        ui.label('Gộp kết quả pHub nhiều ngày').classes(
                            'text-base font-semibold text-red-800 mb-1')
                        ui.label(
                            'Nạp N file TIMEOUT_KHONG_KENH_*.csv + N file GW_CHO_PHUB_*.csv đã '
                            'tải về từ các lượt chạy trước + ĐÚNG 1 file pHub (.xlsx) trong CÙNG '
                            'một lượt. Xem 1 ngày cũng phải qua đây (nạp đủ bộ 3 loại file của '
                            'ngày đó) — kết quả KHÔNG lưu lại trên máy chủ, tải về ngay để giữ.'
                        ).classes('text-xs text-gray-500 mb-3')

                        phub_file_label = ui.label('Chưa chọn file nào').classes(
                            'text-xs text-gray-400 italic mb-2')

                        async def on_upload_phub(e):
                            data = e.content.read()
                            phub_state['files'][e.name] = data
                            names = ', '.join(phub_state['files'].keys())
                            phub_file_label.set_text(
                                f'Đã chọn ({len(phub_state["files"])} file, '
                                f'{_tong_mb(phub_state):.0f} MB): {names}')
                            phub_file_label.classes(
                                remove='text-gray-400 italic', add='text-green-700 font-medium')

                        async def on_clear_phub():
                            phub_state['files'].clear()
                            phub_file_label.set_text('Chưa chọn file nào')
                            phub_file_label.classes(
                                remove='text-green-700 font-medium', add='text-gray-400 italic')
                            phub_ket_qua_container.clear()

                        ui.upload(
                            on_upload=on_upload_phub, auto_upload=True, multiple=True,
                        ).props(
                            'accept=".xlsx,.csv" flat dense label="Chọn file (có thể chọn nhiều)..."'
                        ).classes('w-full mb-1')
                        ui.button('Xóa tất cả file', icon='delete_outline', color='grey-6',
                                  on_click=on_clear_phub).props('flat dense').classes('text-xs')

                        with ui.row().classes('gap-3 mt-4 items-center'):
                            btn_gop_phub = ui.button('Gộp', icon='merge_type', color='red-8').classes(
                                'font-semibold')
                            if not co_quyen_chay:
                                btn_gop_phub.props('disable')
                                btn_gop_phub.tooltip('Bạn không có quyền thực hiện thao tác này')

                        phub_ket_qua_container = ui.column().classes('w-full mt-3 gap-2')

                    async def _dam_bao_tran_dung_luong_phub():
                        """Trần dung lượng dùng CHUNG `_MAX_UPLOAD`/ACH_MAX_UPLOAD_MB với
                        Tab 1/2 (backend/api/ach.py) — lấy qua /api/ach/validate nếu
                        `run_state['max_total_mb']` chưa có sẵn (VD người dùng vào thẳng
                        tab Báo cáo, chưa từng chọn file ở 2 tab kia)."""
                        if run_state['max_total_mb'] is not None:
                            return
                        try:
                            res = await asyncio.to_thread(
                                api.post, '/api/ach/validate', {'filenames': []})
                            run_state['max_total_mb'] = res.get('max_total_mb')
                        except Exception:
                            pass   # không lấy được trần thì máy chủ vẫn tự chặn 413

                    def _render_phub_ket_qua(res: dict):
                        phub_ket_qua_container.clear()
                        tong_ket = res.get('tong_ket') or {}
                        canh_bao = res.get('canh_bao') or []
                        ma       = res.get('ma')
                        ten_file = res.get('ten_file')
                        with phub_ket_qua_container:
                            with ui.row().classes('w-full gap-3 flex-wrap'):
                                for label, key in [
                                    ('Hoàn thành', 'hoan_thanh'),
                                    ('TT lệnh lỗi ngày T', 'tt_lenh_loi'),
                                    ('Trạng thái khác', 'trang_thai_khac'),
                                    ('Tổng', 'tong'),
                                ]:
                                    with ui.column().classes(
                                        'flex-1 min-w-[9rem] p-3 rounded-lg border bg-gray-50 gap-0'
                                    ):
                                        ui.label(label).classes('text-xs font-medium text-gray-600')
                                        ui.label(f'{tong_ket.get(key, 0):,}').classes(
                                            'text-xl font-bold text-red-700')
                            if canh_bao:
                                with ui.column().classes(
                                    'w-full gap-1 mt-1 p-3 rounded bg-orange-50 border border-orange-200'
                                ):
                                    for c in canh_bao:
                                        ui.label(f'⚠ {c}').classes('text-xs text-orange-800')
                            if ten_file:
                                url = f'/api/ach/phub-gop/{ma}/tai'

                                async def _tai_ket_qua_phub(u=url, name=ten_file):
                                    try:
                                        content = await asyncio.to_thread(
                                            api.download, u, params={'filename': name})
                                    except Exception as e:
                                        if not _handle_api_error(e):
                                            ui.notify(str(e), type='negative')
                                        return
                                    ui.download(content, name)

                                ui.button(ten_file, icon='table_chart', color='green-7').on(
                                    'click', _tai_ket_qua_phub
                                ).classes('text-xs mt-2')

                    async def _thuc_hien_gop_phub():
                        if not phub_state['files']:
                            ui.notify('Chưa chọn file nào.', type='warning')
                            return

                        await _dam_bao_tran_dung_luong_phub()
                        loi_dung_luong = _qua_tran_dung_luong(phub_state)
                        if loi_dung_luong:
                            ui.notify(loi_dung_luong, type='negative', timeout=0)
                            return

                        btn_gop_phub.props('disable')
                        phub_ket_qua_container.clear()
                        with phub_ket_qua_container:
                            ui.label('Đang gộp...').classes('text-xs text-gray-500 italic')

                        try:
                            res = await asyncio.to_thread(
                                api.post_upload, '/api/ach/phub-gop',
                                files=[('files', (name, data, 'application/octet-stream'))
                                       for name, data in phub_state['files'].items()],
                                timeout=300.0,
                            )
                        except Exception as e:
                            phub_ket_qua_container.clear()
                            if not _handle_api_error(e):
                                with phub_ket_qua_container:
                                    ui.label(_giai_thich_loi_upload(phub_state, e)).classes(
                                        'text-xs text-red-600')
                            return
                        finally:
                            if co_quyen_chay:
                                btn_gop_phub.props(remove='disable')

                        _render_phub_ket_qua(res)

                    btn_gop_phub.on('click', _thuc_hien_gop_phub)

            # ── Tiến trình (CHUNG) ───────────────────────────────────────────
            progress_card = ui.card().classes('w-full p-4 mb-4')
            progress_card.set_visibility(False)
            with progress_card:
                stepper_box = ui.column().classes('w-full')
                with stepper_box:
                    ui_kit.stepper(_STAGE_LABELS, 0)

            # ── Log card (CHUNG) ─────────────────────────────────────────────
            with ui.card().classes('w-full p-0 mb-4'):
                with ui.row().classes('w-full bg-gray-800 px-4 py-2 rounded-t items-center gap-2'):
                    ui.icon('terminal').classes('text-green-400 text-sm')
                    ui.label('Log xử lý').classes('text-xs font-semibold text-green-300')

                progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
                progress_bar.set_visibility(False)

                log_area = ui.column().classes(
                    'w-full bg-gray-900 font-mono text-xs text-green-200 '
                    'p-3 overflow-y-auto max-h-64 min-h-24 gap-0'
                )
                with log_area:
                    ui.label('Sẵn sàng. Chọn file và bấm "Chạy" ở tab tương ứng.').classes('text-gray-500')

            # ── Checkpoint xác nhận thủ công (chỉ phát sinh từ tab "di") ─────
            checkpoint_dialog = ui.dialog().props('persistent')

            checkpoint_banner = ui.row().classes(
                'w-full items-center gap-3 p-3 mb-4 rounded bg-orange-50 border border-orange-200'
            )
            checkpoint_banner.set_visibility(False)
            with checkpoint_banner:
                ui.icon('notification_important').classes('text-orange-700')
                checkpoint_banner_label = ui.label('').classes('text-sm text-orange-800 flex-grow')
                btn_open_checkpoint = ui.button('Xem và xác nhận', icon='fact_check',
                                                color='orange-8').props('dense')

            # ── Logic CHUNG ───────────────────────────────────────────────────

            def _tong_mb(tstate: dict) -> float:
                return sum(len(d) for d in tstate['files'].values()) / (1024 * 1024)

            def _append_log(msg: str):
                with log_area:
                    ui.label(msg).classes('leading-tight')
                run_state['progress'] = _bump_progress(run_state['progress'], msg)
                progress_bar.set_value(run_state['progress'])

            def _update_stage(stage: int, progress: float | None = None):
                run_state['stage'] = stage
                progress_card.set_visibility(True)
                if progress is not None:
                    run_state['progress'] = progress
                    progress_bar.set_value(progress)
                stepper_box.clear()
                with stepper_box:
                    ui_kit.stepper(_STAGE_LABELS, stage)

            def _render_cards(container, cards, summary: dict):
                container.clear()
                with container:
                    for n_key, s_key, label, icon, box_cls, txt_cls in cards:
                        n = summary.get(n_key)
                        s = summary.get(s_key)
                        with ui.column().classes(
                            f'flex-1 min-w-[11rem] p-3 rounded-lg border gap-0 {box_cls}'
                        ):
                            with ui.row().classes('items-center gap-1'):
                                ui.icon(icon).classes(f'text-sm {txt_cls}')
                                ui.label(label).classes(f'text-xs font-medium {txt_cls}')
                            if n is None:
                                # Chạy giản lược theo file đang có — None nghĩa là
                                # backend CHƯA TÍNH ĐƯỢC (thiếu file), KHÔNG phải 0
                                # dòng thật (feedback_binary_match_status).
                                ui.label('CHƯA ĐỐI CHIẾU ĐƯỢC').classes(
                                    'text-sm font-semibold text-gray-400 italic mt-1')
                            else:
                                ui.label(f'{n:,}').classes(f'text-xl font-bold {txt_cls}')
                                ui.label(f'{s:,} VND').classes('text-xs text-gray-500')

            def _render_summary(summary: dict | None):
                """D-4 — chỉ đổ vào bộ thẻ của TAB đã khởi động job hiện tại."""
                if not summary:
                    return
                if run_state['active_tab'] == 'di':
                    summary_card_di.set_visibility(True)
                    _render_cards(summary_body_di,      _SUMMARY_CARDS_DI,      summary)
                    _render_cards(summary_body_timeout, _SUMMARY_CARDS_TIMEOUT, summary)
                elif run_state['active_tab'] == 'den':
                    summary_card_den.set_visibility(True)
                    _render_cards(summary_body_den, _SUMMARY_CARDS_DEN, summary)

            def _clear_log():
                log_area.clear()
                run_state['progress'] = 0.0
                progress_bar.set_value(0)
                run_state['stage'] = 0
                progress_card.set_visibility(False)
                summary_card_di.set_visibility(False)
                summary_card_den.set_visibility(False)
                summary_body_di.clear()
                summary_body_den.clear()
                summary_body_timeout.clear()

            def _render_validate_result(container, res: dict, relevant_labels: set[str]):
                container.set_visibility(True)
                container.clear()
                checks = [c for c in res.get('checks', []) if c['label'] in relevant_labels]
                with container:
                    for chk in checks:
                        icon  = 'check_circle' if chk['ok'] else 'cancel'
                        color = 'text-green-600' if chk['ok'] else 'text-red-600'
                        with ui.row().classes('items-center gap-2'):
                            ui.icon(icon).classes(f'{color} text-base')
                            ui.label(chk['label']).classes('text-xs font-medium')
                        ui.label(chk['detail']).classes('text-xs text-gray-500 ml-6 -mt-1')

                    # Chạy giản lược theo file đang có — thiếu file KHÔNG CÒN chặn
                    # chạy (trừ PDF), chỉ báo trước phần nào sẽ "CHƯA ĐỐI CHIẾU ĐƯỢC".
                    thieu_lst = [c['label'] for c in checks if not c['ok']]
                    if thieu_lst and res.get('tang0_ok'):
                        thieu = ', '.join(thieu_lst)
                        with ui.row().classes(
                            'w-full items-start gap-2 mt-3 p-3 rounded bg-orange-50 border border-orange-200'
                        ):
                            ui.icon('info').classes('text-orange-700 mt-1')
                            with ui.column().classes('gap-0'):
                                ui.label(
                                    f'Thiếu {thieu} — vẫn chạy được, các mục phụ thuộc sẽ ghi '
                                    f'"CHƯA ĐỐI CHIẾU ĐƯỢC" thay vì số liệu thật, phần còn lại '
                                    f'vẫn ra kết quả bình thường.'
                                ).classes('text-xs text-orange-700 font-medium')

            async def _validate_now(tab_key: str, tstate: dict, container, relevant_labels: set[str]) -> bool:
                """Kiểm tra sớm bộ file theo tên — cập nhật tstate['tang0_ok'] (sàn
                bắt buộc tuyệt đối DUY NHẤT còn lại: PDF, D1 23/09/2026)."""
                tstate['tang0_ok'] = False
                try:
                    if not tstate['files']:
                        container.set_visibility(False)
                        if tab_key == 'di':
                            run_state['mis_di_thieu'] = False
                            _cap_nhat_hint_chay()
                        return False
                    res = await asyncio.to_thread(
                        api.post, '/api/ach/validate',
                        {'filenames': list(tstate['files'].keys())},
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        return False
                    container.set_visibility(True)
                    container.clear()
                    with container:
                        ui.label(f'Không kiểm tra được: {e}').classes('text-xs text-red-600')
                    return False

                if res.get('max_total_mb'):
                    run_state['max_total_mb'] = res['max_total_mb']
                tstate['tang0_ok'] = bool(res.get('tang0_ok'))
                if tab_key == 'di':
                    run_state['mis_di_thieu'] = any(
                        not chk['ok'] for chk in res.get('checks', [])
                        if chk['label'].startswith('MIS_DI')
                    )
                    _cap_nhat_hint_chay()
                _render_validate_result(container, res, relevant_labels)
                return bool(res.get('ok'))

            def _stop_timer():
                if run_state['timer']:
                    run_state['timer'].cancel()
                    run_state['timer'] = None

            def _cap_nhat_khoa_nut_chay():
                """D-3 — job đang CHIẾM SLOT (`job_open`, chạy HOẶC đang chờ xác nhận
                Checkpoint) thì khoá nút Chạy của TAB CÒN LẠI (Báo cáo chưa có nút
                Chạy ở đợt này). Không dùng `.tooltip()` để báo tên tab đang chạy —
                Element.tooltip() LUÔN THÊM tooltip mới, không thay thế cái cũ, gọi
                lặp lại sẽ CHỒNG NHIỀU tooltip lên cùng 1 nút; dùng `running_label`
                (một dòng chữ luôn hiện) để nêu đích danh tab thay cho tooltip."""
                ten_tab = _TAB_LABELS.get(run_state['active_tab'], 'một tab khác')
                if run_state['running']:
                    running_label.set_text(
                        f'Đang chạy ở tab "{ten_tab}" — nút Chạy của tab còn lại tạm khoá '
                        f'(chỉ 1 lượt/lần cho cả trang).')
                    running_bar.set_visibility(True)
                    spinner.set_visibility(True)
                elif run_state['job_open']:
                    running_label.set_text(
                        f'Tab "{ten_tab}" đang chờ xác nhận Checkpoint MIS_đi — xử lý xong '
                        f'rồi mới chạy được tab còn lại.')
                    running_bar.set_visibility(True)
                    spinner.set_visibility(False)
                else:
                    spinner.set_visibility(False)

                if run_state['job_open']:
                    btn_run_di.props('disable')
                    btn_run_den.props('disable')
                elif co_quyen_chay:
                    btn_run_di.props(remove='disable')
                    btn_run_den.props(remove='disable')

            def _stop_running(giu_nut_dung: bool = False):
                """giu_nut_dung=True khi ngừng THEO DÕI mà job phía máy chủ vẫn còn
                sống (mất liên lạc). Giấu nút Dừng lúc đó là cắt mất đường duy nhất
                để dừng job mồ côi — mà job đó vẫn đang ăn RAM/CPU/đĩa của máy chủ.
                job_open CHỈ tắt khi KHÔNG giu_nut_dung — mất liên lạc nghĩa là job
                rất có thể vẫn chiếm slot trên máy chủ, mở khoá lúc đó cho phép bấm
                Chạy tab kia sẽ tạo 2 job chồng nhau."""
                run_state['running'] = False
                if not giu_nut_dung:
                    run_state['job_open'] = False
                _cap_nhat_khoa_nut_chay()
                if not giu_nut_dung:
                    running_bar.set_visibility(False)
                _stop_timer()

            async def _may_chu_dang_ban():
                """Hỏi MÁY CHỦ xem có phiên nào đang chạy dở không — TRƯỚC khi gửi
                file, để bắt cả trường hợp người khác/tab trình duyệt khác đang chạy
                (khác với khoá `_cap_nhat_khoa_nut_chay()` — khoá đó chỉ có tác dụng
                trong CHÍNH phiên trình duyệt này)."""
                try:
                    res = await asyncio.to_thread(
                        api.get, '/api/ach/dang-chay', timeout=_POLL_TIMEOUT,
                    )
                except Exception as e:
                    if api.la_loi_mang(e):
                        return 'khong_hoi_duoc'
                    raise
                nghen = res.get('nghen')
                if res.get('job'):
                    return res['job']
                if nghen:
                    return {'chi_bao': nghen.get('message')}
                return None

            def _mo_ta_phien_dang_chay(job: dict) -> str:
                if job.get('chi_bao'):
                    return job['chi_bao']
                phut = job.get('tuoi_giay', 0) // 60
                da_lau = f', đã {phut} phút' if phut else ''
                if job.get('status') == 'awaiting_confirmation':
                    viec = 'đang giữ một phiên chờ xác nhận MIS_đi'
                    cach = ('Xử lý nốt phiên đó (tải file xác nhận, điền, nộp lại), '
                            'hoặc bấm "Dừng" rồi chạy lại.')
                else:
                    viec = 'đang chạy dở một phiên đối chiếu'
                    cach = 'Chờ nó chạy xong, hoặc bấm "Dừng" rồi chạy lại.'
                return (f'Máy chủ {viec} (job {job.get("job_id")}{da_lau}) — chưa gửi file đi. '
                        f'Chạy chồng hai phiên là máy chủ ôm hai bộ dữ liệu cùng lúc, '
                        f'thường đứt kết nối giữa chừng. {cach}')

            async def _poll():
                if not run_state['job_id']:
                    return

                try:
                    res = await asyncio.to_thread(
                        api.get,
                        f'/api/ach/poll/{run_state["job_id"]}',
                        params={'since': run_state['log_pos']},
                        timeout=_POLL_TIMEOUT,
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        _stop_running()
                        return
                    if not api.la_loi_mang(e):
                        progress_bar.set_visibility(False)
                        _stop_running()
                        run_state['job_id'] = None
                        _append_log(f'[LỖI] Máy chủ từ chối theo dõi tiến trình: {e}')
                        ui.notify(str(e), type='negative', timeout=0)
                        return
                    run_state['poll_fails'] += 1
                    if run_state['poll_fails'] >= _MAX_POLL_FAILS:
                        progress_bar.set_visibility(False)
                        _stop_running(giu_nut_dung=True)
                        _append_log(
                            f'[LỖI] Mất liên lạc với máy chủ sau '
                            f'{_MAX_POLL_FAILS} lần thử ({_MAX_POLL_FAILS * int(_POLL_TIMEOUT)}s): {e}')
                        _append_log(f'[LỖI] Job {run_state["job_id"]} RẤT CÓ THỂ VẪN ĐANG CHẠY '
                                    'trên máy chủ — bấm "Dừng" trước khi chạy lại.')
                        ui.notify(
                            'Mất liên lạc với máy chủ khi theo dõi tiến trình. Job nhiều khả '
                            'năng VẪN ĐANG CHẠY — chạy lại ngay lúc này sẽ có hai lượt đối '
                            'chiếu cùng lúc và máy chủ càng nghẽn. Bấm "Dừng" để huỷ job cũ, '
                            'rồi xem logs/backend.log trên máy chủ trước khi chạy lại.',
                            type='negative', timeout=0,
                        )
                    return

                run_state['poll_fails'] = 0

                if 'stage' in res:
                    _update_stage(res['stage'], res.get('progress'))
                _render_summary(res.get('summary'))

                new_logs = res.get('logs', [])
                for line in new_logs:
                    _append_log(line)
                run_state['log_pos'] += len(new_logs)

                status = res.get('status', '')

                if status == 'awaiting_confirmation':
                    _stop_timer()
                    run_state['running'] = False
                    _cap_nhat_khoa_nut_chay()
                    if run_state['checkpoint_mode'] == 'deferred':
                        _show_checkpoint_banner(res)
                    else:
                        _enter_checkpoint(res)
                    return

                if status in ('done', 'error', 'cancelled'):
                    _stop_running()

                    if status == 'done':
                        _update_stage(len(_STAGE_LABELS) - 1, 1.0)
                        files = res.get('files', [])
                        _show_results(files)
                        ui.notify('Hoàn thành! Xem/tải kết quả ở tab "Báo cáo".', type='positive')
                    elif status == 'error':
                        progress_bar.set_visibility(False)
                        ui.notify(f'Lỗi: {res.get("error", "")}', type='negative', timeout=0)
                    elif status == 'cancelled':
                        progress_bar.set_visibility(False)
                        checkpoint_dialog.close()
                        if not run_state['dang_cho_dung']:
                            ui.notify('Đã dừng theo yêu cầu.', type='warning')

            def _mo_ta_can_xac_nhan(res: dict) -> str:
                so_luong  = res.get('xac_nhan_count')
                tong_tien = res.get('xac_nhan_tong_tien')
                if so_luong is not None and tong_tien is not None:
                    return f'Có {so_luong:,} giao dịch MIS_đi cần xác nhận, tổng {tong_tien:,} VND.'
                return 'Cần xác nhận thủ công MIS_đi.'

            def _enter_checkpoint(res: dict):
                btn_cancel.set_visibility(True)
                checkpoint_dialog.clear()
                run_state['xac_nhan_upload'] = None

                files         = res.get('files', [])
                xac_nhan_file = files[0] if files else None
                loi_lan_truoc = res.get('error')

                with checkpoint_dialog, ui.card().classes('p-5').style('min-width: 480px'):
                    ui.label(_mo_ta_can_xac_nhan(res)).classes(
                        'text-base font-semibold text-orange-800 mb-1')
                    ui.label(f'{xac_nhan_file} đã sẵn sàng.').classes('text-sm text-gray-700 mb-2')
                    if loi_lan_truoc:
                        ui.label(f'File xác nhận vừa nộp bị từ chối: {loi_lan_truoc}').classes(
                            'text-xs text-red-600 mb-2')
                    ui.label(
                        '1) Tải file bên dưới · 2) Mở file, ở sheet MIS_DI_CONFIRM tick "loại bỏ" '
                        'cho dòng cần loại (để trống = giữ lại, mặc định), có thể paste thêm REFHUB '
                        'bị bỏ sót vào vùng "BỔ SUNG" cuối sheet · 3) Kéo-thả (hoặc chọn) lại file đã '
                        'điền rồi bấm "Chạy tiếp".'
                    ).classes('text-xs text-gray-600 mb-3')

                    if xac_nhan_file:
                        url = f'/api/ach/download/{run_state["job_id"]}/{xac_nhan_file}'

                        async def _tai_file_xac_nhan(u=url, fname=xac_nhan_file):
                            try:
                                content = await asyncio.to_thread(api.download, u)
                            except Exception as e:
                                if not _handle_api_error(e):
                                    ui.notify(str(e), type='negative')
                                return
                            ui.download(content, fname)

                        ui.button(f'Tải file cần xác nhận ({xac_nhan_file})', icon='download',
                                  color='orange-7').on(
                            'click', _tai_file_xac_nhan
                        ).classes('text-xs mb-2')

                    upload_label = ui.label(
                        'Chưa chọn file đã điền — có thể kéo-thả trực tiếp vào ô bên dưới'
                    ).classes('text-xs text-gray-400 italic mb-1')

                    async def on_upload_xac_nhan(e):
                        data = e.content.read()
                        run_state['xac_nhan_upload'] = (e.name, data)
                        upload_label.set_text(f'Đã chọn: {e.name}')
                        upload_label.classes(
                            remove='text-gray-400 italic', add='text-green-700 font-medium')

                    ui.upload(
                        on_upload=on_upload_xac_nhan, auto_upload=True, multiple=False,
                    ).props(
                        'accept=".xlsx" flat dense label="Kéo-thả hoặc chọn file đã điền..."'
                    ).classes('w-full mb-2')

                    async def _huy_va_dong():
                        checkpoint_dialog.close()
                        await on_cancel()

                    with ui.row().classes('gap-2 justify-end w-full'):
                        ui.button('Hủy', color='grey-6').props('flat').on('click', _huy_va_dong)
                        btn_chay_tiep = ui.button(
                            'Đã xác nhận – Chạy tiếp', icon='play_arrow', color='red-8'
                        ).classes('font-semibold').on('click', on_continue)
                        if not co_quyen_chay:
                            btn_chay_tiep.props('disable')
                            btn_chay_tiep.tooltip('Bạn không có quyền thực hiện thao tác này')

                checkpoint_dialog.open()

            def _show_checkpoint_banner(res: dict):
                run_state['pending_checkpoint_res'] = res
                btn_cancel.set_visibility(True)
                checkpoint_banner_label.set_text(_mo_ta_can_xac_nhan(res))
                checkpoint_banner.set_visibility(True)

            def _open_pending_checkpoint():
                checkpoint_banner.set_visibility(False)
                _enter_checkpoint(run_state['pending_checkpoint_res'])

            async def on_continue():
                if not run_state.get('xac_nhan_upload'):
                    ui.notify('Chưa chọn file xác nhận đã điền.', type='warning')
                    return

                name, data = run_state['xac_nhan_upload']
                checkpoint_dialog.close()
                progress_bar.set_visibility(True)
                run_state['progress'] = 0.0
                progress_bar.set_value(0)
                _append_log(f'[Chạy tiếp] Đang nộp file xác nhận: {name}...')

                try:
                    await asyncio.to_thread(
                        api.post_upload, f'/api/ach/continue/{run_state["job_id"]}',
                        files={'file': (name, data, 'application/octet-stream')},
                    )
                except Exception as e:
                    progress_bar.set_visibility(False)
                    checkpoint_dialog.open()
                    if not _handle_api_error(e):
                        ui.notify(str(e), type='negative')
                    return

                run_state['running']  = True
                run_state['job_open'] = True
                _cap_nhat_khoa_nut_chay()
                btn_cancel.set_visibility(True)
                run_state['timer'] = ui.timer(_POLL_INTERVAL, _poll)

            def _nut_tai(fname: str, job_id: str | None = None):
                """job_id=None → job vừa chạy trong phiên hiện tại
                (`run_state['job_id']`). Truyền `job_id` tường minh khi tải kết
                quả của một lượt CŨ (D4 — card "Kết quả khác của bạn còn trên
                máy chủ"), không phải job đang mở của phiên này."""
                icon = 'table_chart' if fname.endswith('.xlsx') else 'description'
                color = 'green-7' if fname.endswith('.xlsx') else 'blue-7'
                jid   = job_id or run_state['job_id']
                url   = f'/api/ach/download/{jid}/{fname}'

                async def _tai_ket_qua(u=url, name=fname):
                    try:
                        content = await asyncio.to_thread(api.download, u)
                    except Exception as e:
                        if not _handle_api_error(e):
                            ui.notify(str(e), type='negative')
                        return
                    ui.download(content, name)

                ui.button(fname, icon=icon, color=color).on('click', _tai_ket_qua).classes('text-xs')

            async def _tai_ket_qua_cu():
                """D4 (23/09/2026) — nạp danh sách job CŨ của CHÍNH người đang
                đăng nhập từ `GET /api/ach/ket-qua` (backend đã lọc theo
                `nguoi_tao_id`, xem backend/api/ach.py). Bỏ qua job trùng với
                `run_state['job_id']` — job đó đã hiện ở card "lượt chạy gần
                nhất" phía trên, không cần lặp lại."""
                ket_qua_cu_container.clear()
                try:
                    jobs = await asyncio.to_thread(api.get, '/api/ach/ket-qua')
                except Exception as e:
                    with ket_qua_cu_container:
                        if not _handle_api_error(e):
                            ui.label(f'Không tải được danh sách: {e}').classes(
                                'text-xs text-red-600')
                    return

                jobs = [j for j in jobs if j.get('job_id') != run_state.get('job_id')]
                with ket_qua_cu_container:
                    if not jobs:
                        ui.label(
                            'Không có kết quả nào khác của bạn còn trên máy chủ.'
                        ).classes('text-xs text-gray-400 italic')
                        return
                    for j in jobs:
                        ngay_txt = f" — ngày {j['ngay']}" if j.get('ngay') else ''
                        with ui.column().classes('w-full gap-1 mb-1 p-3 rounded border bg-gray-50'):
                            ui.label(f"Job {j['job_id']}{ngay_txt}").classes(
                                'text-sm font-semibold text-red-800')
                            with ui.row().classes('flex-wrap gap-2'):
                                for fname in j.get('files', []):
                                    _nut_tai(fname, job_id=j['job_id'])

            btn_lam_moi_ket_qua_cu.on('click', _tai_ket_qua_cu)

            def _render_bao_cao(files: list[str]):
                """D3 — thay hẳn danh sách tải phẳng bằng card theo nhóm nghiệp vụ."""
                bao_cao_container.clear()
                if not files:
                    with bao_cao_container:
                        ui.label(
                            'Chưa có kết quả — chạy đối chiếu ở tab "Timeout + Đối chiếu đi" '
                            'hoặc "Đối chiếu đến" trước.'
                        ).classes('text-sm text-gray-400 italic')
                    return
                with bao_cao_container:
                    for ten, mota, fs in _phan_loai_bao_cao(files):
                        with ui.column().classes('w-full gap-1 mb-1 p-3 rounded border bg-gray-50'):
                            ui.label(ten).classes('text-sm font-semibold text-red-800')
                            ui.label(mota).classes('text-xs text-gray-500 mb-1')
                            with ui.row().classes('flex-wrap gap-2'):
                                for fname in fs:
                                    _nut_tai(fname)

            def _show_results(files: list[str]):
                run_state['last_files'] = files
                _render_bao_cao(files)

            def _qua_tran_dung_luong(tstate: dict) -> str | None:
                """Thông báo nếu bộ file vượt trần máy chủ; None nếu còn trong ngưỡng.

                Phải chặn ở ĐÂY chứ không để máy chủ chặn: máy chủ trả 413 rồi đóng
                kết nối trong khi trình duyệt còn đang gửi, nên phía gửi không bao giờ
                đọc được cái 413 đó — nó chỉ thấy socket đứt.
                """
                tran = run_state['max_total_mb']
                tong = _tong_mb(tstate)
                if not tran or tong <= tran:
                    return None
                nang = sorted(tstate['files'].items(), key=lambda kv: -len(kv[1]))[:3]
                chi_tiet = ', '.join(f'{n} ({len(d) / (1024 * 1024):.0f} MB)' for n, d in nang)
                return (f'Bộ file tổng {tong:.0f} MB, vượt trần {tran} MB của máy chủ — '
                        f'chưa gửi đi gì cả. Nặng nhất: {chi_tiet}. Bỏ bớt file không thuộc '
                        'phiên đối chiếu này rồi thử lại, hoặc nhờ quản trị nâng '
                        'ACH_MAX_UPLOAD_MB / MAX_REQUEST_MB trong .env.')

            def _giai_thich_loi_upload(tstate: dict, e: Exception) -> str:
                msg = str(e)
                if not any(k in msg for k in
                           ('10054', '10053', 'ConnectionReset', 'RemoteProtocol',
                            'ReadError', 'WriteError')):
                    return msg
                tran = run_state['max_total_mb']
                return (f'{msg} — Máy chủ cắt kết nối khi đang nhận file (bộ file '
                        f'{_tong_mb(tstate):.0f} MB'
                        + (f', trần {tran} MB' if tran else '') + '). Thường là do bộ file '
                        'quá lớn; cũng có thể backend vừa khởi động lại. Bỏ bớt file rồi thử lại.')

            async def _thuc_hien_chay(tab_key: str, tstate: dict, ngay_input):
                loi_dung_luong = _qua_tran_dung_luong(tstate)
                if loi_dung_luong:
                    ui.notify(loi_dung_luong, type='negative', timeout=0)
                    return

                try:
                    dang = await _may_chu_dang_ban()
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(str(e), type='negative')
                    return

                if isinstance(dang, dict):
                    if not run_state['job_id']:
                        run_state['job_id'] = dang.get('job_id')
                    ui.notify(_mo_ta_phien_dang_chay(dang), type='negative', timeout=0)
                    btn_cancel.set_visibility(bool(run_state['job_id']))
                    running_bar.set_visibility(bool(run_state['job_id']))
                    return

                if dang == 'khong_hoi_duoc':
                    ui.notify(
                        'Máy chủ chưa trả lời về lượt chạy trước nên không rõ nó đã dừng hay '
                        'chưa. Chạy lúc này có thể thành hai lượt cùng lúc. Bấm "Dừng" rồi '
                        'thử lại sau ít phút.',
                        type='negative', timeout=0,
                    )
                    btn_cancel.set_visibility(True)
                    running_bar.set_visibility(True)
                    return

                _clear_log()
                checkpoint_dialog.close()
                checkpoint_banner.set_visibility(False)
                run_state['pending_checkpoint_res'] = None
                run_state['checkpoint_mode'] = checkpoint_mode_radio.value if tab_key == 'di' else 'inline'
                run_state['active_tab'] = tab_key
                run_state['running']  = True
                run_state['job_open'] = True
                run_state['log_pos'] = 0
                _cap_nhat_khoa_nut_chay()
                btn_cancel.set_visibility(True)
                progress_bar.set_visibility(True)

                ngay = ngay_input.value.strip() if ngay_input.value else None
                bo_qua = run_state['bo_qua_checkpoint'] if tab_key == 'di' else False
                # A4 — ô tick chỉ có ý nghĩa ở Tab 1 (Timeout + Đối chiếu đi), Tab 2
                # không có ô này, luôn gửi False.
                tao_gw_cho_phub = run_state['tao_gw_cho_phub'] if tab_key == 'di' else False

                try:
                    _append_log('Đang upload file...')
                    res = await asyncio.to_thread(
                        api.post_upload,
                        '/api/ach/start',
                        files=[('files', (name, data, 'application/octet-stream'))
                               for name, data in tstate['files'].items()],
                        data={
                            'ngay_doi_chieu': ngay or '',
                            'bo_qua_checkpoint': str(bo_qua).lower(),
                            'tao_gw_cho_phub': str(tao_gw_cho_phub).lower(),
                        },
                        timeout=600.0,   # bộ file ACH có thể tới hàng trăm MB
                    )
                except Exception as e:
                    progress_bar.set_visibility(False)
                    btn_cancel.set_visibility(False)
                    running_bar.set_visibility(False)
                    run_state['running']  = False
                    run_state['job_open'] = False   # upload lỗi → backend đã tự bo_job(), slot đã trả lại
                    _cap_nhat_khoa_nut_chay()
                    if not _handle_api_error(e):
                        ui.notify(_giai_thich_loi_upload(tstate, e), type='negative', timeout=0)
                    return

                run_state['job_id'] = res.get('job_id')
                _append_log(f'Job ID: {run_state["job_id"]}')

                run_state['timer'] = ui.timer(_POLL_INTERVAL, _poll)

            async def _on_run(tab_key: str, tstate: dict, container, relevant_labels: set[str], ngay_input):
                if run_state['job_open']:
                    return
                if not tstate['files']:
                    ui.notify('Chưa chọn file nào.', type='warning')
                    return

                await _validate_now(tab_key, tstate, container, relevant_labels)
                if not tstate['tang0_ok']:
                    ui.notify('Thiếu file PDF (session) — không có gì để chạy.', type='negative')
                    return

                if tab_key == 'di' and run_state['bo_qua_checkpoint']:
                    bo_qua_confirm_dialog.open()
                    return

                await _thuc_hien_chay(tab_key, tstate, ngay_input)

            async def on_run_di():
                await _on_run('di', state_di, validate_card_di, _CHECKS_TAB_DI, ngay_input_di)

            async def on_run_den():
                await _on_run('den', state_den, validate_card_den, _CHECKS_TAB_DEN, ngay_input_den)

            async def _on_xac_nhan_chay_thang():
                bo_qua_confirm_dialog.close()
                await _thuc_hien_chay('di', state_di, ngay_input_di)

            btn_xac_nhan_chay_thang.on('click', _on_xac_nhan_chay_thang)

            async def _cho_may_chu_ranh() -> bool:
                for _ in range(int(_HAN_CHO_DUNG / _NHIP_CHO_DUNG)):
                    await asyncio.sleep(_NHIP_CHO_DUNG)
                    try:
                        if await _may_chu_dang_ban() is None:
                            return True
                    except Exception:
                        pass   # hỏi lại ở nhịp sau — im lặng ở đây KHÔNG kết luận gì
                return False

            async def on_cancel():
                if not run_state['job_id']:
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f'/api/ach/cancel/{run_state["job_id"]}',
                        timeout=_POLL_TIMEOUT,
                    )
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(str(e), type='negative')
                    return

                btn_cancel.disable()
                run_state['dang_cho_dung'] = True
                _append_log('[Đã gửi yêu cầu dừng — chờ bước đang chạy kết thúc...]')
                ui.notify('Đang dừng phiên cũ — chờ bước đang chạy kết thúc...', type='ongoing')
                try:
                    da_ranh = await _cho_may_chu_ranh()
                finally:
                    run_state['dang_cho_dung'] = False
                    btn_cancel.enable()

                if da_ranh:
                    _stop_timer()
                    _stop_running()
                    progress_bar.set_visibility(False)
                    run_state['job_id'] = None
                    _append_log('[Đã dừng hẳn — máy chủ đã nhả bộ nhớ, chạy phiên mới được rồi.]')
                    ui.notify('Đã dừng hẳn phiên cũ. Bộ nhớ đã được giải phóng — '
                              'chạy phiên mới được rồi.', type='positive', timeout=0)
                else:
                    _append_log(f'[Chưa dừng được sau {_HAN_CHO_DUNG // 60} phút.]')
                    ui.notify(
                        f'Đã gửi lệnh dừng nhưng sau {_HAN_CHO_DUNG // 60} phút máy chủ vẫn báo '
                        'bận. Bước đang chạy có thể còn dài. ĐỪNG chạy phiên mới lúc này — '
                        'chờ thêm rồi bấm "Dừng" lại để kiểm tra.',
                        type='negative', timeout=0,
                    )

            btn_run_di.on('click', on_run_di)
            btn_run_den.on('click', on_run_den)
            btn_cancel.on('click', on_cancel)
            btn_open_checkpoint.on('click', _open_pending_checkpoint)

            # D4 — nạp danh sách "kết quả khác của bạn" ngay khi mở trang, không
            # đợi người dùng bấm nút làm mới trước. Truyền THẲNG (không
            # `asyncio.create_task`) — hàm async gọi trực tiếp trong lúc trang
            # đang dựng vẫn nằm trong đúng slot NiceGUI (docs/DESIGN.md).
            await _tai_ket_qua_cu()


def _ngay_input():
    """Ô nhập ngày đối chiếu — gõ tay hoặc bấm icon lịch để chọn. Dùng riêng mỗi
    tab (mỗi tab là một lượt chạy độc lập, có thể khác ngày nhau)."""
    with ui.input(
        placeholder='dd/mm/yyyy  (bỏ trống = tự động từ PDF)',
    ).props('dense outlined clearable').classes('w-44') as ngay_input:
        with ui.menu().props('no-parent-event') as ngay_menu:
            ui.date(mask='DD/MM/YYYY').props('first-day-of-week="1"').bind_value(ngay_input)
        with ngay_input.add_slot('append'):
            ui.icon('event').on('click', ngay_menu.open).classes('cursor-pointer text-gray-500')
    return ngay_input
