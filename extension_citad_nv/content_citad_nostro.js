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
            _toast(`✓ Tự lưu: Cổng ${cong} – ${loai.toUpperCase()} – Số món ${res.soMon}, Số tiền ${res.soTien}`);
          } else {
            lastKey = null; // cho phép thử lại lượt sau nếu gửi thất bại
          }
        }
      );
    }

    function _toast(msg) {
      const el = document.createElement('div');
      el.textContent = msg;
      el.style.cssText =
        'position:fixed;bottom:16px;right:16px;z-index:999999;background:#059669;color:#fff;' +
        'padding:10px 14px;border-radius:8px;font:13px sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.2);';
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 3000);
    }

    const observer = new MutationObserver(() => trySave());
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    trySave();
  }
})();
