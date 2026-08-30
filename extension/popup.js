const $ = (id) => document.getElementById(id);

chrome.storage.local.get(["pairedOrigin"], (stored) => {
  $("origin").textContent = stored.pairedOrigin ? `Paired with ${stored.pairedOrigin}` : "Not paired. Open Dashboard and click Link extension.";
});

$("save").addEventListener("click", async () => {
  const title = $("title").value.trim();
  const body = $("body").value.trim();
  $("status").textContent = "";
  if (!title || !body) {
    $("status").textContent = "Title and note are required.";
    return;
  }
  const lowered = `${title} ${body}`.toLowerCase();
  if (["mbs_", "sk_live_", "sk_test_", "whsec_"].some((marker) => lowered.includes(marker))) {
    $("status").textContent = "Do not store credentials in a local draft.";
    return;
  }
  const tabs = await chrome.tabs.query({ url: ["http://127.0.0.1/*", "http://localhost/*"] });
  const appTab = tabs.find((tab) => tab.url && /\/app\/(records|dashboard)\.html/.test(tab.url));
  if (!appTab) {
    $("status").textContent = "Open /app/records.html or dashboard.html first.";
    return;
  }
  chrome.tabs.sendMessage(appTab.id, { type: "memorybridge.extensionRecord", title, body }, () => {
    $("status").textContent = chrome.runtime.lastError ? "Reload the app tab after installing the extension." : "Draft sent to the open app tab.";
  });
});
