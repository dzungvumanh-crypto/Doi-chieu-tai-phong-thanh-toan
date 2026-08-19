"""Trang Chấm ILO1000 — upload file, chạy pipeline, download kết quả."""

import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
    open_folder_picker,
)

_POLL_INTERVAL = 1.5
_FILE_HINT = (
    'pHub_*.xlsx · UUID.csv (CITAD, nhiều file) · '
    'eicp*.XLS · GL02_*.zip hoặc *_gl02_*.csv'
)


@ui.page('/cham_ilo1000')
async def cham_ilo1000_page():
    if not _require_auth():
        return
    if not api.has_feature('menu.cham_ilo1000'):
        ui.navigate.to('/home')
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        'files':   {},
        'job_id':  None,
        'log_pos': 0,
        'timer':   None,
        'running': False,
        'mode':    'upload',   # 'upload' | 'folder'
    }

    with ui.row().classes('w-full'):
        _sidebar('cham_ilo1000')
        with _content_area():
            _page_header('Chấm ILO1000', 'Đối chiếu Hub · CITAD · EICP · Core — Phòng Thanh toán')

            # ── Input card ────────────────────────────────────────────────────
            with ui.card().classes('w-full p-5 mb-4'):
                ui.label('Nguồn dữ liệu').classes('text-base font-semibold text-red-800 mb-3')

                # Toggle chọn chế độ
                mode_toggle = ui.toggle(
                    {'upload': 'Tải file lên', 'folder': 'Chọn thư mục server'},
                    value='upload',
                ).props('dense')

                # ── Chế độ Upload ─────────────────────────────────────────
                upload_section = ui.column().classes('w-full mt-3 gap-1')
                with upload_section:
                    ui.label(_FILE_HINT).classes('text-xs text-gray-400 mb-1')
                    file_list_label = ui.label('Chưa chọn file nào').classes(
                        'text-xs text-gray-400 italic mb-2'
                    )

                    def on_upload(e):
                        data = e.content.read()
                        state['files'][e.name] = data
                        names = ', '.join(state['files'].keys())
                        file_list_label.set_text(f'Đã chọn ({len(state["files"])} file): {names}')
                        file_list_label.classes(
                            remove='text-gray-400 italic', add='text-green-700 font-medium'
                        )

                    def on_clear():
                        state['files'].clear()
                        file_list_label.set_text('Chưa chọn file nào')
                        file_list_label.classes(
                            remove='text-green-700 font-medium', add='text-gray-400 italic'
                        )

                    ui.upload(
                        on_upload=on_upload,
                        auto_upload=True,
                        multiple=True,
                    ).props(
                        'accept=".xlsx,.xls,.csv,.zip" flat dense '
                        'label="Chọn file (có thể chọn nhiều lần)..."'
                    ).classes('w-full mb-1')

                    ui.button('Xóa tất cả file', icon='delete_outline', color='grey-6',
                              on_click=on_clear).props('flat dense').classes('text-xs')

                # ── Chế độ Folder ─────────────────────────────────────────
                folder_section = ui.column().classes('w-full mt-3 gap-2')
                folder_section.set_visibility(False)
                with folder_section:
                    ui.label(
                        'Nhập đường dẫn thư mục chứa file ILO1000 trên server.'
                    ).classes('text-xs text-gray-500')
                    with ui.row().classes('w-full items-center gap-2'):
                        folder_input = ui.input(
                            placeholder='Ví dụ: D:\\Data\\ILO1000\\ngay12',
                        ).props('outlined dense clearable').classes('flex-1')

                        async def _on_pick_folder():
                            def _on_folder_selected(path: str):
                                folder_input.value = path
                            await open_folder_picker(
                                _on_folder_selected, initial_path=folder_input.value or ''
                            )

                        ui.button('Duyệt...', icon='folder_open', color='blue-7',
                                  on_click=_on_pick_folder).props('outlined dense')
                    ui.label(
                        'Thư mục phải chứa đủ: pHub_*.xlsx · UUID.csv · eicp*.XLS · GL02_*.zip'
                    ).classes('text-xs text-gray-400')

                def on_mode_change(val):
                    state['mode'] = val
                    upload_section.set_visibility(val == 'upload')
                    folder_section.set_visibility(val == 'folder')

                mode_toggle.on_value_change(lambda e: on_mode_change(e.value))

                # Nút Chạy / Dừng
                with ui.row().classes('gap-3 mt-4'):
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
                    'p-3 overflow-y-auto max-h-72 min-h-24 gap-0'
                )
                with log_area:
                    ui.label('Sẵn sàng. Chọn file và bấm "Chạy đối chiếu".').classes('text-gray-500')

            # ── Kết quả ───────────────────────────────────────────────────────
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
                        f'/api/ilo1000/poll/{state["job_id"]}',
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
                        _show_results(res.get('files', []))
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
                        url = f'/api/ilo1000/download/{state["job_id"]}/{fname}'

                        async def _tai_ket_qua(u=url, name=fname):
                            try:
                                content = await asyncio.to_thread(api.download, u)
                            except Exception as e:
                                if not _handle_api_error(e):
                                    ui.notify(str(e), type='negative')
                                return
                            ui.download(content, name)

                        ui.button(fname, icon='table_chart', color='green-7').on(
                            'click', _tai_ket_qua
                        ).classes('text-xs')

            async def on_run():
                if state['running']:
                    return

                # Validate đầu vào theo mode
                if state['mode'] == 'upload':
                    if not state['files']:
                        ui.notify('Chưa chọn file nào.', type='warning')
                        return
                else:
                    folder_path = (folder_input.value or '').strip()
                    if not folder_path:
                        ui.notify('Chưa nhập đường dẫn thư mục.', type='warning')
                        return

                _clear_log()
                result_card.set_visibility(False)
                btn_run.set_visibility(False)
                btn_cancel.set_visibility(True)
                spinner.set_visibility(True)
                state['running'] = True
                state['log_pos'] = 0

                try:
                    if state['mode'] == 'upload':
                        _append_log('Đang upload file...')
                        res = await asyncio.to_thread(
                            api.post_multipart,
                            '/api/ilo1000/start',
                            files=[(name, data) for name, data in state['files'].items()],
                        )
                    else:
                        _append_log(f'Thư mục: {folder_path}')
                        res = await asyncio.to_thread(
                            api.post,
                            '/api/ilo1000/start_folder',
                            {'folder_path': folder_path},
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
                state['timer'] = ui.timer(_POLL_INTERVAL, _poll)

            async def on_cancel():
                if not state['job_id']:
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f'/api/ilo1000/cancel/{state["job_id"]}'
                    )
                    _append_log('[Yêu cầu dừng đã gửi — chờ pipeline kết thúc...]')
                except Exception as e:
                    ui.notify(str(e), type='negative')

            btn_run.on('click', on_run)
            btn_cancel.on('click', on_cancel)
