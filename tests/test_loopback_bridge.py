import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.manual_records import BUNDLE_KIND
from scripts.loopback_bridge import (
    LoopbackBridgeError,
    RecordStore,
    assert_loopback_host,
    is_loopback_origin,
    main,
    parse_import_text,
    serve,
)


def test_loopback_host_and_origin_are_strict():
    assert assert_loopback_host("127.0.0.1") == "127.0.0.1"
    assert assert_loopback_host("localhost") == "localhost"
    with pytest.raises(LoopbackBridgeError, match="refuses"):
        assert_loopback_host("0.0.0.0")
    with pytest.raises(LoopbackBridgeError, match="refuses"):
        assert_loopback_host("192.168.1.10")
    assert is_loopback_origin("http://127.0.0.1:8000")
    assert is_loopback_origin("http://localhost:8011")
    assert is_loopback_origin("http://[::1]:8000")
    assert is_loopback_origin("https://127.0.0.1:8000")
    assert not is_loopback_origin("https://example.com")
    assert not is_loopback_origin("http://10.0.0.2:8765")


def test_cli_record_export_import_round_trip(tmp_path: Path):
    db = tmp_path / "drafts.sqlite"
    assert main(["--db", str(db), "record", "--title", "Note", "--body", "It's done"]) == 0
    json_path = tmp_path / "out.json"
    sql_path = tmp_path / "out.sql"
    assert main(["--db", str(db), "export", "--json", str(json_path)]) == 0
    assert main(["--db", str(db), "export", "--sql", str(sql_path)]) == 0
    bundle = json.loads(json_path.read_text(encoding="utf-8"))
    assert bundle["kind"] == BUNDLE_KIND
    assert bundle["records"][0]["body"] == "It's done"
    db2 = tmp_path / "copy.sqlite"
    assert main(["--db", str(db2), "import", str(sql_path)]) == 0
    copied = RecordStore(db2).list_records()
    assert copied[0]["title"] == "Note"
    assert copied[0]["source"] == "cli"
    assert main(["--db", str(db), "list"]) == 0
    assert main(["--db", str(db), "serve", "--host", "0.0.0.0"]) == 1


def test_cli_rejects_secrets(tmp_path: Path):
    db = tmp_path / "drafts.sqlite"
    assert main(["--db", str(db), "record", "--title", "Key", "--body", "mbs_should_not_be_stored"]) == 1
    with pytest.raises(Exception, match="credentials"):
        parse_import_text(
            '{"version":1,"kind":"memorybridge.manual_records","records":[{"title":"Secret","body":"sk_live_dummy","source":"cli"}]}'
        )


def test_serve_is_loopback_only_and_shares_store(tmp_path: Path):
    db = tmp_path / "drafts.sqlite"
    store = RecordStore(db)
    store.upsert({"title": "Bridge", "body": "From CLI", "source": "cli"})
    server = serve("127.0.0.1", 0, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        req = urllib.request.Request(
            f"http://{host}:{port}/health",
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
            assert health["ok"] is True
            assert health["count"] == 1
            assert response.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8000"
        forbidden = urllib.request.Request(
            f"http://{host}:{port}/records",
            headers={"Origin": "https://evil.example"},
        )
        with pytest.raises(urllib.error.HTTPError) as forbidden_exc:
            urllib.request.urlopen(forbidden, timeout=3)
        assert forbidden_exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as api_exc:
            urllib.request.urlopen(f"http://{host}:{port}/v1/account/status", timeout=3)
        assert api_exc.value.code == 404
        secret = urllib.request.Request(
            f"http://{host}:{port}/records",
            data=json.dumps({"title": "Key", "body": "mbs_should_not_be_stored"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as secret_exc:
            urllib.request.urlopen(secret, timeout=3)
        assert secret_exc.value.code == 400
        with urllib.request.urlopen(f"http://{host}:{port}/records", timeout=3) as response:
            bundle = json.loads(response.read().decode("utf-8"))
        assert bundle["records"][0]["title"] == "Bridge"
        payload = json.dumps({"title": "Pushed", "body": "From page", "source": "cli"}).encode()
        post = urllib.request.Request(
            f"http://{host}:{port}/records",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": "http://localhost:8000"},
            method="POST",
        )
        with urllib.request.urlopen(post, timeout=3) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result == {"ok": True, "imported": 1}
        assert any(item["title"] == "Pushed" for item in store.list_records())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
