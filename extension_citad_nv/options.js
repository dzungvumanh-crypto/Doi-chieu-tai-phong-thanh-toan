/* Trang cấu hình Extension — thay cho việc sửa tay content.js/content_paymenthub.js.
 * Lưu vào chrome.storage.local, content script đọc ra lúc khởi động (xem
 * loadConfig() trong content.js/content_paymenthub.js). */

const serverInput = document.getElementById('server');
const tokenInput = document.getElementById('token');
const saveBtn = document.getElementById('save');
const statusEl = document.getElementById('status');

function showStatus(msg, cls) {
  statusEl.textContent = msg;
  statusEl.className = cls;
}

async function load() {
  const cfg = await chrome.storage.local.get(['server', 'extensionToken']);
  if (cfg.server) serverInput.value = cfg.server;
  if (cfg.extensionToken) tokenInput.value = cfg.extensionToken;
}

async function save() {
  const server = serverInput.value.trim().replace(/\/+$/, '');
  const token = tokenInput.value.trim();

  if (!server || !/^https?:\/\/.+/.test(server)) {
    showStatus('SERVER phải bắt đầu bằng http:// hoặc https://', 'err');
    return;
  }
  if (!token) {
    showStatus('Chưa dán Mã kết nối', 'err');
    return;
  }

  // Xin quyền truy cập đúng domain SERVER (MV3 không cho khai host cố định
  // khi domain backend thật chưa biết trước — xin động lúc lưu, đúng domain
  // cần dùng, không xin quyền rộng hơn mức cần thiết).
  let origin;
  try {
    // Regex ở trên chỉ kiểm tra tiền tố http(s):// — chuỗi sau đó vẫn có
    // thể không phải URL hợp lệ (VD ký tự lạ), khiến new URL() throw. Nếu
    // không bọc try/catch, bấm "Lưu cấu hình" sẽ im lặng không phản hồi gì.
    origin = new URL(server).origin + '/*';
  } catch (e) {
    showStatus('SERVER không phải địa chỉ hợp lệ', 'err');
    return;
  }
  try {
    const granted = await chrome.permissions.request({ origins: [origin] });
    if (!granted) {
      showStatus('Bạn cần đồng ý cấp quyền truy cập địa chỉ này để Extension hoạt động', 'err');
      return;
    }
  } catch (e) {
    showStatus('Lỗi xin quyền: ' + e.message, 'err');
    return;
  }

  await chrome.storage.local.set({ server, extensionToken: token });

  if (!server.startsWith('https://')) {
    showStatus('✓ Đã lưu — CẢNH BÁO: SERVER không dùng HTTPS, mã kết nối truyền ở dạng đọc được trên mạng. Chỉ chấp nhận khi test trên localhost.', 'warn');
  } else {
    showStatus('✓ Đã lưu cấu hình', 'ok');
  }
}

saveBtn.addEventListener('click', save);
load();
