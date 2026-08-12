/* ── PaymentHub + Payment Extension – Tự động + Thủ công ──
 * Bản cập nhật để trỏ vào backend TTTT dùng chung (thay vì server cổng
 * 8100 riêng của tool desktop cũ). Toàn bộ logic đọc DOM/scrape số liệu
 * GIỮ NGUYÊN 100% — chỉ đổi SERVER, đường dẫn API (prefix
 * /api/doi-chieu-citad/...) và cách xác thực (mã kết nối cá nhân, xem dưới).
 *
 * CẤU HÌNH: không sửa file này — bấm icon Extension trên thanh công cụ →
 * "Tuỳ chọn" (Options), điền SERVER + dán "Mã kết nối" lấy từ trang
 * /doi_chieu_citad (mục "Kết nối Extension") sau khi đã đăng nhập TTTT thật.
 * KHÔNG dùng chung 1 mã cho nhiều người — backend tra token ra đúng chủ,
 * không còn tin bất kỳ tên nào tự khai (xem options.js).
 */

// Đọc từ chrome.storage.local (điền qua trang Tuỳ chọn của Extension) —
// rỗng cho tới khi người dùng cấu hình lần đầu.
let SERVER = '';
let EXTENSION_TOKEN = '';

async function loadConfig() {
  const cfg = await chrome.storage.local.get(['server', 'extensionToken']);
  SERVER = cfg.server || '';
  EXTENSION_TOKEN = cfg.extensionToken || '';
  if (!SERVER || !EXTENSION_TOKEN) {
    console.warn('[PaymentHub Extension] Chưa cấu hình — bấm icon Extension trên thanh công cụ → Tuỳ chọn.');
  } else if (!SERVER.startsWith('https://')) {
    console.warn('[PaymentHub Extension] SERVER không dùng HTTPS — mã kết nối và số liệu truyền ở dạng đọc được trên mạng nội bộ. Chỉ chấp nhận được khi test trên localhost.');
  }
}

function parseNum(s) {
  return parseInt((s || '').replace(/[^\d]/g, '')) || 0;
}

// Parse SỐ TIỀN (khác parseNum dùng cho SỐ MÓN) — USD/EUR có phần thập phân
// (xu/cent), không thể xoá hết ký tự không phải chữ số như parseNum vì sẽ
// xoá luôn dấu thập phân (vd "1.234,56" thành 123456 — sai gấp 100 lần).
// Tự nhận diện dấu thập phân: dấu phân cách CUỐI CÙNG trong chuỗi chỉ là
// thập phân khi theo sau đúng 1-2 chữ số (độ dài phần lẻ tiền tệ) — nhóm
// nghìn luôn đúng 3 chữ số nên không nhầm lẫn được.
function parseMoney(s) {
  const cleaned = (s || '').replace(/[^\d.,]/g, '');
  if (!cleaned) return 0;
  const lastSep = Math.max(cleaned.lastIndexOf('.'), cleaned.lastIndexOf(','));
  if (lastSep === -1) return parseFloat(cleaned) || 0;
  const intPart = cleaned.slice(0, lastSep).replace(/[.,]/g, '');
  const fracPart = cleaned.slice(lastSep + 1).replace(/[.,]/g, '');
  if (fracPart.length === 0 || fracPart.length > 2) {
    return parseFloat(intPart + fracPart) || 0; // dấu cuối vẫn là phân cách nghìn
  }
  return parseFloat(`${intPart}.${fracPart}`) || 0;
}

function showToast(msg, color='#10b981', duration=4000) {
  const old = document.getElementById('_ph_toast');
  if (old) old.remove();
  if (!document.getElementById('_ph_style')) {
    const s = document.createElement('style');
    s.id = '_ph_style';
    s.textContent = '@keyframes _phFadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}';
    document.head.appendChild(s);
  }
  const t = document.createElement('div');
  t.id = '_ph_toast';
  t.style.cssText = `
    position:fixed;bottom:24px;right:24px;
    background:#1e293b;border:1px solid ${color};border-radius:10px;
    padding:12px 18px;font-family:Arial,sans-serif;font-size:13px;
    color:#fff;z-index:999999;box-shadow:0 4px 16px rgba(0,0,0,.4);
    display:flex;align-items:flex-start;gap:10px;max-width:340px;
    animation:_phFadeIn .2s ease;
  `;
  t.innerHTML = `
    <div style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;margin-top:4px;"></div>
    <div>${msg}</div>
  `;
  document.body.appendChild(t);
  setTimeout(() => { if (t.parentNode) t.remove(); }, duration);
}

function createManualBtn(label, color, onClickFn) {
  const id = '_ph_manual_btn';
  if (document.getElementById(id)) return;
  const btn = document.createElement('div');
  btn.id = id;
  btn.innerHTML = `📥 ${label}`;
  btn.style.cssText = `
    position:fixed;bottom:70px;right:24px;
    background:${color};
    color:#fff;font-family:Arial,sans-serif;font-size:12px;font-weight:bold;
    padding:9px 14px;border-radius:8px;cursor:pointer;z-index:999998;
    box-shadow:0 4px 12px rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.2);
    user-select:none;opacity:0.85;
  `;
  btn.title = 'Nhấn để lưu thủ công (dùng khi đổi điều kiện tìm kiếm)';
  btn.onmouseover = () => { btn.style.opacity = '1'; };
  btn.onmouseout  = () => { btn.style.opacity = '0.85'; };
  btn.onclick = onClickFn;
  document.body.appendChild(btn);
}

