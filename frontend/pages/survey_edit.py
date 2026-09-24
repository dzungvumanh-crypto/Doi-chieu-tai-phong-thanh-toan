"""Soạn khảo sát — tiêu đề, người nhận, thời hạn, danh sách câu hỏi kiểu Google Forms.

Trạng thái soạn thảo nằm trong `qs` (list dict của client này), không trong DOM.
Ô nhập gắn thẳng vào dict bằng bind_value nên gõ chữ không phải vẽ lại; chỉ khi
đổi CẤU TRÚC (thêm/xoá/đổi chỗ câu, đổi loại câu, thêm/xoá lựa chọn) mới vẽ lại
cả danh sách — vẽ lại khi đang gõ là ô mất con trỏ giữa chừng.
"""
import asyncio
import copy

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (_sidebar, _content_area, _page_header, _require_auth,
                             _handle_api_error, _query_params, _qp_int)
from frontend.survey_common import CHOICE_TYPES, QTYPE_ICONS, QTYPE_LABELS, NgayGio, state_chip

_CSS = """<style>
.sv-q { border-left: 4px solid transparent; transition: border-color .12s ease; }
.sv-q:focus-within { border-left-color: #b91c1c; }
.sv-head { border-top: 8px solid #991b1b; }
/* Thanh thao tác cố định đáy — mép trái bám theo sidebar (mở 16rem / thu gọn 4.5rem) */
.sv-bar { left: 16rem; transition: left .2s ease; }
body.sb-collapsed .sv-bar { left: 4.5rem; }
</style>"""


def _q_moi(qtype: str = "single") -> dict:
    return {"qtype": qtype, "title": "", "description": "", "required": False,
            "options": [{"text": "Lựa chọn 1"}, {"text": "Lựa chọn 2"}] if qtype in CHOICE_TYPES else [],
            "scale_min": 1, "scale_max": 5, "scale_min_label": "", "scale_max_label": ""}


def _tu_api(q: dict) -> dict:
    d = {k: q.get(k) for k in ("qtype", "title", "description", "required",
                               "scale_min", "scale_max", "scale_min_label", "scale_max_label")}
    d["description"] = d["description"] or ""
    d["scale_min_label"] = d["scale_min_label"] or ""
    d["scale_max_label"] = d["scale_max_label"] or ""
    d["options"] = [{"text": o} for o in q.get("options") or []]
    return d


def _ra_api(q: dict) -> dict:
    d = {k: q[k] for k in ("qtype", "title", "description", "required",
                           "scale_min", "scale_max", "scale_min_label", "scale_max_label")}
    d["options"] = [o["text"] for o in q["options"]] if q["qtype"] in CHOICE_TYPES else []
    return d


