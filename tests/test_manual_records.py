from app.manual_records import (
    ManualRecordError,
    export_bundle,
    export_json,
    export_sqlite_sql,
    import_bundle,
    import_sqlite_sql,
    normalize_record,
)
import pytest


def test_normalize_rejects_secrets():
    with pytest.raises(ManualRecordError, match="credentials"):
        normalize_record({"title": "Key", "body": "mbs_should_not_be_stored"})


def test_json_round_trip_preserves_manual_record():
    original = [{"title": "Call note", "body": "Follow up Tuesday", "source": "manual"}]
    exported = export_json(original)
    imported = import_bundle(exported)
    assert imported[0]["title"] == "Call note"
    assert imported[0]["body"] == "Follow up Tuesday"
    assert imported[0]["source"] == "manual"
    assert imported[0]["id"]


def test_sqlite_sql_round_trip_and_rejects_foreign_inserts():
    records = [{"id": "rec-1", "created_at": "2026-08-30T08:00:00+00:00", "title": "Note", "body": "It's done", "source": "extension"}]
    sql = export_sqlite_sql(records)
    assert "CREATE TABLE IF NOT EXISTS manual_records" in sql
    imported = import_sqlite_sql(sql)
    assert imported == export_bundle(records)["records"]
    with pytest.raises(ManualRecordError, match="manual_records"):
        import_sqlite_sql("INSERT INTO users (id) VALUES ('1');")


def test_import_bundle_rejects_unknown_kind_and_api_keys():
    with pytest.raises(ManualRecordError, match="kind"):
        import_bundle({"version": 1, "kind": "other", "records": []})
    with pytest.raises(ManualRecordError, match="credentials"):
        import_bundle(
            {
                "version": 1,
                "kind": "memorybridge.manual_records",
                "records": [{"title": "Secret", "body": "sk_live_dummy"}],
            }
        )
