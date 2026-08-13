/* ── CITAD Extension – Tự động lưu khi có kết quả ──
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
    console.warn('[CITAD Extension] Chưa cấu hình — bấm icon Extension trên thanh công cụ → Tuỳ chọn.');
  } else if (!SERVER.startsWith('https://')) {
    console.warn('[CITAD Extension] SERVER không dùng HTTPS — mã kết nối và số liệu truyền ở dạng đọc được trên mạng nội bộ. Chỉ chấp nhận được khi test trên localhost.');
  }
}

// Trước đây chỉ đọc cấu hình 1 lần lúc trang CITAD tải xong (xem IIFE cuối
// file) — mở nhiều tab CITAD RỒI MỚI bấm "Tạo mã kết nối mới" ở /doi_chieu_citad
// (thứ tự rất hay gặp khi mở nhiều tab ẩn danh để đăng nhập nhiều cổng) thì
// các tab đã mở từ trước bị kẹt với SERVER/token rỗng hoặc đã bị thu hồi mãi
// mãi, phải tự tay reload từng tab mới nhận cấu hình mới. chrome.storage.local
// dùng chung cho mọi tab (spanning, không tách incognito — xem README) nên chỉ
// cần lắng nghe onChanged là mọi tab đang mở tự cập nhật ngay, không cần reload.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if ('server' in changes) SERVER = changes.server.newValue || '';
  if ('extensionToken' in changes) EXTENSION_TOKEN = changes.extensionToken.newValue || '';
});

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

// Parse số tiền có thể kèm phần thập phân (USD/EUR có xu/cent) — không thể
// chỉ replace(/[^\d]/g,'') như số món vì sẽ xoá luôn dấu thập phân, làm
// "1.234,56" thành 123456 (sai gấp 100 lần). Không biết trước CITAD dùng
// quy ước dấu nào (','/'.' làm thập phân) nên tự nhận diện: dấu phân cách
// XUẤT HIỆN CUỐI CÙNG trong chuỗi là thập phân CHỈ KHI theo sau đúng 1-2
// chữ số (đúng độ dài phần lẻ tiền tệ) — nhóm nghìn luôn đúng 3 chữ số nên
// không nhầm lẫn được với trường hợp này.
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
      const no = parseMoney(tds[1]?.innerText);
      const co = parseMoney(tds[2]?.innerText);
      res.soTien = no + co;
    }
  }
  return res;
}

function hasResults() {
  return document.querySelectorAll('tr.grid-footer').length > 0;
}

// ── Gửi lên server ───────────────────────────────────────────────────
// Trả về { ok, permanent } thay vì chỉ true/false — "permanent" đánh dấu
// lỗi KHÔNG phải sự cố tạm thời (chưa cấu hình, mã kết nối sai/bị thu hồi)
// để autoSaveIfNew() biết KHÔNG được tự thử lại (xem _makeRetryScheduler).
//
// KHÔNG tự fetch() ở đây — content script mang Origin của trang CITAD nên
// bị CORS chặn (đã kiểm chứng thực tế). Gửi message cho background.js
// (service worker, không bị CORS chặn kiểu này) thực hiện fetch() thật.
async function saveToServer(cfg, res) {
  if (!SERVER || !EXTENSION_TOKEN) {
    showToast('⚠️ Chưa cấu hình Extension — bấm icon Extension trên thanh công cụ → Tuỳ chọn', '#f59e0b', 6000);
    return { ok: false, permanent: true };
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
  const result = await new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        type: 'BUFFER_POST',
        url: `${SERVER}/api/doi-chieu-citad/citad-buffer`,
        token: EXTENSION_TOKEN,
        body: payload,
      },
      (response) => resolve(response || { ok: false, status: null })
    );
  });
  if (result.status === 403) {
    showToast('✗ Mã kết nối không hợp lệ hoặc đã bị thu hồi — tạo mã mới ở /doi_chieu_citad', '#ef4444', 8000);
    return { ok: false, permanent: true };
  }
  return { ok: result.ok, permanent: false };
}

// ── Lùi thời gian thử lại khi gửi thất bại ─────────────────────────────
// showToast() cũng là 1 thay đổi trên document.body — đúng thứ
// MutationObserver bên dưới đang theo dõi. Nếu đặt lại khoá chặn trùng
// NGAY sau khi hiện toast, observer bắt được thay đổi đó và gọi lại hàm
// gửi ngay lập tức — thành vòng lặp không có độ trễ, chỉ bị chặn bởi thời
// gian round-trip của request đang lỗi. Với lỗi permanent (mã kết nối sai/
// bị thu hồi) vòng lặp đó không bao giờ tự tắt, mỗi vòng vẫn tốn 1 dòng
// audit_logs. Chỉ lùi thời gian thử lại (tăng dần, tối đa 5 phút) cho lỗi
// CÓ THỂ tạm thời (mất mạng, server lỗi) — lỗi permanent thì KHÔNG tự thử
// lại, chỉ nút thủ công mới thử lại được.
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
let _saving = false; // đang có 1 lượt gửi dở chưa xong — chặn gửi trùng
const _saveRetry = _makeRetryScheduler(() => { lastSavedKey = ''; });

async function autoSaveIfNew() {
  if (!hasResults()) return;

  const cfg = readConfig();

  // Bỏ qua nếu thiếu thông tin
  if (!cfg.cong || !cfg.chieu || !cfg.loaiDV || cfg.loaiDV === 'all') return;

  const res = readResult();

  // Không lưu nếu kết quả toàn 0 (trang chưa load xong)
  if (res.soMon === 0 && res.soTien === 0) return;

  // Key gồm cả SỐ LIỆU, không chỉ tổ hợp cổng/loại tiền/chiều — để: (1) truy
  // vấn lại đúng tổ hợp cũ nhưng số liệu đã đổi (có giao dịch mới về trong
  // ngày) vẫn được lưu lại đúng số mới nhất; (2) bảng kết quả biến mất rồi
  // hiện lại với ĐÚNG số liệu cũ (trang CITAD nạp lại từng phần mỗi lần bấm
  // truy vấn) không bị coi là "mới" và gửi trùng lên server — mỗi request
  // trùng tốn thêm 1 lượt ghi last_used_at + 1 dòng audit_logs trên cùng 1
  // file SQLite dùng chung toàn app.
  const key = `${cfg.cong}_${cfg.loaiTien}_${cfg.chieu}_${cfg.loaiDV}_${res.soMon}_${res.soTien}`;
  if (key === lastSavedKey) return;
  // Nút thủ công reset lastSavedKey='' rồi gọi lại hàm này ngay lập tức để
  // "bấm tay = thử ngay" — nhưng nếu lượt gửi TRƯỚC (do MutationObserver
  // kích hoạt) còn đang chạy dở (await saveToServer chưa xong), bấm nút
  // nhiều lần liên tiếp sẽ tạo nhiều request POST song song cùng dữ liệu
  // trước khi request đầu kịp hoàn tất → nhân đôi dòng buffer/audit_logs.
  // Chặn bằng cờ _saving thay vì chỉ dựa vào khoá dedup (khoá đã bị nút
  // thủ công chủ động xoá nên không còn tác dụng chặn trong tình huống này).
  if (_saving) return;
  lastSavedKey = key;
  _saving = true;

  try {
    const { ok, permanent } = await saveToServer(cfg, res);

    const loaiLabel = cfg.loaiDV === 'ih' ? 'IH' : 'IL';
    const chieuLabel = cfg.chieu === 'di' ? 'Đi' : 'Đến';

    if (ok) {
      showToast(
        `✓ Tự lưu: Cổng ${cfg.cong} – ${cfg.loaiTien} – ${loaiLabel} ${chieuLabel}<br>` +
        `<small style="color:#94a3b8">${res.soMon.toLocaleString('vi-VN')} món | ${res.soTien.toLocaleString('vi-VN')}</small>`,
        '#10b981', 4000
      );
      _saveRetry.resetBackoff();
    } else {
      // permanent (chưa cấu hình / mã kết nối sai-bị thu hồi): saveToServer()
      // đã tự hiện đúng toast lý do rồi (dòng '⚠️ Chưa cấu hình Extension...'
      // hoặc lỗi 403) — KHÔNG đè thêm toast chung ở đây, nếu không
      // showToast() (xoá toast cũ theo id cố định trước khi vẽ toast mới) sẽ
      // luôn làm mất thông báo đúng, thay vào đó hiện "Không kết nối server
      // ()" vô nghĩa (SERVER rỗng chính là lý do gây permanent). Chỉ hiện
      // toast chung này khi lỗi THẬT là tạm thời (mạng, server lỗi).
      if (!permanent) {
        showToast(`✗ Không kết nối server (${SERVER})`, '#ef4444', 4000);
        _saveRetry.scheduleRetry();
      }
    }
  } finally {
    _saving = false;
  }
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
    _saveRetry.resetBackoff(); // bấm tay = thử ngay, không chờ backoff còn lại
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
      // KHÔNG reset lastSavedKey ở đây nữa — key giờ đã gồm cả số liệu (xem
      // autoSaveIfNew), nên bảng biến mất rồi hiện lại với số liệu CŨ vẫn tự
      // bị chặn gửi trùng; số liệu MỚI (khác) vẫn tính ra key khác, tự gửi
      // bình thường, không cần reset.
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });
}

(async () => {
  await loadConfig();
  observe();
})();
