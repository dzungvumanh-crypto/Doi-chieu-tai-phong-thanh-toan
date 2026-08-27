"""Màn làm bài trắc nghiệm — toàn màn hình, không sidebar.

Tách khỏi `/quiz` vì làm bài cần cả bề ngang: giữ sidebar 16rem thì ô đáp án bị
bóp lại còn hai phần ba, chữ dài phải xuống 4-5 dòng.

Trạng thái bài làm nằm trong `st` (biến của một client), KHÔNG nằm trong DOM:
mỗi lần sang câu là clear và vẽ lại, đọc trạng thái từ DOM sẽ mất sạch.
Câu trả lời chỉ gửi lên máy chủ MỘT lần lúc nộp bài — mạng chập chờn giữa chừng
không làm mất câu đã chọn, đổi lại là đóng trình duyệt giữa bài thì mất cả bài
(lượt đó nằm lại ở trạng thái `in_progress`, không tính điểm).
"""
import asyncio
import time

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _require_auth, _handle_api_error, _query_params, _qp_int

# Bốn ô đáp án theo vị trí HIỂN THỊ — màu + hình khối để nhận ra bằng mắt,
# không phải đọc chữ A/B/C/D. Câu 3 lựa chọn chỉ dùng 3 ô đầu.
_OPT_STYLE = [
    ("#E21B3C", "▲"),
    ("#1368CE", "◆"),
    ("#D89E00", "●"),
    ("#26890C", "■"),
]

_CSS = """<style>
body { background: #1a1330; }
.qp-wrap { min-height: 100vh; display: flex; flex-direction: column;
           background: radial-gradient(1200px 600px at 20% -10%, #4c1d95 0%, #1a1330 55%,
                                       #120d22 100%); }
.qp-bar { background: rgba(0,0,0,.28); backdrop-filter: blur(4px); }
.qp-question { background: #fff; border-radius: 14px; padding: 22px 26px;
               box-shadow: 0 8px 28px rgba(0,0,0,.25); }
/* Ô đáp án dựng bằng q-btn: Quasar canh giữa và viết hoa chữ trong
   `.q-btn__content`, nên phải chỉnh cả lớp trong, không chỉ lớp ngoài. */
.qp-opt { border-radius: 12px !important; color: #fff !important;
          padding: 14px 18px !important; min-height: 68px; width: 100%;
          text-transform: none !important; letter-spacing: 0 !important;
          box-shadow: 0 4px 0 rgba(0,0,0,.22) !important;
          transition: transform .1s ease, filter .1s ease; }
.qp-opt:hover { transform: translateY(-2px); filter: brightness(1.08); }
.qp-opt .q-btn__content { width: 100%; flex-wrap: nowrap; justify-content: flex-start;
                          align-items: center; gap: 14px; text-align: left; }
.qp-opt .sym { font-size: 20px; line-height: 1; opacity: .9; flex-shrink: 0; }
.qp-opt .txt { flex: 1; font-size: 15px; font-weight: 600; line-height: 1.35;
               white-space: normal; }
.qp-dim { opacity: .35; }
.qp-ring { outline: 4px solid #fff; outline-offset: 2px; }
.qp-badge { font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
            background: rgba(255,255,255,.9); color: #111; flex-shrink: 0; }
/* Màn xem lại — bảng đáp án nhỏ gọn, không dùng ô màu lớn */
.qp-rev-opt { border-radius: 8px; padding: 7px 12px; font-size: 13px;
              border: 1px solid #E5E7EB; background: #fff; }
.qp-rev-ok  { background: #DCFCE7; border-color: #16A34A; }
.qp-rev-bad { background: #FEE2E2; border-color: #DC2626; }
</style>"""


def _fmt_clock(sec: int) -> str:
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def _fmt_ms(ms) -> str:
    if not ms:
        return "0 giây"
    total = int(ms / 1000)
    m, s = divmod(total, 60)
    return f"{m} phút {s:02d} giây" if m else f"{s} giây"


