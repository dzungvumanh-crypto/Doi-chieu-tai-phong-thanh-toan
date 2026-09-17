"""Đối chiếu OSB: GL02 (IPCAS, sổ cái) <-> OSB (chi tiết hạch toán) cho 1 tài khoản trung gian
OSB (VD 519910) — tìm "Chênh lệch Nợ" / "Chênh lệch Có".

Verify bằng dữ liệu thật 3 ngày (01/07, 31/07, 04/04/2026, TK 519910) trước khi viết module này —
xem `docs/Implementation-notes.html` mục "Đối chiếu OSB — spike test xác nhận offset=0" và script
spike gốc còn giữ lại tại `scratchpad` của phiên test đó.
"""
