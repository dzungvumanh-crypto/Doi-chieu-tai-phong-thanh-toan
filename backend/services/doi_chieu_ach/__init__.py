"""Đối chiếu ACH — GL02 (NPO/IPCAS) vs MIS PaymentHub.

Port từ app CLI/Flask `DOI-CHIEU-ACH`. Giữ nguyên logic nghiệp vụ B1..B8,
chỉ thay lớp vỏ: chạy nền theo token + poll tiến độ giống các module đối chiếu
khác trong hệ thống.
"""
