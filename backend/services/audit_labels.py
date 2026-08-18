"""Dịch dòng audit thô (method + path + mã HTTP) sang mô tả tiếng Việt dễ đọc.

Nguồn duy nhất dùng chung cho cả trang xem lẫn xuất Excel — sửa nhãn 1 chỗ.
"""
import re

_ID_RE = re.compile(r"/\d+")


def _norm(path: str) -> str:
    """Chuẩn hóa path: mọi đoạn toàn số (ID, năm) → /{id} để tra bảng."""
    return _ID_RE.sub("/{id}", path or "")


# ── Hành động ngữ nghĩa (do write_audit ghi trực tiếp) ───────────────────────
_SEMANTIC = {
    "staff_create":    "Tạo tài khoản người dùng",
    "staff_update":    "Cập nhật tài khoản người dùng",
    "staff_delete":    "Xóa tài khoản người dùng",
    "staff_import_db": "Nhập người dùng từ file",
    "staff_export":    "Xuất danh sách cán bộ ra Excel",
    "staff_export_db": "Xuất file DB người dùng (có mã băm mật khẩu)",
    "password_reset":  "Đặt lại mật khẩu người dùng",
    "signature_upload": "Tải lên ảnh chữ ký",
    "signature_delete": "Xóa ảnh chữ ký",
    "staff_import_join_dates": "Nhập Ngày vào ngành từ Excel",
    "staff_join_date_update":  "Sửa Ngày vào ngành (màn hình quỹ phép)",
    "db_backup_download":      "Tải bản sao cơ sở dữ liệu",
}

