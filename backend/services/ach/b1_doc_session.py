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

    pdf_path = pdfs[0]
    ten_file = os.path.basename(pdf_path)
    m = re.search(r'_NRT_(\d+)_', ten_file)
    if not m:
        raise ValueError(f'Không thể lấy session từ tên file: {ten_file}')

    session_id = m.group(1)
    _log = log_callback or print
    _log(f'[B1] Session: {session_id}  (từ file: {ten_file})')
    return session_id
