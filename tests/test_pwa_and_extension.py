import json
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
EXT = ROOT / "extension"
client = TestClient(app)


def test_pwa_manifest_and_icons_are_served():
    manifest = client.get("/app/manifest.webmanifest")
    assert manifest.status_code == 200
    body = json.loads(manifest.text)
    assert body["start_url"] == "/app/landing.html"
    assert body["scope"] == "/app/"
    assert body["display"] == "standalone"
    assert "application/manifest+json" in manifest.headers["content-type"]
    assert client.get("/app/icons/icon-192.png").status_code == 200
    assert client.get("/app/icons/icon-512.png").status_code == 200


def test_service_worker_is_app_scoped_and_ignores_api():
    sw = client.get("/app/sw.js")
    assert sw.status_code == 200
    text = sw.text
    assert "memorybridge-app-v2" in text
    assert "OFFLINE_FALLBACK" in text
    assert "/app/landing.html" in text
    assert "isApiPath" in text
    assert 'pathname !== "/app/sw.js"' in text
    assert "pathname.startsWith(\"/v1/\")" in text or 'startsWith("/v1/")' in text
    assert "/v1/account" not in text
    assert "PRECACHE" in text
    assert "/app/records.html" in text


def test_install_ux_and_records_page_are_wired():
    landing = client.get("/app/landing.html").text
    dashboard = client.get("/app/dashboard.html").text
    records = client.get("/app/records.html").text
    assert 'rel="manifest"' in landing and 'id="pwaInstallBtn"' in landing
    assert "beforeinstallprompt" in (WEB / "pwa.js").read_text(encoding="utf-8")
    assert "Link extension" in dashboard
    assert 'href="records.html"' in dashboard
    assert "localStorage" not in dashboard
    assert "IndexedDB" in records
    assert "Export SQLite SQL" in records
    assert "Import JSON or SQL" in records
    assert 'id="loopbackPanel"' in records
    assert "Pull from CLI" in records
    assert "Push to CLI" in records
    assert "isLoopbackHost" in records


def test_app_shell_is_revalidatable_while_api_stays_unstoreable():
    landing = client.get("/app/landing.html")
    health = client.get("/health")
    account = client.get("/v1/account/status")
    assert landing.status_code == 200
    assert "must-revalidate" in landing.headers["cache-control"]
    assert "no-store" not in landing.headers["cache-control"]
    assert health.headers["cache-control"] == "no-store"
    assert account.headers["cache-control"] == "no-store"


def test_precache_shell_files_exist_and_are_served():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    start = sw.index("const PRECACHE = [")
    end = sw.index("];", start)
    paths = [line.strip().strip(",").strip('"') for line in sw[start:end].splitlines() if "/app/" in line]
    assert "/app/records.html" in paths
    assert "/app/local_store.js" in paths
    for path in paths:
        assert client.get(path).status_code == 200, path


def test_local_store_rejects_secrets_and_matches_python_kind():
    js = (WEB / "local_store.js").read_text(encoding="utf-8")
    assert "memorybridge.manual_records" in js
    assert "mbs_" in js and "sk_live_" in js and "whsec_" in js
    assert 'source !== "cli"' in js
    assert "CREATE TABLE IF NOT EXISTS manual_records" in js
    assert "indexedDB.open" in js


def test_extension_pairs_origin_only_and_stays_local():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert "https://*/*" not in json.dumps(manifest)
    background = (EXT / "background.js").read_text(encoding="utf-8")
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    content = (EXT / "content.js").read_text(encoding="utf-8")
    assert "memorybridge.pair" in background
    assert "pairedOrigin" in background
    assert "saveDraft" not in background
    assert "mbs_" not in background
    assert "Do not store credentials" in popup
    assert "memorybridge.extensionRecord" in content
    dashboard = (WEB / "dashboard.html").read_text(encoding="utf-8")
    pair_fn = dashboard.split("function linkExtension()", 1)[1].split("window.addEventListener", 1)[0]
    assert "postMessage({type:'memorybridge.pairRequest'},location.origin)" in pair_fn
    assert "state.key" not in pair_fn
    assert all("https://" not in item for item in manifest.get("host_permissions", []))
    assert "mbs_" not in background
    assert "mbs_" not in content
