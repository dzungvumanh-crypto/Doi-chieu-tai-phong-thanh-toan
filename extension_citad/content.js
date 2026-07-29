/* ── CITAD Extension – Tự động lưu khi có kết quả ──
 * Bản cập nhật để trỏ vào backend TTTT dùng chung (thay vì server cổng
 * 8100 riêng của tool desktop cũ). Toàn bộ logic đọc DOM/scrape số liệu
 * GIỮ NGUYÊN 100% — chỉ đổi SERVER, đường dẫn API (prefix
 * /api/doi-chieu-citad/...) và cách xác thực (mã kết nối cá nhân, xem dưới).
 *
 * XÁC THỰC: mỗi người tự tạo 1 "mã kết nối" (token) trên trang
 * /doi_chieu_citad (mục "Kết nối Extension") sau khi đã đăng nhập TTTT thật,
 * dán vào EXTENSION_TOKEN bên dưới. KHÔNG dùng chung 1 mã cho nhiều người —
 * backend tra token ra đúng chủ token, không còn tin bất kỳ tên nào tự khai.
 */

// Đang trỏ về server TEST chạy cục bộ (TTTT_test_run/, xem báo cáo trong hội thoại).
// Khi triển khai thật: đổi SERVER thành domain/IP thật của backend TTTT —
// BẮT BUỘC dùng https:// nếu backend chạy trên mạng thật (không chỉ localhost),
// nếu không mã kết nối và số liệu sẽ truyền ở dạng đọc được trên mạng.
const SERVER = 'http://localhost:8000';
// Mã kết nối cá nhân — lấy từ /doi_chieu_citad, mục "Kết nối Extension".
// Mỗi người có 1 mã riêng, không chia sẻ cho người khác.
const EXTENSION_TOKEN = 'CHUA_CAU_HINH';

if (!SERVER.startsWith('https://')) {
  console.warn('[CITAD Extension] SERVER không dùng HTTPS — mã kết nối và số liệu truyền ở dạng đọc được trên mạng nội bộ. Chỉ chấp nhận được khi test trên localhost.');
}

const CONG_MAP = {
  'CITAD001':  '1',
  'CITAD':     '9',
  'CITAD9212': '12',
  'CITAD7917': '17',
  'CITAD4818': '18',
};

// ── Helpers ──────────────────────────────────────────────────────────
function getEl(id1, id2, sel) {
  return document.getElementById(id1)
      || document.getElementById(id2)
      || document.querySelector(sel);
}
function getSelDV()  { return getEl('ctl00_ContentPlaceHolder1_cboServiceType','ctl00_ContentPlaceHolder2_cboServiceType','[id$="_cboServiceType"]'); }
function getRdbDi()  { return getEl('ctl00_ContentPlaceHolder1_rdbDi','ctl00_ContentPlaceHolder2_rdbDi','[id$="_rdbDi"]'); }
function getRdbDen() { return getEl('ctl00_ContentPlaceHolder1_rdbDen','ctl00_ContentPlaceHolder2_rdbDen','[id$="_rdbDen"]'); }
function getSelCur() { return getEl('ctl00_ContentPlaceHolder1_ddlcurrency','ctl00_ContentPlaceHolder2_ddlcurrency','[id$="_ddlcurrency"]'); }

