"""Chốt hồi quy: job ILO1000 chạy xong phải gom được file kết quả, không nổ NameError.

11/09/2026: `_run()` gọi `os.listdir(output_dir)` nhưng file không `import os` (lọt vào
từ commit 8fd8052, 01/09/2026). Mọi lượt chạy tới bước gom kết quả đều rơi vào nhánh
`except Exception` → job `error` với "name 'os' is not defined" — ILO1000 không bao giờ
trả được kết quả. Không test nào bắt được vì các test cũ đều dừng trước bước này
(file đầu vào giả → `main_from_dir` trả None). Ruff F821 bắt được bằng quét tĩnh.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ilo1000_job_thu_ket_qua.py -v
"""

import logging
from pathlib import Path

from backend.services import ilo1000_service as svc


def test_job_xong_gom_du_file_xlsx(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, 'TEMP_DIR', tmp_path)

    # ── Pipeline giả: ghi 2 file kết quả + 1 file rác, trả đường dẫn như bản thật ──
    def _gia_lap(input_dir, output_dir, log_callback, cancel_event):
        out = Path(output_dir)
        (out / 'b_ket_qua.xlsx').write_bytes(b'x')
        (out / 'a_ket_qua.xlsx').write_bytes(b'x')
        (out / 'nhat_ky.txt').write_bytes(b'x')
        return str(out / 'a_ket_qua.xlsx')

    monkeypatch.setattr(svc, 'main_from_dir', _gia_lap)

    job_id, input_dir = svc.tao_job()
    job = svc.get_job(job_id)
    try:
        svc._run(job_id, str(input_dir), job['output_dir'])

        assert job['status'] == 'done', job['error']
        assert job['files'] == ['a_ket_qua.xlsx', 'b_ket_qua.xlsx']
    finally:
        svc.bo_job(job_id)


def test_job_chay_pipeline_that_o_tien_trinh_rieng(caplog, tien_trinh_that):
    """Pipeline thật, thư mục rỗng → trả None. Log của nó phải về tới job qua ống dẫn.
    Gọi thẳng trong luồng thì hai assert đầu cũng xanh — nên kiểm thêm dòng PID tiến
    trình con do `chay_tach()` ghi. KHÔNG vá `TEMP_DIR` (tiến trình con không thấy bản vá) —
    `bo_job()` dọn thư mục job thật."""

    job_id, input_dir = svc.tao_job()
    job = svc.get_job(job_id)
    try:
        with caplog.at_level(logging.INFO, logger='backend.core.tien_trinh_doi_chieu'):
            svc._run(job_id, str(input_dir), job['output_dir'])

        assert job['status'] == 'error'
        assert 'Tổng file phát hiện: 0' in job['logs']
        assert any('tiến trình riêng' in r.getMessage() for r in caplog.records)
    finally:
        svc.bo_job(job_id)
