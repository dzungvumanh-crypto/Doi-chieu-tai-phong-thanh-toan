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
    "menu.reports":            "Báo cáo (menu)",
    "menu.leaves":             "Nghỉ phép (menu)",
    "menu.th_reports":         "Báo cáo dữ liệu thanh toán — Phòng TH (menu)",
    "menu.staff":              "Quản lý User (menu)",
    "menu.logs":               "Nhật ký hệ thống (menu)",

    # Bàn giao chứng từ — thao tác
    "handovers.save_entry":    "Lưu số tờ chứng từ",
    "handovers.confirm_entry": "Xác nhận cho mượn / đã nhận",
    "handovers.reject_entry":  "Từ chối bàn giao",
    "handovers.borrow":        "Mượn lại chứng từ",
    "handovers.handback":      "Bàn giao lại chứng từ",

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

    # Quản lý User — thao tác
    "staff.create":            "Tạo tài khoản mới",
    "staff.edit":              "Chỉnh sửa nhân viên",
    "staff.delete":            "Xóa nhân viên",
    "staff.export":            "Xuất Excel / DB",
    "staff.import_db":         "Nhập DB",
}

# ── Nhóm theo category cho UI phân quyền ─────────────────────────────────────
FEATURE_GROUPS: dict[str, dict] = {
    "Sidebar — Menu điều hướng": {
        "icon": "menu",
        "codes": [
            "menu.handovers",
            "menu.bundles",
            "menu.storage",
            "menu.reports",
            "menu.leaves",
            "menu.th_reports",
            "menu.staff",
            "menu.logs",
        ],
    },
    "Bàn giao chứng từ — Thao tác": {
        "icon": "receipt_long",
        "codes": [
            "handovers.save_entry",
            "handovers.confirm_entry",
            "handovers.reject_entry",
            "handovers.borrow",
            "handovers.handback",
        ],
    },
    "Đóng chứng từ — Thao tác": {
        "icon": "folder_zip",
        "codes": [
            "bundles.generate",
            "bundles.download_cover",
            "bundles.mark_printed",
            "bundles.delete",
        ],
    },
    "Nghỉ phép — Thao tác": {
        "icon": "event_busy",
        "codes": [
            "leaves.create",
            "leaves.cancel",
            "leaves.resubmit",
            "leaves.approve_ksv",
            "leaves.forward_th",
            "leaves.approve_gd",
        ],
    },
    "Quản lý User — Thao tác": {
        "icon": "manage_accounts",
        "codes": [
            "staff.create",
            "staff.edit",
            "staff.delete",
            "staff.export",
            "staff.import_db",
        ],
    },
}
