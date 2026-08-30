/* PWA install UX. Never stores API keys or intercepts /v1 traffic. */
(function () {
  const installBtn = document.getElementById("pwaInstallBtn");
  const installHint = document.getElementById("pwaInstallHint");
  let deferred = null;

  function showHint(text) {
    if (!installHint) return;
    installHint.textContent = text;
    installHint.hidden = false;
  }

  if (installBtn) {
    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      deferred = event;
      installBtn.hidden = false;
      showHint("Install MemoryBridge as an app on this device.");
    });
    installBtn.addEventListener("click", async () => {
      if (!deferred) {
        showHint("On iOS Safari use Share → Add to Home Screen. On desktop Chrome use the install icon in the address bar.");
        return;
      }
      deferred.prompt();
      await deferred.userChoice;
      deferred = null;
      installBtn.hidden = true;
      showHint("Install accepted or dismissed. Paid entitlement still comes only from a verified Stripe webhook.");
    });
    if (!window.matchMedia("(display-mode: standalone)").matches) {
      installBtn.hidden = false;
    }
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).catch(() => {
      if (installHint) showHint("App shell available online. Service worker registration was skipped.");
    });
  }
})();
