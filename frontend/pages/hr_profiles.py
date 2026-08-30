"""Hồ sơ cán bộ — hồ sơ cá nhân + 7 phân hệ hồ sơ nhân sự.

Form nhập liệu của 7 phân hệ (bằng cấp, bổ nhiệm, quá trình công tác, nghỉ gián
đoạn, lương, đào tạo, công cụ) KHÔNG viết tay từng cái: trang gọi
`/api/hr/meta` lấy đặc tả cột rồi tự dựng bảng và form. Thêm một cột ở
`backend/services/hr_service.py::SECTIONS` là màn hình có ngay cột đó — không có
bản mô tả thứ hai ở frontend để quên đồng bộ.
"""
import asyncio
import base64

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (_content_area, _dmy, _handle_api_error, _page_header,
                             _require_auth, _sidebar)

# Thứ tự tab — đúng thứ tự yêu cầu nghiệp vụ, không theo thứ tự dict của meta
_THU_TU = ["degrees", "appointments", "work-history", "breaks", "salaries",
           "trainings", "tools"]

_CSS = """<style>
/* Ô ghi chú / địa chỉ dài phải xuống dòng, nếu không Quasar kéo bảng rộng ra
   và cả trang cuộn ngang. */
.hr-table td { white-space: normal !important; vertical-align: top; }
.hr-table thead th {
  position: sticky; top: 0; z-index: 2;
  background: #fef2f2; color: #7f1d1d; font-weight: 600;
}
.hr-list { max-height: calc(100vh - 260px); overflow-y: auto; }
.hr-upload .q-uploader { width: auto; min-width: 0; box-shadow: none; background: transparent; }
.hr-upload .q-uploader__header { min-height: 30px; border-radius: 6px; background: #b91c1c; }
.hr-upload .q-uploader__header-content { padding: 2px 10px; min-height: 30px; }
.hr-upload .q-uploader__title { font-size: 12px; font-weight: 500; line-height: 1.3; }
.hr-upload .q-uploader__subtitle, .hr-upload .q-uploader__list { display: none; }
</style>"""


def _hien(gia_tri, spec: dict) -> str:
    """Giá trị thô → chuỗi hiển thị trong bảng."""
    if gia_tri in (None, ""):
        return "—"
    kieu = spec["kieu"]
    if kieu == "date":
        return _dmy(str(gia_tri)[:10])
    if kieu == "bool":
        return "Có" if gia_tri else "Không"
    if kieu == "enum":
        return spec["chon"].get(gia_tri, str(gia_tri))
    if kieu == "num":
        # Hệ số lương 2,34 — dấu phẩy thập phân theo cách viết tiếng Việt
        return f"{gia_tri:g}".replace(".", ",")
    return str(gia_tri)


def _o_nhap(ten: str, spec: dict, gia_tri=None):
    """Dựng đúng một ô nhập theo kiểu dữ liệu khai trong meta."""
    nhan, kieu = spec["nhan"] + (" *" if spec["bat_buoc"] else ""), spec["kieu"]
    if kieu == "date":
        return ui.input(nhan, value=(str(gia_tri)[:10] if gia_tri else "")
                        ).props('type="date" dense outlined').classes("w-full")
    if kieu == "bool":
        # Dòng mới (gia_tri là None) lấy mặc định khai trong meta — ô "Không
        # hưởng lương" của phần nghỉ gián đoạn phải tích sẵn.
        if gia_tri is None:
            gia_tri = spec.get("mac_dinh")
        return ui.checkbox(spec["nhan"], value=bool(gia_tri)).classes("w-full")
    if kieu == "enum":
        return ui.select({None: "—", **spec["chon"]}, label=nhan,
                         value=gia_tri).props("dense outlined").classes("w-full")
    if kieu in ("int", "num"):
        if gia_tri is None:
            gia_tri = spec.get("mac_dinh")
        return ui.number(nhan, value=gia_tri,
                         format="%d" if kieu == "int" else None
                         ).props("dense outlined").classes("w-full")
    if ten in ("note", "permanent_address", "current_address", "contact_address"):
        return ui.textarea(nhan, value=gia_tri or "").props(
            "dense outlined autogrow").classes("w-full")
    return ui.input(nhan, value=gia_tri or "").props("dense outlined").classes("w-full")