@ui.page("/surveys/edit")
async def survey_edit_page():
    if not _require_auth():
        return
    if not api.has_feature("surveys.create"):
        ui.navigate.to("/surveys")
        return

    sid = _qp_int(_query_params(), "id")
    await _sidebar("surveys")
    ui.add_head_html(_CSS)

    try:
        groups = await asyncio.to_thread(api.get, "/api/surveys/groups")
        data = await asyncio.to_thread(api.get, f"/api/surveys/{sid}") if sid else None
    except Exception as e:
        with _content_area():
            if not _handle_api_error(e):
                ui.label("Không tải được khảo sát.").classes("text-red-600")
        return
    if data and not data.get("can_edit"):
        ui.navigate.to("/surveys")
        return

    st = {"id": sid, "status": (data or {}).get("status", "draft"),
          "state": (data or {}).get("state", "draft"), "locked": bool((data or {}).get("locked"))}
    meta = {"title": (data or {}).get("title", ""), "description": (data or {}).get("description") or "",
            "is_anonymous": bool((data or {}).get("is_anonymous")),
            "allow_edit": bool((data or {}).get("allow_edit"))}
    qs: list[dict] = [_tu_api(q) for q in (data or {}).get("questions", [])] or [_q_moi()]
    group_opts = {g["id"]: f"{g['name']} ({g['member_count']} người)" for g in groups}

    with _content_area():
        _page_header("Sửa khảo sát" if sid else "Tạo khảo sát",
                     "Soạn câu hỏi, chọn nhóm nhận và đặt hạn chót")

        with ui.column().classes("w-full max-w-4xl gap-4 pb-24"):
            # ── Tiêu đề ──────────────────────────────────────────────────────
            with ui.card().classes("sv-head w-full rounded-xl shadow-sm p-5 gap-2"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Thông tin chung").classes("text-xs uppercase tracking-wide text-gray-500")
                    state_box = ui.row()
                    with state_box:
                        state_chip(st["state"])
                ui.input("Tên khảo sát *").bind_value(meta, "title").props(
                    "outlined").classes("w-full text-lg")
                ui.textarea("Mô tả / hướng dẫn").bind_value(meta, "description").props(
                    "outlined autogrow").classes("w-full")

            # ── Người nhận & thời hạn ────────────────────────────────────────
            with ui.card().classes("w-full rounded-xl shadow-sm p-5 gap-3"):
                ui.label("Người nhận & thời hạn").classes("font-semibold text-red-900")
                sel_groups = ui.select(group_opts, multiple=True, label="Gửi tới nhóm user *",
                                       value=[g for g in (data or {}).get("group_ids", []) if g in group_opts]
                                       ).props("outlined use-chips").classes("w-full")
                if not group_opts:
                    ui.label("Chưa có nhóm user nào đang hoạt động — nhờ quản trị viên tạo nhóm "
                             "ở màn Phân quyền chức năng.").classes("text-xs text-amber-800")
                ui.label("Danh sách người nhận được chốt lúc phát hành. Sửa nhóm khi khảo sát đang "
                         "mở thì người mới được thêm, người chưa trả lời mà không còn trong nhóm "
                         "sẽ bị bỏ ra.").classes("text-xs text-gray-500 -mt-1")
                with ui.row().classes("w-full gap-8 flex-wrap"):
                    with ui.column().classes("gap-1"):
                        ui.label("Bắt đầu nhận trả lời (bỏ trống = ngay khi phát hành)").classes(
                            "text-xs text-gray-600")
                        f_start = NgayGio("Ngày bắt đầu", (data or {}).get("start_at"), "08:00")
                    with ui.column().classes("gap-1"):
                        ui.label("Hạn chót *").classes("text-xs text-gray-600")
                        f_deadline = NgayGio("Ngày hết hạn", (data or {}).get("deadline"), "17:00")
                with ui.row().classes("gap-6 flex-wrap"):
                    sw_anon = ui.switch("Ẩn danh").bind_value(meta, "is_anonymous")
                    ui.switch("Cho phép sửa câu trả lời trước hạn chót").bind_value(meta, "allow_edit")
                ui.label("Ẩn danh: người xem kết quả không thấy tên và giờ nộp của từng câu trả lời "
                         "(vẫn thấy ai đã/chưa trả lời để nhắc). Hệ thống vẫn lưu ai trả lời để "
                         "chặn trả lời hai lần.").classes("text-xs text-gray-500")
                # Đã phát hành ẩn danh thì backend chặn tắt (409) — khoá luôn ở đây
                if st["locked"] or (st["status"] != "draft" and meta["is_anonymous"]):
                    sw_anon.disable()

            # ── Câu hỏi ──────────────────────────────────────────────────────
            if st["locked"]:
                ui.label("Đã có người trả lời nên câu hỏi bị khoá — sửa hoặc thêm lựa chọn lúc này "
                         "làm câu trả lời cũ trỏ sang ý khác. Vẫn đổi được tên, mô tả, nhóm nhận, "
                         "thời hạn.").classes(
                    "w-full text-sm text-amber-900 bg-amber-50 border border-amber-300 rounded-lg px-3 py-2")
            q_box = ui.column().classes("w-full gap-3")

            def render():
                q_box.clear()
                with q_box:
                    for i, q in enumerate(qs):
                        _q_card(i, q)
                    if not st["locked"]:
                        with ui.row().classes("w-full justify-center"):
                            with ui.button("Thêm câu hỏi", icon="add_circle").props(
                                    "outline no-caps color=red-8"):
                                with ui.menu():
                                    for k, lbl in QTYPE_LABELS.items():
                                        ui.menu_item(lbl, on_click=lambda k=k: (qs.append(_q_moi(k)), render()))

            def _move(i: int, d: int):
                j = i + d
                if 0 <= j < len(qs):
                    qs[i], qs[j] = qs[j], qs[i]
                    render()

            def _dup(i: int):
                qs.insert(i + 1, copy.deepcopy(qs[i]))
                render()

            def _del(i: int):
                qs.pop(i)
                render()

            def _doi_loai(q: dict, new: str):
                if new in CHOICE_TYPES and not q["options"]:
                    q["options"] = [{"text": "Lựa chọn 1"}, {"text": "Lựa chọn 2"}]
                q["qtype"] = new
                render()

            def _q_card(i: int, q: dict):
                lk = st["locked"]
                with ui.card().classes("sv-q w-full rounded-xl shadow-sm p-5 gap-2"):
                    with ui.row().classes("w-full items-start gap-3 no-wrap"):
                        ui.label(f"{i + 1}.").classes("text-lg font-semibold text-red-900 pt-2")
                        t = ui.input("Câu hỏi *").bind_value(q, "title").props("outlined").classes("flex-1")
                        sel = ui.select(QTYPE_LABELS, value=q["qtype"],
                                        on_change=lambda e, q=q: _doi_loai(q, e.value)
                                        ).props("outlined dense options-dense").classes("w-60")
                        with sel.add_slot("prepend"):
                            ui.icon(QTYPE_ICONS[q["qtype"]]).classes("text-red-800")
                        if lk:
                            t.disable()
                            sel.disable()
                    ui.input("Mô tả thêm (tuỳ chọn)").bind_value(q, "description").props(
                        "dense borderless").classes("w-full text-sm pl-7")

                    with ui.column().classes("w-full pl-7 gap-1"):
                        if q["qtype"] in CHOICE_TYPES:
                            _options(q, lk)
                        elif q["qtype"] == "scale":
                            with ui.row().classes("items-center gap-3"):
                                a = ui.select({0: "0", 1: "1"}, value=q["scale_min"]).bind_value(
                                    q, "scale_min").props("dense outlined").classes("w-20")
                                ui.label("đến")
                                b = ui.select({n: str(n) for n in range(2, 11)}, value=q["scale_max"]
                                              ).bind_value(q, "scale_max").props("dense outlined").classes("w-20")
                                if lk:
                                    a.disable()
                                    b.disable()
                            with ui.row().classes("gap-3"):
                                ui.input("Nhãn điểm thấp nhất (VD: Rất không hài lòng)").bind_value(
                                    q, "scale_min_label").props("dense outlined").classes("w-72")
                                ui.input("Nhãn điểm cao nhất (VD: Rất hài lòng)").bind_value(
                                    q, "scale_max_label").props("dense outlined").classes("w-72")
                        else:
                            hint = {"short_text": "Người trả lời gõ một dòng chữ",
                                    "paragraph": "Người trả lời gõ đoạn văn dài",
                                    "date": "Người trả lời chọn một ngày"}[q["qtype"]]
                            ui.label(hint).classes("text-sm text-gray-400 italic border-b border-dashed "
                                                   "border-gray-300 pb-1 w-80")

                    ui.separator().classes("mt-2")
                    with ui.row().classes("w-full items-center justify-end gap-1"):
                        if not lk:
                            ui.button(icon="arrow_upward", on_click=lambda i=i: _move(i, -1)).props(
                                "flat dense round").tooltip("Lên trên").set_enabled(i > 0)
                            ui.button(icon="arrow_downward", on_click=lambda i=i: _move(i, 1)).props(
                                "flat dense round").tooltip("Xuống dưới").set_enabled(i < len(qs) - 1)
                            ui.button(icon="content_copy", on_click=lambda i=i: _dup(i)).props(
                                "flat dense round").tooltip("Nhân bản")
                            ui.button(icon="delete", on_click=lambda i=i: _del(i)).props(
                                "flat dense round").classes("text-red-700").tooltip("Xoá câu")
                            ui.separator().props("vertical").classes("mx-2")
                        sw = ui.switch("Bắt buộc").bind_value(q, "required")
                        if lk:
                            sw.disable()

            def _options(q: dict, lk: bool):
                icon = {"single": "radio_button_unchecked", "multi": "check_box_outline_blank",
                        "dropdown": "chevron_right"}[q["qtype"]]
                for j, o in enumerate(q["options"]):
                    with ui.row().classes("items-center gap-2 no-wrap w-full"):
                        ui.icon(icon).classes("text-gray-400")
                        inp = ui.input().bind_value(o, "text").props("dense borderless").classes("flex-1")
                        if lk:
                            inp.disable()
                        elif len(q["options"]) > 2:
                            ui.button(icon="close", on_click=lambda q=q, j=j: (q["options"].pop(j), render())
                                      ).props("flat dense round size=sm").classes("text-gray-500")
                if not lk:
                    ui.button("Thêm lựa chọn", icon="add",
                              on_click=lambda q=q: (q["options"].append(
                                  {"text": f"Lựa chọn {len(q['options']) + 1}"}), render())
                              ).props("flat dense no-caps").classes("text-red-800 self-start")

            render()

        # ── Thanh thao tác ───────────────────────────────────────────────────
        def _body() -> dict:
            return {
                "title": meta["title"], "description": meta["description"] or None,
                "is_anonymous": meta["is_anonymous"], "allow_edit": meta["allow_edit"],
                "start_at": f_start.get(), "deadline": f_deadline.get(),
                "group_ids": list(sel_groups.value or []),
                "questions": [_ra_api(q) for q in qs],
            }

        async def save(notify: bool = True) -> bool:
            if not (meta["title"] or "").strip():
                ui.notify("Vui lòng nhập tên khảo sát", type="warning")
                return False
            try:
                if st["id"]:
                    res = await asyncio.to_thread(api.put, f"/api/surveys/{st['id']}", _body())
                else:
                    res = await asyncio.to_thread(api.post, "/api/surveys", _body())
                    st["id"] = res["id"]
                    # F5 sau lần lưu đầu phải mở lại đúng bản nháp, không phải form trắng
                    ui.run_javascript(f"history.replaceState(null, '', '/surveys/edit?id={st['id']}')")
            except Exception as e:
                _handle_api_error(e)
                return False
            if notify:
                extra = ""
                if res.get("added") or res.get("removed"):
                    extra = f" — người nhận +{res.get('added', 0)} / -{res.get('removed', 0)}"
                ui.notify("Đã lưu" + extra, type="positive")
            return True

        async def publish():
            if not await save(notify=False):
                return
            try:
                res = await asyncio.to_thread(api.post, f"/api/surveys/{st['id']}/publish")
            except Exception as e:
                _handle_api_error(e)
                return
            ui.notify(f"Đã phát hành tới {res['recipient_count']} người", type="positive")
            ui.navigate.to("/surveys")

        async def preview():
            if await save(notify=False):
                # from=edit: trang trả lời hiện mũi tên quay về đúng màn soạn này
                ui.navigate.to(f"/surveys/fill?id={st['id']}&from=edit")

        async def _save_click():
            await save()

        with ui.row().classes("sv-bar fixed bottom-0 right-0 z-[100] bg-white/95 border-t "
                              "border-gray-200 px-6 py-3 gap-2 justify-end shadow-lg"):
            ui.button("Quay lại", icon="arrow_back", on_click=lambda: ui.navigate.to("/surveys")
                      ).props("flat no-caps").classes("text-gray-600 mr-auto")
            ui.button("Xem trước", icon="visibility", on_click=preview).props(
                "outline no-caps color=red-8")
            ui.button("Lưu", icon="save", on_click=_save_click).props("outline no-caps color=red-8")
            if st["status"] != "published":
                ui.button("Lưu & phát hành" if st["status"] == "draft" else "Lưu & mở lại",
                          icon="send", on_click=publish).classes("bg-red-700 text-white").props("no-caps")
