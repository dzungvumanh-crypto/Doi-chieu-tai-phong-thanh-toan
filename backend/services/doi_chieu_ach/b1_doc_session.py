"""B1 — Lấy số session từ tên file PDF sao kê ACH."""
import glob
import os
import re


def doc_session(input_dir: str, log_callback=None) -> str:
    """Tên file dạng: ACH_20260612_VBAAVNVN_NRT_15882_N03_1.pdf → session 15882."""
    pattern = os.path.join(os.path.abspath(input_dir), "**", "*.pdf")
    pdfs = sorted(glob.glob(pattern, recursive=True))
    if not pdfs:
        raise FileNotFoundError("Không tìm thấy file PDF sao kê ACH trong dữ liệu tải lên")

    ten_file = os.path.basename(pdfs[0])
    m = re.search(r"_NRT_(\d+)_", ten_file)
    if not m:
        raise ValueError(f"Không lấy được số session từ tên file PDF: {ten_file}")

    session_id = m.group(1)
    (log_callback or print)(f"[B1] Session: {session_id}  (từ file: {ten_file})")
    return session_id
