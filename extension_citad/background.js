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
