"""Trang Chấm đối chiếu ACH — upload file (hoặc chọn thư mục server), chạy pipeline, download kết quả."""

import re
import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
    open_folder_picker,
)

# ─── Hằng số ──────────────────────────────────────────────────────────────────
_POLL_INTERVAL = 1.5   # giây
_FILE_HINT = (
    'PDF (session) · GL02*.zip · GW*.xlsx · '
    '2× *_DI_*.zip · 2× *_DEN_*.zip'
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

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        'files':       {},     # {filename: bytes}
        'job_id':      None,
        'log_pos':     0,      # số log đã hiển thị
        'timer':       None,
        'running':     False,
        'mode':        'folder',   # 'upload' | 'folder' — folder là luồng chính (chỉ chọn 1 thư mục)
        'progress':    0.0,
        'poll_fails':  0,      # số lần poll lỗi liên tiếp
        'xac_nhan_upload': None,   # (filename, bytes) file xác nhận đã điền, chờ upload
        'checkpoint_mode': 'inline',   # 'inline' | 'deferred' — cách xử lý khi tới Checkpoint
        'pending_checkpoint_res': None,   # kết quả poll lúc tới Checkpoint (mode deferred, chờ mở)
    }

    with ui.row().classes('w-full'):
        _sidebar('cham_ach')
        with _content_area():
            _page_header('Chấm đối chiếu ACH', 'Đối chiếu GL02 (NPO) với MIS — Phòng Thanh toán')

            # ── Input card ────────────────────────────────────────────────────
            with ui.card().classes('w-full p-5 mb-4'):
                ui.label('Nguồn dữ liệu').classes('text-base font-semibold text-red-800 mb-3')

                mode_toggle = ui.toggle(
                    {'folder': 'Chọn thư mục server', 'upload': 'Tải file lên'},
                    value='folder',
                ).props('dense')

                # ── Chế độ Upload ─────────────────────────────────────────
                upload_section = ui.column().classes('w-full mt-3 gap-1')
                upload_section.set_visibility(False)
                with upload_section:
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
                        'accept=".zip,.xlsx,.pdf" flat dense label="Chọn file (có thể chọn nhiều)..."'
                    ).classes('w-full mb-1')

                    ui.button('Xóa tất cả file', icon='delete_outline', color='grey-6',
                              on_click=on_clear).props('flat dense').classes('text-xs')

                # ── Chế độ Folder ─────────────────────────────────────────
                folder_section = ui.column().classes('w-full mt-3 gap-2')
                with folder_section:
                    ui.label(
                        'Nhập đường dẫn 1 thư mục duy nhất chứa đủ file ACH của 1 phiên/1 ngày — '
                        'chương trình tự nhận diện toàn bộ file cần thiết. Kết quả cuối sẽ được '
                        'lưu lại ngay trong thư mục này (thư mục con "Output").'
                    ).classes('text-xs text-gray-500')
                    with ui.row().classes('w-full items-center gap-2'):
                        folder_input = ui.input(
                            placeholder='Ví dụ: D:\\Data\\ACH\\ngay16',
                        ).props('outlined dense clearable').classes('flex-1')

                        async def _on_pick_folder():
                            async def _on_folder_selected(path: str):
                                folder_input.value = path
                                await _validate_now()
                            await open_folder_picker(
                                _on_folder_selected, initial_path=folder_input.value or ''
                            )

                        ui.button('Duyệt...', icon='folder_open', color='blue-7',
                                  on_click=_on_pick_folder).props('outlined dense')
                    ui.label(_FILE_HINT).classes('text-xs text-gray-400')
                    ui.button('Kiểm tra thư mục', icon='fact_check', color='blue-7',
                              on_click=lambda: _validate_now()).props('flat dense').classes('text-xs')

                def on_mode_change(val):
                    state['mode'] = val
                    upload_section.set_visibility(val == 'upload')
                    folder_section.set_visibility(val == 'folder')
                    validate_card.set_visibility(False)

                mode_toggle.on_value_change(lambda e: on_mode_change(e.value))

                # Ngày đối chiếu
                with ui.row().classes('items-center gap-3 mt-3'):
                    ui.label('Ngày đối chiếu:').classes('text-sm text-gray-600')
                    ngay_input = ui.input(
                        placeholder='dd/mm/yyyy  (bỏ trống = tự động từ PDF)',
                    ).props('dense outlined clearable').classes('w-44')
                    ui.label('Bỏ trống → tự động lấy từ tên file PDF').classes('text-xs text-gray-400')

                # ── Kết quả kiểm tra file ───────────────────────────────────
                validate_card = ui.column().classes('w-full mt-3 gap-1 p-3 rounded bg-gray-50 border')
                validate_card.set_visibility(False)

                # ── Chế độ xử lý Checkpoint ───────────────────────────────
                ui.label('Chế độ xử lý Checkpoint').classes('text-sm font-medium text-gray-700 mt-4')
                checkpoint_mode_radio = ui.radio(
                    {
                        'inline':   'Xác nhận ngay khi phát hiện Timeout (quy trình hiện tại)',
                        'deferred': 'Chạy hết phần tự động, sau đó mới xác nhận Timeout rồi tiếp tục chạy',
                    },
                    value='inline',
                ).props('dense')

                # Nút Chạy / Dừng
                with ui.row().classes('gap-3 mt-4 items-center'):
                    btn_run = ui.button('Chạy đối chiếu', icon='play_arrow',
                                        color='red-8').classes('font-semibold')
                    btn_cancel = ui.button('Dừng', icon='stop_circle',
                                           color='grey-6').classes('font-semibold')
                    btn_cancel.set_visibility(False)
                    ui.label(
                        'Pipeline sẽ dừng lại sau khi so khớp GW để bạn xác nhận nhánh '
                        'Timeout, rồi mới chạy tiếp tới báo cáo cuối.'
                    ).classes('text-xs text-gray-400')

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
                result_location_label = ui.label('').classes('text-xs mb-3')
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
                    if state['mode'] == 'upload':
                        if not state['files']:
                            validate_card.set_visibility(False)
                            return False
                        res = await asyncio.to_thread(
                            api.post, '/api/ach/validate',
                            {'filenames': list(state['files'].keys())},
                        )
                    else:
                        folder_path = (folder_input.value or '').strip()
                        if not folder_path:
                            validate_card.set_visibility(False)
                            return False
                        res = await asyncio.to_thread(
                            api.post, '/api/ach/validate_folder',
                            {'folder_path': folder_path},
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
                        _show_results(files, res.get('final_output_dir'), res.get('copy_error'))
                        if res.get('final_output_dir'):
                            ui.notify(f'Đối chiếu hoàn thành. Kết quả đã lưu tại: {res["final_output_dir"]}',
                                      type='positive', timeout=0)
                        else:
                            ui.notify('Hoàn thành! Tải file kết quả bên dưới.', type='positive')
                    elif status == 'error':
                        progress_bar.set_visibility(False)
                        ui.notify(f'Lỗi: {res.get("error", "")}', type='negative', timeout=0)
                    elif status == 'cancelled':
                        progress_bar.set_visibility(False)
                        checkpoint_dialog.close()
                        ui.notify('Đã dừng theo yêu cầu.', type='warning')

            def _enter_checkpoint(res: dict):
                """Job đã dừng ở Checkpoint sau khop_voi_gw() — hiện NGAY popup để
                người dùng tải, điền cột KET_QUA_XAC_NHAN, kéo-thả (hoặc chọn) lại
                file rồi bấm "Chạy tiếp". Không đổi cơ chế Checkpoint — chỉ đổi cách
                trình bày (card ẩn/hiện → popup tự mở)."""
                btn_run.set_visibility(False)
                btn_cancel.set_visibility(True)
                result_card.set_visibility(False)
                checkpoint_dialog.clear()
                state['xac_nhan_upload'] = None

                files         = res.get('files', [])
                xac_nhan_file = files[0] if files else None
                loi_lan_truoc = res.get('error')
                so_luong      = res.get('xac_nhan_count')

                with checkpoint_dialog, ui.card().classes('p-5').style('min-width: 480px'):
                    if so_luong is not None:
                        ui.label(f'Có {so_luong:,} giao dịch cần xác nhận.').classes(
                            'text-base font-semibold text-orange-800 mb-1'
                        )
                    else:
                        ui.label('Cần xác nhận thủ công nhánh Timeout.').classes(
                            'text-base font-semibold text-orange-800 mb-1'
                        )
                    ui.label(f'{xac_nhan_file} đã sẵn sàng.').classes('text-sm text-gray-700 mb-2')
                    if loi_lan_truoc:
                        ui.label(f'File xác nhận vừa nộp bị từ chối: {loi_lan_truoc}').classes(
                            'text-xs text-red-600 mb-2'
                        )
                    ui.label(
                        '1) Tải file bên dưới · 2) Mở file, ở sheet CAN_XAC_NHAN chọn '
                        'KET_QUA_XAC_NHAN cho MỌI dòng (có thể paste thêm MSGREF bị bỏ sót vào '
                        'vùng "BỔ SUNG" cuối sheet) · 3) Kéo-thả (hoặc chọn) lại file đã điền '
                        'rồi bấm "Chạy tiếp".'
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
                        ui.button('Đã xác nhận – Chạy tiếp', icon='play_arrow', color='red-8').classes(
                            'font-semibold'
                        ).on('click', on_continue)

                checkpoint_dialog.open()

            def _show_checkpoint_banner(res: dict):
                """Chế độ B — không tự mở popup, chỉ báo lặng lẽ trên màn hình. Nút
                Dừng ẩn cho tới khi người dùng chủ động mở xác nhận — lúc đó mới gọi
                lại đúng _enter_checkpoint() như Chế độ A (không tách logic riêng)."""
                state['pending_checkpoint_res'] = res
                btn_cancel.set_visibility(False)
                so_luong = res.get('xac_nhan_count')
                text = (f'Có {so_luong:,} giao dịch Timeout cần xác nhận.' if so_luong is not None
                        else 'Cần xác nhận thủ công nhánh Timeout.')
                checkpoint_banner_label.set_text(text)
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

            def _show_results(files: list[str], final_output_dir: str | None = None,
                              copy_error: str | None = None):
                result_card.set_visibility(True)
                if final_output_dir:
                    result_location_label.set_text(f'Đã lưu tại: {final_output_dir}')
                    result_location_label.classes(remove='text-red-600', add='text-green-700')
                elif copy_error:
                    result_location_label.set_text(
                        f'Không copy được kết quả về thư mục dữ liệu ({copy_error}) — '
                        f'vui lòng tải xuống thủ công bên dưới.'
                    )
                    result_location_label.classes(remove='text-green-700', add='text-red-600')
                else:
                    result_location_label.set_text('')
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

            async def on_run():
                if state['running']:
                    return

                if state['mode'] == 'upload' and not state['files']:
                    ui.notify('Chưa chọn file nào.', type='warning')
                    return
                if state['mode'] == 'folder' and not (folder_input.value or '').strip():
                    ui.notify('Chưa nhập đường dẫn thư mục.', type='warning')
                    return

                # Chốt kiểm tra ngay trước khi chạy — chặn nếu thiếu/sai file.
                ok = await _validate_now()
                if not ok:
                    ui.notify('Bộ file chưa đủ/đúng — xem chi tiết bên trên trước khi chạy.',
                              type='negative')
                    return

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
                    if state['mode'] == 'upload':
                        _append_log('Đang upload file...')
                        res = await asyncio.to_thread(
                            api.post_multipart,
                            '/api/ach/start',
                            files=[(name, data) for name, data in state['files'].items()],
                            data={'ngay_doi_chieu': ngay or ''},
                        )
                    else:
                        folder_path = folder_input.value.strip()
                        _append_log(f'Thư mục: {folder_path}')
                        res = await asyncio.to_thread(
                            api.post, '/api/ach/start_folder',
                            {'folder_path': folder_path, 'ngay_doi_chieu': ngay or ''},
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
