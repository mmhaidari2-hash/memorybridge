from app.observability import safe_request_id


def test_safe_request_id_accepts_bounded_correlation_value():
    assert safe_request_id("req_123-abc.xyz") == "req_123-abc.xyz"


def test_safe_request_id_replaces_secret_shaped_or_unbounded_value():
    secret_like = "mbs_super_secret key with spaces"
    result = safe_request_id(secret_like)
    assert result != secret_like
    assert "mbs_" not in result

    very_long = "x" * 200
    result2 = safe_request_id(very_long)
    assert result2 != very_long


def test_safe_request_id_rejects_control_characters():
    supplied = "safe\nSTRIPE_SECRET_KEY=sk_live_leak"
    result = safe_request_id(supplied)
    assert "sk_live" not in result
    assert "\n" not in result
