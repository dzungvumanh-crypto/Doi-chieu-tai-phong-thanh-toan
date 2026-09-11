"""Trả lời khảo sát — mở từ khối "Công việc chờ xử lý" hoặc từ /surveys.

KHÔNG kiểm `menu.surveys`: có tên trong danh sách người nhận là trả lời được
(backend tự chặn người ngoài danh sách). Người tạo / người có surveys.view_all
mở được ở chế độ xem trước, không nộp được.
"""
import asyncio

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (_sidebar, _content_area, _require_auth, _handle_api_error,
                             _query_params, _qp_int, _dmy, _iso_tu_dmy)
from frontend.survey_common import fmt_dt, state_chip

_CSS = """<style>
.sv-head { border-top: 8px solid #991b1b; }
.sv-err  { border: 1px solid #dc2626 !important; }
</style>"""

_LY_DO_KHOA = {
    "scheduled": "Khảo sát chưa tới giờ mở — quay lại sau {start}.",
    "expired":   "Khảo sát đã quá hạn, không nhận thêm câu trả lời.",
    "closed":    "Khảo sát đã được người tạo đóng lại.",
    "draft":     "Đây là bản nháp — bạn đang xem trước, không nộp được.",
}


@ui.page("/surveys/fill")
async def survey_fill_page():
    if not _require_auth():
        return
    params = _query_params()
    sid = _qp_int(params, "id")
    # Mở từ nút "Xem trước" của màn soạn thảo
    preview = params.get("from") == "edit"
    if not sid:
        ui.navigate.to("/surveys")
        return

    await _sidebar("surveys")
    ui.add_head_html(_CSS)
    try:
        f = await asyncio.to_thread(api.get, f"/api/surveys/{sid}/form")
    except Exception as e:
        with _content_area():
            if not _handle_api_error(e):
                ui.label("Không mở được khảo sát này.").classes("text-red-600")
        return

    answers: dict[int, object] = {}
    for q in f["questions"]:
        v = f["answers"].get(str(q["id"]))
        if q["qtype"] == "date" and v:
            v = _dmy(v)                           # ô ngày hiển thị dd/mm/yyyy
        answers[q["id"]] = v if v is not None else ([] if q["qtype"] == "multi" else None)

    with _content_area():
        page = ui.column().classes("w-full max-w-3xl mx-auto gap-4 pb-16")

    def _render_form():
        page.clear()
        # Xem trước KHÔNG nộp được: người tạo cũng nằm trong nhóm nhận thì một lần
        # bấm "Gửi" để thử là ghi câu trả lời thật — và câu hỏi bị khoá luôn từ đó.
        can = f["can_submit"] and not preview
        with page:
            if preview:
                ui.button("Quay lại soạn thảo", icon="arrow_back",
                          on_click=lambda: ui.navigate.to(f"/surveys/edit?id={sid}")
                          ).props("flat no-caps").classes("text-red-800 self-start -mb-2")
            with ui.card().classes("sv-head w-full rounded-xl shadow-sm p-6 gap-2"):
                with ui.row().classes("w-full items-start justify-between no-wrap gap-3"):
                    ui.label(f["title"]).classes("text-2xl font-bold text-gray-900 leading-tight")
                    state_chip(f["state"])
                if f.get("description"):
                    ui.label(f["description"]).classes("text-sm text-gray-700 whitespace-pre-line")
                ui.separator()
                with ui.row().classes("gap-4 text-xs text-gray-500 flex-wrap"):
                    ui.label(f"Người tạo: {f.get('created_by_name') or '—'}")
                    ui.label(f"Hạn chót: {fmt_dt(f['deadline'])}").classes("text-red-800 font-medium")
                    if f["is_anonymous"]:
                        ui.label("Ẩn danh — người xem kết quả không thấy tên bạn").classes("text-green-700")
                if any(q["required"] for q in f["questions"]):
                    ui.label("* Câu bắt buộc").classes("text-xs text-red-600")

            # Vì sao không nộp được — nói rõ, đừng chỉ làm mờ nút
            msg = None
            if preview:
                msg = ("Đang xem trước — chọn / gõ thử được nhưng không gửi được. "
                       "Bấm «Quay lại soạn thảo» để sửa tiếp.")
            elif not f["is_recipient"]:
                msg = "Bạn đang xem trước — khảo sát này không gửi tới bạn nên không nộp được."
            elif f["responded"] and not can:
                msg = (f"Bạn đã trả lời lúc {fmt_dt(f['submitted_at'])}."
                       + ("" if f["allow_edit"] else " Khảo sát không cho sửa câu trả lời."))
            elif not can:
                msg = _LY_DO_KHOA.get(f["state"], "").format(start=fmt_dt(f.get("start_at")))
            elif f["responded"]:
                msg = f"Bạn đã trả lời lúc {fmt_dt(f['submitted_at'])} — có thể sửa trước hạn chót."
            if msg:
                ui.label(msg).classes("w-full text-sm text-blue-900 bg-blue-50 border border-blue-200 "
                                      "rounded-lg px-3 py-2")

            cards: dict[int, tuple] = {}
            for i, q in enumerate(f["questions"], start=1):
                # Xem trước vẫn cho thao tác thử trên ô nhập, chỉ không có nút Gửi
                cards[q["id"]] = _q_card(i, q, can or preview)

            if can:
                with ui.row().classes("w-full items-center justify-between"):
                    ui.button("Nộp lại" if f["responded"] else "Gửi", icon="send",
                              on_click=lambda: submit(cards)).classes("bg-red-700 text-white px-6"
                                                                     ).props("no-caps")
                    ui.button("Quay lại", on_click=lambda: ui.navigate.to("/surveys" if api.has_feature(
                        "menu.surveys") else "/home")).props("flat no-caps").classes("text-gray-600")

    def _q_card(i: int, q: dict, can: bool):
        qid, qt = q["id"], q["qtype"]
        with ui.card().classes("w-full rounded-xl shadow-sm p-5 gap-2") as card:
            with ui.row().classes("gap-1 items-baseline no-wrap"):
                ui.label(f"{i}. {q['title']}").classes("text-base font-medium text-gray-900")
                if q["required"]:
                    ui.label("*").classes("text-red-600 font-bold")
            if q.get("description"):
                ui.label(q["description"]).classes("text-xs text-gray-500 whitespace-pre-line")

            def _set(v, qid=qid):
                answers[qid] = v

            opts = {j: o for j, o in enumerate(q["options"])}
            w = None
            if qt == "short_text":
                w = ui.input("Câu trả lời của bạn", value=answers[qid] or "",
                             on_change=lambda e: _set(e.value)).props("dense").classes("w-full max-w-md")
            elif qt == "paragraph":
                w = ui.textarea("Câu trả lời của bạn", value=answers[qid] or "",
                                on_change=lambda e: _set(e.value)).props("autogrow").classes("w-full")
            elif qt == "single":
                w = ui.radio(opts, value=answers[qid], on_change=lambda e: _set(e.value))
            elif qt == "dropdown":
                w = ui.select(opts, value=answers[qid], label="Chọn",
                              on_change=lambda e: _set(e.value)).props(
                    "outlined dense clearable").classes("w-72")
            elif qt == "multi":
                chosen = set(answers[qid] or [])

                def _tick(j, val, qid=qid, chosen=chosen):
                    (chosen.add if val else chosen.discard)(j)
                    answers[qid] = sorted(chosen)
                with ui.column().classes("gap-0"):
                    boxes = [ui.checkbox(o, value=j in chosen, on_change=lambda e, j=j: _tick(j, e.value))
                             for j, o in opts.items()]
                if not can:
                    for b in boxes:
                        b.disable()
            elif qt == "scale":
                with ui.row().classes("items-end gap-3 no-wrap overflow-x-auto"):
                    if q.get("scale_min_label"):
                        ui.label(q["scale_min_label"]).classes("text-xs text-gray-600 pb-2 max-w-[8rem]")
                    w = ui.radio({n: str(n) for n in range(q["scale_min"], q["scale_max"] + 1)},
                                 value=answers[qid], on_change=lambda e: _set(e.value)).props("inline")
                    if q.get("scale_max_label"):
                        ui.label(q["scale_max_label"]).classes("text-xs text-gray-600 pb-2 max-w-[8rem]")
            elif qt == "date":
                with ui.input("dd/mm/yyyy", value=answers[qid] or "",
                              on_change=lambda e: _set(e.value)).props("dense outlined clearable"
                                                                        ).classes("w-44") as w:
                    with w.add_slot("append"):
                        ui.icon("edit_calendar").on("click", lambda: m.open()).classes("cursor-pointer")
                    with ui.menu() as m:
                        kw = {"value": answers[qid]} if answers[qid] else {}
                        ui.date(mask="DD/MM/YYYY", on_change=m.close, **kw).bind_value(w)

            # Chọn một mà không bắt buộc: phải có đường bỏ chọn, radio không tự bỏ được
            if can and qt in ("single", "scale") and not q["required"]:
                ui.button("Xoá lựa chọn", on_click=lambda w=w, qid=qid: (w.set_value(None), _set(None, qid))
                          ).props("flat dense no-caps size=sm").classes("text-gray-500 self-end")
            if w is not None and not can:
                w.disable()
            err = ui.label("Đây là câu bắt buộc").classes("text-xs text-red-600")
            err.set_visibility(False)
        return card, err

    def _rong(v) -> bool:
        return v is None or v == "" or v == []

    async def submit(cards: dict):
        # ── Kiểm câu bắt buộc ngay trên máy — backend vẫn kiểm lại ──
        missing = []
        for q in f["questions"]:
            card, err = cards[q["id"]]
            bad = q["required"] and _rong(answers[q["id"]])
            err.set_visibility(bad)
            (card.classes(add="sv-err") if bad else card.classes(remove="sv-err"))
            if bad:
                missing.append(q)
        if missing:
            ui.notify(f"Còn {len(missing)} câu bắt buộc chưa trả lời", type="warning")
            return

        body = []
        for q in f["questions"]:
            v = answers[q["id"]]
            if q["qtype"] == "date" and v:
                v = _iso_tu_dmy(v)
            body.append({"question_id": q["id"], "value": v})
        try:
            await asyncio.to_thread(api.post, f"/api/surveys/{sid}/responses", {"answers": body})
        except Exception as e:
            _handle_api_error(e)
            return
        _render_done()

    def _render_done():
        page.clear()
        with page:
            with ui.card().classes("sv-head w-full rounded-xl shadow-sm p-8 items-center gap-3"):
                ui.icon("task_alt").classes("text-6xl text-green-600")
                ui.label(f["title"]).classes("text-xl font-bold text-gray-900 text-center")
                ui.label("Đã ghi nhận câu trả lời của bạn. Cảm ơn!").classes("text-gray-600")
                if f["allow_edit"]:
                    ui.label(f"Bạn có thể sửa câu trả lời trước {fmt_dt(f['deadline'])}.").classes(
                        "text-xs text-gray-500")
                with ui.row().classes("gap-2 mt-2"):
                    if f["allow_edit"]:
                        ui.button("Sửa câu trả lời", icon="edit",
                                  on_click=lambda: ui.navigate.to(f"/surveys/fill?id={sid}")
                                  ).props("outline no-caps color=red-8")
                    ui.button("Về trang chủ", icon="home", on_click=lambda: ui.navigate.to("/home")
                              ).classes("bg-red-700 text-white").props("no-caps")

    _render_form()