@ui.page("/quiz/play")
async def quiz_play_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.quiz"):
        ui.navigate.to("/home")
        return

    attempt_id = _qp_int(_query_params(), "attempt")
    if not attempt_id:
        ui.navigate.to("/quiz")
        return

    ui.add_head_html(_CSS)
    # Khung .nicegui-content mặc định có padding + gap; để nguyên thì nền tím
    # hở ra một viền trắng quanh trang.
    ui.query(".nicegui-content").classes("p-0 gap-0")

    try:
        att = await asyncio.to_thread(api.get, f"/api/quiz/attempts/{attempt_id}")
    except Exception as e:
        if _handle_api_error(e):
            return
        ui.notify(str(e), type="negative", timeout=6000)
        ui.navigate.to("/quiz")
        return

    cfg = att["settings"]
    questions = att["questions"]
    total = len(questions)

    st = {
        "idx": 0,
        "answers": {},            # item_id → {"chosen_no": int|None, "time_ms": int}
        "locked": False,          # đã chốt câu này, chỉ còn nút sang câu kế
        "q_left": 0,
        "t_left": (cfg.get("total_minutes") or 0) * 60,
        "q_t0": time.monotonic(),
        "t0": time.monotonic(),
        "done": att["status"] == "finished",
        "submitting": False,
    }

    root = ui.column().classes("qp-wrap w-full gap-0")

    # ── Kết quả & xem lại ─────────────────────────────────────────────────────
    def _render_result(res: dict):
        root.clear()
        with root:
            with ui.column().classes("w-full items-center px-4 py-8 gap-5"):
                score = float(res.get("score") or 0)
                tone = "#16A34A" if score >= 80 else ("#D97706" if score >= 50 else "#DC2626")
                with ui.column().classes("items-center gap-1"):
                    ui.label(res["set_name"]).classes("text-white/70 text-sm")
                    ui.label(
                        "Hoàn thành bài thi thử" if res["mode"] == "exam"
                        else "Hoàn thành buổi ôn tập"
                    ).classes("text-white text-2xl font-bold")
                ui.html(
                    f'<div style="width:170px;height:170px;border-radius:50%;'
                    f'display:flex;flex-direction:column;align-items:center;'
                    f'justify-content:center;background:#fff;'
                    f'box-shadow:0 0 0 10px {tone}33, 0 8px 30px rgba(0,0,0,.3)">'
                    f'<div style="font-size:44px;font-weight:800;color:{tone};'
                    f'line-height:1">{score:.1f}%</div>'
                    f'<div style="font-size:13px;color:#6B7280;margin-top:4px">'
                    f'{res["correct_count"]}/{res["total_questions"]} câu đúng</div></div>'
                )

                with ui.row().classes("gap-3 flex-wrap justify-center"):
                    for label, value, color in (
                        ("Câu đúng", res["correct_count"], "#16A34A"),
                        ("Câu sai", res["wrong_count"], "#DC2626"),
                        ("Bỏ trống", res["skipped_count"], "#6B7280"),
                        ("Thời gian", _fmt_ms(res.get("duration_ms")), "#4C1D95"),
                    ):
                        with ui.card().classes("px-5 py-3 rounded-xl items-center gap-0"):
                            ui.label(str(value)).style(
                                f"font-size:20px;font-weight:700;color:{color}")
                            ui.label(label).classes("text-xs text-gray-500")

                with ui.row().classes("gap-2 mt-1"):
                    ui.button("Về danh sách bộ câu hỏi", icon="grid_view",
                              on_click=lambda: ui.navigate.to("/quiz")).props(
                        "no-caps").classes("bg-white text-red-900")

                # ── Xem lại từng câu ──
                ui.label("Xem lại bài làm").classes("text-white text-lg font-semibold mt-3")
                with ui.column().classes("w-full max-w-4xl gap-3"):
                    for it in res.get("review", []):
                        _render_review_item(it)

    def _render_review_item(it: dict):
        if it["is_correct"]:
            chip, chip_cls = "Đúng", "bg-green-100 text-green-700 border-green-300"
        elif it["chosen_no"] is None:
            chip, chip_cls = "Bỏ trống", "bg-gray-100 text-gray-600 border-gray-300"
        else:
            chip, chip_cls = "Sai", "bg-red-100 text-red-700 border-red-300"
        with ui.card().classes("w-full rounded-xl p-4 gap-2"):
            with ui.row().classes("w-full items-start gap-2 flex-nowrap"):
                ui.label(f"Câu {it['order_no']}").classes(
                    "text-xs font-bold text-gray-500 mt-1 shrink-0")
                ui.label(it["content"]).classes("text-sm font-medium text-gray-900 flex-grow")
                ui.label(chip).classes(
                    f"text-xs font-medium px-2 py-0.5 rounded border shrink-0 {chip_cls}")
            for opt in it["options"]:
                cls = "qp-rev-opt w-full"
                if opt["no"] == it["correct_no"]:
                    cls += " qp-rev-ok"
                elif opt["no"] == it["chosen_no"]:
                    cls += " qp-rev-bad"
                with ui.row().classes(cls + " items-center gap-2 flex-nowrap"):
                    if opt["no"] == it["correct_no"]:
                        ui.icon("check_circle").classes("text-green-700 text-base shrink-0")
                    elif opt["no"] == it["chosen_no"]:
                        ui.icon("cancel").classes("text-red-600 text-base shrink-0")
                    else:
                        ui.icon("radio_button_unchecked").classes(
                            "text-gray-300 text-base shrink-0")
                    ui.label(opt["text"]).classes("text-gray-800")

    async def _load_result():
        try:
            res = await asyncio.to_thread(api.get, f"/api/quiz/attempts/{attempt_id}/result")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative", timeout=6000)
            ui.navigate.to("/quiz")
            return
        _render_result(res)

    # Vào bằng nút "xem lại" ở lịch sử → bài đã nộp, hiện thẳng kết quả
    if st["done"]:
        await _load_result()
        return

    # ── Nộp bài ───────────────────────────────────────────────────────────────
    async def submit(_=None):
        if st["submitting"]:
            return                      # chặn bấm hai lần / hết giờ trùng lúc bấm nộp
        st["submitting"] = True
        st["done"] = True
        timer.active = False
        body = {
            "answers": [
                {"item_id": iid, "chosen_no": a["chosen_no"], "time_ms": a["time_ms"]}
                for iid, a in st["answers"].items()
            ],
            "duration_ms": int((time.monotonic() - st["t0"]) * 1000),
        }
        try:
            res = await asyncio.to_thread(
                api.post, f"/api/quiz/attempts/{attempt_id}/submit", body)
        except Exception as e:
            st["submitting"] = False
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative", timeout=8000)
            return
        _render_result(res)

    async def confirm_exit():
        with ui.dialog() as d, ui.card():
            ui.label("Thoát khi chưa nộp bài?").classes("font-semibold")
            ui.label("Bài đang làm sẽ không được chấm điểm.").classes(
                "text-sm text-gray-600")
            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Ở lại", on_click=lambda: d.submit(False)).props("flat")
                ui.button("Thoát", on_click=lambda: d.submit(True)).classes(
                    "bg-red-700 text-white")
        if await d:
            timer.active = False
            ui.navigate.to("/quiz")

    # ── Khung cố định: tiến trình + đồng hồ ───────────────────────────────────
    with root:
        with ui.row().classes(
            "qp-bar w-full items-center gap-3 px-5 py-3 flex-nowrap"
        ):
            ui.label(att["set_name"]).classes(
                "text-white font-semibold text-sm truncate max-w-xs")
            ui.label("Thi thử" if cfg["mode"] == "exam" else "Ôn tập").classes(
                "qp-badge")
            ui.space()
            q_clock = ui.label("").classes("text-white font-mono text-sm")
            t_clock = ui.label("").classes("text-white/70 font-mono text-sm")
            ui.button(icon="close", on_click=confirm_exit).props(
                "dense flat round").classes("text-white")

        progress = ui.linear_progress(value=0, show_value=False, size="6px").props(
            "color=amber track-color=transparent").classes("w-full")
        counter = ui.label("").classes("text-white/70 text-xs px-5 pt-2")
        body = ui.column().classes("w-full flex-grow items-center px-4 pb-8 pt-2 gap-4")

    # ── Vẽ một câu ────────────────────────────────────────────────────────────
    def render():
        q = questions[st["idx"]]
        st["locked"] = False
        st["q_t0"] = time.monotonic()
        st["q_left"] = cfg.get("seconds_per_question") or 0
        counter.text = f"Câu {st['idx'] + 1} / {total}"
        progress.set_value(st["idx"] / total)
        _tick_labels()

        body.clear()
        with body:
            with ui.column().classes("w-full max-w-4xl gap-4"):
                with ui.element("div").classes("qp-question w-full"):
                    ui.label(q["content"]).classes(
                        "text-lg font-semibold text-gray-900 leading-snug")
                opts_box = ui.grid().classes("w-full gap-3").style(
                    "grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))")
                foot = ui.row().classes("w-full items-center gap-2 pt-1")

        def _paint():
            """Vẽ lại 4 ô đáp án theo trạng thái hiện tại của câu."""
            opts_box.clear()
            chosen = (st["answers"].get(q["item_id"]) or {}).get("chosen_no")
            correct = q.get("correct_no")          # None ở chế độ thi thử
            reveal = st["locked"] and cfg.get("instant_feedback") and correct is not None
            with opts_box:
                for pos, opt in enumerate(q["options"]):
                    color, sym = _OPT_STYLE[pos % 4]
                    cls = "qp-opt"
                    if reveal:
                        if opt["no"] == correct:
                            color = "#16A34A"
                        elif opt["no"] == chosen:
                            color = "#9F1239"
                        else:
                            cls += " qp-dim"
                    elif chosen is not None and opt["no"] == chosen:
                        cls += " qp-ring"
                    btn = ui.button().props("unelevated no-caps").classes(cls).style(
                        f"background:{color} !important")
                    with btn:
                        ui.html(f'<span class="sym">{sym}</span>'
                                f'<span class="txt">{opt["text"]}</span>')
                    if st["locked"]:
                        btn.props("disable")
                    else:
                        btn.on("click", lambda _=None, n=opt["no"]: choose(n))

        def _paint_foot():
            foot.clear()
            last = st["idx"] >= total - 1
            with foot:
                answered = (st["answers"].get(q["item_id"]) or {}).get("chosen_no") is not None
                if st["locked"] and cfg.get("instant_feedback"):
                    correct = q.get("correct_no")
                    chosen = (st["answers"].get(q["item_id"]) or {}).get("chosen_no")
                    if chosen == correct:
                        ui.label("Chính xác!").classes(
                            "text-green-300 font-semibold text-sm")
                    else:
                        ui.label("Chưa đúng — đáp án đúng đã tô xanh").classes(
                            "text-amber-300 font-semibold text-sm")
                ui.space()
                if not st["locked"] and not answered:
                    ui.button("Bỏ qua câu này", on_click=lambda: advance(skip=True)).props(
                        "flat no-caps dense").classes("text-white/70")
                ui.button("Nộp bài" if last else "Câu tiếp theo",
                          icon="done_all" if last else "arrow_forward",
                          on_click=lambda: advance()).props("no-caps").classes(
                    "bg-white text-red-900 px-4")

        def choose(opt_no: int):
            if st["locked"]:
                return
            st["answers"][q["item_id"]] = {
                "chosen_no": opt_no,
                "time_ms": int((time.monotonic() - st["q_t0"]) * 1000),
            }
            # Chế độ ôn tập: chốt luôn để hiện đáp án đúng. Thi thử: để mở cho
            # người làm đổi ý trước khi bấm sang câu kế.
            if cfg.get("instant_feedback"):
                st["locked"] = True
            _paint()
            _paint_foot()

        def advance(skip: bool = False):
            if skip:
                st["answers"].setdefault(
                    q["item_id"],
                    {"chosen_no": None,
                     "time_ms": int((time.monotonic() - st["q_t0"]) * 1000)},
                )
            if st["idx"] >= total - 1:
                return submit()          # coroutine — NiceGUI await hộ trong đúng slot
            st["idx"] += 1
            render()

        st["advance"] = advance
        _paint()
        _paint_foot()

    # ── Đồng hồ ───────────────────────────────────────────────────────────────
    def _tick_labels():
        per_q = cfg.get("seconds_per_question") or 0
        q_clock.text = f"⏱ {_fmt_clock(st['q_left'])}" if per_q else ""
        if cfg.get("total_minutes"):
            t_clock.text = f"Còn lại {_fmt_clock(st['t_left'])}"
        else:
            t_clock.text = ""

    def tick():
        """Chạy mỗi giây. Trả về coroutine khi cần nộp bài — NiceGUI await hộ,
        không tự gọi asyncio.create_task (sẽ mất slot, xem DESIGN.md)."""
        if st["done"]:
            return None
        if cfg.get("total_minutes"):
            st["t_left"] -= 1
            if st["t_left"] <= 0:
                ui.notify("Hết giờ làm bài — hệ thống tự nộp", type="warning", timeout=5000)
                return submit()
        # Đã chốt câu ở chế độ ôn tập thì dừng đếm: thời gian đó là để TRẢ LỜI,
        # không phải để đọc đáp án đúng — đang đọc mà bị nhảy câu là mất công.
        if cfg.get("seconds_per_question") and not st["locked"]:
            st["q_left"] -= 1
            if st["q_left"] <= 0:
                _tick_labels()
                # Hết giờ câu này: giữ nguyên lựa chọn nếu đã bấm, chưa bấm thì
                # tính bỏ trống. Câu cuối hết giờ → advance() tự nộp bài.
                return st["advance"](skip=True)
        _tick_labels()
        return None

    timer = ui.timer(1.0, tick)
    render()