# ── Ánh xạ "METHOD /path_chuẩn_hóa" → mô tả công việc ────────────────────────
_WORK = {
    # Đóng tập chứng từ
    "POST /api/bundles/generate":                 "Đóng tập chứng từ",
    "PUT /api/bundles/{id}":                       "Sửa tập chứng từ",
    "POST /api/bundles/{id}/mark-printed":         "Đánh dấu đã in bìa tập",
    "POST /api/bundles/groups/{id}/mark-printed":  "Đánh dấu đã in bìa (cả nhóm)",
    "PATCH /api/bundles/storage-view":             "Cập nhật lưu trữ tập chứng từ",
    "DELETE /api/bundles/groups/{id}":             "Xóa nhóm tập chứng từ",
    # Bàn giao chứng từ
    "PUT /api/handovers/entry-upsert":                        "Nhập/cập nhật bàn giao chứng từ",
    "POST /api/handovers/entries/{id}/confirm-received":      "Xác nhận đã nhận chứng từ",
    "POST /api/handovers/entries/{id}/borrow":               "Mượn chứng từ",
    "POST /api/handovers/entries/{id}/handback":             "Trả lại chứng từ đã mượn",
    "POST /api/handovers/entries/{id}/confirm-returned":     "Xác nhận chứng từ đã trả",
    "POST /api/handovers/entries/{id}/reject":               "Từ chối bàn giao chứng từ",
    "POST /api/handovers/entries/{id}/resubmit":             "Gửi lại bàn giao chứng từ",
    "POST /api/handovers/entries/{id}/return-to-staff":      "Chuyển trả chứng từ cho GDV",
    # Nghỉ phép
    "POST /api/leaves/":                          "Tạo đơn nghỉ phép",
    "DELETE /api/leaves/{id}":                    "Xóa đơn nghỉ phép",
    "PUT /api/leaves/{id}/ksv-review":            "KSV duyệt đơn nghỉ phép",
    "POST /api/leaves/{id}/tong-hop-review":      "Tổng hợp duyệt đơn nghỉ phép",
    "PUT /api/leaves/{id}/gd-review":             "Giám đốc duyệt đơn nghỉ phép",
    "PUT /api/leaves/{id}/resubmit":              "Gửi lại đơn nghỉ phép",
    "PATCH /api/leaves/{id}/cancel":              "Hủy đơn nghỉ phép",
    "POST /api/leaves/quotas":                    "Đặt quỹ ngày phép",
    # Giữ lại cho các dòng ghi TRƯỚC khi endpoint này có write_audit ngữ nghĩa
    # riêng — từ nay AuditMiddleware bỏ qua nó, xem _SKIP_EXACT ở audit_middleware.
    "PATCH /api/leaves/quotas/staff/{id}/join-date": "Sửa ngày vào ngành (quỹ phép)",
    "PATCH /api/leaves/quotas/staff/{id}/used-days": "Sửa số ngày phép đã dùng",
    "POST /api/leaves/direct":                    "Tạo nghỉ phép trực tiếp",
    "POST /api/leaves/{id}/recall":               "Thu hồi đơn nghỉ phép",
    "PUT /api/leaves/{id}/recall-approve":        "Duyệt thu hồi nghỉ phép",
    # Nhóm & phân quyền
    "POST /api/groups":                           "Tạo nhóm người dùng",
    "PUT /api/groups/{id}":                       "Sửa nhóm người dùng",
    "DELETE /api/groups/{id}":                    "Xóa nhóm người dùng",
    "POST /api/groups/{id}/members":              "Thêm thành viên vào nhóm",
    "DELETE /api/groups/{id}/members/{id}":       "Xóa thành viên khỏi nhóm",
    "PUT /api/groups/{id}/features":              "Cập nhật phân quyền nhóm",
    # Ngày lễ
    "POST /api/admin/holidays/":                  "Thêm ngày lễ",
    "DELETE /api/admin/holidays/{id}":            "Xóa ngày lễ",
    # Phân ca trực — lịch
    "POST /api/duty/schedule/generate-week":      "Xếp ca trực (tuần)",
    "POST /api/duty/schedule/generate-month":     "Xếp ca trực (tháng)",
    "PUT /api/duty/schedule/{id}":                "Sửa ca trực",
    "POST /api/duty/schedule/{id}/confirm":       "Chốt ca trực",
    "POST /api/duty/schedule/{id}/unconfirm":     "Bỏ chốt ca trực",
    "POST /api/duty/schedule/confirm-week":       "Chốt ca trực cả tuần",
    "DELETE /api/duty/schedule/week":             "Xóa ca trực cả tuần",
    "DELETE /api/duty/schedule/{id}":             "Xóa ca trực",
    "POST /api/duty/schedule/rotation/reset":     "Đặt lại luân phiên trực",
    # Phân ca trực — ràng buộc
    "POST /api/duty/constraints/absences":        "Đăng ký vắng (trực)",
    "POST /api/duty/constraints/absences/range":  "Đăng ký vắng nhiều ngày (trực)",
    "DELETE /api/duty/constraints/absences/range": "Xóa đăng ký vắng nhiều ngày (trực)",
    "DELETE /api/duty/constraints/absences/{id}": "Xóa đăng ký vắng (trực)",
    "POST /api/duty/constraints/requests":        "Đăng ký nguyện vọng trực",
    "DELETE /api/duty/constraints/requests/{id}": "Xóa nguyện vọng trực",
    "POST /api/duty/constraints/special-days":    "Thêm ngày đặc biệt (trực)",
    "POST /api/duty/constraints/special-days/{id}/confirm": "Chốt ngày đặc biệt (trực)",
    "DELETE /api/duty/constraints/special-days/{id}":       "Xóa ngày đặc biệt (trực)",
    "POST /api/duty/constraints/special-days/compute-cutoff": "Tính ngày chốt đặc biệt (trực)",
    "POST /api/duty/constraints/special-days/seed-holidays":  "Nạp ngày lễ vào lịch trực",
    "PUT /api/duty/constraints/shift-config/{id}": "Cấu hình ca trực theo năm",
    "POST /api/duty/staff/{id}/meta":             "Cập nhật thông tin cán bộ trực",
    # Báo cáo
    "POST /api/th-reports/generate":              "Tạo báo cáo Tổng hợp",
    "POST /api/reports/parse-gdv":                "Đọc dữ liệu GDV (báo cáo hậu kiểm)",
    "POST /api/reports/parse-hkv":                "Đọc dữ liệu HKV (báo cáo hậu kiểm)",
    "POST /api/reports/generate-dept":            "Tạo báo cáo hậu kiểm theo phòng",
    "POST /api/reports/generate-word":            "Xuất báo cáo hậu kiểm (Word)",
    "POST /api/reports/generate-dept-zip":        "Xuất báo cáo hậu kiểm các phòng (ZIP)",
    # Ủy quyền
    "POST /api/delegations/":                     "Tạo ủy quyền duyệt",
    "PATCH /api/delegations/{id}/deactivate":     "Ngừng ủy quyền duyệt",
    # Đối chiếu
    "POST /api/cham459901/process":               "Chấm đối chiếu 459901",
    "POST /api/doi_chieu_song_phuong/process":    "Đối chiếu song phương",
    "POST /api/ach/start":                        "Chạy đối chiếu ACH",
    "POST /api/ach/continue/{job_id}":            "Tiếp tục ACH sau Checkpoint MIS_đi",
    "POST /api/ach/cancel/{job_id}":              "Dừng đối chiếu ACH",
    "POST /api/swift-recon/parse-preview":        "Xem trước dữ liệu SWIFT",
    "POST /api/swift-recon/reconcile-den":        "Đối chiếu SWIFT (điện đến)",
    "POST /api/swift-recon/reconcile-di":         "Đối chiếu SWIFT (điện đi)",
    "POST /api/swift-recon/export-summary":       "Xuất tổng hợp đối chiếu SWIFT",
    "POST /api/swift-recon/export-diff":          "Xuất chênh lệch đối chiếu SWIFT",
    "POST /api/swift-recon/export-filtered":      "Xuất dữ liệu SWIFT đã lọc",
}

