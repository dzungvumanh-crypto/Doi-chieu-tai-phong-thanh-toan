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
import logging
import time

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _require_auth, _handle_api_error, _query_params, _qp_int

_log = logging.getLogger(__name__)

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
/* Lưới đáp án 2×2 — mọi ô BẰNG NHAU cả bề ngang lẫn bề cao.
   `grid-auto-rows: 1fr` là mấu chốt: không có nó, hàng nào chứa câu trả lời dài
   sẽ cao hơn hàng kia và bốn ô trông xô lệch. Bốn cột trên một hàng thì với câu
   trả lời dài (bộ thật có câu 25 chữ) mỗi ô chỉ còn ~240px, chữ xuống 6-7 dòng. */
.qp-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
           grid-auto-rows: 1fr; gap: 14px; width: 100%; }
@media (max-width: 720px) { .qp-grid { grid-template-columns: 1fr; } }

/* Ô đáp án dựng bằng q-btn: Quasar canh giữa và viết hoa chữ trong
   `.q-btn__content`, nên phải chỉnh cả lớp trong, không chỉ lớp ngoài. */
.qp-opt { border-radius: 12px !important; color: #fff !important;
          padding: 14px 18px !important; min-height: 76px; width: 100%; height: 100%;
          text-transform: none !important; letter-spacing: 0 !important;
          box-shadow: 0 4px 0 rgba(0,0,0,.22) !important;
          transition: transform .1s ease, filter .1s ease; }
.qp-opt:hover { transform: translateY(-2px); filter: brightness(1.08); }
.qp-opt .q-btn__content { width: 100%; flex-wrap: nowrap; justify-content: flex-start;
                          align-items: center; gap: 14px; text-align: left; }
.qp-opt .sym { font-size: 20px; line-height: 1; opacity: .9; flex-shrink: 0; }
.qp-opt .txt { flex: 1; font-size: 15px; font-weight: 600; line-height: 1.35;
               white-space: normal; }
