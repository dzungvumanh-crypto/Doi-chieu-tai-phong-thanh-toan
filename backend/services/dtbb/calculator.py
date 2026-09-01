"""Logic tính DTBB — nhóm tài khoản theo CV 2353/NHNo-KHNV (kèm TT30/2019/TT-NHNN),
quy đổi tỷ giá. Danh mục tài khoản + cách quy đổi đã được thảo luận và verify bằng
dữ liệu thật (xem plan lúc thiết kế) — không tự ý đổi mã tài khoản ở đây.

Công thức quy đổi tỷ giá (xác nhận bằng cách dò ngược số liệu tay thật của Kế toán,
khớp sát 0,0007–0,0013% — xem docs/Implementation-notes.html):
    rate_to_vnd(ngoại tệ) = bsrt(ngoại tệ)  — tỷ giá BÌNH QUÂN mua-bán chuyển khoản
                             hoặc taxrt(ngoại tệ) nếu bsrt = 0 (fallback)
    rate_usd_to_vnd        = ttbuyrt(USD)   — tỷ giá MUA chuyển khoản của USD
                             hoặc taxrt(USD) nếu ttbuyrt = 0 (fallback)
    rate_to_usd(ngoại tệ) = rate_to_vnd(ngoại tệ) / rate_usd_to_vnd
Bản cũ dùng taxrt/taxrt cho mọi mã tiền — SAI khác công thức thật đang dùng, và một
số kỳ taxrt = 0 cho toàn bộ/một phần mã tiền khiến bản cũ raise lỗi chặn hết. Bản
này: mã tiền nào không quy đổi được (cả bsrt lẫn taxrt đều 0) thì bỏ qua đóng góp
của riêng mã đó, liệt vào DtbbResult.unconverted_ccy — không âm thầm mất số, không
chặn các mã tiền khác đã có tỷ giá hợp lệ.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.dtbb.reader import (
    DtbbFileError,
    extract_report_date_and_branch,
    read_balance_file,
    read_tygia_file,
    sniff_file_type,
)

# ── Danh mục tài khoản DTBB (phụ lục CV 2353/NHNo-KHNV) ──────────────────────
GROUP1 = ['401', '4211', '4214', '421201', '4251', '4254', '425201', '4231', '423201',
          '423803', '423808', '423809', '423821', '431001', '431002', '431009', '432001', '433001']
GROUP2_DIRECT = ['421202', '421203', '425202', '425203', '431041', '431042', '432002', '433002']
EXCL_423 = ['4231', '423201', '423803', '423808', '423809', '423821']
EXCL_431 = ['431001', '431002', '431009', '431041', '431042']


def compute_native_groups(balances: dict[str, float]) -> tuple[float, float, float]:
    """(group1, group2, tk413) nguyên tệ từ {Acctcd: afterbal_cr} của 1 file cân đối."""
    g1 = sum(balances.get(c, 0.0) for c in GROUP1)
    g2 = sum(balances.get(c, 0.0) for c in GROUP2_DIRECT)
    g2 += balances.get('423', 0.0) - sum(balances.get(c, 0.0) for c in EXCL_423)
    g2 += balances.get('431', 0.0) - sum(balances.get(c, 0.0) for c in EXCL_431)
    tk413 = balances.get('413', 0.0)
    return g1, g2, tk413


def _rate_to_vnd(info: dict) -> float:
    """bsrt (bình quân mua-bán) — fallback taxrt khi bsrt=0. info: {"ttbuyrt","bsrt","taxrt"}."""
    return info.get("bsrt", 0.0) or info.get("taxrt", 0.0)


def _rate_usd_to_vnd(info: dict) -> float:
    """ttbuyrt (mua chuyển khoản) của USD — fallback taxrt khi ttbuyrt=0."""
    return info.get("ttbuyrt", 0.0) or info.get("taxrt", 0.0)


@dataclass
class CurrencyResult:
    ccy: str
    rate_to_vnd: float | None  # None cho VND (giữ nguyên tệ, không quy đổi)
    group1_native: float
    group2_native: float
    tk413_native: float


@dataclass
class DtbbResult:
    report_date: str
    branch_code: str
    file_count: int
    vnd_duoi12: float = 0.0  # đã gộp TK413-VND (theo yêu cầu người dùng — không tách cột riêng)
    vnd_tu12: float = 0.0
    usd_duoi12: float = 0.0
    usd_tu12: float = 0.0
    tk413_usd: float = 0.0
    # Tỷ giá VND/USD đã dùng để quy đổi (ttbuyrt hoặc taxrt fallback) — lưu lại để FE/lịch
    # sử tính ra "USD quy đổi" theo từng mã tiền, so sánh với USD nguyên tệ sẵn có. Không
    # lưu thì không tái tạo được con số này từ dữ liệu đã lưu (mỗi mã tiền chỉ lưu tỷ giá
    # riêng của nó, không lưu tỷ giá USD dùng làm mẫu số).
    rate_usd_to_vnd: float = 0.0
    all_ccy_codes: list[str] = field(default_factory=list)   # toàn bộ mã trong tygia — FE tô ô vàng/trắng
    currencies_used: list[str] = field(default_factory=list)  # mã đã có file upload
    unconverted_ccy: list[str] = field(default_factory=list)  # có file + có số dư nhưng KHÔNG quy đổi được (bsrt và taxrt đều 0)
    netted_9300_ccy: list[str] = field(default_factory=list)  # mã tiền đã bị trừ số liệu chi nhánh 9300 (chỉ áp dụng khi tính chi nhánh 9999)
    details: list[CurrencyResult] = field(default_factory=list)  # chi tiết theo currency, kể cả VND (tk413_native riêng để tra cứu)


def calculate(
    balance_files: list[tuple[str, dict]],
    tygia_rates: dict[str, dict],
    report_date: str,
    branch_code: str,
) -> DtbbResult:
    """balance_files: list (ccy, balances) đã đọc — ngày/chi nhánh đã validate khớp
    nhau trước khi gọi. tygia_rates: {ccy: {"ttbuyrt","bsrt","taxrt"}}."""
    usd_info = tygia_rates.get('USD')
    rate_usd_to_vnd = _rate_usd_to_vnd(usd_info) if usd_info else 0.0
    if not rate_usd_to_vnd:
        raise DtbbFileError(
            "File tỷ giá không có tỷ giá USD hợp lệ (cột ttbuyrt lẫn taxrt đều trống/0) "
            "— không có cơ sở quy đổi bất kỳ mã tiền nào sang USD."
        )

    result = DtbbResult(report_date=report_date, branch_code=branch_code,
                         file_count=len(balance_files), rate_usd_to_vnd=rate_usd_to_vnd,
                         all_ccy_codes=sorted(tygia_rates.keys()))
    seen_ccy: set[str] = set()
    for ccy, balances in balance_files:
        if ccy in seen_ccy:
            raise DtbbFileError(f"Có từ 2 file trở lên cùng mã tiền '{ccy}' — chỉ được upload 1 file/loại tiền")
        seen_ccy.add(ccy)

        g1, g2, tk413 = compute_native_groups(balances)
        if ccy == 'VND':
            # TK413-VND gộp thẳng vào "dưới 12 tháng" — không tách cột riêng cho VND
            # (khác USD: TK413-USD vẫn giữ cột riêng, xem tk413_usd bên dưới).
            result.vnd_duoi12 += g1 + tk413
            result.vnd_tu12 += g2
            result.details.append(CurrencyResult(ccy, None, g1, g2, tk413))
        elif ccy == 'USD':
            # USD là đơn vị đích — cộng thẳng nguyên tệ, KHÔNG chạy qua công thức quy
            # đổi. Chú ý: rate_to_vnd(USD) dùng bsrt còn rate_usd_to_vnd dùng ttbuyrt —
            # hai cột KHÁC NHAU, nên tỷ số bsrt(USD)/ttbuyrt(USD) != 1 (từng gây lỗi
            # thật: USD tự nhân với ~1,0073 do thiếu nhánh riêng này).
            result.usd_duoi12 += g1
            result.usd_tu12 += g2
            result.tk413_usd += tk413
            result.details.append(CurrencyResult(ccy, None, g1, g2, tk413))
        else:
            info = tygia_rates.get(ccy)
            rate_to_vnd = _rate_to_vnd(info) if info else 0.0
            if not rate_to_vnd:
                # Không quy đổi được (vd KHR nhiều kỳ không có giá mua/bán/hạch toán
                # nào cho Riel) — bỏ qua đóng góp USD của mã này, KHÔNG chặn các mã
                # khác đã có tỷ giá hợp lệ. Vẫn ghi vào details với rate=None để FE
                # biết có số dư nhưng chưa quy đổi được.
                result.unconverted_ccy.append(ccy)
                result.details.append(CurrencyResult(ccy, None, g1, g2, tk413))
            else:
                rate_to_usd = rate_to_vnd / rate_usd_to_vnd
                result.usd_duoi12 += g1 * rate_to_usd
                result.usd_tu12 += g2 * rate_to_usd
                result.tk413_usd += tk413 * rate_to_usd
                result.details.append(CurrencyResult(ccy, rate_to_vnd, g1, g2, tk413))
        result.currencies_used.append(ccy)
    return result


# Chi nhánh 9999 (file không mã) trừ đi chi nhánh 9300 (file cùng mã tiền, tiền tố
# '9300') — nghiệp vụ xác nhận 2026-08-27: số 9999 "thật" phải loại phần 9300 ra.
_BRANCH_9999 = "9999"
_BRANCH_9300 = "9300"


def _merge_9999_minus_9300(
    balance_entries: list[tuple[str, dict, str, str, str]],
) -> tuple[list[tuple[str, dict]], list[str]]:
    """balance_entries đã lọc đúng 2 chi nhánh {9999, 9300} (mỗi phần tử:
    (ccy, balances, file_date, branch_code, filename)). Trả về (list (ccy, balances)
    đã gộp cho chi nhánh 9999, list mã tiền đã bị trừ 9300).

    Mã tiền có ở CẢ hai chi nhánh: trừ ĐÚNG THEO TỪNG DÒNG tài khoản (Acctcd) — lấy
    union toàn bộ mã tài khoản của cả 2 file, không chỉ các mã có sẵn ở file 9999.
    Tài khoản chỉ có ở 1 bên coi phía kia = 0 — nếu tài khoản đó CHỈ có ở file 9300,
    kết quả dòng đó thành số ÂM sau khi trừ. Đây là hệ quả đúng của phép trừ theo
    dòng, không phải lỗi.

    Mã tiền chỉ có ở 9999 (không có 9300 tương ứng): giữ nguyên, không trừ — theo
    đúng quyết định nghiệp vụ. Mã tiền chỉ có ở 9300 (không có 9999 tương ứng): không
    có gì để trừ VÀO — báo lỗi rõ ràng thay vì lặng lẽ bỏ qua hoặc cộng âm nhầm vào
    tổng chung.
    """
    by_branch: dict[str, dict[str, tuple[dict, str]]] = {_BRANCH_9999: {}, _BRANCH_9300: {}}
    for ccy, balances, _file_date, branch_code, filename in balance_entries:
        existing = by_branch[branch_code].get(ccy)
        if existing is not None:
            raise DtbbFileError(
                f"Có từ 2 file trở lên cùng mã tiền '{ccy}' cho chi nhánh {branch_code} "
                "— chỉ được upload 1 file/loại tiền/chi nhánh",
                filenames=[existing[1], filename],
            )
        by_branch[branch_code][ccy] = (balances, filename)

    only_9300 = set(by_branch[_BRANCH_9300]) - set(by_branch[_BRANCH_9999])
    if only_9300:
        detail = ", ".join(f"{ccy} ({by_branch[_BRANCH_9300][ccy][1]})" for ccy in sorted(only_9300))
        raise DtbbFileError(
            "Có file chi nhánh 9300 nhưng không có file chi nhánh 9999 (không mã) tương "
            f"ứng cùng mã tiền để trừ: {detail}",
            filenames=[by_branch[_BRANCH_9300][ccy][1] for ccy in sorted(only_9300)],
        )

    merged: list[tuple[str, dict]] = []
    netted: list[str] = []
    for ccy, (bal_9999, _fn) in by_branch[_BRANCH_9999].items():
        entry_9300 = by_branch[_BRANCH_9300].get(ccy)
        if entry_9300 is None:
            merged.append((ccy, bal_9999))
            continue
        bal_9300, _fn2 = entry_9300
        all_codes = set(bal_9999) | set(bal_9300)
        merged_balances = {c: bal_9999.get(c, 0.0) - bal_9300.get(c, 0.0) for c in all_codes}
        merged.append((ccy, merged_balances))
        netted.append(ccy)
    return merged, netted


def calculate_from_uploads(files: list[tuple[str, bytes]]) -> DtbbResult:
    """files: list (filename, content) người dùng vừa upload — tự nhận diện file tỷ giá
    vs file cân đối, validate ngày + chi nhánh khớp nhau, rồi tính. Ném DtbbFileError nếu
    có vấn đề (báo lỗi rõ ràng thay vì âm thầm tính sai)."""
    tygia_rates: dict[str, dict] | None = None
    tygia_date: str | None = None
    balance_entries: list[tuple[str, dict, str, str, str]] = []  # (ccy, balances, file_date, branch_code, filename)

    for filename, content in files:
        kind = sniff_file_type(content, filename)
        if kind == 'tygia':
            if tygia_rates is not None:
                raise DtbbFileError("Có nhiều hơn 1 file tỷ giá được upload", filenames=[filename])
            tygia_rates, tygia_date = read_tygia_file(content, filename)
        else:
            ccy, balances = read_balance_file(content, filename)
            file_date, branch_code = extract_report_date_and_branch(filename, ccy)
            balance_entries.append((ccy, balances, file_date, branch_code, filename))

    if tygia_rates is None or tygia_date is None:
        raise DtbbFileError("Chưa upload file tỷ giá")
    if not balance_entries:
        raise DtbbFileError("Chưa upload file cân đối nào")

    mismatched_date = [(fn, fd) for _, _, fd, _, fn in balance_entries if fd != tygia_date]
    if mismatched_date:
        detail = ", ".join(f"{fn} (ngày {fd})" for fn, fd in mismatched_date)
        raise DtbbFileError(
            f"Ngày không khớp file tỷ giá (ngày {tygia_date}): {detail}",
            filenames=[fn for fn, _ in mismatched_date],
        )

    branch_codes = {bc for _, _, _, bc, _ in balance_entries}
    netted_9300_ccy: list[str] = []
    if len(branch_codes) == 1:
        branch_code = branch_codes.pop()
        # Check trùng mã tiền SỚM ở đây (còn giữ filename) thay vì để calculate()
        # tự phát hiện — calculate() nhận balance_files đã bị lột filename (dòng dưới)
        # nên lỗi trùng mã tiền của nó không tô đỏ được đúng file trên FE. Check
        # trong calculate() vẫn giữ nguyên làm lưới an toàn cho caller gọi trực tiếp
        # (vd tests/test_dtbb_formula.py::test_hai_file_cung_ma_tien_bi_chan).
        seen_ccy_fn: dict[str, str] = {}
        for ccy, _balances, _fd, _bc, filename in balance_entries:
            if ccy in seen_ccy_fn:
                raise DtbbFileError(
                    f"Có từ 2 file trở lên cùng mã tiền '{ccy}' — chỉ được upload 1 file/loại tiền",
                    filenames=[seen_ccy_fn[ccy], filename],
                )
            seen_ccy_fn[ccy] = filename
        balance_files = [(ccy, balances) for ccy, balances, _, _, _ in balance_entries]
    elif branch_codes == {_BRANCH_9999, _BRANCH_9300}:
        # Trường hợp đặc biệt duy nhất được phép trộn 2 chi nhánh trong 1 lượt: 9999
        # trừ đi 9300 (xem _merge_9999_minus_9300).
        branch_code = _BRANCH_9999
        balance_files, netted_9300_ccy = _merge_9999_minus_9300(balance_entries)
    else:
        detail = ", ".join(f"{fn} (chi nhánh {bc})" for _, _, _, bc, fn in balance_entries)
        raise DtbbFileError(
            f"Các file cân đối không cùng chi nhánh trong 1 lượt tính: {detail} — "
            "mỗi lượt tính chỉ được gồm file của đúng 1 chi nhánh (riêng cặp 9999 + 9300 "
            "được phép, để trừ số liệu 9300 khỏi 9999).",
            filenames=[fn for _, _, _, _, fn in balance_entries],
        )

    result = calculate(balance_files, tygia_rates, tygia_date, branch_code)
    # calculate() đếm len(balance_files) — SAU khi 9999+9300 đã gộp thành 1 dòng/mã
    # tiền, nên đếm thiếu khi có gộp 9300. Ghi đè bằng tổng số file THẬT SỰ đã upload
    # (gồm cả file tỷ giá) — đúng ý nghĩa hiển thị "(từ {file_count} file)" ở FE.
    result.file_count = len(files)
    result.netted_9300_ccy = netted_9300_ccy
    return result
