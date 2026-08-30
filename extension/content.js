(function () {
  function isAppPage() {
    return /\/app\/(dashboard|records)\.html$/.test(location.pathname);
  }
  if (!isAppPage()) return;

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data || {};
    if (data.type === "memorybridge.pairRequest") {
      chrome.runtime.sendMessage({ type: "memorybridge.pair", origin: location.origin }, (response) => {
        window.postMessage({ type: "memorybridge.pairResult", ok: !!(response && response.ok) }, location.origin);
      });
    }
  });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "memorybridge.extensionRecord") return;
    window.postMessage({
      type: "memorybridge.extensionRecord",
      title: message.title,
      body: message.body,
    }, location.origin);
    sendResponse({ ok: true });
    return true;
  });
})();