function removeManualBtn() {
  const el = document.getElementById('_ph_manual_btn');
  if (el) el.remove();
}

// ── Lùi thời gian thử lại khi gửi thất bại ─────────────────────────────
// showToast() cũng là 1 thay đổi trên document.body — đúng thứ
// MutationObserver bên dưới đang theo dõi. Nếu đặt lại khoá chặn trùng
// NGAY sau khi hiện toast, observer bắt được thay đổi đó và gọi lại hàm
// gửi ngay lập tức — thành vòng lặp không có độ trễ, chỉ bị chặn bởi thời
// gian round-trip của request đang lỗi. Với mã 403 (mã kết nối sai/bị thu
// hồi) vòng lặp đó không bao giờ tự tắt, mỗi vòng vẫn tốn 1 dòng
// audit_logs. Chỉ lùi thời gian thử lại (tăng dần, tối đa 5 phút) cho lỗi
// CÓ THỂ tạm thời (mất mạng, server lỗi) — 403 thì KHÔNG tự thử lại, chỉ
// nút thủ công mới thử lại được.
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

/* ══════════════════════════════════════════════════════
   1. PAYMENTHUB – Báo cáo kênh thanh toán
   ══════════════════════════════════════════════════════ */

function readLoaiTienPH() {
  // Ưu tiên đọc từ select element "Loại tiền" — chính xác nhất
  const selects = document.querySelectorAll('select');
  for (const sel of selects) {
    const label = sel.closest('.ant-form-item, .form-item, .filter-item, tr, td');
    const labelTxt = label ? label.innerText : '';
    if (labelTxt.includes('Loại tiền') || sel.id?.includes('tien') || sel.name?.includes('tien')) {
      const val = (sel.options[sel.selectedIndex]?.text || sel.value || '').trim().toUpperCase();
      if (val.includes('USD')) return 'USD';
      if (val.includes('EUR')) return 'EUR';
      if (val.includes('VN') || val.includes('VND') || val === '') return 'VNĐ';
    }
  }

  // Thử đọc từ label/span "Loại tiền: ..." — chỉ lấy đúng text sau dấu :
  const allText = document.body?.innerText || '';
  const m = allText.match(/Loại tiền[^:]*:\s*(VN[DĐ]|USD|EUR)/i);
  if (m) {
    const v = m[1].toUpperCase();
    if (v.includes('USD')) return 'USD';
    if (v.includes('EUR')) return 'EUR';
    return 'VNĐ';
  }

  // Đọc từ text hiển thị trên trang — chỉ đoạn tiêu đề báo cáo
  const heading = document.querySelector('h3, h4, .report-title, .bao-cao-title');
  if (heading) {
    const h = heading.innerText.toUpperCase();
    if (h.includes('USD')) return 'USD';
    if (h.includes('EUR')) return 'EUR';
  }

  // Kiểm tra dropdown ant-design đang chọn
  const antSelects = document.querySelectorAll('.ant-select-selection-item, .ant-select-selected-value');
  for (const el of antSelects) {
    const txt = el.innerText.trim().toUpperCase();
    const parent = el.closest('.ant-form-item, .filter-row');
    const parentLabel = parent?.querySelector('label, .ant-form-item-label')?.innerText || '';
    if (parentLabel.includes('Loại tiền') || parentLabel.includes('tien')) {
      if (txt.includes('USD')) return 'USD';
      if (txt.includes('EUR')) return 'EUR';
      if (txt.includes('VN') || txt.includes('VIỆT')) return 'VNĐ';
    }
  }

  return 'VNĐ'; // Mặc định VNĐ
}

function readBaoCaoData() {
  const result = { ih: null, il: null, loaiTien: readLoaiTienPH() };
  for (const row of document.querySelectorAll('table tbody tr')) {
    const tds = row.querySelectorAll('td');
    if (tds.length < 7) continue;
    const ten = (tds[2]?.innerText || '').trim();
    if (ten.includes('CITAD cao')) {
      result.ih = {
        den_m: parseNum(tds[3]?.innerText), den_t: parseMoney(tds[4]?.innerText),
        di_m:  parseNum(tds[5]?.innerText), di_t:  parseMoney(tds[6]?.innerText),
      };
    }
    if (ten.includes('CITAD thấp')) {
      result.il = {
        den_m: parseNum(tds[3]?.innerText), den_t: parseMoney(tds[4]?.innerText),
        di_m:  parseNum(tds[5]?.innerText), di_t:  parseMoney(tds[6]?.innerText),
      };
    }
  }
  return result;
}

function hasBaoCaoResults() {
  for (const r of document.querySelectorAll('table tbody tr')) {
    if (r.innerText.includes('CITAD cao') || r.innerText.includes('CITAD thấp')) return true;
  }
  return false;
}

let lastBaoCaoKey = '';
let _savingBaoCao = false; // đang có 1 lượt gửi dở chưa xong — chặn gửi trùng
const _baoCaoRetry = _makeRetryScheduler(() => { lastBaoCaoKey = ''; });

