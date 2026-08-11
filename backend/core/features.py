"""Feature codes cho hệ thống phân quyền theo nhóm.

Mỗi code map tới 1 tính năng UI cụ thể. Backend RBAC (deps.py) không thay đổi.
Admin role luôn bypass toàn bộ feature check.
"""

# ── Feature codes ─────────────────────────────────────────────────────────────
# format: "category.action" — lowercase, dấu chấm phân cách

FEATURES: dict[str, str] = {
    # Sidebar menus
    "menu.handovers":          "Bàn giao chứng từ (menu)",
    "menu.bundles":            "Đóng chứng từ (menu)",
    "menu.storage":            "Lưu trữ (menu)",
    # Giữ nguyên code "menu.reports" — đổi code sẽ mất quyền đã gán trong group_features
    "menu.reports":            "Báo cáo hậu kiểm (menu)",
    "menu.handover_reports":   "Báo cáo bàn giao chứng từ (menu)",
    "menu.leaves":             "Nghỉ phép (menu)",
    "menu.th_reports":         "Báo cáo dữ liệu thanh toán — Phòng TH (menu)",
    "menu.staff":              "Quản lý User (menu)",
    "menu.logs":               "Nhật ký hệ thống (menu)",
    "menu.ttqt_branches":      "Danh sách CN TTQT (menu)",

    # Bàn giao chứng từ — thao tác
    "handovers.save_entry":    "Lưu số tờ chứng từ",
    "handovers.confirm_entry": "Xác nhận cho mượn / đã nhận",
    "handovers.reject_entry":  "Từ chối bàn giao",
    "handovers.borrow":        "Mượn lại chứng từ",
    "handovers.handback":      "Bàn giao lại chứng từ",
    "handovers.return_entry":  "Trả lại chứng từ cho cán bộ",

    # Đóng chứng từ — thao tác
    "bundles.generate":        "Tạo bìa chứng từ",
    "bundles.download_cover":  "Tải xuống bìa",
    "bundles.mark_printed":    "Đánh dấu đã in",
    "bundles.delete":          "Xóa nhóm bìa",

    # Nghỉ phép — thao tác
    "leaves.create":           "Tạo đơn nghỉ phép",
    "leaves.cancel":           "Huỷ đơn nghỉ phép",
    "leaves.resubmit":         "Sửa & Nộp lại đơn",
    "leaves.approve_ksv":      "Duyệt / Từ chối (bước KSV)",
    "leaves.forward_th":       "Chuyển GĐ/PGĐ / Từ chối (bước Tổng hợp)",
    "leaves.approve_gd":       "Duyệt / Từ chối (bước Giám đốc)",
    "leaves.dashboard":        "Dashboard nghỉ phép (tổng quan + thống kê)",
    "leaves.quota_admin":      "Quản lý hạn mức phép theo năm",
    "leaves.stats_export":     "Xuất báo cáo tổng hợp phép năm",
    "leaves.declare_direct":   "Khai báo hộ nghỉ phép",
    "leaves.recall":           "Rút đơn nhiều cấp",

    # Danh sách CN TTQT — thao tác
    "ttqt_branches.create":    "Thêm chi nhánh",
    "ttqt_branches.edit":      "Sửa chi nhánh",
    "ttqt_branches.delete":    "Xoá chi nhánh",
    "ttqt_branches.import":    "Nhập danh sách từ Excel",
    "ttqt_branches.export":    "Xuất danh sách ra Excel",

    # Quản lý User — thao tác
    "staff.create":            "Tạo tài khoản mới",
    "staff.edit":              "Chỉnh sửa nhân viên",
    "staff.delete":            "Xóa nhân viên",
    "staff.export":            "Xuất Excel / DB",
    "staff.import_db":         "Nhập DB",

    # Phân lịch trực — Phòng Thanh toán
    "menu.duty_schedule":      "Phân lịch trực — Phòng Thanh toán (menu)",
    "duty.generate":           "Tạo lịch trực tự động",
    "duty.confirm":            "Xác nhận lịch trực",
    "duty.delete":             "Xóa lịch trực",
    "duty.export":             "Xuất Excel lịch trực",
    "duty.manage_staff":       "Quản lý nhân viên phân lịch (can_do_sp, is_on_project...)",
    "duty.manage_config":      "Cài đặt ca trực / ngày đặc biệt",

    # Chấm 459901 — Phòng Thanh toán
    "menu.cham_459901":    "Chấm 459901 — Phân loại bút toán TK 459901 (menu)",
    "cham_459901.process": "Xử lý file ZIP 459901",

    # Đối chiếu Song phương — Phòng Thanh toán
    "menu.doi_chieu_song_phuong":    "Đối chiếu Song phương — Định tuyến lệnh IPCAS (menu)",
    "doi_chieu_song_phuong.process": "Xử lý file ZIP Đối chiếu Song phương",
    # Đối chiếu ACH — Phòng Thanh toán
    "menu.doi_chieu_ach":       "Đối chiếu ACH — GL02 ↔ MIS (menu)",
    "doi_chieu_ach.process":    "Chạy đối chiếu ACH",
    # Đối chiếu CITAD ↔ PaymentHub — Phòng Thanh toán
    # Nhãn phải khớp tên menu ở frontend/shared.py, phần mô tả sau dấu — mới
    # nói rõ đối chiếu/đối soát với hệ thống nào.
    "menu.doi_chieu_citad":     "Đối chiếu CITAD cuối ngày — CITAD ↔ PaymentHub (menu)",
    # Đối soát CITAD ↔ IPCAS — Phòng Thanh toán
    "menu.doi_soat_citad":      "Đối soát chênh lệch CITAD cuối ngày — CITAD ↔ IPCAS (menu)",
    # Đối chiếu điện SWIFT — SWIFT
    "menu.swift_recon":        "Đối chiếu điện SWIFT — Phòng Swift (menu)",
}

