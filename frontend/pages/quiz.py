"""Ôn tập trắc nghiệm — chọn bộ câu hỏi, đặt thông số thi thử, xem lịch sử & xếp hạng.

Màn làm bài nằm ở trang riêng `/quiz/play` (frontend/pages/quiz_play.py): làm
bài cần cả màn hình, giữ nguyên sidebar thì phần câu hỏi bị bóp còn hai phần ba.
"""
import asyncio

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

_CSS = """<style>
/* Thẻ bộ câu hỏi — dải màu trên đầu cho dễ phân biệt khi có nhiều bộ */
.qz-card { transition: transform .12s ease, box-shadow .12s ease; }
.qz-card:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(0,0,0,.12); }
.qz-band { height: 74px; display: flex; align-items: center; padding: 0 16px;
           background: linear-gradient(135deg, #7f1d1d 0%, #b91c1c 60%, #dc2626 100%); }
.qz-name { color: #fff; font-weight: 700; font-size: 15px; line-height: 1.3;
           display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
           overflow: hidden; }
</style>"""

_MODE_OPTS = {
    "practice": "Ôn tập — hiện đáp án ngay sau mỗi câu",
    "exam": "Thi thử — chỉ chấm điểm khi nộp bài",
}
_NUM_OPTS = {0: "Tất cả câu trong bộ", 10: "10 câu", 20: "20 câu",
             30: "30 câu", 50: "50 câu", 100: "100 câu"}
_SEC_OPTS = {0: "Không giới hạn", 10: "10 giây", 15: "15 giây", 20: "20 giây",
             30: "30 giây", 45: "45 giây", 60: "60 giây", 90: "90 giây"}
_MIN_OPTS = {0: "Không giới hạn", 5: "5 phút", 10: "10 phút", 15: "15 phút",
             20: "20 phút", 30: "30 phút", 45: "45 phút", 60: "60 phút", 90: "90 phút"}

_XLSX_MIME = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _fmt_ms(ms) -> str:
    """Mili giây → 'm phút s giây' — người dùng đọc số phút, không đọc mili giây."""
    if not ms:
        return "—"
    total = int(ms / 1000)
    m, s = divmod(total, 60)
    return f"{m} phút {s:02d} giây" if m else f"{s} giây"


def _fmt_dt(iso: str) -> str:
    """'2026-08-26 09:15:03' → '26/08/2026 09:15'."""
    if not iso:
        return "—"
    try:
        d, t = str(iso).split(" ")[0], str(iso).split(" ")[1]
        y, m, dd = d.split("-")
        return f"{dd}/{m}/{y} {t[:5]}"
    except (ValueError, IndexError):
        return str(iso)


