"""Kiểm tra sớm bộ file đầu vào ACH — dùng chung cho mode upload và mode folder.

Chỉ kiểm tra theo TÊN file (không mở nội dung) nên là gần đúng; pipeline
(`main_from_dir`) vẫn là nơi kiểm tra chặt cuối cùng khi thực sự chạy.
"""
import fnmatch
import re

_PDF_SESSION_RE = re.compile(r'_NRT_(\d+)_', re.IGNORECASE)


def _match_any(names: list[str], pattern: str) -> list[str]:
    return [n for n in names if fnmatch.fnmatch(n.lower(), pattern.lower())]


def validate_required_files(filenames: list[str]) -> dict:
    """
    Trả về {'ok': bool, 'checks': [{'label', 'ok', 'detail'}, ...]}.
    """
    checks = []

    pdfs = [n for n in filenames if n.lower().endswith('.pdf')]
    pdf_hop_le = [n for n in pdfs if _PDF_SESSION_RE.search(n)]
    if pdf_hop_le:
        checks.append({'label': 'File PDF (session)', 'ok': True,
                       'detail': f'Tìm thấy: {pdf_hop_le[0]}'})
    elif pdfs:
        checks.append({'label': 'File PDF (session)', 'ok': False,
                       'detail': f'Có {len(pdfs)} file PDF nhưng tên không đúng định dạng '
                                 f'(...NRT_<số>...): {", ".join(pdfs)}'})
    else:
        checks.append({'label': 'File PDF (session)', 'ok': False,
                       'detail': 'Thiếu file PDF chứa session (tên dạng ..._NRT_<số>_...)'})

    gl02 = _match_any(filenames, 'GL02*.zip')
    checks.append({'label': 'GL02 (.zip)', 'ok': bool(gl02),
                   'detail': f'Tìm thấy: {", ".join(gl02)}' if gl02 else 'Thiếu file GL02*.zip'})

    xlsx = [n for n in filenames if n.lower().endswith('.xlsx')]
    gw   = [n for n in xlsx if 'gw' in n.lower()]
    if gw:
        checks.append({'label': 'GW (.xlsx)', 'ok': True, 'detail': f'Tìm thấy: {gw[0]}'})
    elif xlsx:
        checks.append({'label': 'GW (.xlsx)', 'ok': True,
                       'detail': f'Không có file tên chứa "GW" — sẽ dò nội dung: {", ".join(xlsx)}'})
    else:
        checks.append({'label': 'GW (.xlsx)', 'ok': False, 'detail': 'Thiếu file GW*.xlsx'})

    mis_di = _match_any(filenames, '*_DI_*.zip')
    checks.append({
        'label': 'MIS_DI (cần 2 file .zip)', 'ok': len(mis_di) >= 2,
        'detail': f'Tìm thấy {len(mis_di)}: {", ".join(mis_di)}' if mis_di
                  else 'Thiếu file *_DI_*.zip (cần 2)',
    })

    mis_den = _match_any(filenames, '*_DEN_*.zip')
    checks.append({
        'label': 'MIS_DEN (cần 2 file .zip)', 'ok': len(mis_den) >= 2,
        'detail': f'Tìm thấy {len(mis_den)}: {", ".join(mis_den)}' if mis_den
                  else 'Thiếu file *_DEN_*.zip (cần 2)',
    })

    return {'ok': all(c['ok'] for c in checks), 'checks': checks}
