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
# ERPO/CALD = IPCAS báo lệnh Đi thất bại/huỷ. Nếu CITAD KHÔNG có lệnh này
# thì đúng bản chất (chưa từng đi kênh) — không phải bất thường. Nhưng nếu
# CITAD VẪN CÓ (đi kênh thành công thật) thì IPCAS đang sai — bất thường
# thật, phải bắt vào 'lech_trang_thai' kèm ghi chú rõ (xem bên dưới và vòng
# lặp "IPCAS Đi dư").
ERR_DI = {'ERPO', 'CALD'}
# Ưu tiên khi 1 msgref có NHIỀU dòng IPCAS Đi — số nhỏ thắng.
# Cần từ khi ERR_DI được giữ lại khi parse: trước đó chỉ có trạng thái thành
# công/đang xử lý nên "dòng đầu tiên thắng" vô hại, nay một msgref có thể có
# cả ERPO/CALD lẫn SCNL và dòng đầu tiên là dòng nào thì phụ thuộc THỨ TỰ
# DÒNG TRONG FILE — mà thứ tự đó đổi được thật (người dùng chọn file theo thứ
# tự khác, hoặc thứ tự entry trong ZIP khác). Đã đo: cùng dữ liệu, ERPO đứng
# trước cho n_khop=0, SCNL đứng trước cho n_khop=1. Một cỗ máy đối soát không
# được phụ thuộc thứ tự đọc, nên cho SCNL luôn thắng. Cùng khuôn mẫu với
# PRIORITY_TT của chiều Đến ngay bên dưới.
PRIORITY_DI = {'SCNL': 0}


def run_doiSoat_ram(citad_rows, ipcas_rows, hub_rows):
    """Đối soát trong RAM bằng dict Python — xem docstring module để biết
    quy tắc khớp lệnh và ghi chú về nhánh dead-code đã bỏ khi chuẩn bị PR."""
    # Build map IPCAS Đi/Đến — msgref/txid -> row. Đi ưu tiên theo PRIORITY_DI,
    # Đến ưu tiên theo PRIORITY_TT (cả hai bên dưới) — không bên nào để "dòng
    # đầu tiên thắng" thuần tuý, vì thứ tự dòng trong file không ổn định.
    ipcas_di_map = {}
    ipcas_den_map = {}
    for r in ipcas_rows:
        if r['chieu'] == 'di':
            k = r['msgref']
            if not k:
                continue
            if k not in ipcas_di_map:
                ipcas_di_map[k] = r
            elif (PRIORITY_DI.get(r['trang_thai'], 9)
                  < PRIORITY_DI.get(ipcas_di_map[k]['trang_thai'], 9)):
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

    # Phát hiện CITAD gửi TRÙNG cùng 1 so_gd cho lệnh Đi VND — bug thật đã
    # xác nhận qua test thực tế (và có sẵn trong bản gốc citad-fixed): vòng
    # lặp bên dưới chạy theo TỪNG DÒNG CITAD, không loại trùng trước khi
    # khớp, nên 1 so_gd trùng N lần mà IPCAS chỉ có 1 bản ghi sẽ bị tính
    # "khớp" thêm N-1 lần một cách im lặng. Chỉ áp dụng lệnh Đi theo yêu cầu
    # — đếm TRƯỚC vòng lặp chính, dùng `di_vnd_seen` để chỉ dòng ĐẦU TIÊN
    # của mỗi so_gd trùng đi qua khớp lệnh bình thường (không đổi kết quả
    # khớp/lệch cho trường hợp không trùng), các dòng trùng SAU đó tách
    # riêng thành lệch 'dup_citad', không tính khớp.
    di_vnd_count = {}
    di_vnd_congs = {}
    for r in citad_rows:
        if r['chieu'] == 'di' and r['loai_tien'] == 'VND':
            k = r['so_gd']
            di_vnd_count[k] = di_vnd_count.get(k, 0) + 1
            di_vnd_congs.setdefault(k, []).append(r.get('cong') or '?')
    di_vnd_seen = set()

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
            if sogd in di_vnd_seen:
                n_dup = di_vnd_count.get(sogd, 1)
                congs = ', '.join(sorted(set(di_vnd_congs.get(sogd, [])), key=lambda x: (len(x), x)))
                lech.append({
                    **r,
                    'status': 'dup_citad', 'key_agri': '', 'nh_nhan': '', 'trang_thai': '',
                    'ghi_chu': f'Phát hiện lệnh đi kênh bị dup {n_dup} lần, cổng {congs}',
                })
                continue
            di_vnd_seen.add(sogd)
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
                    row = {
                        **r,
                        'status': 'lech_trang_thai',
                        'key_agri': m.get('msgref', sogd),
                        'nh_nhan': m.get('nh_nhan', ''),
                        'trang_thai': tt,
                    }
                    if tt in ERR_DI:
                        row['ghi_chu'] = (
                            f'IPCAS ghi nhận {tt} (thất bại) nhưng lệnh THỰC TẾ đã '
                            f'đi kênh CITAD thành công — cần kiểm tra lại'
                        )
                    lech.append(row)
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

    # IPCAS Đi dư - bỏ ERPO/CALD không khớp CITAD (thất bại bình thường,
    # chưa từng đi kênh — không phải chênh lệch cần xử lý, xem ERR_DI)
    for k, r in ipcas_di_map.items():
        if r.get('trang_thai') in ERR_DI:
            continue
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
