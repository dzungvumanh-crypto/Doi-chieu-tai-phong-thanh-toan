/* ── PaymentHub + Payment Extension – Tự động + Thủ công ──
 * Bản cập nhật để trỏ vào backend TTTT dùng chung (thay vì server cổng
 * 8100 riêng của tool desktop cũ). Toàn bộ logic đọc DOM/scrape số liệu
 * GIỮ NGUYÊN 100% — chỉ đổi SERVER, đường dẫn API (prefix
 * /api/doi-chieu-citad/...) và thêm header X-Extension-Key.
 */

// Đang trỏ về server TEST chạy cục bộ (TTTT_test_run/, xem báo cáo trong hội thoại).
// Khi triển khai thật: đổi SERVER thành domain/IP thật của backend TTTT, và
// EXTENSION_KEY thành đúng giá trị CITAD_EXTENSION_KEY đã cấu hình ở backend (.env).
const SERVER = 'http://localhost:8000';
const EXTENSION_KEY = 'test-local-key';
// Username TTTT của người dùng máy này — BẮT BUỘC đặt đúng, dùng để tách
// buffer riêng cho từng người (nhiều người cùng dùng chung 1 backend).
// Đổi giá trị này thành đúng username đăng nhập TTTT của bạn trước khi dùng.
const STAFF_USERNAME = 'CHUA_CAU_HINH';

function parseNum(s) {
  return parseInt((s || '').replace(/[^\d]/g, '')) || 0;
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
        den_m: parseNum(tds[3]?.innerText), den_t: parseNum(tds[4]?.innerText),
        di_m:  parseNum(tds[5]?.innerText), di_t:  parseNum(tds[6]?.innerText),
      };
    }
    if (ten.includes('CITAD thấp')) {
      result.il = {
        den_m: parseNum(tds[3]?.innerText), den_t: parseNum(tds[4]?.innerText),
        di_m:  parseNum(tds[5]?.innerText), di_t:  parseNum(tds[6]?.innerText),
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

async function saveBaoCao(manual=false) {
  if (STAFF_USERNAME === 'CHUA_CAU_HINH') {
    if (manual) showToast('⚠️ Chưa cấu hình STAFF_USERNAME trong content_paymenthub.js', '#f59e0b', 6000);
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
  lastBaoCaoKey = key;

  const items = [
    { key:`ph_${tien}_den_ih`, loai:'ih', chieu:'den', tien, soMon: ih.den_m, soTien: ih.den_t },
    { key:`ph_${tien}_di_ih`,  loai:'ih', chieu:'di',  tien, soMon: ih.di_m,  soTien: ih.di_t  },
    { key:`ph_${tien}_den_il`, loai:'il', chieu:'den', tien, soMon: il.den_m, soTien: il.den_t },
    { key:`ph_${tien}_di_il`,  loai:'il', chieu:'di',  tien, soMon: il.di_m,  soTien: il.di_t  },
  ];

  try {
    const r = await fetch(`${SERVER}/api/doi-chieu-citad/paymenthub-buffer`, {
      method:'POST',
      headers:{'Content-Type':'application/json', 'X-Extension-Key': EXTENSION_KEY},
      body: JSON.stringify({ owner: STAFF_USERNAME, items, ts: new Date().toLocaleTimeString('vi-VN') })
    });
    if (r.ok) {
      showToast(
        `✓ ${manual?'Đã lưu':'Tự lưu'} PaymentHub – ${tien}<br>` +
        `<small style="color:#94a3b8">IH Đến: ${ih.den_m.toLocaleString('vi-VN')} món | IL Đi: ${il.di_m.toLocaleString('vi-VN')} món</small>`,
        '#10b981', 5000
      );
    } else {
      showToast(`✗ Lỗi server (${SERVER})`, '#ef4444');
      lastBaoCaoKey = '';
    }
  } catch(e) {
    showToast('✗ Không kết nối server. Kiểm tra backend TTTT đang chạy.', '#ef4444');
    lastBaoCaoKey = '';
  }
}

function observeBaoCao() {
  createManualBtn('Lưu lại PaymentHub', '#1d4ed8', () => {
    lastBaoCaoKey = '';
    saveBaoCao(true);
  });

  const observer = new MutationObserver(() => saveBaoCao(false));
  observer.observe(document.body, { childList: true, subtree: true });
  setInterval(() => saveBaoCao(false), 1500);
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
    soTien:  mTien ? (parseInt(mTien[1].replace(/[^\d]/g,'')) || 0) : 0,
    loaiTien: mTien ? (mTien[2].toUpperCase() === 'VND' ? 'VNĐ' : mTien[2].toUpperCase()) : 'VNĐ',
  };
}

function hasTraCuuResults() {
  return /Tổng số tiền:/.test(document.body?.innerText || '');
}

let lastTraCuuKey = '';

async function saveTraCuu(source, manual=false) {
  if (STAFF_USERNAME === 'CHUA_CAU_HINH') {
    if (manual) showToast('⚠️ Chưa cấu hình STAFF_USERNAME trong content_paymenthub.js', '#f59e0b', 6000);
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

  const key = `${data.loaiTien}_${data.soTien}_${source}`;
  if (!manual && key === lastTraCuuKey) return;
  lastTraCuuKey = key;

  const payload = {
    key:    `napas_ih_den_${data.loaiTien}`,
    loai:   'ih', chieu: 'den',
    tien:   data.loaiTien,
    soMon:  data.soMon,
    soTien: data.soTien,
    source: 'napas',
    ts: new Date().toLocaleTimeString('vi-VN')
  };

  try {
    const r = await fetch(`${SERVER}/api/doi-chieu-citad/paymenthub-buffer`, {
      method:'POST',
      headers:{'Content-Type':'application/json', 'X-Extension-Key': EXTENSION_KEY},
      body: JSON.stringify({ owner: STAFF_USERNAME, items: [payload], ts: payload.ts })
    });
    if (r.ok) {
      showToast(
        `✓ ${manual?'Đã lưu':'Tự lưu'} Napas IH Đến – ${data.loaiTien}<br>` +
        `<small style="color:#94a3b8">${data.soMon.toLocaleString('vi-VN')} món | ${data.soTien.toLocaleString('vi-VN')}</small>`,
        '#10b981', 5000
      );
    } else {
      showToast(`✗ Lỗi server (${SERVER})`, '#ef4444');
      lastTraCuuKey = '';
    }
  } catch(e) {
    showToast('✗ Không kết nối server. Kiểm tra backend TTTT đang chạy.', '#ef4444');
    lastTraCuuKey = '';
  }
}

function observeTraCuu(source) {
  createManualBtn('Lưu lại Napas IH Đến', '#065f46', () => {
    lastTraCuuKey = '';
    saveTraCuu(source, true);
  });

  const observer = new MutationObserver(() => saveTraCuu(source, false));
  observer.observe(document.body, { childList: true, subtree: true });
  setInterval(() => saveTraCuu(source, false), 1500);
}

/* ══════════════════════════════════════════════════════
   KHỞI CHẠY theo URL
   ══════════════════════════════════════════════════════ */
const _url = window.location.href;

if (_url.includes('paymenthub.agribank.com.vn/statistic')) {
  observeBaoCao();
} else if (_url.includes('paymenthub.agribank.com.vn')) {
  observeTraCuu('paymenthub');
} else if (_url.includes('payment.agribank.com.vn/payment-in')) {
  observeTraCuu('payment');
}
