"""Trang Chấm đối chiếu ACH — upload file, chạy pipeline, download kết quả."""

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
    '2× *_DI_*.zip · 2× *_DEN_*.zip'
)


@ui.page('/cham_ach')
async def cham_ach_page():
    if not _require_auth():
        return
    if not api.has_feature('menu.cham_ach'):
        ui.navigate.to('/home')
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        'files':    {},     # {filename: bytes}
        'job_id':   None,
        'log_pos':  0,      # số log đã hiển thị
        'timer':    None,
        'running':  False,
    }

    with ui.row().classes('w-full'):
        _sidebar('cham_ach')
        with _content_area():
            _page_header('Chấm đối chiếu ACH', 'Đối chiếu GL02 (NPO) với MIS — Phòng Thanh toán')

            # ── Upload card ───────────────────────────────────────────────────
            with ui.card().classes('w-full p-5 mb-4'):
                ui.label('Tải lên file dữ liệu').classes('text-base font-semibold text-red-800 mb-1')
                ui.label(_FILE_HINT).classes('text-xs text-gray-400 mb-3')

                file_list_label = ui.label('Chưa chọn file nào').classes(
                    'text-xs text-gray-400 italic mb-2'
                )

                def on_upload(e):
                    data = e.content.read()
                    state['files'][e.name] = data
                    names = ', '.join(state['files'].keys())
                    file_list_label.set_text(f'Đã chọn ({len(state["files"])} file): {names}')
                    file_list_label.classes(remove='text-gray-400 italic', add='text-green-700 font-medium')

                ui.upload(
                    on_upload=on_upload,
                    auto_upload=True,
                    multiple=True,
                ).props(
                    'accept=".zip,.xlsx,.pdf" flat dense label="Chọn file (có thể chọn nhiều)..."'
                ).classes('w-full mb-3')

                # Ngày đối chiếu
                with ui.row().classes('items-center gap-3 mb-3'):
                    ui.label('Ngày đối chiếu:').classes('text-sm text-gray-600')
                    ngay_input = ui.input(
                        placeholder='dd/mm/yyyy  (bỏ trống = tự động từ PDF)',
                    ).props('dense outlined clearable').classes('w-44')
                    ui.label('Bỏ trống → tự động lấy từ tên file PDF').classes('text-xs text-gray-400')

                # Nút Chạy / Dừng
                with ui.row().classes('gap-3'):
                    btn_run = ui.button('Chạy đối chiếu', icon='play_arrow',
                                        color='red-8').classes('font-semibold')
                    btn_cancel = ui.button('Dừng', icon='stop_circle',
                                           color='grey-6').classes('font-semibold')
                    btn_cancel.set_visibility(False)

            # ── Log card ──────────────────────────────────────────────────────
            with ui.card().classes('w-full p-0 mb-4'):
                with ui.row().classes('w-full bg-gray-800 px-4 py-2 rounded-t items-center gap-2'):
                    ui.icon('terminal').classes('text-green-400 text-sm')
                    ui.label('Log xử lý').classes('text-xs font-semibold text-green-300')
                    spinner = ui.spinner('dots', size='xs', color='green')
                    spinner.set_visibility(False)

                log_area = ui.column().classes(
                    'w-full bg-gray-900 font-mono text-xs text-green-200 '
                    'p-3 overflow-y-auto max-h-64 min-h-24 gap-0'
                )
                with log_area:
                    ui.label('Sẵn sàng. Chọn file và bấm "Chạy đối chiếu".').classes('text-gray-500')

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

            def _clear_log():
                log_area.clear()

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
                        return
                    return

                new_logs = res.get('logs', [])
                for line in new_logs:
                    _append_log(line)
                state['log_pos'] += len(new_logs)

                status = res.get('status', '')

                if status in ('done', 'error', 'cancelled'):
                    spinner.set_visibility(False)
                    btn_cancel.set_visibility(False)
                    btn_run.set_visibility(True)
                    state['running'] = False
                    if state['timer']:
                        state['timer'].cancel()
                        state['timer'] = None

                    if status == 'done':
                        files = res.get('files', [])
                        _show_results(files)
                        ui.notify('Hoàn thành! Tải file kết quả bên dưới.', type='positive')
                    elif status == 'error':
                        ui.notify(f'Lỗi: {res.get("error", "")}', type='negative', timeout=0)
                    elif status == 'cancelled':
                        ui.notify('Đã dừng theo yêu cầu.', type='warning')

            def _show_results(files: list[str]):
                result_card.set_visibility(True)
                download_row.clear()
                with download_row:
                    for fname in files:
                        icon = 'table_chart' if fname.endswith('.xlsx') else 'description'
                        color = 'green-7' if fname.endswith('.xlsx') else 'blue-7'
                        url   = f'/api/ach/download/{state["job_id"]}/{fname}'
                        ui.button(fname, icon=icon, color=color).on(
                            'click', lambda u=url: ui.navigate.to(u)
                        ).classes('text-xs')

            async def on_run():
                if not state['files']:
                    ui.notify('Chưa chọn file nào.', type='warning')
                    return
                if state['running']:
                    return

                _clear_log()
                _append_log('Đang upload file...')
                result_card.set_visibility(False)
                btn_run.set_visibility(False)
                btn_cancel.set_visibility(True)
                spinner.set_visibility(True)
                state['running'] = True
                state['log_pos'] = 0

                ngay = ngay_input.value.strip() if ngay_input.value else None

                try:
                    res = await asyncio.to_thread(
                        api.post_multipart,
                        '/api/ach/start',
                        files=[(name, data) for name, data in state['files'].items()],
                        data={'ngay_doi_chieu': ngay or ''},
                    )
                except Exception as e:
                    spinner.set_visibility(False)
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

            async def on_cancel():
                if not state['job_id']:
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f'/api/ach/cancel/{state["job_id"]}'
                    )
                    _append_log('[Yêu cầu dừng đã gửi — chờ pipeline kết thúc...]')
                except Exception as e:
                    ui.notify(str(e), type='negative')

            btn_run.on('click', on_run)
            btn_cancel.on('click', on_cancel)
