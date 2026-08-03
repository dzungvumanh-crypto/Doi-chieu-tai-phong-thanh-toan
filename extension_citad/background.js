/* ── Service worker — nhận cấu hình TỰ ĐỘNG từ trang /doi_chieu_citad ──
 *
 * Chỉ nhận message từ đúng các origin khai trong manifest.json
 * ("externally_connectable") — trang web KHÁC không gửi được, kể cả biết
 * đúng EXTENSION_ID (Chrome tự chặn theo whitelist origin, không phải do
 * code này tự kiểm tra).
 *
 * KHÔNG thay thế trang Tuỳ chọn (options.html) — vẫn giữ nguyên làm
 * phương án dự phòng khi: dùng trình duyệt không hỗ trợ externally_connectable
 * giống Chrome, hoặc trang web đổi domain chưa kịp cập nhật whitelist bên
 * dưới (khi đó phải build lại + phát lại bản .zip mới, xem README.md).
 */
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'SET_CONFIG') {
    sendResponse({ ok: false, error: 'unknown message type' });
    return;
  }
  if (!message.server || !message.token) {
    sendResponse({ ok: false, error: 'missing server/token' });
    return;
  }
  chrome.storage.local.set(
    { server: message.server, extensionToken: message.token },
    () => sendResponse({ ok: true })
  );
  return true; // giữ kênh sendResponse mở cho thao tác set() bất đồng bộ
});

/* ── Gửi buffer thay cho content script (né CORS) ──────────────────────
 *
 * content.js/content_paymenthub.js KHÔNG tự fetch() nữa. fetch() gọi từ
 * content script mang Origin của TRANG ĐANG MỞ (CITAD/PaymentHub), không
 * phải origin của extension — backend/main.py không (và không nên) liệt
 * 2 origin đó vào ALLOWED_ORIGINS (CORSMiddleware gắn cấp app, thêm vào
 * đó sẽ mở CORS cho TOÀN BỘ API mọi module, không riêng CITAD) nên trình
 * duyệt luôn chặn preflight — đã kiểm chứng thực tế.
 *
 * Service worker thì khác: request từ đây mang origin
 * chrome-extension://<id>, và với extension ĐÃ có host_permissions cho
 * đúng domain backend (xin qua options.js khi Lưu cấu hình) thì KHÔNG bị
 * CORS chặn — đây là cơ chế chuẩn của Chrome cho tình huống này, không
 * phải hack. content script chỉ gửi `chrome.runtime.sendMessage` sang
 * đây, việc fetch() thật xảy ra ở service worker.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'BUFFER_POST') return false; // không phải gửi cho mình

  (async () => {
    try {
      const r = await fetch(message.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Extension-Token': message.token },
        body: JSON.stringify(message.body),
      });
      sendResponse({ ok: r.ok, status: r.status });
    } catch (e) {
      // Mất mạng / server không phản hồi / CORS vẫn còn chặn vì thiếu
      // host_permissions — status=null để content script biết đây không
      // phải lỗi HTTP cụ thể (không phải 403).
      sendResponse({ ok: false, status: null, error: String(e) });
    }
  })();
  return true; // giữ kênh sendResponse mở cho fetch() bất đồng bộ
});