async function saveBaoCao(manual=false) {
  if (!SERVER || !EXTENSION_TOKEN) {
    if (manual) showToast('⚠️ Chưa cấu hình Extension — bấm icon Extension trên thanh công cụ → Tuỳ chọn', '#f59e0b', 6000);
    return;
  }
  if (!hasBaoCaoResults()) {
    if (manual) showToast('Chưa có kết quả, hãy Lập báo cáo trước', '#f59e0b');
    return;
  }
  const data = readBaoCaoData();
  if (!data.ih && !data.il) return;

  const ih = data.ih || { den_m:0, den_t:0, di_m:0, di_t:0 };
  const il = data.il || { den_m:0, den_t:0, di_m:0, di_t:0 };
  const tien = data.loaiTien;
  const key = `${tien}_${ih.den_t}_${il.di_t}`;

  if (!manual && key === lastBaoCaoKey) return;
  if (ih.den_t === 0 && il.den_t === 0 && ih.di_t === 0 && il.di_t === 0) {
    if (manual) showToast('Số liệu toàn 0, kiểm tra lại kết quả', '#f59e0b');
    return;
  }
  // Nút thủ công reset lastBaoCaoKey='' rồi gọi saveBaoCao(true) ngay lập
  // tức — nếu request TRƯỚC (do observer/interval kích hoạt) còn đang chạy
  // dở, bấm nút nhiều lần liên tiếp sẽ gửi trùng dữ liệu. Chặn bằng cờ
  // đang-xử-lý, không chỉ dựa vào khoá dedup (đã bị nút thủ công xoá).
  if (_savingBaoCao) return;
  lastBaoCaoKey = key;
  _savingBaoCao = true;

  try {
    await _doSaveBaoCao(ih, il, tien, manual);
  } finally {
    _savingBaoCao = false;
  }
}

async function _doSaveBaoCao(ih, il, tien, manual) {
  const items = [
    { key:`ph_${tien}_den_ih`, loai:'ih', chieu:'den', tien, soMon: ih.den_m, soTien: ih.den_t },
    { key:`ph_${tien}_di_ih`,  loai:'ih', chieu:'di',  tien, soMon: ih.di_m,  soTien: ih.di_t  },
    { key:`ph_${tien}_den_il`, loai:'il', chieu:'den', tien, soMon: il.den_m, soTien: il.den_t },
    { key:`ph_${tien}_di_il`,  loai:'il', chieu:'di',  tien, soMon: il.di_m,  soTien: il.di_t  },
  ];

  // fetch() thật chạy trong background.js (service worker) để né CORS —
  // fetch() từ content script mang Origin của trang PaymentHub, bị chặn
  // (đã kiểm chứng thực tế), xem background.js.
  const result = await new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        type: 'BUFFER_POST',
        url: `${SERVER}/api/doi-chieu-citad/paymenthub-buffer`,
        token: EXTENSION_TOKEN,
        body: { items, ts: new Date().toLocaleTimeString('vi-VN') },
      },
      (response) => resolve(response || { ok: false, status: null })
    );
  });

  if (result.status === 403) {
    // Mã kết nối sai/bị thu hồi — KHÔNG phải sự cố tạm thời, không tự thử
    // lại (return sớm, không rơi xuống nhánh else bên dưới — trước đây
    // status===403 vẫn có ok===false nên lọt xuống else, reset khoá và
    // lặp lại vô hạn).
    showToast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở /doi_chieu_citad', '#ef4444', 8000);
    return;
  }
  if (result.ok) {
    showToast(
      `✓ ${manual?'Đã lưu':'Tự lưu'} PaymentHub – ${tien}<br>` +
      `<small style="color:#94a3b8">IH Đến: ${ih.den_m.toLocaleString('vi-VN')} món | IL Đi: ${il.di_m.toLocaleString('vi-VN')} món</small>`,
      '#10b981', 5000
    );
    _baoCaoRetry.resetBackoff();
  } else {
    showToast(`✗ Lỗi server (${SERVER})`, '#ef4444');
    _baoCaoRetry.scheduleRetry();
  }
}

