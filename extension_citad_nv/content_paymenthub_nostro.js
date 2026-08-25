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
    return parseInt((s || '').replace(/[^\d]/g, ''), 10) || 0;
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
            _toast(`✓ Tự lưu PaymentHub: GTT ${totals.gtt.soMon} món, GTC Trước15h30 ${totals.gtc_truoc.soMon} món, Từ15h30 ${totals.gtc_tu.soMon} món`);
          } else {
            lastKey = null;
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