# ── Fallback: tên module theo prefix + động từ theo method ────────────────────
_MODULE = [
    ("/api/handover-reports",      "báo cáo bàn giao"),
    ("/api/handovers",             "bàn giao chứng từ"),
    ("/api/bundles",               "tập chứng từ"),
    ("/api/leaves",                "nghỉ phép"),
    ("/api/delegations",           "ủy quyền"),
    ("/api/admin/holidays",        "ngày lễ"),
    ("/api/groups",                "nhóm & phân quyền"),
    ("/api/duty",                  "phân ca trực"),
    ("/api/swift-recon",           "đối chiếu SWIFT"),
    ("/api/doi_chieu_song_phuong", "đối chiếu song phương"),
    ("/api/ach",                   "đối chiếu ACH"),
    ("/api/cham459901",            "chấm 459901"),
    ("/api/th-reports",            "báo cáo Tổng hợp"),
    ("/api/reports",               "báo cáo hậu kiểm"),
    ("/api/departments",           "phòng ban"),
]
_VERB = {"POST": "Thực hiện", "PUT": "Cập nhật", "PATCH": "Cập nhật", "DELETE": "Xóa"}


def describe_work(action: str, target_type: str) -> str:
    """Mô tả 'công việc đã làm' bằng tiếng Việt dễ đọc."""
    if action in _SEMANTIC:
        return _SEMANTIC[action]
    key = f"{action} {_norm(target_type)}"
    if key in _WORK:
        return _WORK[key]
    # Chưa map: động từ + tên module (còn hơn hiện path thô)
    for prefix, name in _MODULE:
        if (target_type or "").startswith(prefix):
            return f"{_VERB.get(action, action)} — {name}"
    return f"{_VERB.get(action, action)} {target_type or ''}".strip()


def describe_result(detail: str, action: str) -> str:
    """Dịch mã HTTP trong detail sang kết quả tiếng Việt."""
    if action in _SEMANTIC:
        return "Thành công"           # write_audit chỉ ghi khi thao tác thành công
    m = re.search(r"HTTP\s+(\d+)", detail or "")
    if not m:
        return detail or "—"
    code = int(m.group(1))
    if code < 300:
        return "Thành công"
    if code == 401:
        return "Chưa đăng nhập"
    if code == 403:
        return "Không đủ quyền"
    if code == 409:
        return "Trùng / xung đột dữ liệu"
    if code == 422:
        return "Dữ liệu không hợp lệ"
    if 400 <= code < 500:
        return "Yêu cầu không hợp lệ"
    if code >= 500:
        return "Lỗi hệ thống"
    return f"Mã {code}"


def result_ok(detail: str, action: str) -> bool:
    """True nếu kết quả là thành công (để tô màu)."""
    if action in _SEMANTIC:
        return True
    m = re.search(r"HTTP\s+(\d+)", detail or "")
    return bool(m) and int(m.group(1)) < 300
