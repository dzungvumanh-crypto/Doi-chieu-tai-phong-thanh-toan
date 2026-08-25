// ── PaymentHub "Lập bảng kê phí chia sẻ CITAD" — Phòng QLTK Nostro, Vostro ──
//
// Trang https://paymenthub.agribank.com.vn/final-settlement-citad/charges.
// Selector lấy từ HTML thật (bảng bootstrap-table, 17/08/2026-20/08/2026):
// header 3 hàng, 16 cột lá (data-field 0-15):
//   0 checkbox, 1 STT, 2 BRCD, 3 Chi nhánh, 4 Trạng thái, 5 Loại tiền,
//   6-8   = GTT: Tổng món / Tổng tiền / Tổng tiền phí,
//   9-11  = GTC Trước 15h30: Tổng món / Tổng tiền / Tổng tiền phí,
//   12-14 = GTC Từ 15h30: Tổng món / Tổng tiền / Tổng tiền phí,
//   15    = Tổng tiền phí TOÀN BỘ (không dùng).
// Dòng "Tổng cộng" ở cuối bảng (cùng <table> với header, không tách bảng
// riêng) có đúng 11 <td>: ô đầu colspan=6 (gộp cột 0-5, chữ "Tổng cộng"),
// 9 ô tiếp theo khớp field 6-14 theo ĐÚNG THỨ TỰ, ô cuối field 15 (bỏ qua).
(function () {
  const SERVER_KEY = 'server';
  const TOKEN_KEY = 'extensionToken';

  chrome.storage.local.get([SERVER_KEY, TOKEN_KEY], (cfg) => {
    if (!cfg[SERVER_KEY] || !cfg[TOKEN_KEY]) return;
    run(cfg[SERVER_KEY], cfg[TOKEN_KEY]);
  });

  function _num(s) {
    // Giữ dấu âm: strip sạch mọi ký tự không phải chữ số sẽ biến -1.234
    // thành 1.234 — sai số liệu (đảo dấu), không phải làm tròn.
    const t = (s || '').trim();
    const am = t.startsWith('-') || /^\(.*\)$/.test(t); // "-1.234" hoặc "(1.234)"
    const n = parseInt(t.replace(/[^\d]/g, ''), 10) || 0;
    return am ? -n : n;
  }

  // Bảng có thể có nhiều <table> khác trên cùng trang — chọn đúng bảng có
  // cả dòng "Tổng cộng" LẪN tiêu đề "Tổng món đi thành công" (đã xác nhận
  // trên trang thật: header + dòng Tổng cộng nằm CHUNG 1 <table>).
  function _findChargesTable() {
    for (const t of document.querySelectorAll('table')) {
      const text = t.innerText || '';
      if (text.includes('Tổng cộng') && text.includes('Tổng món đi thành công')) return t;
    }
    return null;
  }

  function readTongCong() {
    const table = _findChargesTable();
    if (!table) return null;
    const tongCongRow = [...table.querySelectorAll('tr')].find(
      (r) => r.innerText.trim().startsWith('Tổng cộng')
    );
    if (!tongCongRow) return null;
    const tds = [...tongCongRow.querySelectorAll('td')];
    if (tds.length < 10) return null; // thiếu cột — cấu trúc trang đã đổi, không đoán bừa
    return {
      gtt:       { soMon: _num(tds[1].innerText), soTien: _num(tds[2].innerText) },
      gtc_truoc: { soMon: _num(tds[4].innerText), soTien: _num(tds[5].innerText) },
      gtc_tu:    { soMon: _num(tds[7].innerText), soTien: _num(tds[8].innerText) },
    };
  }

  // ── Lùi thời gian thử lại khi gửi thất bại ───────────────────────────
  // Giống content_citad_nostro.js — xem comment giải thích đầy đủ ở đó.
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
    let lastKey = null;

    function trySave() {
      const totals = readTongCong();
      if (!totals) return;
      const key = JSON.stringify(totals);
      if (key === lastKey) return;
      lastKey = key;

      const items = ['gtt', 'gtc_truoc', 'gtc_tu'].map((loai) => ({
        key: `ph_${loai}`,
        loai,
        soMon: totals[loai].soMon,
        soTien: totals[loai].soTien,
      }));
      const body = { items, ts: new Date().toISOString() };
      chrome.runtime.sendMessage(
        { type: 'BUFFER_POST', url: `${server}/api/doi-chieu-citad-nostro/paymenthub-buffer`, token, body },
        (resp) => {
          if (resp && resp.ok) {
            retry.resetBackoff();
            _toast(`✓ Tự lưu PaymentHub: GTT ${totals.gtt.soMon} món, GTC Trước15h30 ${totals.gtc_truoc.soMon} món, Từ15h30 ${totals.gtc_tu.soMon} món`);
          } else if (resp && resp.status === 403) {
            // Lỗi VĨNH VIỄN — dừng hẳn, giữ nguyên lastKey (xem giải thích ở
            // content_citad_nostro.js). Trang này là bootstrap-table, DOM đổi
            // liên tục nên nếu tự thử lại thì mỗi lần đổi là 1 dòng audit_logs.
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