.qp-opt .tag { flex-shrink: 0; align-self: flex-start; font-size: 11px; font-weight: 800;
               letter-spacing: .4px; padding: 3px 9px; border-radius: 999px;
               background: #fff; color: #111; white-space: nowrap; }

/* Lúc lộ đáp án: ô không liên quan bị XÁM HẲN, không chỉ mờ đi.
   Bản trước chỉ giảm opacity — trên nền tối ô mờ vẫn còn nguyên màu, mà màu ô
   thứ tư (#26890C) lại là xanh lá y như màu "đáp án đúng" (#16A34A) nên nhìn ra
   hai ô đúng. Xám hết thì trên màn hình chỉ còn ĐÚNG hai ô có màu. */
.qp-mute { background: #38334D !important; opacity: .5;
           box-shadow: 0 4px 0 rgba(0,0,0,.25) !important; }
.qp-mute:hover { transform: none; filter: none; }
.qp-correct { outline: 4px solid #FFFFFF; outline-offset: 3px;
              box-shadow: 0 0 0 8px rgba(34,197,94,.30), 0 6px 0 rgba(0,0,0,.25) !important; }
.qp-wrong   { outline: 3px dashed #FCA5A5; outline-offset: 3px; }
.qp-ring    { outline: 4px solid #fff; outline-offset: 2px; }
.qp-badge { font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
            background: rgba(255,255,255,.9); color: #111; flex-shrink: 0; }
/* Màn xem lại — bảng đáp án nhỏ gọn, không dùng ô màu lớn */
.qp-rev-opt { border-radius: 8px; padding: 7px 12px; font-size: 13px;
              border: 1px solid #E5E7EB; background: #fff; }
.qp-rev-ok  { background: #DCFCE7; border-color: #16A34A; }
.qp-rev-bad { background: #FEE2E2; border-color: #DC2626; }

/* Nút sáng trên nền tối.
   `ui.button()` mặc định gắn `color="primary"`, Quasar dịch ra `bg-primary text-white`
   và `.text-white` của Quasar có `!important`, còn `.text-red-900` của Tailwind thì
   KHÔNG — nên nút ra nền trắng (Tailwind `bg-white` thắng) với chữ trắng: nhìn như
   một ô trống. Chữa ở hai lớp: truyền `color=None` để Quasar đừng gắn hai lớp đó
   nữa, và các lớp dưới đây đặt màu THẲNG lên `.q-btn__content` — khai báo trực tiếp
   luôn thắng màu kế thừa từ phần tử cha, bất kể `!important`. */
.qp-btn-light .q-btn__content { color: #7F1D1D !important; }
.qp-btn-light { background: #FFFFFF !important; color: #7F1D1D !important;
                font-weight: 700; text-transform: none !important;
                letter-spacing: 0 !important; }
.qp-btn-ghost .q-btn__content { color: #E4DEF3 !important; }
.qp-btn-ghost { color: #E4DEF3 !important; text-transform: none !important;
                letter-spacing: 0 !important; }
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
        # Vào lại bài dở: nối đúng chỗ đã đứng. Máy chủ đã kẹp `current_idx` vào
        # khoảng hợp lệ, kẹp lại lần nữa cho chắc — đề có thể ngắn đi nếu bộ câu
        # hỏi bị sửa giữa chừng.
        "idx": min(max(att.get("current_idx") or 0, 0), max(total - 1, 0)),
        # Khôi phục câu đã trả lời từ những gì máy chủ giữ. `time_ms` không lấy
        # lại được (không lưu riêng cho câu chưa nộp) — để 0, nó chỉ dùng để
        # thống kê chứ không tham gia chấm điểm.
        "answers": {q["item_id"]: {"chosen_no": q["chosen_no"], "time_ms": 0}
                    for q in questions if q.get("chosen_no") is not None},
        "locked": False,          # đã chốt câu này, chỉ còn nút sang câu kế
        "q_left": 0,
        "q_t0": time.monotonic(),
        # Đồng hồ tổng cộng dồn qua các phiên: `base_ms` là phần đã tiêu ở những
        # lần trước, `t0` là mốc của phiên đang chạy.
        "base_ms": att.get("elapsed_ms") or 0,
        "t0": time.monotonic(),
        "done": att["status"] == "finished",
        "submitting": False,
        # Câu đã trả lời nhưng chưa gửi lên được (mạng chập chờn). Giữ lại để
        # lần lưu sau gửi kèm — mất một lần lưu không được phép mất câu trả lời.
        "cho_luu": {},
        "lan_luu_cuoi": 0.0,
    }
    st["t_left"] = max(
        0, (cfg.get("total_minutes") or 0) * 60 - int(st["base_ms"] / 1000))

    root = ui.column().classes("qp-wrap w-full gap-0")

    # ── Kết quả & xem lại ─────────────────────────────────────────────────────
    def _render_result(res: dict):
        root.clear()
        with root:
            with ui.column().classes("w-full items-center px-4 py-8 gap-5"):
                score = float(res.get("score") or 0)
                tone = "#16A34A" if score >= 80 else ("#D97706" if score >= 50 else "#DC2626")
                with ui.column().classes("items-center gap-1"):
                    ui.label(res["set_name"]).style("color:#C9C2DE;font-size:13px")
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
                    ui.button("Về danh sách bộ câu hỏi", icon="grid_view", color=None,
                              on_click=lambda: ui.navigate.to("/quiz")).props(
                        "no-caps").classes("qp-btn-light px-4")

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

    # ── Lưu tiến độ ───────────────────────────────────────────────────────────
    def _da_tieu_ms() -> int:
        """Tổng thời gian đã làm bài = các phiên trước + phiên đang chạy."""
        return int(st["base_ms"] + (time.monotonic() - st["t0"]) * 1000)

    async def luu_tien_do(bat_buoc: bool = False) -> bool:
        """Gửi phần đã trả lời lên máy chủ. Trả True nếu lưu được.

        Gọi sau MỖI câu chứ không đợi nộp bài: máy ngủ hay mất điện thì không
        có sự kiện nào để bám vào mà lưu, nên phải lưu sẵn từ trước.

        Chỉ gửi phần THAY ĐỔI. Gửi lỗi thì giữ nguyên hàng chờ để lần sau gửi
        kèm — một lần mạng chập không được phép làm mất câu trả lời.
        """
        if st["done"]:
            return False
        # Nhịp nền (bat_buoc=False) chỉ để cập nhật đồng hồ; không có gì mới thì
        # 10 giây một lần là đủ, khỏi bắn request mỗi giây.
        if not bat_buoc and not st["cho_luu"] and time.monotonic() - st["lan_luu_cuoi"] < 10:
            return False
        dang_gui = dict(st["cho_luu"])
        body = {
            "answers": [{"item_id": iid, "chosen_no": a["chosen_no"], "time_ms": a["time_ms"]}
                        for iid, a in dang_gui.items()],
            "current_idx": st["idx"],
            "elapsed_ms": _da_tieu_ms(),
        }
        try:
            # 4 giây: lời gọi này chạy xen giữa các thao tác của người dùng và
            # trong nhịp đồng hồ — chờ lâu hơn là giao diện khựng thấy rõ.
            await asyncio.to_thread(
                api.patch, f"/api/quiz/attempts/{attempt_id}/progress", body, 4.0)
        except Exception as e:
            if isinstance(e, (api.SessionExpiredError, api.DisplacedSessionError,
                              api.MustChangePasswordError)):
                # Phiên hỏng thì lần lưu nào cũng hỏng. Phải DỪNG HẲN nhịp đồng
                # hồ, nếu không trang cứ bắn một request 401 mỗi giây cho tới khi
                # người dùng đóng tab — đo được 683 lần trên một bài bỏ quên.
                st["done"] = True
                timer.active = False
                _handle_api_error(e)
                return False
            _log.warning("Không lưu được tiến độ bài %s: %s", attempt_id, e)
            return False
        for iid in dang_gui:
            # Chỉ xoá đúng những mục vừa gửi — người dùng có thể đã trả lời thêm
            # câu khác trong lúc chờ phản hồi.
            st["cho_luu"].pop(iid, None)
        st["lan_luu_cuoi"] = time.monotonic()
        return True

    async def _luu_va_bao() -> None:
        """Lưu rồi cập nhật chỉ báo nhỏ trên thanh trên.

        Người làm bài cần biết công sức của mình đang được giữ lại — nếu im
        lặng, mất kết nối thật thì họ chỉ phát hiện lúc quay lại và thấy trắng.
        """
        ok = await luu_tien_do(bat_buoc=True)
        if st["done"]:
            return
        if ok:
            save_dot.text = "✓ đã lưu"
            save_dot.style("color:#86EFAC")
        else:
            save_dot.text = f"⚠ chưa lưu ({len(st['cho_luu'])} câu)"
            save_dot.style("color:#FCD34D")

    # ── Nộp bài ───────────────────────────────────────────────────────────────
    async def submit(_=None):
        if st["submitting"]:
            return                      # chặn bấm hai lần / hết giờ trùng lúc bấm nộp
        st["submitting"] = True
        st["done"] = True
        timer.active = False
        # Gửi cả bài chứ không riêng hàng chờ: máy chủ chấm từ DB nên phần đã
        # lưu vẫn tính, còn gửi thừa thì chỉ ghi đè đúng giá trị cũ.
        body = {
            "answers": [
                {"item_id": iid, "chosen_no": a["chosen_no"], "time_ms": a["time_ms"]}
                for iid, a in st["answers"].items()
            ],
            "duration_ms": _da_tieu_ms(),
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

    # ── Tạm dừng / bỏ bài ─────────────────────────────────────────────────────
    async def tam_dung(_=None):
        """Lưu rồi về danh sách. Lưu hỏng thì KHÔNG rời trang — đi tiếp là mất
        đúng những câu vừa trả lời mà người dùng tưởng đã an toàn."""
        timer.active = False
        if not await luu_tien_do(bat_buoc=True):
            timer.active = True
            ui.notify("Chưa lưu được tiến độ — kiểm tra kết nối rồi thử lại",
                      type="negative", timeout=7000)
            return
        st["done"] = True
        ui.notify("Đã lưu. Vào lại bộ câu hỏi này và bấm «Làm tiếp» để học tiếp.",
                  type="positive", timeout=6000)
        ui.navigate.to("/quiz")

    async def confirm_exit():
        with ui.dialog() as d, ui.card().classes("w-full max-w-sm"):
            ui.label("Rời khỏi bài đang làm").classes("text-lg font-bold text-red-900")
            ui.label(f"Đã trả lời {len(st['answers'])}/{total} câu.").classes(
                "text-sm text-gray-600 mb-2")
            with ui.column().classes("w-full gap-2"):
                ui.button("Tạm dừng — làm tiếp sau", icon="pause_circle",
                          on_click=lambda: d.submit("pause")).props("no-caps").classes(
                    "bg-red-700 text-white w-full")
                ui.button("Bỏ bài này, không tính điểm", icon="delete_outline",
                          on_click=lambda: d.submit("drop")).props(
                    "no-caps flat").classes("text-gray-600 w-full")
                ui.button("Ở lại làm tiếp", on_click=lambda: d.submit(None)).props(
                    "no-caps flat").classes("text-gray-600 w-full")
        chon = await d
        if chon == "pause":
            await tam_dung()
        elif chon == "drop":
            timer.active = False
            st["done"] = True
            try:
                await asyncio.to_thread(api.delete, f"/api/quiz/attempts/{attempt_id}")
            except Exception as e:
                # Xoá không được thì bài vẫn nằm đó dưới dạng "đang dở" — không
                # sao, người dùng bỏ qua hoặc bỏ lại từ màn danh sách.
                _log.warning("Không xoá được bài dở %s: %s", attempt_id, e)
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
            q_clock = ui.label("").classes("font-mono text-sm font-bold").style("color:#FFFFFF")
            t_clock = ui.label("").classes("font-mono text-sm").style("color:#C9C2DE")
            save_dot = ui.label("").classes("text-xs").style("color:#C9C2DE")
            ui.button("Tạm dừng", icon="pause", on_click=tam_dung, color=None).props(
                "dense no-caps flat").classes("qp-btn-ghost")
            ui.button(icon="close", on_click=confirm_exit, color=None).props(
                "dense flat round").classes("qp-btn-ghost")

        progress = ui.linear_progress(value=0, show_value=False, size="6px").props(
            "color=amber track-color=transparent").classes("w-full")
        counter = ui.label("").classes("text-xs px-5 pt-2").style("color:#C9C2DE")
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
                opts_box = ui.element("div").classes("qp-grid")
                foot = ui.row().classes("w-full items-center gap-2 pt-1")

        def _paint():
            """Vẽ lại 4 ô đáp án theo trạng thái hiện tại của câu.

            Lúc lộ đáp án phải phân biệt bằng BA thứ cùng lúc — màu, viền, và
            nhãn chữ — chứ không riêng màu: người mù màu đỏ-lục (khoảng 8% nam
            giới) nhìn ô "đúng" xanh lá và ô "bạn chọn" đỏ y hệt nhau.
            """
            opts_box.clear()
            chosen = (st["answers"].get(q["item_id"]) or {}).get("chosen_no")
            correct = q.get("correct_no")          # None ở chế độ thi thử
            reveal = st["locked"] and cfg.get("instant_feedback") and correct is not None
            with opts_box:
                for pos, opt in enumerate(q["options"]):
                    color, sym = _OPT_STYLE[pos % 4]
                    cls, tag = "qp-opt", ""
                    if reveal:
                        if opt["no"] == correct:
                            color, cls = "#15803D", "qp-opt qp-correct"
                            tag = "ĐÁP ÁN ĐÚNG"
                        elif opt["no"] == chosen:
                            color, cls = "#9F1239", "qp-opt qp-wrong"
                            tag = "BẠN CHỌN"
                        else:
                            # Màu phải đổi ở style INLINE, không thể để cho lớp
                            # .qp-mute lo: nền màu cũng là inline `!important`,
                            # mà inline `!important` thắng mọi `!important` trong
                            # stylesheet — ô đáng lẽ xám sẽ vẫn giữ nguyên màu.
                            color, cls = "#38334D", "qp-opt qp-mute"
                    elif chosen is not None and opt["no"] == chosen:
                        cls = "qp-opt qp-ring"
                    btn = ui.button(color=None).props("unelevated no-caps").classes(cls).style(
                        f"background:{color} !important")
                    with btn:
                        ui.html(f'<span class="sym">{sym}</span>'
                                f'<span class="txt">{opt["text"]}</span>'
                                + (f'<span class="tag">{tag}</span>' if tag else ""))
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
                        ui.label("Chính xác!").style(
                            "color:#86EFAC;font-weight:700;font-size:14px")
                    else:
                        ui.label("Chưa đúng — ô gắn nhãn ĐÁP ÁN ĐÚNG mới là câu trả lời "
                                 "đúng").style("color:#FCD34D;font-weight:700;font-size:14px")
                ui.space()
                if not st["locked"] and not answered:
                    ui.button("Bỏ qua câu này", color=None,
                              on_click=lambda: advance(skip=True)).props(
                        "flat no-caps dense").classes("qp-btn-ghost")
                ui.button("Nộp bài" if last else "Câu tiếp theo",
                          icon="done_all" if last else "arrow_forward",
                          color=None, on_click=lambda: advance()).props("no-caps").classes(
                    "qp-btn-light px-4")

        async def choose(opt_no: int):
            if st["locked"]:
                return
            ans = {
                "chosen_no": opt_no,
                "time_ms": int((time.monotonic() - st["q_t0"]) * 1000),
            }
            st["answers"][q["item_id"]] = ans
            st["cho_luu"][q["item_id"]] = ans
            # Chế độ ôn tập: chốt luôn để hiện đáp án đúng. Thi thử: để mở cho
            # người làm đổi ý trước khi bấm sang câu kế.
            if cfg.get("instant_feedback"):
                st["locked"] = True
            # Vẽ TRƯỚC rồi mới lưu: người dùng thấy phản hồi ngay, không phải
            # chờ một vòng mạng mới biết mình đã bấm trúng ô nào.
            _paint()
            _paint_foot()
            await _luu_va_bao()

        async def advance(skip: bool = False):
            if skip:
                bo_trong = {"chosen_no": None,
                            "time_ms": int((time.monotonic() - st["q_t0"]) * 1000)}
                if q["item_id"] not in st["answers"]:
                    st["answers"][q["item_id"]] = bo_trong
                    st["cho_luu"][q["item_id"]] = bo_trong
            if st["idx"] >= total - 1:
                return await submit()
            st["idx"] += 1
            render()
            # Lưu cả vị trí mới: người dùng bấm "Câu tiếp theo" rồi máy ngủ thì
            # lần vào sau phải đứng ở câu đang xem, không lùi về câu trước.
            await _luu_va_bao()

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

    async def tick():
        """Chạy mỗi giây: đếm giờ và lưu tiến độ nền.

        Là `async` để `await` được lời gọi lưu. NiceGUI await callback này trong
        đúng slot của trang, nên tuyệt đối KHÔNG bọc `asyncio.create_task`
        (mất slot → ui.notify/ui.navigate ném lỗi câm, xem DESIGN.md).
        """
        if st["done"]:
            return
        if cfg.get("total_minutes"):
            st["t_left"] -= 1
            if st["t_left"] <= 0:
                ui.notify("Hết giờ làm bài — hệ thống tự nộp", type="warning", timeout=5000)
                await submit()
                return
        # Đã chốt câu ở chế độ ôn tập thì dừng đếm: thời gian đó là để TRẢ LỜI,
        # không phải để đọc đáp án đúng — đang đọc mà bị nhảy câu là mất công.
        if cfg.get("seconds_per_question") and not st["locked"]:
            st["q_left"] -= 1
            if st["q_left"] <= 0:
                _tick_labels()
                # Hết giờ câu này: giữ nguyên lựa chọn nếu đã bấm, chưa bấm thì
                # tính bỏ trống. Câu cuối hết giờ → advance() tự nộp bài.
                await st["advance"](skip=True)
                return
        _tick_labels()
        # Nhịp nền: cập nhật đồng hồ đã tiêu và gửi lại phần chưa lưu được.
        # `luu_tien_do` tự giãn xuống 10 giây/lần khi không có gì mới.
        if await luu_tien_do():
            if st["cho_luu"]:
                save_dot.text = f"⚠ chưa lưu ({len(st['cho_luu'])} câu)"
                save_dot.style("color:#FCD34D")
            elif save_dot.text.startswith("⚠"):
                save_dot.text = "✓ đã lưu"
                save_dot.style("color:#86EFAC")

    timer = ui.timer(1.0, tick)
    render()
