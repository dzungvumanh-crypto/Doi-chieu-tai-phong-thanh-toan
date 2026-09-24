// ── CITAD "Tra cứu dữ liệu ngoại tệ" (USD/EUR) — Phòng QLTK Nostro, Vostro ──
//
// Trang KHÁC content_citad_nostro.js (trang đó chỉ VNĐ, module TraCuuDuLieu) —
// đây là module TraCuuDuLieuNgoaiTe/frmLookUp_Trx.aspx. Selector lấy từ HTML
// thật (CITAD001, 14/09/2026, dump bằng console.log trên trang thật):
//   - #ctl00_ContentPlaceHolder1_cboDichVu — Loại dịch vụ (select). Trang
//     này KHÔNG có "giá trị thấp" như trang VNĐ — chỉ có value "FH" = Chuyển
//     Có giá trị cao (GTC) và "FP" = Chuyển Nợ giá trị cao (bỏ qua, giống
//     nguyên tắc chỉ chấm "Chuyển Có" của trang VNĐ). Ngoại tệ CHỈ có GTC,
//     không có GTT — khớp thực tế PaymentHub: cột GTT luôn ra 0 khi lọc
//     USD/EUR (xác nhận qua ảnh chụp thực tế 14/09/2026).
//   - #ctl00_ContentPlaceHolder1_ddlCurrency — Loại tiền (select), value
//     "USD"/"EUR" (bỏ qua "" và "ALL" — gộp nhiều loại tiền, không chấm được).
//   - #ctl00_ContentPlaceHolder1_cboTinhTrang, #...rdbDi, #...lblNumTotal,
//     #...lblTotalAmount — TRÙNG id với trang VNĐ (cùng master page).
//   - #ctl00_ContentPlaceHolder1_rdbDuLieuCI — "Nguồn dữ liệu: Dữ liệu tại
//     CI" (mặc định chọn sẵn) — trang VNĐ không có control này. Bắt buộc
//     đang chọn đúng lựa chọn này mới lưu, tránh lỡ tay chấm nhầm "Dữ liệu
//     nhận về từ TT xử lý" (rdbDuLieuRPC).
//
// Nghiệp vụ: chỉ chấm chiều ĐI, chỉ giao dịch THÀNH CÔNG, chỉ "Chuyển Có
// giá trị cao", chỉ "Dữ liệu tại CI", tra đủ 5 cổng CITAD — mỗi lần chỉ ra
// kết quả của 1 loại tiền (đổi dropdown Loại tiền + bấm Truy vấn lại để lấy
// loại tiền kia), nên phải quét lần lượt USD rồi EUR, không có ở cùng lúc.
(function () {
  const SERVER_KEY = 'server';
  const TOKEN_KEY = 'extensionToken';

  chrome.storage.local.get([SERVER_KEY, TOKEN_KEY], (cfg) => {
    if (!cfg[SERVER_KEY] || !cfg[TOKEN_KEY]) return;
    run(cfg[SERVER_KEY], cfg[TOKEN_KEY]);
  });

  // Giống hệt CONG_MAP trong content_citad_nostro.js — 5 cổng CITAD dùng
  // chung 1 mã số, không phụ thuộc tên module trong URL.
  const CONG_MAP = {
    'CITAD001': '1',
    'CITAD': '9',
    'CITAD9212': '12',
    'CITAD7917': '17',
    'CITAD4818': '18',
  };

  const ID_DICH_VU = 'ctl00_ContentPlaceHolder1_cboDichVu';
  const ID_CURRENCY = 'ctl00_ContentPlaceHolder1_ddlCurrency';
  const ID_TINH_TRANG = 'ctl00_ContentPlaceHolder1_cboTinhTrang';
  const ID_RDB_DI = 'ctl00_ContentPlaceHolder1_rdbDi';
  const ID_RDB_DU_LIEU_CI = 'ctl00_ContentPlaceHolder1_rdbDuLieuCI';
  const ID_LBL_MON = 'ctl00_ContentPlaceHolder1_lblNumTotal';
  const ID_LBL_TIEN = 'ctl00_ContentPlaceHolder1_lblTotalAmount';
  const VAL_GTC = 'FH';
  const VAL_THANH_CONG = 'STMSG8_Value';

  function getCong() {
    const m = window.location.href.match(/10\.0\.85\.100\/([^/]+)\//);
    return m ? (CONG_MAP[m[1]] || m[1]) : '';
  }

  function getLoaiDichVu() {
    const sel = document.getElementById(ID_DICH_VU);
    if (!sel) return '';
    return sel.value === VAL_GTC ? 'gtc' : '';
  }

  function getCurrency() {
    const sel = document.getElementById(ID_CURRENCY);
    if (!sel) return '';
    const v = sel.value;
    return (v === 'USD' || v === 'EUR') ? v : ''; // '' hoặc 'ALL' = bỏ qua
  }

  function isChieuDi() {
    const rdb = document.getElementById(ID_RDB_DI);
    return !!(rdb && rdb.checked);
  }

  function isThanhCong() {
    const sel = document.getElementById(ID_TINH_TRANG);
    return !!(sel && sel.value === VAL_THANH_CONG);
  }

  function isDuLieuCI() {
    const rdb = document.getElementById(ID_RDB_DU_LIEU_CI);
    return !!(rdb && rdb.checked);
  }

  function readResult() {
    const monEl = document.getElementById(ID_LBL_MON);
    const tienEl = document.getElementById(ID_LBL_TIEN);
    const soMon = monEl ? parseInt((monEl.innerText || '').replace(/[^\d]/g, ''), 10) || 0 : 0;
    const soTien = tienEl ? parseInt((tienEl.innerText || '').replace(/[^\d]/g, ''), 10) || 0 : 0;
    return { soMon, soTien };
  }

  function hasResults() {
    const monEl = document.getElementById(ID_LBL_MON);
    return !!(monEl && monEl.innerText.trim() !== '');
  }

  // ── Lùi thời gian thử lại khi gửi thất bại — giống hệt content_citad_nostro.js.
  function _makeRetryScheduler(resetFn) {
    let failCount = 0;
    let timer = null;
    return {
      scheduleRetry() {
        failCount++;
        const delay = Math.min(5000 * (2 ** (failCount - 1)), 300000); // 5s → tối đa 5 phút
        if (timer) clearTimeout(timer);
        timer = setTimeout(resetFn, delay);
      },
      resetBackoff() {
        failCount = 0;
        if (timer) { clearTimeout(timer); timer = null; }
      },
    };
  }

  function run(server, token) {
    const cong = getCong();
    if (!cong) return;

    let lastKey = null;

    function trySave() {
      if (!hasResults()) return;
      // Đúng nghiệp vụ: Đi + Thành công + Dữ liệu tại CI — tránh lỡ tay lưu
      // nhầm bộ lọc khác (trang có cả chiều Đến, nguồn RPC, trạng thái khác).
      if (!isChieuDi() || !isThanhCong() || !isDuLieuCI()) return;
      const loai = getLoaiDichVu();
      if (!loai) return; // không phải "Chuyển Có giá trị cao"
      const ccy = getCurrency();
      if (!ccy) return; // "Tất cả"/chưa chọn — không tách được theo loại tiền

      const res = readResult();
      const key = `${cong}_${loai}_${ccy}_${res.soMon}_${res.soTien}`;
      if (key === lastKey) return; // đã lưu đúng tổ hợp này rồi, tránh gửi lặp
      lastKey = key;

      const body = {
        key: `citad_${cong}_${loai}_${ccy}`,
        cong, loai, ccy,
        soMon: res.soMon, soTien: res.soTien,
        ts: new Date().toISOString(),
      };
      chrome.runtime.sendMessage(
        { type: 'BUFFER_POST', url: `${server}/api/doi-chieu-citad-nostro/citad-buffer`, token, body },
        (resp) => {
          if (resp && resp.ok) {
            retry.resetBackoff();
            _toast(`✓ Tự lưu: Cổng ${cong} – ${ccy} – GTC – Số món ${res.soMon}, Số tiền ${res.soTien}`);
          } else if (resp && resp.status === 403) {
            _toast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở trang Đối chiếu CITAD - PaymentHub', '#dc2626', 8000);
          } else {
            _toast('⚠ Chưa gửi được số liệu về máy chủ — sẽ tự thử lại', '#f59e0b', 6000);
            retry.scheduleRetry();
          }
        }
      );
    }

    const retry = _makeRetryScheduler(() => {
      lastKey = null;
      trySave();
    });

    function _toast(msg, color, ms) {
      const old = document.getElementById('_citad_nv_toast');
      if (old) old.remove();
      const el = document.createElement('div');
      el.id = '_citad_nv_toast';
      el.textContent = msg;
      el.style.cssText =
        'position:fixed;bottom:16px;right:16px;z-index:999999;color:#fff;' +
        'padding:10px 14px;border-radius:8px;font:13px sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.2);' +
        `background:${color || '#059669'};`;
      document.body.appendChild(el);
      setTimeout(() => el.remove(), ms || 3000);
    }

    const observer = new MutationObserver(() => trySave());
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    trySave();
  }
})();