# ── Cấu trúc phân cấp: Phòng → Menu → Action ─────────────────────────────────
# Thêm phòng/menu/action mới tại đây — group_features.py tự render theo.
# "actions": [] = menu hiển thị checkbox đơn, không có sub-items.
FEATURE_GROUPS: list[dict] = [
    {
        "dept": "Phòng KSNB & HTVH",
        "icon": "account_balance",
        "menus": [
            {
                "code": "menu.handovers",
                "actions": [
                    "handovers.save_entry",
                    "handovers.confirm_entry",
                    "handovers.reject_entry",
                    "handovers.borrow",
                    "handovers.handback",
                    "handovers.return_entry",
                ],
            },
            {
                "code": "menu.bundles",
                "actions": [
                    "bundles.generate",
                    "bundles.download_cover",
                    "bundles.mark_printed",
                    "bundles.delete",
                ],
            },
            {"code": "menu.storage",  "actions": []},
            {"code": "menu.reports",  "actions": []},
            {"code": "menu.handover_reports", "actions": []},
            {
                "code": "menu.ttqt_branches",
                "actions": [
                    "ttqt_branches.create",
                    "ttqt_branches.edit",
                    "ttqt_branches.delete",
                    "ttqt_branches.import",
                    "ttqt_branches.export",
                ],
            },
        ],
    },
    {
        "dept": "Phòng Tổng hợp",
        "icon": "summarize",
        "menus": [
            {
                "code": "menu.leaves",
                "actions": [
                    "leaves.create",
                    "leaves.cancel",
                    "leaves.resubmit",
                    "leaves.approve_ksv",
                    "leaves.forward_th",
                    "leaves.approve_gd",
                    "leaves.dashboard",
                    "leaves.quota_admin",
                    "leaves.stats_export",
                    "leaves.declare_direct",
                    "leaves.recall",
                ],
            },
            {"code": "menu.th_reports", "actions": []},
        ],
    },
    {
        "dept": "Phòng Thanh toán",
        "icon": "payments",
        "menus": [
            {
                "code": "menu.duty_schedule",
                "actions": [
                    "duty.generate",
                    "duty.confirm",
                    "duty.delete",
                    "duty.export",
                    "duty.manage_staff",
                    "duty.manage_config",
                ],
            },
            {
                "code": "menu.cham_459901",
                "actions": ["cham_459901.process"],
            },
            {
                "code": "menu.doi_chieu_song_phuong",
                "actions": ["doi_chieu_song_phuong.process"],
            },
            {
                "code": "menu.doi_chieu_ach",
                "actions": ["doi_chieu_ach.process"],
            },
            {"code": "menu.doi_chieu_citad", "actions": []},
            {"code": "menu.doi_soat_citad", "actions": []},
        ],
    },
    {
        "dept": "Quản lý hệ thống",
        "icon": "admin_panel_settings",
        "menus": [
            {
                "code": "menu.staff",
                "actions": [
                    "staff.create",
                    "staff.edit",
                    "staff.delete",
                    "staff.export",
                    "staff.import_db",
                ],
            },
            {"code": "menu.logs", "actions": []},
        ],
    },
    {
        "dept": "Phòng Swift",
        "icon": "swap_horiz",
        "menus": [
            {"code": "menu.swift_recon", "actions": []},
        ],
    },
]