function observeBaoCao() {
  createManualBtn('Lưu lại PaymentHub', '#1d4ed8', () => {
    _baoCaoRetry.resetBackoff();
    lastBaoCaoKey = '';
    saveBaoCao(true);
  });

  // PaymentHub là SPA (Ant Design) — điều hướng nội bộ không reload trang,
  // nên content script cũ (đã inject 1 lần) vẫn tiếp tục chạy trên URL
  // MỚI nếu không tự dừng. hasTraCuuResults()/hasBaoCaoResults() chỉ quét
  // text chung trên toàn document.body nên có thể vô tình khớp ở 1 trang
  // không liên quan, tự POST nhầm dữ liệu. Ghi lại URL lúc bắt đầu, huỷ
  // observer/interval + gỡ nút thủ công ngay khi URL đổi.
  const startHref = window.location.href;
  const observer = new MutationObserver(() => {
    if (window.location.href !== startHref) { _stopWatching(observer, interval); return; }
    saveBaoCao(false);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  const interval = setInterval(() => {
    if (window.location.href !== startHref) { _stopWatching(observer, interval); return; }
    saveBaoCao(false);
  }, 1500);
}

function _stopWatching(observer, intervalId) {
  observer.disconnect();
  clearInterval(intervalId);
  removeManualBtn();
}

/* ══════════════════════════════════════════════════════
   2. TRA CỨU GD ĐẾN (PaymentHub + Payment)
   ══════════════════════════════════════════════════════ */

function readTraCuuData() {
  const txt = document.body?.innerText || '';
  const mMon  = txt.match(/Tổng số giao dịch:\s*([\d.,]+)/);
  const mTien = txt.match(/Tổng số tiền:\s*([\d.,]+)\s*(VND|USD|EUR)/i);
  return {
    soMon:   mMon  ? (parseInt(mMon[1].replace(/[^\d]/g,'')) || 0) : 0,
    soTien:  mTien ? parseMoney(mTien[1]) : 0,
    loaiTien: mTien ? (mTien[2].toUpperCase() === 'VND' ? 'VNĐ' : mTien[2].toUpperCase()) : 'VNĐ',
  };
}

function hasTraCuuResults() {
  return /Tổng số tiền:/.test(document.body?.innerText || '');
}

// PSS - MDP: cùng màn "Tra cứu giao dịch đến" như Napas, chỉ khác bộ lọc
// "Ngân hàng gửi" đang chọn tài khoản Mobifone (mã 99991032) — người dùng
// tự lọc đúng tài khoản trước khi bấm Tìm kiếm, ở đây chỉ đọc lại ô đang
// hiện gì để tự gắn đúng nhãn, không đoán mò. Quét trong đoạn text ngay
// sau nhãn (không quét cả trang) để tránh khớp nhầm nếu mã 99991032 vô
// tình xuất hiện ở dòng kết quả khác.
function isPssMdpFilter() {
  const allText = document.body?.innerText || '';
  const idx = allText.indexOf('Ngân hàng gửi');
  if (idx === -1) return false;
  return allText.slice(idx, idx + 200).includes('99991032');
}

let lastTraCuuKey = '';
let _savingTraCuu = false; // đang có 1 lượt gửi dở chưa xong — chặn gửi trùng
const _traCuuRetry = _makeRetryScheduler(() => { lastTraCuuKey = ''; });

async function saveTraCuu(source, manual=false) {
  if (!SERVER || !EXTENSION_TOKEN) {
    if (manual) showToast('⚠️ Chưa cấu hình Extension — bấm icon Extension trên thanh công cụ → Tuỳ chọn', '#f59e0b', 6000);
    return;
  }
  if (!hasTraCuuResults()) {
    if (manual) showToast('Chưa có kết quả, hãy Tìm kiếm trước', '#f59e0b');
    return;
  }
  const data = readTraCuuData();
  if (data.soTien === 0) {
    if (manual) showToast('Số tiền = 0, kiểm tra lại kết quả', '#f59e0b');
    return;
  }

  // src: kênh THẬT theo bộ lọc đang chọn (napas/pssmdp) — khác `source`
  // tham số truyền vào (paymenthub/payment, chỉ cho biết đang ở site nào,
  // không nói lên kênh nghiệp vụ). Đưa vào khoá chống trùng để đổi bộ lọc
  // (napas ↔ pssmdp) mà số tiền/loại tiền trùng ngẫu nhiên vẫn không bị
  // coi là "đã lưu rồi" và bỏ qua.
  const src = isPssMdpFilter() ? 'pssmdp' : 'napas';
  const key = `${data.loaiTien}_${data.soTien}_${source}_${src}`;
  if (!manual && key === lastTraCuuKey) return;
  // Cùng lý do với saveBaoCao(): nút thủ công xoá khoá dedup rồi gọi lại
  // ngay — cần cờ đang-xử-lý riêng để double-click không gửi trùng.
  if (_savingTraCuu) return;
  lastTraCuuKey = key;
  _savingTraCuu = true;

  try {
    await _doSaveTraCuu(data, src, manual);
  } finally {
    _savingTraCuu = false;
  }
}

async function _doSaveTraCuu(data, src, manual) {
  const payload = {
    key:    `${src}_ih_den_${data.loaiTien}`,
    loai:   'ih', chieu: 'den',
    tien:   data.loaiTien,
    soMon:  data.soMon,
    soTien: data.soTien,
    source: src,
    ts: new Date().toLocaleTimeString('vi-VN')
  };

  // fetch() thật chạy trong background.js (service worker) để né CORS —
  // xem ghi chú tương tự ở saveBaoCao()/background.js.
  const result = await new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        type: 'BUFFER_POST',
        url: `${SERVER}/api/doi-chieu-citad/paymenthub-buffer`,
        token: EXTENSION_TOKEN,
        body: { items: [payload], ts: payload.ts },
      },
      (response) => resolve(response || { ok: false, status: null })
    );
  });

  if (result.ok) {
    const nhanLabel = src === 'pssmdp' ? 'PSS - MDP' : 'Napas';
    showToast(
      `✓ ${manual?'Đã lưu':'Tự lưu'} ${nhanLabel} IH Đến – ${data.loaiTien}<br>` +
      `<small style="color:#94a3b8">${data.soMon.toLocaleString('vi-VN')} món | ${data.soTien.toLocaleString('vi-VN')}</small>`,
      '#10b981', 5000
    );
    _traCuuRetry.resetBackoff();
  } else if (result.status === 403) {
    // Mã kết nối sai/bị thu hồi — không phải sự cố tạm thời, không lên
    // lịch thử lại.
    showToast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở /doi_chieu_citad', '#ef4444', 8000);
  } else {
    showToast(`✗ Lỗi server (${SERVER})`, '#ef4444');
    _traCuuRetry.scheduleRetry();
  }
}

