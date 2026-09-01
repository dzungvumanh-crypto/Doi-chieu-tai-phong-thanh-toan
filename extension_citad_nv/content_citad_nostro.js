// ── CITAD "Tra cứu dữ liệu" — Phòng QLTK Nostro, Vostro ────────────────────
//
// Trang KHÁC hẳn "Bảng kê giao dịch" mà content.js (Phòng Thanh toán) quét —
// đây là module TraCuuDuLieu/frmLookUp_Trx.aspx. Selector lấy từ HTML thật
// (frmLookUp_Trx.aspx, CITAD001, 19/08/2026) — không còn dò theo label như
// bản đầu, mọi ASP.NET control đều có id ổn định:
//   - #ctl00_ContentPlaceHolder1_cboDichVu   — Loại dịch vụ (select), value
//     "LF" = Chuyển Có giá trị thấp (GTT), "HF" = Chuyển Có giá trị cao (GTC)
//     — các value khác (PA/HP/tổng hợp/hoàn chuyển/tra soát) KHÔNG lưu.
//   - #ctl00_ContentPlaceHolder1_rdbDi        — radio "Đi" (checked=true khi chọn)
//   - #ctl00_ContentPlaceHolder1_cboTinhTrang — Tình trạng (select), value
//     "STMSG8_Value" = Giao dịch thành công (mặc định trang đã chọn sẵn).
//   - #ctl00_ContentPlaceHolder1_lblNumTotal    — số "Tổng số giao dịch"
//   - #ctl00_ContentPlaceHolder1_lblTotalAmount — số "Tổng số tiền"
// Trang dùng ASP.NET UpdatePanel (#ctl00_ContentPlaceHolder1_UpdatePanel1) —
// bấm "Truy vấn" chỉ postback AJAX một phần, id giữ nguyên, nội dung 2 span
// tổng được thay mới — MutationObserver bắt được thay đổi này bình thường.
//
// Nghiệp vụ Phòng QLTK Nostro, Vostro (đã xác nhận): chỉ chấm chiều ĐI, chỉ
// giao dịch THÀNH CÔNG, tra đủ 5 cổng CITAD (5 địa chỉ 10.0.85.100/CITAD*/...).
(function () {
  const SERVER_KEY = 'server';
  const TOKEN_KEY = 'extensionToken';

  chrome.storage.local.get([SERVER_KEY, TOKEN_KEY], (cfg) => {
    if (!cfg[SERVER_KEY] || !cfg[TOKEN_KEY]) return; // chưa cấu hình — im lặng, giống content.js
    run(cfg[SERVER_KEY], cfg[TOKEN_KEY]);
  });

  // Giống hệt CONG_MAP trong content.js — 5 cổng CITAD dùng chung 1 mã số
  // cho cả 2 module (Phòng Thanh toán lẫn Phòng QLTK Nostro, Vostro).
  const CONG_MAP = {
    'CITAD001': '1',
    'CITAD': '9',
    'CITAD9212': '12',
    'CITAD7917': '17',
    'CITAD4818': '18',
  };

  const ID_DICH_VU = 'ctl00_ContentPlaceHolder1_cboDichVu';
  const ID_TINH_TRANG = 'ctl00_ContentPlaceHolder1_cboTinhTrang';
  const ID_RDB_DI = 'ctl00_ContentPlaceHolder1_rdbDi';
  const ID_LBL_MON = 'ctl00_ContentPlaceHolder1_lblNumTotal';
  const ID_LBL_TIEN = 'ctl00_ContentPlaceHolder1_lblTotalAmount';
  const VAL_GTT = 'LF';
  const VAL_GTC = 'HF';
  const VAL_THANH_CONG = 'STMSG8_Value';

  function getCong() {
    const m = window.location.href.match(/10\.0\.85\.100\/([^/]+)\//);
    return m ? (CONG_MAP[m[1]] || m[1]) : '';
  }

  function getLoaiDichVu() {
    const sel = document.getElementById(ID_DICH_VU);
    if (!sel) return '';
    if (sel.value === VAL_GTT) return 'gtt';
    if (sel.value === VAL_GTC) return 'gtc';
    return '';
  }

  function isChieuDi() {
    const rdb = document.getElementById(ID_RDB_DI);
    return !!(rdb && rdb.checked);
  }

  function isThanhCong() {
    const sel = document.getElementById(ID_TINH_TRANG);
    return !!(sel && sel.value === VAL_THANH_CONG);
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

  // ── Lùi thời gian thử lại khi gửi thất bại ───────────────────────────
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
      // Chỉ lưu khi đúng "Đi" + "Giao dịch thành công" — đúng nghiệp vụ
      // Phòng QLTK Nostro, Vostro, tránh lỡ tay lưu nhầm bộ lọc khác (trang
      // có cả chiều Đến và các trạng thái khác).
      if (!isChieuDi() || !isThanhCong()) return;
      const loai = getLoaiDichVu();
      if (!loai) return;

      const res = readResult();
      const key = `${cong}_${loai}_${res.soMon}_${res.soTien}`;
      if (key === lastKey) return; // đã lưu đúng tổ hợp này rồi, tránh gửi lặp
      lastKey = key;

      const body = {
        key: `citad_${cong}_${loai}`,
        cong, loai,
        soMon: res.soMon, soTien: res.soTien,
        ts: new Date().toISOString(),
      };
      chrome.runtime.sendMessage(
        { type: 'BUFFER_POST', url: `${server}/api/doi-chieu-citad-nostro/citad-buffer`, token, body },
        (resp) => {
          if (resp && resp.ok) {
            retry.resetBackoff();
            _toast(`✓ Tự lưu: Cổng ${cong} – ${loai.toUpperCase()} – Số món ${res.soMon}, Số tiền ${res.soTien}`);
          } else if (resp && resp.status === 403) {
            // Lỗi VĨNH VIỄN — thử lại bao nhiêu lần cũng vẫn 403, mỗi lần
            // còn tốn 1 dòng audit_logs. Dừng hẳn, giữ nguyên lastKey để
            // MutationObserver không kích lại; người dùng phải tạo mã mới.
            _toast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở trang Đối chiếu CITAD - PaymentHub', '#dc2626', 8000);
          } else {
            // Lỗi CÓ THỂ tạm thời (mất mạng, máy chủ lỗi) — báo cho người
            // dùng biết là CHƯA lưu được, rồi tự thử lại với độ trễ tăng dần.
            _toast('⚠ Chưa gửi được số liệu về máy chủ — sẽ tự thử lại', '#f59e0b', 6000);
            retry.scheduleRetry();
          }
        }
      );
    }

    // Đặt lại khoá chặn trùng NGAY sau khi gửi lỗi là vòng lặp không độ trễ:
    // _toast() cũng là một thay đổi trên document.body — đúng thứ
    // MutationObserver bên dưới đang theo dõi — nên observer kích trySave()
    // lại tức thì, chỉ bị chặn bởi round-trip của request đang lỗi. Lùi thời
    // gian tăng dần (5s → tối đa 5 phút) và chỉ áp dụng cho lỗi có thể tạm
    // thời; lỗi vĩnh viễn (403) không tự thử lại.
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