def _gia_tri(o, spec: dict):
    """Ô nhập → giá trị gửi lên API. Chuỗi rỗng thành None để backend xoá trắng đúng ý."""
    v = o.value
    if spec["kieu"] == "bool":
        return bool(v)
    if isinstance(v, str):
        v = v.strip()
    return v if v not in ("", None) else None


@ui.page("/hr_profiles")
async def hr_profiles_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.hr_profiles"):
        ui.navigate.to("/home")
        return

    await _sidebar("hr_profiles")
    ui.add_head_html(_CSS)

    try:
        meta, depts = await asyncio.gather(
            asyncio.to_thread(api.get, "/api/hr/meta"),
            asyncio.to_thread(api.get, "/api/departments/"),
            return_exceptions=True,
        )
    except Exception as e:            # pragma: no cover — lỗi mạng lúc mở trang
        _handle_api_error(e)
        return
    for r in (meta, depts):
        if isinstance(r, Exception):
            if _handle_api_error(r):
                return
            ui.notify(str(r), type="negative")
            return

    me = api.get_current_user() or {}
    # Quản trị viên vẫn vào được màn hình để nhập hộ hồ sơ người khác, nhưng bản
    # thân họ không có hồ sơ — xem hr_service.ROLES_KHONG_HO_SO.
    la_qtv = me.get("role") in ("admin", "admin_l2")
    quyen = meta["quyen"]
    # Đuôi file + trần dung lượng lấy từ backend, không khai lại ở đây: khai hai
    # nơi thì ô chọn file cho chọn thứ backend từ chối, người dùng tải xong mới biết.
    tep = meta["tep"]
    chuc_vu = meta["chuc_vu"]        # nhãn vai trò, lấy từ backend
    dept_opts = {None: "Tất cả phòng", **{d["id"]: d["name"] for d in depts}}

    with _content_area():
        _page_header("Hồ sơ cán bộ",
                     "Hồ sơ cá nhân, bằng cấp, bổ nhiệm, công tác, lương, đào tạo, công cụ")

        state: dict = {"staff_id": None, "data": None}

        with ui.row().classes("w-full items-start gap-4 flex-nowrap"):
            # ── Cột trái: danh sách cán bộ ───────────────────────────────────
            with ui.column().classes("w-72 shrink-0 gap-2"):
                s_q = ui.input("Tìm mã / họ tên").props("dense outlined clearable").classes("w-full")
                s_dept = ui.select(dept_opts, value=None, label="Phòng").props(
                    "dense outlined").classes("w-full")
                dem = ui.label("").classes("text-xs text-gray-500")
                khung_ds = ui.column().classes("w-full gap-0 hr-list border rounded bg-white")

            # ── Cột phải: hồ sơ ──────────────────────────────────────────────
            khung_ho_so = ui.column().classes("flex-1 min-w-0 gap-3")

        # ── Danh sách ────────────────────────────────────────────────────────
        async def tai_danh_sach():
            tham_so = {}
            if s_q.value and s_q.value.strip():
                tham_so["q"] = s_q.value.strip()
            if s_dept.value:
                tham_so["department_id"] = s_dept.value
            try:
                rows = await asyncio.to_thread(api.get, "/api/hr/profiles", tham_so)
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            dem.text = f"{len(rows)} cán bộ"
            khung_ds.clear()
            with khung_ds:
                if not rows:
                    # Quản trị viên cấp 2 chưa được cấp `hr.view_all` sẽ ra danh
                    # sách rỗng (không có hồ sơ của chính mình để rơi về) — nói rõ
                    # lý do thay vì để màn hình trống không giải thích gì.
                    ui.label("Chưa được cấp quyền xem hồ sơ cán bộ khác"
                             if la_qtv else "Không có cán bộ nào khớp"
                             ).classes("text-gray-500 text-sm text-center py-6")
                for r in rows:
                    dang_chon = r["staff_id"] == state["staff_id"]
                    nen = "bg-red-50 border-l-4 border-red-700" if dang_chon else "hover:bg-gray-50"
                    with ui.column().classes(
                        f"w-full px-3 py-2 cursor-pointer border-b {nen} gap-0"
                    ).on("click", lambda s=r["staff_id"]: chon_can_bo(s)):
                        with ui.row().classes("items-center gap-1 w-full"):
                            ui.label(r["full_name"]).classes("text-sm font-medium flex-1 truncate")
                            if not r["co_ho_so"]:
                                ui.icon("info").classes("text-amber-500 text-xs").tooltip(
                                    "Chưa khai hồ sơ")
                        # Chức vụ hiện ngay dưới tên: danh sách sắp lãnh đạo
                        # trước, không ghi chức vụ thì thứ tự nhìn như ngẫu nhiên.
                        ui.label(f"{chuc_vu.get(r['role'], '—')} · "
                                 f"{r['employee_code'] or '—'}"
                                 ).classes("text-xs text-gray-500 truncate")
                        ui.label(r["department"] or "Chưa có phòng"
                                 ).classes("text-[11px] text-gray-400 truncate")

        # ── Hồ sơ cá nhân ────────────────────────────────────────────────────
        def _form_ho_so(data: dict):
            ho_so, staff = data["profile"], data["staff"]
            q = data["quyen"]
            o: dict = {}

            with ui.card().classes("w-full p-4"):
                with ui.row().classes("w-full items-start gap-4 flex-nowrap"):
                    # Ảnh: nạp qua API rồi nhúng base64 — thẻ <img> không gắn
                    # được Bearer token nên không trỏ thẳng vào endpoint được.
                    with ui.column().classes("w-32 shrink-0 items-center gap-1"):
                        khung_anh = ui.column().classes("w-32 h-40 items-center justify-center "
                                                        "border rounded bg-gray-50")
                        with khung_anh:
                            ui.icon("account_circle").classes("text-6xl text-gray-300")
                        if q["sua_tu_khai"]:
                            with ui.element("div").classes("hr-upload"):
                                ui.upload(label="Tải ảnh", auto_upload=True,
                                          on_upload=_tai_anh
                                          ).props(f"accept=\"{tep['anh_accept']}\" flat")
                            ui.label(f"{tep['anh_accept'].replace(',', ' ')} · tối đa "
                                     f"{tep['tran_anh_mb']} MB").classes("text-[10px] text-gray-400")
                    with ui.column().classes("flex-1 min-w-0 gap-0"):
                        ui.label(staff["full_name"]).classes("text-xl font-bold text-red-900")
                        ui.label(f"Mã cán bộ: {staff['employee_code'] or '—'} · "
                                 f"{staff['department'] or 'Chưa có phòng'}"
                                 ).classes("text-sm text-gray-600")

                ui.separator().classes("my-3")
                ui.label("Thông tin cá nhân").classes("font-semibold text-red-800 text-sm")
                with ui.grid(columns=3).classes("w-full gap-3"):
                    for ten, spec in meta["profile"]["tai_khoan"].items():
                        o[ten] = _o_nhap(ten, spec, staff.get(ten))
                    for ten, spec in meta["profile"]["tu_khai"].items():
                        o[ten] = _o_nhap(ten, spec, ho_so.get(ten))
                if not q["sua_tu_khai"]:
                    for ten in list(meta["profile"]["tai_khoan"]) + list(meta["profile"]["tu_khai"]):
                        o[ten].props("readonly")

                ui.label("Thông tin công tác").classes(
                    "font-semibold text-red-800 text-sm mt-4")
                with ui.grid(columns=3).classes("w-full gap-3"):
                    # `tai_khoan_hr` (ngày vào ngành) đọc từ `staff` vì nó nằm ở
                    # bảng user_tttt, không phải hr_profiles — nhưng về quyền thì
                    # thuộc khối công tác nên vẽ chung ở đây.
                    for ten, spec in meta["profile"]["tai_khoan_hr"].items():
                        o[ten] = _o_nhap(ten, spec, staff.get(ten))
                        if not q["sua_cong_tac"]:
                            o[ten].props("readonly")
                    for ten, spec in meta["profile"]["cong_tac"].items():
                        o[ten] = _o_nhap(ten, spec, ho_so.get(ten))
                        if not q["sua_cong_tac"]:
                            o[ten].props("readonly")
                if q["sua_cong_tac"]:
                    ui.label("Ngày vào ngành quyết định số ngày phép năm — sửa ở đây là "
                             "đổi luôn hạn mức phép của cán bộ."
                             ).classes("text-xs text-amber-700")
                else:
                    ui.label("Phần công tác do người làm nhân sự nhập — bạn chỉ xem."
                             ).classes("text-xs text-amber-700")

                async def luu():
                    body = {}
                    nhom = {**meta["profile"]["tai_khoan"], **meta["profile"]["tu_khai"]} \
                        if q["sua_tu_khai"] else {}
                    if q["sua_cong_tac"]:
                        nhom = {**nhom, **meta["profile"]["cong_tac"],
                                **meta["profile"]["tai_khoan_hr"]}
                    for ten, spec in nhom.items():
                        body[ten] = _gia_tri(o[ten], spec)
                    if not body:
                        ui.notify("Bạn không có quyền sửa hồ sơ này", type="warning")
                        return
                    try:
                        await asyncio.to_thread(
                            api.put, f"/api/hr/profiles/{staff['staff_id']}", body)
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    ui.notify("Đã lưu hồ sơ", type="positive")
                    await chon_can_bo(staff["staff_id"])

                if q["sua_tu_khai"] or q["sua_cong_tac"]:
                    with ui.row().classes("w-full justify-end mt-3"):
                        ui.button("Lưu hồ sơ", icon="save", on_click=luu
                                  ).props("no-caps").classes("bg-red-700 text-white")
            return khung_anh

        async def _tai_anh(e):
            try:
                await asyncio.to_thread(
                    api.post_upload, f"/api/hr/profiles/{state['staff_id']}/photo",
                    {"file": (e.name, e.content.read(), e.type or "image/jpeg")})
            except Exception as ex:
                if _handle_api_error(ex):
                    return
                ui.notify(str(ex), type="negative")
                return
            ui.notify("Đã cập nhật ảnh", type="positive")
            await chon_can_bo(state["staff_id"])

        async def _ve_anh(khung_anh, staff_id: int):
            """Nạp ảnh sau khi trang đã vẽ — ảnh nặng hơn phần chữ nhiều lần,
            chờ nó thì cả hồ sơ hiện chậm theo."""
            try:
                raw = await asyncio.to_thread(api.get_bytes,
                                              f"/api/hr/profiles/{staff_id}/photo")
            except Exception as e:
                _log_bo_qua(e)
                return
            if state["staff_id"] != staff_id:      # người dùng đã đổi sang hồ sơ khác
                return
            khung_anh.clear()
            with khung_anh:
                ui.image("data:image/jpeg;base64," + base64.b64encode(raw).decode()
                         ).classes("w-32 h-40 object-cover rounded")

        def _log_bo_qua(e):
            # Không có ảnh (404) là chuyện bình thường; lỗi khác vẫn báo cho người dùng
            if "404" not in str(e):
                ui.notify(f"Không tải được ảnh: {e}", type="warning")

        # ── Một phân hệ dạng danh sách ───────────────────────────────────────
        def _ve_section(ten: str, rows: list[dict], staff_id: int, sua_duoc: bool):
            spec = meta["sections"][ten]
            fields = spec["fields"]

            with ui.row().classes("w-full items-center justify-between mb-2"):
                ui.label(f"{len(rows)} dòng").classes("text-xs text-gray-500")
                if sua_duoc:
                    ui.button("Thêm dòng", icon="add",
                              on_click=lambda: _mo_form(ten, staff_id, None)
                              ).props("dense no-caps").classes("bg-red-700 text-white px-3")

            if not rows:
                ui.label("Chưa có dữ liệu").classes("text-gray-500 text-sm py-6 text-center w-full")
                return

            cols = [{"name": f, "label": s["nhan"], "field": f, "align": "left"}
                    for f, s in fields.items()]
            if spec["co_file"]:
                cols.append({"name": "files", "label": "Tệp", "field": "files_txt",
                             "align": "left"})
            cols.append({"name": "actions", "label": "", "field": "actions",
                         "align": "center", "style": "width:70px"})

            ban_ghi = {r["id"]: r for r in rows}
            dong = []
            for r in rows:
                d = {f: _hien(r.get(f), s) for f, s in fields.items()}
                d["id"] = r["id"]
                d["sua_duoc"] = sua_duoc
                d["files_txt"] = ", ".join(f["filename"] for f in r.get("files", [])) or "—"
                dong.append(d)

            bang = ui.table(columns=cols, rows=dong, row_key="id",
                            pagination={"rowsPerPage": 0}).props(
                'bordered dense flat separator="cell"').classes("w-full hr-table")
            bang.add_slot("body", r"""
                <q-tr :props="props">
                  <q-td v-for="col in props.cols" :key="col.name" :props="props">
                    <template v-if="col.name === 'actions'">
                      <q-btn dense flat round size="sm" color="primary" icon="edit"
                             @click="() => $parent.$emit('rowEdit', props.row.id)" />
                      <q-btn dense flat round size="sm" color="negative" icon="delete"
                             v-if="props.row.sua_duoc"
                             @click="() => $parent.$emit('rowDel', props.row.id)" />
                    </template>
                    <template v-else>{{ col.value }}</template>
                  </q-td>
                </q-tr>
            """)
            bang.on("rowEdit", lambda e: _mo_form(ten, staff_id, ban_ghi[int(e.args)]))

            async def _xoa(e):
                await _xoa_dong(ten, ban_ghi[int(e.args)])
            bang.on("rowDel", _xoa)

        def _mo_form(ten: str, staff_id: int, item: dict | None):
            """Form thêm / sửa một dòng hồ sơ, kèm luôn phần đính kèm tệp.

            Ở bước THÊM, tệp được giữ tạm rồi mới tải lên sau khi dòng hồ sơ được
            tạo (API đính kèm cần `item_id`, mà id chỉ có sau khi lưu). Người dùng
            không phải lưu rồi mở lại nữa — chọn tệp và bấm Lưu một lần.
            """
            spec = meta["sections"][ten]
            sua_duoc = _sua_duoc(ten)
            o: dict = {}
            da_luu: list = list((item or {}).get("files", []))   # tệp đã ở máy chủ
            cho_tai: list = []                                   # tệp chờ lưu cùng dòng mới

            with ui.dialog() as hop, ui.card().classes("w-full max-w-3xl"):
                ui.label(("Sửa — " if item else "Thêm — ") + spec["nhan"]
                         ).classes("text-lg font-bold text-red-900")
                with ui.grid(columns=2).classes("w-full gap-3"):
                    for f, s_ in spec["fields"].items():
                        o[f] = _o_nhap(f, s_, (item or {}).get(f))
                        if not sua_duoc:
                            o[f].props("readonly")

                if spec["co_file"]:
                    ui.separator().classes("my-2")
                    ui.label(f"Tệp đính kèm ({tep['file_accept'].replace(',', ', ')} — "
                             f"tối đa {tep['tran_file_mb']} MB mỗi tệp)"
                             ).classes("font-semibold text-sm text-red-800")
                    khung_file = ui.column().classes("w-full gap-1")

                    def _ve_file():
                        khung_file.clear()
                        with khung_file:
                            for f in da_luu:
                                _dong_da_luu(f, sua_duoc, da_luu, _ve_file)
                            for f in cho_tai:
                                _dong_cho_tai(f, cho_tai, _ve_file)
                            if not da_luu and not cho_tai:
                                ui.label("Chưa có tệp nào").classes("text-xs text-gray-500")
                            if not sua_duoc:
                                return

                            async def _nhan_tep(e):
                                noi_dung = e.content.read()
                                if item:
                                    # Dòng đã có id → tải lên ngay
                                    try:
                                        kq = await asyncio.to_thread(
                                            api.post_upload,
                                            f"/api/hr/attachments/{ten}/{item['id']}",
                                            {"file": (e.name, noi_dung,
                                                      e.type or "application/octet-stream")})
                                    except Exception as ex:
                                        if _handle_api_error(ex):
                                            return
                                        ui.notify(str(ex), type="negative")
                                        return
                                    da_luu.append(kq)
                                    ui.notify(f"Đã đính kèm «{kq['filename']}»", type="positive")
                                else:
                                    cho_tai.append({"name": e.name, "bytes": noi_dung,
                                                    "type": e.type})
                                    ui.notify(f"«{e.name}» sẽ được tải lên khi bấm Lưu",
                                              type="ongoing", timeout=2500)
                                _ve_file()

                            with ui.element("div").classes("hr-upload"):
                                ui.upload(label="Chọn tệp", auto_upload=True, multiple=True,
                                          on_upload=_nhan_tep
                                          ).props(f"accept=\"{tep['file_accept']}\" flat")

                    _ve_file()

                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Đóng", on_click=hop.close).props("flat no-caps")

                    async def luu():
                        body = {f: _gia_tri(o[f], s_) for f, s_ in spec["fields"].items()}
                        duong = (f"/api/hr/items/{ten}/{item['id']}" if item
                                 else f"/api/hr/sections/{ten}/{staff_id}")
                        goi = api.patch if item else api.post
                        try:
                            dong = await asyncio.to_thread(goi, duong, body)
                        except Exception as e:
                            if _handle_api_error(e):
                                return
                            ui.notify(str(e), type="negative")
                            return

                        # Dòng lưu xong mới có id để gắn tệp. Tệp lỗi KHÔNG làm mất
                        # dòng vừa tạo — báo đích danh tệp nào hỏng để tải lại.
                        loi = []
                        for f in cho_tai:
                            try:
                                await asyncio.to_thread(
                                    api.post_upload,
                                    f"/api/hr/attachments/{ten}/{dong['id']}",
                                    {"file": (f["name"], f["bytes"],
                                              f["type"] or "application/octet-stream")})
                            except Exception as ex:
                                if _handle_api_error(ex):
                                    return
                                loi.append(f"{f['name']}: {ex}")
                        hop.close()
                        if loi:
                            ui.notify("Đã lưu dòng hồ sơ, nhưng có tệp chưa đính kèm được — "
                                      "mở lại dòng này để tải lại", type="warning", timeout=8000)
                            for m in loi[:5]:
                                ui.notify(m, type="negative", timeout=8000)
                        else:
                            ui.notify("Đã lưu" + (f" kèm {len(cho_tai)} tệp" if cho_tai else ""),
                                      type="positive")
                        await chon_can_bo(staff_id)

                    if sua_duoc:
                        ui.button("Lưu", icon="save", on_click=luu).props("no-caps").classes(
                            "bg-red-700 text-white")
            hop.open()

        def _dong_da_luu(f: dict, sua_duoc: bool, da_luu: list, ve_lai):
            """Tệp đã nằm trên máy chủ — tải về / xoá ngay trong form."""
            with ui.row().classes("items-center gap-2 w-full"):
                ui.icon("description").classes("text-red-700")
                ui.label(f"{f['filename']} ({(f.get('size_bytes') or 0) // 1024} KB)"
                         ).classes("text-sm flex-1 truncate")

                async def tai():
                    try:
                        raw = await asyncio.to_thread(
                            api.download, f"/api/hr/attachments/{f['id']}/download")
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    ui.download(raw, f["filename"])

                ui.button(icon="download", on_click=tai).props("dense flat round size=sm")

                async def xoa():
                    try:
                        await asyncio.to_thread(api.delete, f"/api/hr/attachments/{f['id']}")
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    da_luu.remove(f)
                    ui.notify("Đã xoá tệp", type="positive")
                    ve_lai()

                if sua_duoc:
                    ui.button(icon="delete", on_click=xoa).props(
                        "dense flat round size=sm color=negative")

        def _dong_cho_tai(f: dict, cho_tai: list, ve_lai):
            """Tệp vừa chọn ở form THÊM, chưa lên máy chủ — bỏ ra được trước khi lưu."""
            with ui.row().classes("items-center gap-2 w-full"):
                ui.icon("upload_file").classes("text-amber-600")
                ui.label(f"{f['name']} ({len(f['bytes']) // 1024} KB)"
                         ).classes("text-sm flex-1 truncate")
                ui.label("chờ lưu").classes("text-xs text-amber-700")

                def bo():
                    cho_tai.remove(f)
                    ve_lai()

                ui.button(icon="close", on_click=bo).props(
                    "dense flat round size=sm color=negative")

        async def _xoa_dong(ten: str, item: dict):
            with ui.dialog() as hoi, ui.card():
                ui.label("Xoá dòng hồ sơ này?").classes("font-semibold")
                ui.label("Tệp đính kèm của dòng cũng bị xoá theo.").classes(
                    "text-xs text-gray-500")
                with ui.row().classes("justify-end gap-2 w-full mt-2"):
                    ui.button("Huỷ", on_click=lambda: hoi.submit(False)).props("flat no-caps")
                    ui.button("Xoá", on_click=lambda: hoi.submit(True)).props("no-caps").classes(
                        "bg-red-700 text-white")
            if not await hoi:
                return
            try:
                await asyncio.to_thread(api.delete, f"/api/hr/items/{ten}/{item['id']}")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            ui.notify("Đã xoá", type="positive")
            await chon_can_bo(state["staff_id"])

        def _sua_duoc(ten: str) -> bool:
            """Phân hệ này người đang đăng nhập có sửa được cho cán bộ đang mở không."""
            data = state["data"] or {}
            spec = meta["sections"][ten]
            la_minh = state["staff_id"] == me.get("id")
            if ten == "salaries":
                return bool(quyen["salary_edit"])
            if spec["tu_sua"] and la_minh:
                return True
            return bool(data.get("quyen", {}).get("edit_all"))

        # ── Chọn một cán bộ ──────────────────────────────────────────────────
        async def chon_can_bo(staff_id: int):
            state["staff_id"] = staff_id
            try:
                data = await asyncio.to_thread(api.get, f"/api/hr/profiles/{staff_id}")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            state["data"] = data
            khung_ho_so.clear()
            with khung_ho_so:
                khung_anh = _form_ho_so(data)
                with ui.card().classes("w-full p-0"):
                    with ui.tabs().props("dense inline-label").classes(
                            "w-full text-red-800") as tabs:
                        the = {t: ui.tab(t, label=meta["sections"][t]["nhan"])
                               for t in _THU_TU if t in data["sections"]}
                    # `value=` phải là tab đầu tiên CÒN LẠI: người không được xem
                    # lương thì phân hệ đó không có trong data["sections"].
                    if the:
                        with ui.tab_panels(tabs, value=next(iter(the.values()))
                                           ).classes("w-full"):
                            for t, tab in the.items():
                                with ui.tab_panel(tab):
                                    _ve_section(t, data["sections"][t], staff_id,
                                                _sua_duoc(t))
                if "salaries" not in data["sections"]:
                    ui.label("Hồ sơ lương bị ẩn — cần quyền «Xem hồ sơ lương của cán bộ khác»."
                             ).classes("text-xs text-amber-700")
            if data["co_anh"]:
                await _ve_anh(khung_anh, staff_id)
            await tai_danh_sach()      # tô đậm lại dòng đang chọn

        s_q.on("keydown.enter", lambda: tai_danh_sach())
        s_q.on("blur", lambda: tai_danh_sach())
        s_dept.on_value_change(lambda _e: tai_danh_sach())

        await tai_danh_sach()
        # Mở sẵn hồ sơ của chính mình: người không có quyền xem hồ sơ người khác
        # thì đây là hồ sơ duy nhất họ thao tác được. Quản trị viên KHÔNG có hồ sơ
        # (xem hr_service.ROLES_KHONG_HO_SO) — mở sẵn sẽ ra 404 ngay khi vào trang.
        if me.get("id") and not la_qtv:
            await chon_can_bo(me["id"])
        else:
            with khung_ho_so:
                with ui.card().classes("w-full p-8 items-center gap-2"):
                    ui.icon("badge").classes("text-5xl text-gray-300")
                    ui.label("Chọn một cán bộ ở danh sách bên trái để xem hồ sơ"
                             ).classes("text-gray-500")
                    ui.label("Tài khoản quản trị viên không có hồ sơ nhân sự."
                             ).classes("text-xs text-gray-400")
