chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || typeof message !== "object") return;
  if (message.type === "memorybridge.pair") {
    if (typeof message.origin !== "string" || !message.origin) {
      sendResponse({ ok: false, error: "Missing origin" });
      return;
    }
    chrome.storage.local.set({ pairedOrigin: message.origin, pairedAt: Date.now() }, () => {
      sendResponse({ ok: true });
    });
    return true;
  }
  return undefined;
});
