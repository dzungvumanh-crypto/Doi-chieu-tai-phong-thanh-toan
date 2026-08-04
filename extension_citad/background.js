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
  if (!message) {
    sendResponse({ ok: false, error: 'unknown message type' });
    return;
  }
  // GET_VERSION: trang /doi_chieu_citad dùng để so sánh với bản mới nhất
  // backend đang phát hành, báo popup nếu Extension đang cài đã cũ — chỉ
  // đọc chrome.runtime.getManifest(), không cần permission gì thêm.
  if (message.type === 'GET_VERSION') {
    sendResponse({ ok: true, version: chrome.runtime.getManifest().version });
    return;
  }
  if (message.type !== 'SET_CONFIG') {
    sendResponse({ ok: false, error: 'unknown message type' });
    return;
  }
  if (!message.server || !message.token) {
    sendResponse({ ok: false, error: 'missing server/token' });
    return;
  }
  // externally_connectable đã giới hạn origin GỬI được message này (Chrome
  // tự chặn, không phải code ở đây) — nhưng KHÔNG kiểm tra giá trị BÊN
  // TRONG message, nên nếu chính origin đó bị XSS (hoặc cổng dev bị app
  // khác chiếm), 1 trang độc hại vẫn có thể gửi `server` trỏ sang máy chủ
  // khác, khiến buffer/token thật bị POST nhầm sang đó ở lần lưu kế tiếp.
  // Chặn bớt rủi ro này bằng cách bắt buộc `server` là URL http/https hợp
  // lệ (không chấp nhận `javascript:`, `data:`, chuỗi rác...).
  let parsed;
  try {
    parsed = new URL(message.server);
  } catch (e) {
    sendResponse({ ok: false, error: 'invalid server URL' });
    return;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    sendResponse({ ok: false, error: 'server URL must be http(s)' });
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
    // Không có timeout thì backend "treo" (nhận TCP nhưng không phản hồi)
    // sẽ làm fetch() không bao giờ resolve/reject — content script đã set
    // khoá dedup TRƯỚC khi gọi sang đây nên cơ chế tự lưu cho tổ hợp đó bị
    // treo vĩnh viễn, không toast lỗi, không lên lịch retry. AbortController
    // đảm bảo luôn có phản hồi (ok:false) trong tối đa 20s để content script
    // biết mà lên lịch thử lại qua _makeRetryScheduler.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const r = await fetch(message.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Extension-Token': message.token },
        body: JSON.stringify(message.body),
        signal: controller.signal,
      });
      sendResponse({ ok: r.ok, status: r.status });
    } catch (e) {
      // Mất mạng / server không phản hồi / bị abort do timeout / CORS vẫn
      // còn chặn vì thiếu host_permissions — status=null để content script
      // biết đây không phải lỗi HTTP cụ thể (không phải 403).
      sendResponse({ ok: false, status: null, error: String(e) });
    } finally {
      clearTimeout(timer);
    }
  })();
  return true; // giữ kênh sendResponse mở cho fetch() bất đồng bộ
});
