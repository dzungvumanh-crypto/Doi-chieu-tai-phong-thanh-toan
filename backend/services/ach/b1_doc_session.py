import re
import glob
import os


def doc_session(input_dir: str, log_callback=None) -> str:
    """
    Tìm file PDF trong input_dir (đệ quy), lấy số session từ tên file.
    Tên file dạng: ACH_20260612_VBAAVNVN_NRT_15882_N03_1.pdf
    """
    pattern = os.path.join(os.path.abspath(input_dir), '**', '*.pdf')
    pdfs = sorted(glob.glob(pattern, recursive=True))
    if not pdfs:
        raise FileNotFoundError(f'Không tìm thấy file PDF trong {input_dir}')

    _log = log_callback or print
    # Audit 2026-08-04 — trước đây chọn PDF đầu tiên theo thứ tự sort tên mà không
    # cảnh báo khi có ≥2 file ứng viên (đã từng gây chọn nhầm PDF thật trên dữ liệu
    # 16.7, xem project_ach_timeout_rule.md 2026-07-23). session_id quyết định lọc
    # TOÀN BỘ MIS_đi/đến/GW ở các bước sau — chọn nhầm sẽ sai lệch cả kết quả mà
    # không có dấu hiệu gì trong log để chẩn đoán. CHƯA sửa logic chọn (cần quyết
    # định nghiệp vụ tiêu chí đúng là gì) — chỉ thêm cảnh báo để không còn im lặng.
    if len(pdfs) > 1:
        _log(f'[B1][WARN] Có {len(pdfs)} file PDF trong thư mục, đang lấy file đầu '
             f'theo thứ tự tên: {[os.path.basename(p) for p in pdfs]}')

    pdf_path = pdfs[0]
    ten_file = os.path.basename(pdf_path)
    m = re.search(r'_NRT_(\d+)_', ten_file)
    if not m:
        raise ValueError(f'Không thể lấy session từ tên file: {ten_file}')

    session_id = m.group(1)
    _log(f'[B1] Session: {session_id}  (từ file: {ten_file})')
    return session_id
