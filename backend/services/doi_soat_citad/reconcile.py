# -*- coding: utf-8 -*-
"""
reconcile.py
------------
Port thuật toán đối soát từ `DoiSoatCITAD.py::run_doiSoat_ram` của tool
desktop gốc — quy tắc nghiệp vụ cốt lõi ĐÃ DUYỆT và giữ nguyên khi port:
khớp theo msgref (Đi) / txid (Đến), ưu tiên trạng thái IPCAS Đến theo
PRIORITY_TT khi trùng txid, chỉ nhận SCNL là thành công cho lệnh Đi (khác đi
→ 'lech_trang_thai'), bỏ PYED/PYEK khi tính dư IPCAS Đến.

Ghi chú review (phát hiện khi chuẩn bị PR, ĐÃ SỬA — không phải thay đổi quy
tắc nghiệp vụ đã duyệt): bản gốc có 1 nhánh "phân biệt theo nh_nhan khi
msgref trùng" (map phụ `ipcas_di_map2`) nhưng chưa từng chạy được — map phụ
được dựng từ CÙNG vòng lặp, CÙNG thứ tự với map chính nên luôn suy ra lại
đúng map chính (dict đầu tiên theo msgref thắng ở cả 2 map); hơn nữa dữ liệu
CITAD parse ra (`parsers.py`) không có field `nh_nhan` nên không có gì để so
khớp. Đã bỏ hẳn map phụ chết này thay vì giữ code không chạy — hành vi khớp
lệnh KHÔNG đổi (map phụ chưa bao giờ ảnh hưởng tới kết quả).
"""
from __future__ import annotations

PRIORITY_TT = {'PYED': 0, 'PYEK': 1, 'WFPG': 2, 'RFED': 3, 'SDEB': 4, 'SBFL': 5, 'SBSC': 6}
VALID_DI = {'SCNL'}  # Đi: chỉ SCNL là thành công


def run_doiSoat_ram(citad_rows, ipcas_rows, hub_rows):
    """Đối soát trong RAM bằng dict Python — xem docstring module để biết
    quy tắc khớp lệnh và ghi chú về nhánh dead-code đã bỏ khi chuẩn bị PR."""
    # Build map IPCAS Đi/Đến — msgref/txid -> row (bản ghi đầu tiên thắng
    # nếu trùng, trừ Đến ưu tiên theo PRIORITY_TT bên dưới)
    ipcas_di_map = {}
    ipcas_den_map = {}
    for r in ipcas_rows:
        if r['chieu'] == 'di':
            k = r['msgref']
            if not k:
                continue
            if k not in ipcas_di_map:
                ipcas_di_map[k] = r
        else:
            k = r['txid']
            if not k:
                continue
            if k not in ipcas_den_map:
                ipcas_den_map[k] = r
            else:
                cur_pri = PRIORITY_TT.get(ipcas_den_map[k]['trang_thai'], 99)
                new_pri = PRIORITY_TT.get(r['trang_thai'], 99)
                if new_pri < cur_pri:
                    ipcas_den_map[k] = r

    # Build map Hub
    hub_di_map = {}
    hub_den_map = {}
    for r in hub_rows:
        k = r['so_gd']
        if r['chieu'] == 'di':
            if k not in hub_di_map:
                hub_di_map[k] = r
        else:
            if k not in hub_den_map:
                hub_den_map[k] = r

    n_khop = 0
    lech = []
    citad_matched_di = set()
    citad_matched_den = set()

    for r in citad_rows:
        sogd = r['so_gd']
        chieu = r['chieu']
        lt = r['loai_tien']

        if lt != 'VND':
            # Ngoại tệ: khớp Hub
            m = hub_di_map.get(sogd) if chieu == 'di' else hub_den_map.get(sogd)
            if m:
                n_khop += 1
                if chieu == 'di':
                    citad_matched_di.add(sogd)
                else:
                    citad_matched_den.add(sogd)
            else:
                lech.append({**r, 'status': 'only_citad', 'key_agri': '', 'nh_nhan': '', 'trang_thai': ''})

        elif chieu == 'di':
            # VND Đi: tìm theo msgref
            m = ipcas_di_map.get(sogd)
            if m:
                citad_matched_di.add(sogd)
                tt = m.get('trang_thai', '')
                if tt in VALID_DI:
                    # Khớp hoàn toàn
                    n_khop += 1
                else:
                    # Có ở cả 2 bên nhưng IPCAS chưa SCNL → lệch trạng thái
                    lech.append({
                        **r,
                        'status': 'lech_trang_thai',
                        'key_agri': m.get('msgref', sogd),
                        'nh_nhan': m.get('nh_nhan', ''),
                        'trang_thai': tt,
                    })
            else:
                lech.append({**r, 'status': 'only_citad', 'key_agri': '', 'nh_nhan': '', 'trang_thai': ''})

        else:
            # VND Đến: giữ nguyên như cũ, không check trạng thái
            m = ipcas_den_map.get(sogd)
            if m:
                n_khop += 1
                citad_matched_den.add(sogd)
            else:
                lech.append({**r, 'status': 'only_citad', 'key_agri': '', 'nh_nhan': '', 'trang_thai': ''})

    # IPCAS Đi dư
    for k, r in ipcas_di_map.items():
        if k not in citad_matched_di:
            lech.append({
                'so_gd': k, 'dich_vu': r.get('kenh', ''), 'loai': r.get('loai', ''),
                'chieu': 'di', 'loai_tien': 'VND', 'so_tien': r.get('so_tien', 0),
                'ngay': r.get('ngay', ''), 'status': 'only_ipcas',
                'key_agri': k, 'nh_nhan': r.get('nh_nhan', ''), 'trang_thai': r.get('trang_thai', ''),
            })

    # IPCAS Đến dư - bỏ PYED/PYEK
    for k, r in ipcas_den_map.items():
        if r.get('trang_thai') in ('PYED', 'PYEK'):
            continue
        if k not in citad_matched_den:
            lech.append({
                'so_gd': k, 'dich_vu': r.get('kenh', ''), 'loai': r.get('loai', ''),
                'chieu': 'den', 'loai_tien': 'VND', 'so_tien': r.get('so_tien', 0),
                'ngay': r.get('ngay', ''), 'status': 'only_ipcas',
                'key_agri': k, 'nh_nhan': r.get('nh_nhan', ''), 'trang_thai': r.get('trang_thai', ''),
            })

    # Hub dư
    for k, r in hub_di_map.items():
        if k not in citad_matched_di:
            lech.append({**r, 'so_gd': k, 'status': 'only_hub', 'key_agri': k, 'trang_thai': ''})
    for k, r in hub_den_map.items():
        if k not in citad_matched_den:
            lech.append({**r, 'so_gd': k, 'status': 'only_hub', 'key_agri': k, 'trang_thai': ''})

    return n_khop, lech
