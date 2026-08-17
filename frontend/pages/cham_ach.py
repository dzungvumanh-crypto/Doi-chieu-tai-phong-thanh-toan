"""Trang Chấm đối chiếu ACH — chọn file từ máy người dùng, chạy pipeline, download kết quả."""

import re
import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

# ─── Hằng số ──────────────────────────────────────────────────────────────────
_POLL_INTERVAL = 1.5   # giây
_FILE_HINT = (
    'PDF (session) · GL02*.zip · GW*.xlsx · '
    '2× *_DI_*.zip · 2× *_DEN_*.zip · '
    '(tùy chọn, Điểm 4) MIS_DI_THUA*.csv / MIS_DEN_THUA*.csv của lần chạy ngày T-2 · '
    '(tùy chọn, Điểm 2) QT*.xlsx (Quyết toán OSB đi/đến)'
)

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

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        'files':       {},     # {filename: bytes}
        'job_id':      None,
        'log_pos':     0,      # số log đã hiển thị
        'timer':       None,
        'running':     False,
        'progress':    0.0,
        'poll_fails':  0,      # số lần poll lỗi liên tiếp
        'xac_nhan_upload': None,   # (filename, bytes) file xác nhận đã điền, chờ upload
        'checkpoint_mode': 'inline',   # 'inline' | 'deferred' — cách xử lý khi tới Checkpoint
        'pending_checkpoint_res': None,   # kết quả poll lúc tới Checkpoint (mode deferred, chờ mở)
        'bo_qua_checkpoint': False,   # True = chạy thẳng, coi MIS_đi đúng 100%, không dừng chờ xác nhận
    }

    with ui.row().classes('w-full'):
        _sidebar('cham_ach')
        with _content_area():
            _page_header('Chấm đối chiếu ACH', 'Đối chiếu GL02 (NPO) với MIS — Phòng Thanh toán')

            # ── Input card ────────────────────────────────────────────────────
            with ui.card().classes('w-full p-5 mb-4'):
                ui.label('Nguồn dữ liệu').classes('text-base font-semibold text-red-800 mb-3')

                upload_section = ui.column().classes('w-full mt-1 gap-1')
                with upload_section:
                    ui.label(
                        'Mở thư mục chứa đủ file ACH của 1 phiên/1 ngày trên máy bạn, '
                        'chọn tất cả file bằng Ctrl+A (hoặc giữ Shift để chọn khoảng) '
                        'rồi kéo-thả hoặc bấm Mở.'
                    ).classes('text-xs text-gray-500 mb-1')
                    ui.label(_FILE_HINT).classes('text-xs text-gray-400 mb-1')
                    file_list_label = ui.label('Chưa chọn file nào').classes(
                        'text-xs text-gray-400 italic mb-2'
                    )

                    async def on_upload(e):
                        data = e.content.read()
                        state['files'][e.name] = data
                        names = ', '.join(state['files'].keys())
                        file_list_label.set_text(f'Đã chọn ({len(state["files"])} file): {names}')
                        file_list_label.classes(
                            remove='text-gray-400 italic', add='text-green-700 font-medium'
                        )
                        await _validate_now()

                    async def on_clear():
                        state['files'].clear()
                        file_list_label.set_text('Chưa chọn file nào')
                        file_list_label.classes(
                            remove='text-green-700 font-medium', add='text-gray-400 italic'
                        )
                        await _validate_now()

                    ui.upload(
                        on_upload=on_upload,
                        auto_upload=True,
                        multiple=True,
                    ).props(
                        'accept=".zip,.xlsx,.pdf,.csv" flat dense label="Chọn file (có thể chọn nhiều)..."'
                    ).classes('w-full mb-1')

                    ui.button('Xóa tất cả file', icon='delete_outline', color='grey-6',
                              on_click=on_clear).props('flat dense').classes('text-xs')

                # Ngày đối chiếu — gõ tay hoặc bấm icon lịch để chọn ngày
                with ui.row().classes('items-center gap-3 mt-3'):
                    ui.label('Ngày đối chiếu:').classes('text-sm text-gray-600')
                    with ui.input(
                        placeholder='dd/mm/yyyy  (bỏ trống = tự động từ PDF)',
                    ).props('dense outlined clearable').classes('w-44') as ngay_input:
                        with ui.menu().props('no-parent-event') as ngay_menu:
                            ui.date(mask='DD/MM/YYYY').props(
                                'first-day-of-week="1"'
                            ).bind_value(ngay_input)
                        with ngay_input.add_slot('append'):
                            ui.icon('event').on('click', ngay_menu.open).classes(
                                'cursor-pointer text-gray-500'
                            )
                    ui.label('Bỏ trống → tự động lấy từ tên file PDF').classes('text-xs text-gray-400')

                # ── Kết quả kiểm tra file ───────────────────────────────────
                validate_card = ui.column().classes('w-full mt-3 gap-1 p-3 rounded bg-gray-50 border')
                validate_card.set_visibility(False)

                # ── Chế độ xử lý Checkpoint ───────────────────────────────
                checkpoint_section = ui.column().classes('w-full gap-1 mt-4')
                with checkpoint_section:
                    ui.label('Chế độ xử lý Checkpoint').classes('text-sm font-medium text-gray-700')
                    checkpoint_mode_radio = ui.radio(
                        {
                            'inline':   'Xác nhận ngay khi MIS_đi vừa tạo xong (quy trình hiện tại)',
                            'deferred': 'Chạy hết phần tự động, sau đó mới xác nhận MIS_đi rồi tiếp tục chạy',
                        },
                        value='inline',
                    ).props('dense')

                # ── Chạy thẳng, bỏ qua Checkpoint (2026-07-31) ─────────────
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

                # Nút Chạy / Dừng
                with ui.row().classes('gap-3 mt-4 items-center'):
                    btn_run = ui.button('Chạy đối chiếu', icon='play_arrow',
                                        color='red-8').classes('font-semibold')
                    btn_cancel = ui.button('Dừng', icon='stop_circle',
                                           color='grey-6').classes('font-semibold')
                    btn_cancel.set_visibility(False)
                    if not co_quyen_chay:
                        btn_run.props('disable')
                        btn_run.tooltip('Bạn không có quyền thực hiện thao tác này')
                    hint_chay_label = ui.label(
                        'Pipeline sẽ dừng lại ngay sau khi tạo xong MIS_đi để bạn xác nhận, '
                        'rồi mới chạy tiếp tới báo cáo cuối.'
                    ).classes('text-xs text-gray-400')

                def _cap_nhat_hint_chay():
                    if state['bo_qua_checkpoint']:
                        hint_chay_label.set_text(
                            'Sẽ CHẠY THẲNG tới báo cáo cuối — KHÔNG dừng lại chờ xác nhận MIS_đi.'
                        )
                        hint_chay_label.classes(
                            remove='text-gray-400', add='text-orange-700 font-semibold'
                        )
                    else:
                        hint_chay_label.set_text(
                            'Pipeline sẽ dừng lại ngay sau khi tạo xong MIS_đi để bạn xác nhận, '
                            'rồi mới chạy tiếp tới báo cáo cuối.'
                        )
                        hint_chay_label.classes(
                            remove='text-orange-700 font-semibold', add='text-gray-400'
                        )

                def _on_bo_qua_change(val: bool):
                    state['bo_qua_checkpoint'] = val
                    checkpoint_section.set_visibility(not val)
                    _cap_nhat_hint_chay()

                bo_qua_checkbox.on_value_change(lambda e: _on_bo_qua_change(e.value))

                # ── Popup xác nhận lại trước khi chạy thẳng ────────────────
                bo_qua_confirm_dialog = ui.dialog()
                with bo_qua_confirm_dialog, ui.card().classes('p-5').style('min-width: 420px'):
                    ui.label('Xác nhận chạy thẳng, bỏ qua Checkpoint').classes(
                        'text-base font-semibold text-orange-800 mb-2'
                    )
                    ui.label(
                        'Pipeline sẽ KHÔNG dừng lại để bạn xác nhận MIS_đi — toàn bộ được coi là đúng 100% '
                        'và đi thẳng vào báo cáo cuối. Nếu sau này phát hiện sai sót, bạn cần chạy lại '
                        '(bỏ tick) để đi qua Checkpoint như bình thường.'
                    ).classes('text-sm text-gray-700 mb-4')
                    with ui.row().classes('gap-2 justify-end w-full'):
                        ui.button('Hủy', color='grey-6').props('flat').on(
                            'click', bo_qua_confirm_dialog.close
                        )
                        btn_xac_nhan_chay_thang = ui.button(
                            'Tôi hiểu, chạy thẳng luôn', icon='play_arrow', color='orange-8',
                        ).classes('font-semibold')

            # ── Log card ──────────────────────────────────────────────────────
            with ui.card().classes('w-full p-0 mb-4'):
                with ui.row().classes('w-full bg-gray-800 px-4 py-2 rounded-t items-center gap-2'):
                    ui.icon('terminal').classes('text-green-400 text-sm')
                    ui.label('Log xử lý').classes('text-xs font-semibold text-green-300')
                    spinner = ui.spinner('dots', size='xs', color='green')
                    spinner.set_visibility(False)

                progress_bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
                progress_bar.set_visibility(False)

                log_area = ui.column().classes(
                    'w-full bg-gray-900 font-mono text-xs text-green-200 '
                    'p-3 overflow-y-auto max-h-64 min-h-24 gap-0'
                )
                with log_area:
                    ui.label('Sẵn sàng. Chọn file và bấm "Chạy đối chiếu".').classes('text-gray-500')

            # ── Checkpoint xác nhận thủ công (popup — hiện ngay khi tới Checkpoint) ──
            checkpoint_dialog = ui.dialog().props('persistent')

            # ── Banner Chế độ B — báo lặng lẽ khi tới Checkpoint, không tự mở popup ──
            checkpoint_banner = ui.row().classes(
                'w-full items-center gap-3 p-3 mb-4 rounded bg-orange-50 border border-orange-200'
            )
            checkpoint_banner.set_visibility(False)
            with checkpoint_banner:
                ui.icon('notification_important').classes('text-orange-700')
                checkpoint_banner_label = ui.label('').classes('text-sm text-orange-800 flex-grow')
                btn_open_checkpoint = ui.button('Xem và xác nhận', icon='fact_check',
                                                color='orange-8').props('dense')

            # ── Kết quả download ─────────────────────────────────────────────
            result_card = ui.card().classes('w-full p-5')
            result_card.set_visibility(False)
            with result_card:
                ui.label('Kết quả').classes('text-base font-semibold text-red-800 mb-3')
                download_row = ui.row().classes('flex-wrap gap-3')

            # ── Logic ─────────────────────────────────────────────────────────

            def _append_log(msg: str):
                with log_area:
                    ui.label(msg).classes('leading-tight')
                state['progress'] = _bump_progress(state['progress'], msg)
                progress_bar.set_value(state['progress'])

            def _clear_log():
                log_area.clear()
                state['progress'] = 0.0
                progress_bar.set_value(0)

            def _render_validate_result(res: dict):
                validate_card.set_visibility(True)
                validate_card.clear()
                with validate_card:
                    for chk in res.get('checks', []):
                        icon  = 'check_circle' if chk['ok'] else 'cancel'
                        color = 'text-green-600' if chk['ok'] else 'text-red-600'
                        with ui.row().classes('items-center gap-2'):
                            ui.icon(icon).classes(f'{color} text-base')
                            ui.label(chk['label']).classes('text-xs font-medium')
                        ui.label(chk['detail']).classes('text-xs text-gray-500 ml-6 -mt-1')

            async def _validate_now() -> bool:
                """Kiểm tra sớm bộ file theo tên — trả True nếu đủ, chặn chạy nếu thiếu."""
                try:
                    if not state['files']:
                        validate_card.set_visibility(False)
                        return False
                    res = await asyncio.to_thread(
                        api.post, '/api/ach/validate',
                        {'filenames': list(state['files'].keys())},
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        return False
                    validate_card.set_visibility(True)
                    validate_card.clear()
                    with validate_card:
                        ui.label(f'Không kiểm tra được: {e}').classes('text-xs text-red-600')
                    return False

                _render_validate_result(res)
                return bool(res.get('ok'))

            _MAX_POLL_FAILS = 4  # ~6s liên tiếp lỗi mới báo — tránh báo nhầm khi mạng chập chờn

            def _stop_timer():
                if state['timer']:
                    state['timer'].cancel()
                    state['timer'] = None

            def _stop_running():
                spinner.set_visibility(False)
                btn_cancel.set_visibility(False)
                btn_run.set_visibility(True)
                state['running'] = False
                _stop_timer()

            async def _poll():
                if not state['job_id']:
                    return

                try:
                    res = await asyncio.to_thread(
                        api.get,
                        f'/api/ach/poll/{state["job_id"]}',
                        params={'since': state['log_pos']},
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        _stop_running()
                        return
                    state['poll_fails'] += 1
                    if state['poll_fails'] >= _MAX_POLL_FAILS:
                        progress_bar.set_visibility(False)
                        _stop_running()
                        _append_log(f'[LỖI] Mất kết nối tới máy chủ khi theo dõi tiến trình: {e}')
                        ui.notify(
                            'Mất kết nối tới máy chủ hoặc job đã hết hạn (có thể do backend '
                            'khởi động lại) — không rõ pipeline đã chạy xong hay chưa. '
                            'Vui lòng kiểm tra lại và chạy lại nếu cần.',
                            type='negative', timeout=0,
                        )
                    return

                state['poll_fails'] = 0

                new_logs = res.get('logs', [])
                for line in new_logs:
                    _append_log(line)
                state['log_pos'] += len(new_logs)

                status = res.get('status', '')

                if status == 'awaiting_confirmation':
                    _stop_timer()
                    spinner.set_visibility(False)
                    state['running'] = False
                    if state['checkpoint_mode'] == 'deferred':
                        _show_checkpoint_banner(res)
                    else:
                        _enter_checkpoint(res)
                    return

                if status in ('done', 'error', 'cancelled'):
                    _stop_running()

                    if status == 'done':
                        progress_bar.set_value(1.0)
                        files = res.get('files', [])
                        _show_results(files)
                        ui.notify('Hoàn thành! Tải file kết quả bên dưới.', type='positive')
                    elif status == 'error':
                        progress_bar.set_visibility(False)
                        ui.notify(f'Lỗi: {res.get("error", "")}', type='negative', timeout=0)
                    elif status == 'cancelled':
                        progress_bar.set_visibility(False)
                        checkpoint_dialog.close()
                        ui.notify('Đã dừng theo yêu cầu.', type='warning')

            def _mo_ta_can_xac_nhan(res: dict) -> str:
                so_luong  = res.get('xac_nhan_count')
                tong_tien = res.get('xac_nhan_tong_tien')
                if so_luong is not None and tong_tien is not None:
                    return f'Có {so_luong:,} giao dịch MIS_đi cần xác nhận, tổng {tong_tien:,} VND.'
                return 'Cần xác nhận thủ công MIS_đi.'

            def _enter_checkpoint(res: dict):
                """Job đã dừng ở Checkpoint ngay sau khi tạo xong MIS_đi (Điểm 1,
                2026-07-31) — hiện NGAY popup để người dùng tải, tick cột LOAI_BO,
                kéo-thả (hoặc chọn) lại file rồi bấm "Chạy tiếp". Không đổi cơ chế
                Checkpoint — chỉ đổi cách trình bày (card ẩn/hiện → popup tự mở)."""
                btn_run.set_visibility(False)
                btn_cancel.set_visibility(True)
                result_card.set_visibility(False)
                checkpoint_dialog.clear()
                state['xac_nhan_upload'] = None

                files         = res.get('files', [])
                xac_nhan_file = files[0] if files else None
                loi_lan_truoc = res.get('error')

                with checkpoint_dialog, ui.card().classes('p-5').style('min-width: 480px'):
                    ui.label(_mo_ta_can_xac_nhan(res)).classes(
                        'text-base font-semibold text-orange-800 mb-1'
                    )
                    ui.label(f'{xac_nhan_file} đã sẵn sàng.').classes('text-sm text-gray-700 mb-2')
                    if loi_lan_truoc:
                        ui.label(f'File xác nhận vừa nộp bị từ chối: {loi_lan_truoc}').classes(
                            'text-xs text-red-600 mb-2'
                        )
                    ui.label(
                        '1) Tải file bên dưới · 2) Mở file, ở sheet MIS_DI_CONFIRM tick "loại bỏ" '
                        'cho dòng cần loại (để trống = giữ lại, mặc định), có thể paste thêm REFHUB '
                        'bị bỏ sót vào vùng "BỔ SUNG" cuối sheet · 3) Kéo-thả (hoặc chọn) lại file đã '
                        'điền rồi bấm "Chạy tiếp".'
                    ).classes('text-xs text-gray-600 mb-3')

                    if xac_nhan_file:
                        url = f'/api/ach/download/{state["job_id"]}/{xac_nhan_file}'

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

                    upload_label = ui.label('Chưa chọn file đã điền — có thể kéo-thả trực tiếp vào ô bên dưới').classes(
                        'text-xs text-gray-400 italic mb-1'
                    )

                    async def on_upload_xac_nhan(e):
                        data = e.content.read()
                        state['xac_nhan_upload'] = (e.name, data)
                        upload_label.set_text(f'Đã chọn: {e.name}')
                        upload_label.classes(
                            remove='text-gray-400 italic', add='text-green-700 font-medium'
                        )

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
                """Chế độ B — không tự mở popup, chỉ báo lặng lẽ trên màn hình. Nút
                Dừng ẩn cho tới khi người dùng chủ động mở xác nhận — lúc đó mới gọi
                lại đúng _enter_checkpoint() như Chế độ A (không tách logic riêng)."""
                state['pending_checkpoint_res'] = res
                btn_cancel.set_visibility(False)
                checkpoint_banner_label.set_text(_mo_ta_can_xac_nhan(res))
                checkpoint_banner.set_visibility(True)

            def _open_pending_checkpoint():
                checkpoint_banner.set_visibility(False)
                _enter_checkpoint(state['pending_checkpoint_res'])

            async def on_continue():
                if not state.get('xac_nhan_upload'):
                    ui.notify('Chưa chọn file xác nhận đã điền.', type='warning')
                    return

                name, data = state['xac_nhan_upload']
                checkpoint_dialog.close()
                spinner.set_visibility(True)
                progress_bar.set_visibility(True)
                state['progress'] = 0.0
                progress_bar.set_value(0)
                _append_log(f'[Chạy tiếp] Đang nộp file xác nhận: {name}...')

                try:
                    await asyncio.to_thread(
                        api.post_upload, f'/api/ach/continue/{state["job_id"]}',
                        files={'file': (name, data, 'application/octet-stream')},
                    )
                except Exception as e:
                    spinner.set_visibility(False)
                    progress_bar.set_visibility(False)
                    checkpoint_dialog.open()
                    if not _handle_api_error(e):
                        ui.notify(str(e), type='negative')
                    return

                state['running'] = True
                btn_cancel.set_visibility(True)
                state['timer'] = ui.timer(_POLL_INTERVAL, _poll)

            def _show_results(files: list[str]):
                result_card.set_visibility(True)
                download_row.clear()
                with download_row:
                    for fname in files:
                        icon = 'table_chart' if fname.endswith('.xlsx') else 'description'
                        color = 'green-7' if fname.endswith('.xlsx') else 'blue-7'
                        url   = f'/api/ach/download/{state["job_id"]}/{fname}'

                        async def _tai_ket_qua(u=url, name=fname):
                            try:
                                content = await asyncio.to_thread(api.download, u)
                            except Exception as e:
                                if not _handle_api_error(e):
                                    ui.notify(str(e), type='negative')
                                return
                            ui.download(content, name)

                        ui.button(fname, icon=icon, color=color).on(
                            'click', _tai_ket_qua
                        ).classes('text-xs')

            async def _thuc_hien_chay():
                _clear_log()
                result_card.set_visibility(False)
                checkpoint_dialog.close()
                checkpoint_banner.set_visibility(False)
                state['pending_checkpoint_res'] = None
                state['checkpoint_mode'] = checkpoint_mode_radio.value
                btn_run.set_visibility(False)
                btn_cancel.set_visibility(True)
                spinner.set_visibility(True)
                progress_bar.set_visibility(True)
                state['running'] = True
                state['log_pos'] = 0

                ngay = ngay_input.value.strip() if ngay_input.value else None

                try:
                    _append_log('Đang upload file...')
                    # /api/ach/start nhận `list[UploadFile]` → mọi file phải là part
                    # CÙNG tên field 'files' ⇒ dùng dạng list, không dùng dict.
                    res = await asyncio.to_thread(
                        api.post_upload,
                        '/api/ach/start',
                        files=[('files', (name, data, 'application/octet-stream'))
                               for name, data in state['files'].items()],
                        data={
                            'ngay_doi_chieu': ngay or '',
                            'bo_qua_checkpoint': str(state['bo_qua_checkpoint']).lower(),
                        },
                        timeout=600.0,   # bộ file ACH có thể tới hàng trăm MB
                    )
                except Exception as e:
                    spinner.set_visibility(False)
                    progress_bar.set_visibility(False)
                    btn_cancel.set_visibility(False)
                    btn_run.set_visibility(True)
                    state['running'] = False
                    if not _handle_api_error(e):
                        ui.notify(str(e), type='negative')
                    return

                state['job_id'] = res.get('job_id')
                _append_log(f'Job ID: {state["job_id"]}')

                # Polling timer
                state['timer'] = ui.timer(_POLL_INTERVAL, _poll)

            async def on_run():
                if state['running']:
                    return

                if not state['files']:
                    ui.notify('Chưa chọn file nào.', type='warning')
                    return

                # Chốt kiểm tra ngay trước khi chạy — chặn nếu thiếu/sai file.
                ok = await _validate_now()
                if not ok:
                    ui.notify('Bộ file chưa đủ/đúng — xem chi tiết bên trên trước khi chạy.',
                              type='negative')
                    return

                if state['bo_qua_checkpoint']:
                    # Lớp an toàn thêm: xác nhận lại lần nữa trước khi chạy thẳng bỏ
                    # qua Checkpoint (2026-07-31) — tránh bấm nhầm/quên đang bật.
                    bo_qua_confirm_dialog.open()
                    return

                await _thuc_hien_chay()

            async def _on_xac_nhan_chay_thang():
                bo_qua_confirm_dialog.close()
                await _thuc_hien_chay()

            btn_xac_nhan_chay_thang.on('click', _on_xac_nhan_chay_thang)

            async def on_cancel():
                if not state['job_id']:
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f'/api/ach/cancel/{state["job_id"]}'
                    )
                    _append_log('[Yêu cầu dừng đã gửi — chờ pipeline kết thúc...]')
                    if not state['timer']:
                        # Không có polling đang chạy (vd đang ở Checkpoint chờ xác
                        # nhận) — huỷ có hiệu lực ngay, poll 1 lần để cập nhật UI.
                        await _poll()
                except Exception as e:
                    ui.notify(str(e), type='negative')

            btn_run.on('click', on_run)
            btn_cancel.on('click', on_cancel)
            btn_open_checkpoint.on('click', _open_pending_checkpoint)