function getCong() {
  const m = window.location.href.match(/10\.0\.85\.100\/([^/]+)\//);
  return m ? (CONG_MAP[m[1]] || m[1]) : '';
}

function isNgoaiTe() {
  return window.location.href.includes('BangKeGiaoDichNgoaiTeTrongNgay');
}

// ── Đọc cấu hình hiện tại từ trang ──────────────────────────────────
function readConfig() {
  const cfg = { cong: getCong(), loaiDV: '', chieu: '', loaiTien: '' };

  // Loại tiền
  if (!isNgoaiTe()) {
    cfg.loaiTien = 'VNĐ';
  } else {
    const sel = getSelCur();
    const v = (sel?.value || '').toUpperCase();
    cfg.loaiTien = v === 'EUR' ? 'EUR' : 'USD';
  }

  // IH / IL
  const selDV = getSelDV();
  if (selDV) {
    cfg.loaiDV = selDV.value === 'HV' ? 'ih' : selDV.value === 'LV' ? 'il' : 'all';
  }

  // Đi / Đến
  const rdbDi = getRdbDi(), rdbDen = getRdbDen();
  if (rdbDi  && rdbDi.checked)  cfg.chieu = 'di';
  if (rdbDen && rdbDen.checked) cfg.chieu = 'den';

  return cfg;
}

// ── Đọc kết quả bảng ────────────────────────────────────────────────
function readResult() {
  const res = { soMon: 0, soTien: 0 };
  for (const row of document.querySelectorAll('tr.grid-footer')) {
    const txt = row.innerText || '';
    const tds = row.querySelectorAll('td');
    if (txt.includes('Tổng số giao dịch')) {
      const m = txt.match(/Tổng số giao dịch:\s*([\d.,]+)/);
      if (m) res.soMon = parseInt(m[1].replace(/[^\d]/g,'')) || 0;
    }
    if (txt.includes('Tổng cộng') && tds.length >= 3) {
      const no = parseInt((tds[1]?.innerText||'').replace(/[^\d]/g,'')) || 0;
      const co = parseInt((tds[2]?.innerText||'').replace(/[^\d]/g,'')) || 0;
      res.soTien = no + co;
    }
  }
  return res;
}

function hasResults() {
  return document.querySelectorAll('tr.grid-footer').length > 0;
}

// ── Gửi lên server ───────────────────────────────────────────────────
async function saveToServer(cfg, res) {
  if (EXTENSION_TOKEN === 'CHUA_CAU_HINH') {
    showToast('⚠️ Chưa cấu hình EXTENSION_TOKEN trong content.js — vào /doi_chieu_citad để tạo mã kết nối', '#f59e0b', 6000);
    return false;
  }
  const payload = {
    key:    `citad_${cfg.cong}_${cfg.loaiTien}_${cfg.chieu}_${cfg.loaiDV}`,
    cong:   cfg.cong,
    loai:   cfg.loaiDV,
    chieu:  cfg.chieu,
    tien:   cfg.loaiTien,
    soMon:  res.soMon,
    soTien: res.soTien,
    ts: new Date().toLocaleTimeString('vi-VN')
  };
  try {
    const r = await fetch(`${SERVER}/api/doi-chieu-citad/citad-buffer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Extension-Token': EXTENSION_TOKEN },
      body: JSON.stringify(payload)
    });
    if (r.status === 403) {
      showToast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở /doi_chieu_citad', '#ef4444', 8000);
    }
    return r.ok;
  } catch(e) { return false; }
}

// ── Toast thông báo nhỏ ──────────────────────────────────────────────
function showToast(msg, color='#10b981', duration=3000) {
  const old = document.getElementById('_citad_toast');
  if (old) old.remove();

  const t = document.createElement('div');
  t.id = '_citad_toast';
  t.style.cssText = `
    position:fixed;bottom:24px;right:24px;
    background:#1e293b;border:1px solid ${color};border-radius:10px;
    padding:12px 18px;font-family:Arial,sans-serif;font-size:13px;
    color:#fff;z-index:999999;box-shadow:0 4px 16px rgba(0,0,0,.4);
    display:flex;align-items:center;gap:10px;max-width:320px;
    animation:_fadeIn .2s ease;
  `;

  // Thêm CSS animation
  if (!document.getElementById('_citad_style')) {
    const s = document.createElement('style');
    s.id = '_citad_style';
    s.textContent = '@keyframes _fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}';
    document.head.appendChild(s);
  }

  t.innerHTML = `
    <div style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></div>
    <div>${msg}</div>
  `;
  document.body.appendChild(t);
  setTimeout(() => { if(t.parentNode) t.remove(); }, duration);
}

// ── Auto-save: tự động lưu khi phát hiện kết quả mới ───────────────
let lastSavedKey = '';

async function autoSaveIfNew() {
  if (!hasResults()) return;

  const cfg = readConfig();
  const key = `${cfg.cong}_${cfg.loaiTien}_${cfg.chieu}_${cfg.loaiDV}`;

  // Tránh lưu trùng cùng tổ hợp
  if (key === lastSavedKey) return;

  // Bỏ qua nếu thiếu thông tin
  if (!cfg.cong || !cfg.chieu || !cfg.loaiDV || cfg.loaiDV === 'all') return;

  const res = readResult();

  // Không lưu nếu kết quả toàn 0 (trang chưa load xong)
  if (res.soMon === 0 && res.soTien === 0) return;

  lastSavedKey = key;

  const ok = await saveToServer(cfg, res);

  const loaiLabel = cfg.loaiDV === 'ih' ? 'IH' : 'IL';
  const chieuLabel = cfg.chieu === 'di' ? 'Đi' : 'Đến';

  if (ok) {
    showToast(
      `✓ Tự lưu: Cổng ${cfg.cong} – ${cfg.loaiTien} – ${loaiLabel} ${chieuLabel}<br>` +
      `<small style="color:#94a3b8">${res.soMon.toLocaleString('vi-VN')} món | ${res.soTien.toLocaleString('vi-VN')}</small>`,
      '#10b981', 4000
    );
  } else {
    showToast(`✗ Không kết nối server (${SERVER})`, '#ef4444', 4000);
    lastSavedKey = ''; // cho phép thử lại
  }
}

// ── Popup thành công ─────────────────────────────────────────────────
function showPopup(msg) {
  const old = document.getElementById('_citad_popup');
  if (old) old.remove();
  const overlay = document.createElement('div');
  overlay.id = '_citad_popup';
  overlay.style.cssText = `
    position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999999;
    display:flex;align-items:center;justify-content:center;
    animation:_fadeIn .15s ease;
  `;
  overlay.innerHTML = `
    <div style="
      background:#1e293b;border:1.5px solid #10b981;border-radius:14px;
      padding:28px 32px;min-width:320px;max-width:420px;
      box-shadow:0 8px 32px rgba(0,0,0,.5);font-family:Arial,sans-serif;
      text-align:center;position:relative;
    ">
      <div style="font-size:36px;margin-bottom:10px;">✅</div>
      <div style="color:#10b981;font-size:15px;font-weight:bold;margin-bottom:12px;">Nạp dữ liệu thành công</div>
      <div style="color:#e2e8f0;font-size:13px;line-height:1.7;">${msg}</div>
      <button onclick="document.getElementById('_citad_popup').remove()" style="
        margin-top:18px;background:#10b981;color:#fff;border:none;
        border-radius:8px;padding:8px 28px;font-size:13px;font-weight:bold;
        cursor:pointer;
      ">OK</button>
    </div>
  `;
  overlay.addEventListener('click', function(e){
    if (e.target === overlay) overlay.remove();
  });
  document.body.appendChild(overlay);
  // Tu dong dong sau 6 giay
  setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 6000);
}


// ── Nút thủ công (dự phòng) ─────────────────────────────────────────
function createManualBtn() {
  if (document.getElementById('_citad_btn')) return;
  const btn = document.createElement('div');
  btn.id = '_citad_btn';
  btn.innerHTML = '📥 Lưu lại tổ hợp này';
  btn.style.cssText = `
    position:fixed;bottom:70px;right:24px;
    background:linear-gradient(135deg,#92400e,#78350f);
    color:#fff;font-family:Arial,sans-serif;font-size:12px;font-weight:bold;
    padding:9px 14px;border-radius:8px;cursor:pointer;z-index:999998;
    box-shadow:0 4px 12px rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.2);
    user-select:none;opacity:0.85;
  `;
  btn.title = 'Nhấn để lưu thủ công nếu tự động không lưu';
  btn.onmouseover = () => { btn.style.opacity='1'; };
  btn.onmouseout  = () => { btn.style.opacity='0.85'; };
  btn.onclick = async () => {
    if (!hasResults()) { showToast('Chưa có kết quả, hãy Truy vấn trước', '#f59e0b'); return; }
    lastSavedKey = ''; // reset để cho phép lưu lại
    await autoSaveIfNew();
  };
  document.body.appendChild(btn);
}

function removeManualBtn() {
  const el = document.getElementById('_citad_btn');
  if (el) el.remove();
}

// ── Observer ─────────────────────────────────────────────────────────
function observe() {
  // Kiểm tra ngay lần đầu
  if (hasResults()) {
    createManualBtn();
    autoSaveIfNew();
  }

  const observer = new MutationObserver(() => {
    if (hasResults()) {
      createManualBtn();
      autoSaveIfNew();
    } else {
      removeManualBtn();
      lastSavedKey = ''; // reset khi trang xóa kết quả (đang load mới)
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
}

observe();