function observeTraCuu(source) {
  createManualBtn('Lưu lại Napas/PSS-MDP IH Đến', '#065f46', () => {
    _traCuuRetry.resetBackoff();
    lastTraCuuKey = '';
    saveTraCuu(source, true);
  });

  // Cùng lý do dừng theo URL như observeBaoCao() — tránh tự POST nhầm dữ
  // liệu nếu SPA điều hướng sang trang khác mà không reload.
  const startHref = window.location.href;
  const observer = new MutationObserver(() => {
    if (window.location.href !== startHref) { _stopWatching(observer, interval); return; }
    saveTraCuu(source, false);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  const interval = setInterval(() => {
    if (window.location.href !== startHref) { _stopWatching(observer, interval); return; }
    saveTraCuu(source, false);
  }, 1500);
}

/* ══════════════════════════════════════════════════════
   3. PAYMENT — Chuyển tiền đến, lọc "Loại lệnh: Lệnh quyết toán"
   ══════════════════════════════════════════════════════
   Khác PaymentHub (1 số "Tổng số tiền" gộp sẵn): ở đây kết quả gộp CẢ
   Napas lẫn PSS-MDP làm một, không tách được bằng cách đọc số tổng — phải
   đọc TỪNG DÒNG, cột "NH gửi" ghi rõ mã từng dòng, tự cộng dồn riêng theo
   mã (readPaymentDetailTotals()). Cột "NH gửi" CÓ SẴN ngay trong bảng kết
   quả mặc định (Loại lệnh: Lệnh quyết toán, NH gửi để "Tất cả") — chỉ cần
   kéo bảng sang phải, KHÔNG cần bấm "Xem chi tiết lệnh" (đã xác nhận thực
   tế nhiều lần).

   NGUYÊN NHÂN THẬT khiến trước đây không đọc được cột này (đã xác nhận qua
   console người dùng tự chạy: `[...t.querySelectorAll('th')].map(x=>x.
   innerText)` liệt kê đủ "NH gửi"/"Số tiền", chữ sạch) — KHÔNG PHẢI do tên
   cột lệch/có icon, mà do selector định vị <th> quá hẹp: bản cũ dùng
   `'thead th, tr:first-child th, tr:first-child td'` (chỉ tìm trong
   <thead> hoặc đúng dòng <tr> đầu tiên), nhưng bảng thật của trang này
   không đặt <th> theo 1 trong 2 kiểu đó nên luôn trượt. Nay dùng đơn giản
   `'th'` (mọi thẻ <th> trong bảng, không giới hạn vị trí) — xem
   _findPaymentTable()/_findResultsTableWithAmount(). _cleanHeader()/
   _headerIndexOf() (so khớp "chứa chuỗi" sau chuẩn hoá khoảng trắng) vẫn
   giữ lại vì vô hại và có thể hữu ích cho biến thể khác, nhưng KHÔNG phải
   nguyên nhân chính đã sửa.

   Có 2 cách tách, thử theo thứ tự (savePaymentDetail()):
     1. NGƯỜI DÙNG tự lọc theo bộ lọc "NH gửi" = 1 mã cụ thể ở form tìm
        kiếm → cả bảng chỉ thuộc 1 kênh, chỉ cần cộng dồn cột "Số tiền" của
        TẤT CẢ dòng (readNhGuiFilterChannel() + readFilteredChannelTotals()).
     2. Mặc định (đường chính, "Tất cả" các bộ lọc) → đọc cột "NH gửi" theo
        từng dòng trong bảng kết quả có sẵn (readPaymentDetailTotals()).
        _tryExpandDetail() chỉ là lưới an toàn dự phòng cho trường hợp bảng
        thật sự chưa có cột "NH gửi" (hasPaymentResults() == false) —
        thường sẽ không cần chạy tới vì cột đã có sẵn.
   Mã NH gửi ở đây KHÁC mã dùng trên PaymentHub (01401001 vẫn là Napas —
   không đổi giữa 2 hệ thống — nhưng PSS-MDP ở đây là 01406001, không phải
   99991032 như PaymentHub) — 2 hằng số tách riêng, không dùng chung, tránh
   nhầm hệ thống. */

const NH_GUI_NAPAS = '01401001';
const NH_GUI_PSSMDP = '01406001';

// Chuẩn hoá text tiêu đề cột: gộp mọi khoảng trắng/xuống dòng liên tiếp
// thành 1 dấu cách. Bảng có nút sắp xếp cột thường chèn icon/khoảng trắng
// phụ vào trong <th> (vd icon mũi tên nằm trên dòng riêng) khiến innerText
// ra "NH gửi\n" hoặc có khoảng trắng kép — so khớp TUYỆT ĐỐI (===) trước đây
// trượt trong các trường hợp này dù cột "NH gửi" hiển thị đúng, có sẵn ngay
// ở bảng kết quả mặc định (đã xác nhận thực tế, KHÔNG cần "Xem chi tiết
// lệnh"). Nay so khớp kiểu "chứa chuỗi" sau khi chuẩn hoá, khoan dung hơn.
function _cleanHeader(s) {
  return (s || '').replace(/\s+/g, ' ').trim();
}

function _headerIndexOf(headers, name) {
  return headers.findIndex(h => h.includes(name));
}

function _findPaymentTable() {
  for (const t of document.querySelectorAll('table')) {
    const headCells = t.querySelectorAll('th');
    for (const c of headCells) {
      if (_cleanHeader(c.innerText).includes('NH gửi')) return t;
    }
  }
  return null;
}

function hasPaymentResults() {
  const t = _findPaymentTable();
  return !!(t && t.querySelectorAll('tbody tr').length > 0);
}

// Lưới an toàn dự phòng: bảng kết quả mặc định ĐÃ CÓ SẴN cột "NH gửi" (xác
// nhận thực tế qua console), nên bình thường không cần hàm này — chỉ chạy
// tới khi hasPaymentResults() vẫn false dù đã sửa đúng selector định vị
// <th> (xem comment đầu mục "3. PAYMENT"), phòng trường hợp hiếm bảng thật
// sự ở dạng khác (vd chưa tải xong). Cooldown theo thời gian (không phải
// khoá một-lần) để tự thử lại nếu bảng tải chậm, nhưng không bấm dồn dập
// mỗi 1.5s — nút "Xem chi tiết lệnh" có thể là dạng bật/tắt, bấm khi đang
// tải dở có thể vô tình ẩn lại bảng vừa hiện.
let _lastExpandAttempt = 0;
function _tryExpandDetail() {
  if (_findPaymentTable()) return; // đã có cột "NH gửi" rồi, khỏi làm gì thêm
  if (!/Tổng số giao dịch:/.test(document.body?.innerText || '')) return; // chưa tìm kiếm gì cả

  const now = Date.now();
  if (now - _lastExpandAttempt < 4000) return;
  _lastExpandAttempt = now;

  // Tích "chọn tất cả" ở đầu bảng tóm tắt — "Xem chi tiết lệnh" cần tích ít
  // nhất 1 dòng mới bấm được (đã xác nhận thực tế, nút bị khoá nếu bỏ trống).
  const headCheckbox = document.querySelector('table thead input[type="checkbox"]');
  if (headCheckbox && !headCheckbox.checked) headCheckbox.click();

  for (const btn of document.querySelectorAll('button')) {
    if ((btn.innerText || '').trim() === 'Xem chi tiết lệnh') {
      btn.click();
      return;
    }
  }
}

// Trả về { napas: {VNĐ: {soMon, soTien}, ...}, pssmdp: {...} } — cộng dồn
// theo TỪNG dòng bảng, không đọc số tổng có sẵn (số đó gộp cả 2 kênh).
function readPaymentDetailTotals() {
  const table = _findPaymentTable();
  const totals = { napas: {}, pssmdp: {} };
  if (!table) return totals;

  const headers = Array.from(table.querySelectorAll('th'))
    .map(c => _cleanHeader(c.innerText));
  const idxNH = _headerIndexOf(headers, 'NH gửi');
  const idxTien = _headerIndexOf(headers, 'Số tiền');
  const idxLoaiTien = _headerIndexOf(headers, 'Loại tiền');
  if (idxNH === -1 || idxTien === -1) return totals;

  for (const row of table.querySelectorAll('tbody tr')) {
    const cells = row.querySelectorAll('td');
    if (cells.length <= Math.max(idxNH, idxTien)) continue;
    const nhGui = (cells[idxNH]?.innerText || '').trim();
    let channel = null;
    if (nhGui.startsWith(NH_GUI_NAPAS)) channel = 'napas';
    else if (nhGui.startsWith(NH_GUI_PSSMDP)) channel = 'pssmdp';
    if (!channel) continue; // dòng không thuộc 2 kênh này — bỏ qua, không đoán

    const tien = parseMoney(cells[idxTien]?.innerText);
    const loaiTienRaw = idxLoaiTien !== -1 ? (cells[idxLoaiTien]?.innerText || '').trim().toUpperCase() : 'VND';
    const loaiTien = loaiTienRaw === 'VND' ? 'VNĐ' : loaiTienRaw;

    totals[channel][loaiTien] = totals[channel][loaiTien] || { soMon: 0, soTien: 0 };
    totals[channel][loaiTien].soMon += 1;
    totals[channel][loaiTien].soTien += tien;
  }
  return totals;
}

// ── Lọc sẵn theo 1 mã "NH gửi" cụ thể ở bộ lọc tìm kiếm ─────────────────
// Cách khác để tách Napas/PSS-MDP, KHÔNG cần "Xem chi tiết lệnh": người dùng
// tự chọn bộ lọc "NH gửi" = 01401001 (Napas) hoặc 01406001 (PSS-MDP) rồi bấm
// Tìm kiếm — cả bảng lúc đó chỉ thuộc 1 kênh, khỏi cần đọc cột "NH gửi" theo
// từng dòng nữa. Khác PaymentHub: trang KHÔNG tự cộng sẵn "Tổng số tiền" khi
// lọc kiểu này (chỉ có "Tổng số giao dịch" đếm SỐ MÓN) — phải tự quét cộng
// dồn cột "Số tiền" của từng dòng mới ra tổng tiền.
// Tìm đúng thẻ nhãn "NH gửi" trong form lọc rồi dò lên từng cấp cha để tìm
// giá trị đang chọn — không đoán chỉ 1 kiểu hiển thị vì mỗi khung giao diện
// khác nhau: có nơi hiện chữ ngay trong thẻ (span/div, đọc được qua
// textContent), có nơi hiện qua ô <input readonly value="..."> (KHÔNG tính
// vào textContent/innerText — lần trước lỗi chính là chỗ này). Dừng ở cấp
// cha ĐẦU TIÊN tìm thấy mã, để không lỡ quét rộng sang các trường lọc khác.
function readNhGuiFilterChannel() {
  const labelEls = Array.from(document.querySelectorAll('label, span, div, td, th'))
    .filter(el => el.children.length === 0 && (el.textContent || '').trim() === 'NH gửi');
  for (const label of labelEls) {
    let scope = label.parentElement;
    for (let hop = 0; scope && hop < 4; hop++, scope = scope.parentElement) {
      for (const c of scope.querySelectorAll('input, select')) {
        const v = c.value || '';
        if (v.includes(NH_GUI_NAPAS)) return 'napas';
        if (v.includes(NH_GUI_PSSMDP)) return 'pssmdp';
      }
      const txt = scope.textContent || '';
      if (txt.includes(NH_GUI_NAPAS)) return 'napas';
      if (txt.includes(NH_GUI_PSSMDP)) return 'pssmdp';
    }
  }
  return null;
}

function _findResultsTableWithAmount() {
  for (const t of document.querySelectorAll('table')) {
    const headCells = t.querySelectorAll('th');
    for (const c of headCells) {
      if (_cleanHeader(c.innerText).includes('Số tiền')) return t;
    }
  }
  return null;
}

function _totalGiaoDichCount() {
  const m = (document.body?.innerText || '').match(/Tổng số giao dịch:\s*([\d.,]+)/);
  return m ? (parseInt(m[1].replace(/[^\d]/g, '')) || null) : null;
}

// Trả về { VNĐ: {soMon, soTien}, USD: {...}, ... } — cộng dồn TẤT CẢ dòng
// đang hiển thị (đã lọc sẵn 1 kênh qua bộ lọc "NH gửi", không cần phân biệt
// gì thêm theo dòng).
function readFilteredChannelTotals() {
  const table = _findResultsTableWithAmount();
  const totals = {};
  if (!table) return totals;
  const headers = Array.from(table.querySelectorAll('th'))
    .map(c => _cleanHeader(c.innerText));
  const idxTien = _headerIndexOf(headers, 'Số tiền');
  const idxLoaiTien = _headerIndexOf(headers, 'Loại tiền');
  if (idxTien === -1) return totals;

  for (const row of table.querySelectorAll('tbody tr')) {
    const cells = row.querySelectorAll('td');
    if (cells.length <= idxTien) continue;
    const tien = parseMoney(cells[idxTien]?.innerText);
    const loaiTienRaw = idxLoaiTien !== -1 ? (cells[idxLoaiTien]?.innerText || '').trim().toUpperCase() : 'VND';
    const loaiTien = loaiTienRaw === 'VND' ? 'VNĐ' : loaiTienRaw;
    totals[loaiTien] = totals[loaiTien] || { soMon: 0, soTien: 0 };
    totals[loaiTien].soMon += 1;
    totals[loaiTien].soTien += tien;
  }
  return totals;
}

let lastPaymentKey = '';
let _savingPayment = false;
const _paymentRetry = _makeRetryScheduler(() => { lastPaymentKey = ''; });

// Gửi buffer lên backend — dùng chung cho cả 2 đường lấy dữ liệu (đọc bảng
// chi tiết theo cột "NH gửi" NGƯỜI DÙNG KHÔNG lọc, và đọc bảng đã lọc sẵn 1
// kênh qua bộ lọc "NH gửi"). `sourceLabel` chỉ khác nhau ở dòng mô tả trên
// toast, logic gửi/dedup/lùi thời gian thử lại giống hệt nhau.
async function _postPaymentItems(items, manual, sourceLabel) {
  const key = JSON.stringify(items.map(i => [i.key, i.soMon, i.soTien]));
  if (!manual && key === lastPaymentKey) return;
  if (_savingPayment) return;
  lastPaymentKey = key;
  _savingPayment = true;

  try {
    const ts = new Date().toLocaleTimeString('vi-VN');
    const result = await new Promise((resolve) => {
      chrome.runtime.sendMessage(
        {
          type: 'BUFFER_POST',
          url: `${SERVER}/api/doi-chieu-citad/paymenthub-buffer`,
          token: EXTENSION_TOKEN,
          body: { items: items.map(i => ({ ...i, ts })), ts },
        },
        (response) => resolve(response || { ok: false, status: null })
      );
    });

    if (result.ok) {
      const parts = items.map(i =>
        `${i.source === 'pssmdp' ? 'PSS-MDP' : 'Napas'} ${i.tien}: ${i.soMon.toLocaleString('vi-VN')} món | ${i.soTien.toLocaleString('vi-VN')}`
      ).join('<br>');
      showToast(`✓ ${manual ? 'Đã lưu' : 'Tự lưu'} ${sourceLabel}<br><small style="color:#94a3b8">${parts}</small>`, '#10b981', 6000);
      _paymentRetry.resetBackoff();
    } else if (result.status === 403) {
      showToast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở /doi_chieu_citad', '#ef4444', 8000);
    } else {
      showToast(`✗ Lỗi server (${SERVER})`, '#ef4444');
      _paymentRetry.scheduleRetry();
    }
  } finally {
    _savingPayment = false;
  }
}

// Đường lấy dữ liệu khi đã LỌC SẴN theo 1 mã "NH gửi" ở bộ lọc tìm kiếm —
// khỏi cần "Xem chi tiết lệnh"/đọc cột "NH gửi" theo dòng, vì cả bảng chỉ
// thuộc đúng 1 kênh rồi. Trang không tự cộng sẵn tổng tiền kiểu lọc này nên
// phải tự quét cộng dồn — ĐỐI CHIẾU số dòng quét được với "Tổng số giao
// dịch" trang báo: nếu ít hơn (bảng đang phân trang, chưa xem hết) thì
// KHÔNG lưu (kể cả tự động) để tránh nạp nhầm số liệu thiếu vào form.
async function _saveFilteredChannel(channel, manual) {
  const totals = readFilteredChannelTotals();
  const items = [];
  for (const [tien, v] of Object.entries(totals)) {
    if (!v.soTien) continue;
    items.push({
      key: `${channel}_ih_den_${tien}`,
      loai: 'ih', chieu: 'den', tien,
      soMon: v.soMon, soTien: v.soTien,
      source: channel,
    });
  }
  if (items.length === 0) {
    if (manual) showToast('Đã lọc theo NH gửi nhưng chưa đọc được cột "Số tiền" — hãy Tìm kiếm trước', '#f59e0b');
    return;
  }

  const totalCount = _totalGiaoDichCount();
  const summedCount = items.reduce((s, i) => s + i.soMon, 0);
  if (totalCount !== null && summedCount < totalCount) {
    if (manual) {
      showToast(
        `⚠️ Bảng đang phân trang: chỉ quét được ${summedCount}/${totalCount} giao dịch hiển thị — ` +
        `tăng số dòng/trang hoặc xem hết các trang rồi thử lại. KHÔNG lưu số liệu thiếu.`,
        '#f59e0b', 8000
      );
    }
    return;
  }

  const nhanLabel = channel === 'pssmdp' ? 'PSS-MDP' : 'Napas';
  await _postPaymentItems(items, manual, `${nhanLabel} (lọc theo NH gửi)`);
}

async function savePaymentDetail(manual = false) {
  if (!SERVER || !EXTENSION_TOKEN) {
    if (manual) showToast('⚠️ Chưa cấu hình Extension — bấm icon Extension trên thanh công cụ → Tuỳ chọn', '#f59e0b', 6000);
    return;
  }

  const filterChannel = readNhGuiFilterChannel();
  if (filterChannel) {
    await _saveFilteredChannel(filterChannel, manual);
    return;
  }

  if (!hasPaymentResults()) {
    // Bình thường không tới đây — cột "NH gửi" đã có sẵn trong bảng kết quả
    // mặc định. Chỉ rơi vào đây khi thật sự chưa tìm kiếm, hoặc bảng đang ở
    // dạng khác không có cột này — thử bung "Xem chi tiết lệnh" như lưới an
    // toàn dự phòng.
    _tryExpandDetail();
    if (manual) {
      const msg = /Tổng số giao dịch:/.test(document.body?.innerText || '')
        ? 'Không đọc được cột "NH gửi" trong bảng — đang thử bung "Xem chi tiết lệnh", đợi vài giây rồi bấm lại'
        : 'Chưa có kết quả, hãy Tìm kiếm trước';
      showToast(msg, '#f59e0b');
    }
    return;
  }
  const totals = readPaymentDetailTotals();
  const items = [];
  for (const channel of ['napas', 'pssmdp']) {
    for (const [tien, v] of Object.entries(totals[channel])) {
      if (!v.soTien) continue;
      items.push({
        key: `${channel}_ih_den_${tien}`,
        loai: 'ih', chieu: 'den', tien,
        soMon: v.soMon, soTien: v.soTien,
        source: channel,
      });
    }
  }
  if (items.length === 0) {
    if (manual) showToast('Không có dòng Napas/PSS-MDP nào trong bảng (cột NH gửi)', '#f59e0b');
    return;
  }
  await _postPaymentItems(items, manual, 'từ bảng chi tiết');
}

function observePaymentDetail() {
  createManualBtn('Lưu Napas + PSS-MDP (bảng chi tiết)', '#065f46', () => {
    _paymentRetry.resetBackoff();
    lastPaymentKey = '';
    savePaymentDetail(true);
  });

  const startHref = window.location.href;
  const observer = new MutationObserver(() => {
    if (window.location.href !== startHref) { _stopWatching(observer, interval); return; }
    if (!readNhGuiFilterChannel()) _tryExpandDetail();
    savePaymentDetail(false);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  const interval = setInterval(() => {
    if (window.location.href !== startHref) { _stopWatching(observer, interval); return; }
    if (!readNhGuiFilterChannel()) _tryExpandDetail();
    savePaymentDetail(false);
  }, 1500);
}

/* ══════════════════════════════════════════════════════
   KHỞI CHẠY theo URL
   ══════════════════════════════════════════════════════ */
(async () => {
await loadConfig();
const _url = window.location.href;

if (_url.includes('paymenthub.agribank.com.vn/statistic')) {
  observeBaoCao();
} else if (_url.includes('paymenthub.agribank.com.vn')) {
  observeTraCuu('paymenthub');
} else if (_url.includes('payment.agribank.com.vn/payment-in')) {
  // Trang này gộp Napas + PSS-MDP vào 1 số tổng — phải đọc bảng chi tiết
  // (cột "NH gửi") để tách riêng, KHÔNG dùng observeTraCuu() (đọc số tổng
  // có sẵn, đúng cho PaymentHub nhưng SAI ở đây vì gộp cả 2 kênh).
  observePaymentDetail();
}
})();