@ui.page("/quiz")
async def quiz_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.quiz"):
        ui.navigate.to("/home")
        return

    can_upload = api.has_feature("quiz.upload")
    can_delete = api.has_feature("quiz.delete")

    await _sidebar("quiz")
    ui.add_head_html(_CSS)

    sets_cache: list[dict] = []
    picked = {"id": None, "name": "", "count": 0}

    with _content_area():
        _page_header("Ôn tập trắc nghiệm",
                     "Chọn một bộ câu hỏi có sẵn để ôn tập hoặc thi thử")

        # ── Dialog cài đặt trước khi làm bài ──────────────────────────────────
        with ui.dialog() as cfg_dialog, ui.card().classes("w-full max-w-xl"):
            cfg_title = ui.label("").classes("text-lg font-bold text-red-900")
            cfg_sub = ui.label("").classes("text-sm text-gray-500 mb-2")

            f_mode = ui.select(_MODE_OPTS, value="practice", label="Chế độ").props(
                "dense outlined").classes("w-full")
            with ui.grid(columns=2).classes("w-full gap-3 mt-1"):
                f_num = ui.select(_NUM_OPTS, value=0, label="Số câu hỏi").props("dense outlined")
                f_sec = ui.select(_SEC_OPTS, value=0, label="Thời gian mỗi câu").props("dense outlined")
                f_min = ui.select(_MIN_OPTS, value=0, label="Tổng thời gian làm bài").props("dense outlined")
                with ui.column().classes("gap-1 justify-center"):
                    f_shuffle_q = ui.switch("Trộn thứ tự câu hỏi", value=True).props("dense")
                    f_shuffle_o = ui.switch("Trộn thứ tự đáp án", value=True).props("dense")

            # Hai thông số dưới đây gắn với nhau: thi thử mà hiện đáp án ngay
            # thì không còn là thi thử. Đổi chế độ sẽ đặt lại ô này cho khớp,
            # nhưng vẫn cho người dùng tự bật/tắt sau đó.
            f_instant = ui.switch("Hiện đáp án đúng ngay sau khi chọn", value=True).props("dense")

            def _on_mode(_=None):
                f_instant.set_value(f_mode.value == "practice")
            f_mode.on_value_change(_on_mode)

            ui.label(
                "Bài ở chế độ Thi thử mới được tính vào bảng xếp hạng."
            ).classes("text-xs text-gray-500 mt-1")

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Huỷ", on_click=cfg_dialog.close).props("flat").classes("text-gray-600")

                async def do_start():
                    body = {
                        "set_id": picked["id"],
                        "settings": {
                            "mode": f_mode.value,
                            "num_questions": int(f_num.value or 0),
                            "shuffle_questions": bool(f_shuffle_q.value),
                            "shuffle_options": bool(f_shuffle_o.value),
                            "seconds_per_question": int(f_sec.value or 0),
                            "total_minutes": int(f_min.value or 0),
                            "instant_feedback": bool(f_instant.value),
                        },
                    }
                    try:
                        att = await asyncio.to_thread(api.post, "/api/quiz/attempts", body)
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    cfg_dialog.close()
                    ui.navigate.to(f"/quiz/play?attempt={att['id']}")

                ui.button("Bắt đầu", icon="play_arrow", on_click=do_start).classes(
                    "bg-red-700 text-white")

        def open_cfg(s: dict):
            picked.update(id=s["id"], name=s["name"], count=s["question_count"])
            cfg_title.text = s["name"]
            cfg_sub.text = f"{s['question_count']} câu hỏi trong bộ"
            # Đề dài hơn bộ thì backend tự cắt, nhưng để lựa chọn vô nghĩa trong
            # danh sách vẫn khó chịu — bỏ luôn các mức lớn hơn số câu thật có.
            opts = {k: v for k, v in _NUM_OPTS.items() if k == 0 or k <= s["question_count"]}
            f_num.set_options(opts, value=0)
            cfg_dialog.open()

        # ── Đổi tên bộ ────────────────────────────────────────────────────────
        rename_target = {"id": None}
        with ui.dialog() as rn_dialog, ui.card().classes("w-full max-w-md"):
            ui.label("Đổi tên bộ câu hỏi").classes("text-lg font-bold text-red-900 mb-1")
            rn_name = ui.input("Tên bộ *").props("dense outlined").classes("w-full")
            rn_desc = ui.textarea("Mô tả").props("dense outlined autogrow").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Huỷ", on_click=rn_dialog.close).props("flat").classes("text-gray-600")

                async def do_rename():
                    if not (rn_name.value or "").strip():
                        ui.notify("Vui lòng nhập tên bộ", type="warning")
                        return
                    try:
                        await asyncio.to_thread(
                            api.patch, f"/api/quiz/sets/{rename_target['id']}",
                            {"name": rn_name.value.strip(),
                             "description": (rn_desc.value or "").strip() or None})
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    rn_dialog.close()
                    ui.notify("Đã đổi tên bộ câu hỏi", type="positive")
                    await load()

                ui.button("Lưu", icon="save", on_click=do_rename).classes("bg-red-700 text-white")

        def open_rename(s: dict):
            rename_target["id"] = s["id"]
            rn_name.set_value(s["name"])
            rn_desc.set_value(s.get("description") or "")
            rn_dialog.open()

        async def do_delete(s: dict):
            with ui.dialog() as confirm, ui.card():
                ui.label(f"Xoá bộ «{s['name']}»?").classes("font-semibold")
                ui.label(
                    f"Xoá cả {s['question_count']} câu hỏi, toàn bộ lượt làm bài của mọi "
                    "người và bảng xếp hạng của bộ này. Không hoàn tác được."
                ).classes("text-sm text-gray-600 max-w-md")
                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Huỷ", on_click=lambda: confirm.submit(False)).props("flat")
                    ui.button("Xoá", on_click=lambda: confirm.submit(True)).classes(
                        "bg-red-700 text-white")
            if not await confirm:
                return
            try:
                res = await asyncio.to_thread(api.delete, f"/api/quiz/sets/{s['id']}")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            ui.notify(f"Đã xoá bộ câu hỏi ({res.get('deleted_attempts', 0)} lượt làm bài)",
                      type="positive")
            await load()

        # ── Bảng xếp hạng ─────────────────────────────────────────────────────
        with ui.dialog() as lb_dialog, ui.card().classes("w-full max-w-2xl"):
            lb_title = ui.label("").classes("text-lg font-bold text-red-900 mb-1")
            ui.label("Chỉ tính bài Thi thử — mỗi người lấy lượt tốt nhất").classes(
                "text-xs text-gray-500 mb-2")
            lb_area = ui.column().classes("w-full")
            ui.button("Đóng", on_click=lb_dialog.close).props("flat").classes(
                "text-gray-600 self-end")

        async def open_leaderboard(s: dict):
            lb_title.text = f"Bảng xếp hạng — {s['name']}"
            lb_area.clear()
            lb_dialog.open()
            try:
                rows = await asyncio.to_thread(
                    api.get, f"/api/quiz/sets/{s['id']}/leaderboard", {"limit": 20})
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            with lb_area:
                if not rows:
                    ui.label("Chưa có ai thi thử bộ này").classes(
                        "text-gray-500 text-center py-6 w-full")
                    return
                ui.table(
                    columns=[
                        {"name": "rank", "label": "#", "field": "rank", "align": "center",
                         "style": "width:48px"},
                        {"name": "staff_name", "label": "Họ tên", "field": "staff_name",
                         "align": "left"},
                        {"name": "score", "label": "Điểm", "field": "score", "align": "right",
                         "style": "width:80px"},
                        {"name": "detail", "label": "Số câu đúng", "field": "detail",
                         "align": "center", "style": "width:110px"},
                        {"name": "duration", "label": "Thời gian", "field": "duration",
                         "align": "right", "style": "width:130px"},
                    ],
                    rows=[{
                        "rank": i,
                        "staff_name": r.get("staff_name") or "—",
                        "score": f"{r.get('score') or 0:.1f}%",
                        "detail": f"{r.get('correct_count') or 0}/{r['total_questions']}",
                        "duration": _fmt_ms(r.get("duration_ms")),
                    } for i, r in enumerate(rows, start=1)],
                    row_key="rank",
                    pagination={"rowsPerPage": 0},
                ).props('bordered dense flat separator="cell"').classes("w-full")

        # ── Thanh thao tác ────────────────────────────────────────────────────
        with ui.card().classes("w-full shadow-sm rounded-lg bg-white px-3 py-2 mb-4"):
            with ui.row().classes("items-center gap-2 flex-wrap w-full"):
                count_label = ui.label("").classes("text-sm text-gray-600")
                ui.space()

                async def show_history():
                    hist_area.clear()
                    try:
                        rows = await asyncio.to_thread(api.get, "/api/quiz/attempts",
                                                       {"limit": 30})
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    with hist_area:
                        if not rows:
                            ui.label("Bạn chưa làm bài nào").classes(
                                "text-gray-500 text-center py-6 w-full")
                            return
                        tbl = ui.table(
                            columns=[
                                {"name": "set_name", "label": "Bộ câu hỏi", "field": "set_name",
                                 "align": "left"},
                                {"name": "mode", "label": "Chế độ", "field": "mode",
                                 "align": "center", "style": "width:90px"},
                                {"name": "score", "label": "Điểm", "field": "score",
                                 "align": "right", "style": "width:80px"},
                                {"name": "detail", "label": "Đúng", "field": "detail",
                                 "align": "center", "style": "width:90px"},
                                {"name": "duration", "label": "Thời gian", "field": "duration",
                                 "align": "right", "style": "width:120px"},
                                {"name": "finished_at", "label": "Lúc", "field": "finished_at",
                                 "align": "left", "style": "width:140px"},
                                {"name": "actions", "label": "", "field": "actions",
                                 "align": "center", "style": "width:70px"},
                            ],
                            rows=[{
                                "id": r["id"],
                                "set_name": r["set_name"],
                                "mode": "Thi thử" if r["mode"] == "exam" else "Ôn tập",
                                "score": f"{r.get('score') or 0:.1f}%",
                                "detail": f"{r.get('correct_count') or 0}/{r['total_questions']}",
                                "duration": _fmt_ms(r.get("duration_ms")),
                                "finished_at": _fmt_dt(r.get("finished_at")),
                            } for r in rows],
                            row_key="id",
                            pagination={"rowsPerPage": 10},
                        ).props('bordered dense flat separator="cell"').classes("w-full")
                        tbl.add_slot("body-cell-actions", r"""
                            <q-td :props="props">
                              <q-btn dense flat round size="sm" color="primary" icon="visibility"
                                     @click="() => $parent.$emit('viewOne', props.row.id)" />
                            </q-td>
                        """)
                        tbl.on("viewOne",
                               lambda e: ui.navigate.to(f"/quiz/play?attempt={int(e.args)}"))
                    hist_dialog.open()

                with ui.dialog() as hist_dialog, ui.card().classes("w-full max-w-4xl"):
                    ui.label("Lịch sử làm bài của tôi").classes(
                        "text-lg font-bold text-red-900 mb-2")
                    hist_area = ui.column().classes("w-full")
                    ui.button("Đóng", on_click=hist_dialog.close).props("flat").classes(
                        "text-gray-600 self-end")

                ui.button("Lịch sử của tôi", icon="history", on_click=show_history).props(
                    "dense no-caps").classes("bg-gray-700 text-white px-3")

                if can_upload:
                    async def do_template():
                        try:
                            content = await asyncio.to_thread(
                                api.download, "/api/quiz/template")
                        except Exception as e:
                            if _handle_api_error(e):
                                return
                            ui.notify(str(e), type="negative")
                            return
                        ui.download(content, "Mau_bo_cau_hoi.xlsx")

                    ui.button("Tải file mẫu", icon="download", on_click=do_template).props(
                        "dense no-caps flat").classes("text-red-800 px-2")
                    ui.button("Tải bộ câu hỏi lên", icon="upload_file",
                              on_click=lambda: up_dialog.open()).props(
                        "dense no-caps").classes("bg-red-700 text-white px-3")

        # ── Dialog tải bộ lên ─────────────────────────────────────────────────
        if can_upload:
            with ui.dialog() as up_dialog, ui.card().classes("w-full max-w-lg"):
                ui.label("Tải bộ câu hỏi lên").classes("text-lg font-bold text-red-900")
                ui.label(
                    "File Excel, cột theo thứ tự: Câu hỏi | Đáp án 1 | Đáp án 2 | Đáp án 3 | "
                    "Đáp án 4 | Đáp án đúng (số 1-4). Bỏ trống Đáp án 4 nếu câu chỉ có 3 lựa chọn."
                ).classes("text-sm text-gray-600 mb-2")
                up_name = ui.input("Tên bộ (bỏ trống thì lấy tên file)").props(
                    "dense outlined").classes("w-full")
                up_desc = ui.textarea("Mô tả").props("dense outlined autogrow").classes("w-full")
                up_busy = ui.row().classes("items-center gap-2 py-2 hidden")
                with up_busy:
                    ui.spinner(size="1.5em", color="red")
                    ui.label("Đang đọc file...").classes("text-sm text-gray-600")

                async def do_upload(e):
                    up_busy.classes(remove="hidden")
                    params = []
                    if (up_name.value or "").strip():
                        params.append(("name", up_name.value.strip()))
                    if (up_desc.value or "").strip():
                        params.append(("description", up_desc.value.strip()))
                    from urllib.parse import urlencode
                    qs = f"?{urlencode(params)}" if params else ""
                    try:
                        res = await asyncio.to_thread(
                            api.post_upload, f"/api/quiz/sets/upload{qs}",
                            {"file": (e.name, e.content.read(), _XLSX_MIME)},
                            None, 120.0,
                        )
                    except Exception as ex:
                        if _handle_api_error(ex):
                            return
                        ui.notify(str(ex), type="negative", timeout=8000)
                        return
                    finally:
                        up_busy.classes(add="hidden")
                    up_dialog.close()
                    up_name.set_value("")
                    up_desc.set_value("")
                    ui.notify(f"Đã nhập «{res['name']}»: {res['imported']} câu"
                              + (f", bỏ qua {res['skipped']} dòng lỗi" if res["skipped"] else ""),
                              type="positive", timeout=6000)
                    for w in res.get("errors", [])[:10]:
                        ui.notify(w, type="warning", timeout=9000)
                    await load()

                # Truyền THẲNG hàm async — bọc asyncio.create_task sẽ làm
                # ui.notify/ui.navigate ném "slot stack is empty" (xem DESIGN.md).
                ui.upload(label="Chọn file Excel", auto_upload=True,
                          on_upload=do_upload).props('accept=".xlsx" flat').classes("w-full")
                ui.button("Đóng", on_click=up_dialog.close).props("flat").classes(
                    "text-gray-600 self-end")

        # ── Lưới bộ câu hỏi ───────────────────────────────────────────────────
        loading = ui.row().classes("w-full justify-center items-center py-8")
        with loading:
            ui.spinner(size="2em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
        grid = ui.column().classes("w-full")

        def _render(data: list[dict]):
            grid.clear()
            with grid:
                if not data:
                    with ui.column().classes("w-full items-center py-16 gap-2"):
                        ui.icon("school").classes("text-6xl text-gray-300")
                        ui.label("Chưa có bộ câu hỏi nào").classes("text-gray-500")
                        if can_upload:
                            ui.label("Bấm «Tải bộ câu hỏi lên» để nhập từ file Excel"
                                     ).classes("text-sm text-gray-400")
                        else:
                            ui.label("Liên hệ quản trị viên để tải bộ câu hỏi lên"
                                     ).classes("text-sm text-gray-400")
                    return
                with ui.grid().classes("w-full gap-4").style(
                    "grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))"
                ):
                    for s in data:
                        _render_card(s)

        def _render_card(s: dict):
            with ui.card().classes(
                "qz-card w-full p-0 overflow-hidden rounded-xl shadow-sm bg-white"
            ):
                with ui.element("div").classes("qz-band w-full"):
                    ui.label(s["name"]).classes("qz-name")
                with ui.column().classes("w-full p-3 gap-2"):
                    with ui.row().classes("items-center gap-3 text-xs text-gray-600"):
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("help_outline").classes("text-sm")
                            ui.label(f"{s['question_count']} câu")
                        with ui.row().classes("items-center gap-1"):
                            ui.icon("person").classes("text-sm")
                            ui.label(s.get("created_by_name") or "—")
                    if s.get("description"):
                        ui.label(s["description"]).classes(
                            "text-xs text-gray-500 line-clamp-2")
                    with ui.row().classes("items-center gap-2"):
                        if s.get("my_attempts"):
                            ui.label(f"Đã làm {s['my_attempts']} lần").classes(
                                "text-xs px-2 py-0.5 rounded border bg-gray-100 "
                                "text-gray-600 border-gray-300")
                        if s.get("my_best_score") is not None:
                            best = float(s["my_best_score"])
                            tone = ("bg-green-100 text-green-700 border-green-300"
                                    if best >= 80 else
                                    "bg-orange-100 text-orange-700 border-orange-300")
                            ui.label(f"Tốt nhất {best:.1f}%").classes(
                                f"text-xs px-2 py-0.5 rounded border {tone}")
                    with ui.row().classes("w-full items-center gap-1 mt-1"):
                        ui.button("Bắt đầu", icon="play_arrow",
                                  on_click=lambda _=None, s=s: open_cfg(s)).props(
                            "dense no-caps").classes("bg-red-700 text-white px-3 flex-grow")
                        ui.button(icon="leaderboard",
                                  on_click=lambda _=None, s=s: open_leaderboard(s)).props(
                            "dense flat round size=sm").classes("text-gray-600").tooltip(
                            "Bảng xếp hạng")
                        if can_upload or can_delete:
                            with ui.button(icon="more_vert").props(
                                "dense flat round size=sm"
                            ).classes("text-gray-600"):
                                with ui.menu():
                                    if can_upload:
                                        ui.menu_item(
                                            "Đổi tên / sửa mô tả",
                                            lambda _=None, s=s: open_rename(s))
                                    if can_delete:
                                        ui.menu_item(
                                            "Xoá bộ câu hỏi",
                                            lambda _=None, s=s: do_delete(s))

        async def load():
            loading.classes(remove="hidden")
            try:
                data = await asyncio.to_thread(api.get, "/api/quiz/sets")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            finally:
                loading.classes(add="hidden")
            sets_cache.clear()
            sets_cache.extend(data)
            total_q = sum(s["question_count"] for s in data)
            count_label.text = f"{len(data)} bộ câu hỏi — tổng {total_q} câu"
            _render(data)

        await load()
