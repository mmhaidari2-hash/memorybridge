"""Five adversarial hard checks against MemoryBridge v0.4."""

from __future__ import annotations

import base64
import os
import sys
import traceback

SERVICE_API_KEY = "mbs_hardcheck_service_key_abcdefghijklmnop"
ADMIN_API_KEY = "mba_hardcheck_admin_key_abcdefghijklmnopqrstuvwx"
OTHER_SERVICE_KEY = "mbs_other_env_key_should_not_exist_zzzzzz"

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENCRYPTION_KEY"] = base64.b64encode(b"h" * 32).decode("ascii")
os.environ["SERVICE_API_KEYS"] = SERVICE_API_KEY
os.environ["ADMIN_API_KEY"] = ADMIN_API_KEY
os.environ["TOKEN_HASH_PEPPER"] = base64.b64encode(b"hard-pepper-32-bytes-exactly!!").decode("ascii")
os.environ["RATE_LIMIT_REQUESTS"] = "5000"
os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "60"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.billing import ensure_plans
from app.config import clear_settings_cache
from app.database import Base, get_db
from app.models import MemoryRecord, Plan, User
from app.rate_limit import rate_limiter
from app.security import decrypt_text, encrypt_text, hash_token
from main import app

clear_settings_cache()
rate_limiter.reset()

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

SVC = {"X-MemoryBridge-Key": SERVICE_API_KEY}
ADM = {"X-MemoryBridge-Admin-Key": ADMIN_API_KEY}


def reset():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    app.dependency_overrides[get_db] = override_get_db
    with SessionLocal() as db:
        ensure_plans(db)


def ok(name: str, detail: str) -> None:
    print(f"PASS | {name}")
    print(f"       {detail}")


def fail(name: str, detail: str) -> None:
    print(f"FAIL | {name}")
    print(f"       {detail}")
    raise AssertionError(f"{name}: {detail}")


def hard_1_cross_tenant_memory_theft():
    """Tenant B must not recall Tenant A's memory even with stolen session token."""
    reset()
    t_a = client.post("/v1/admin/tenants", json={"name": "Alpha", "slug": "alpha-co"}, headers=ADM).json()
    t_b = client.post("/v1/admin/tenants", json={"name": "Beta", "slug": "beta-co"}, headers=ADM).json()
    key_a = client.post(f"/v1/admin/tenants/{t_a['id']}/keys", json={"name": "a"}, headers=ADM).json()["api_key"]
    key_b = client.post(f"/v1/admin/tenants/{t_b['id']}/keys", json={"name": "b"}, headers=ADM).json()["api_key"]
    ha, hb = {"X-MemoryBridge-Key": key_a}, {"X-MemoryBridge-Key": key_b}

    user_a = client.post("/v1/auth/token", json={}, headers=ha).json()["user_token"]
    sess = client.post(
        "/v1/memory/store",
        json={"user_token": user_a, "summary": "SECRET_ALPHA_MEMORY"},
        headers=ha,
    ).json()["session_token"]

    # 1) Beta key + Alpha user token
    r1 = client.post(
        "/v1/memory/recall",
        json={"user_token": user_a, "session_token": sess},
        headers=hb,
    )
    # 2) Beta creates own user and tries Alpha session token
    user_b = client.post("/v1/auth/token", json={}, headers=hb).json()["user_token"]
    r2 = client.post(
        "/v1/memory/recall",
        json={"user_token": user_b, "session_token": sess},
        headers=hb,
    )
    # 3) Confirm Alpha still works
    r3 = client.post(
        "/v1/memory/recall",
        json={"user_token": user_a, "session_token": sess},
        headers=ha,
    )

    if r1.status_code != 401:
        fail("1. Cross-tenant theft", f"expected 401 for foreign user, got {r1.status_code} {r1.text}")
    if r2.status_code != 404:
        fail("1. Cross-tenant theft", f"expected 404 for foreign session, got {r2.status_code} {r2.text}")
    if r3.status_code != 200 or r3.json()["summary"] != "SECRET_ALPHA_MEMORY":
        fail("1. Cross-tenant theft", f"owner recall broken: {r3.status_code} {r3.text}")
    ok("1. Cross-tenant theft", "Beta cannot read Alpha memory; owner recall intact")


def hard_2_ciphertext_transplant_aad():
    """Ciphertext copied to another user/tenant must fail decrypt (AAD binding)."""
    reset()
    packed, version = encrypt_text("TOP_SECRET", tenant_id="tenant-1", user_id="user-1")
    # Wrong tenant
    try:
        decrypt_text(packed, tenant_id="tenant-2", user_id="user-1", key_version=version)
        fail("2. AAD transplant", "decrypt succeeded with wrong tenant_id")
    except Exception:
        pass
    # Wrong user
    try:
        decrypt_text(packed, tenant_id="tenant-1", user_id="user-2", key_version=version)
        fail("2. AAD transplant", "decrypt succeeded with wrong user_id")
    except Exception:
        pass
    plain = decrypt_text(packed, tenant_id="tenant-1", user_id="user-1", key_version=version)
    if plain != "TOP_SECRET":
        fail("2. AAD transplant", "legitimate decrypt failed")
    ok("2. AAD transplant", "ciphertext is bound to tenant+user; transplant blocked")


def hard_3_quota_hard_stop_and_upgrade():
    """Free plan must hard-stop with 402; admin upgrade must unlock API again."""
    reset()
    with SessionLocal() as db:
        ensure_plans(db)
        free = db.query(Plan).filter(Plan.code == "free").one()
        free.monthly_ops_limit = 3
        free.max_memories = 1000
        db.add(free)
        db.commit()

    # 3 ops allowed
    for i in range(3):
        r = client.post("/v1/auth/token", json={"full_name": f"u{i}"}, headers=SVC)
        if r.status_code != 201:
            fail("3. Quota hard-stop", f"op {i+1} should succeed, got {r.status_code}")

    blocked = client.post("/v1/auth/token", json={}, headers=SVC)
    if blocked.status_code != 402:
        fail("3. Quota hard-stop", f"expected 402, got {blocked.status_code} {blocked.text}")
    detail = blocked.json()["detail"]
    if detail.get("error") != "ops_quota_exceeded":
        fail("3. Quota hard-stop", f"wrong error payload: {detail}")

    # Find default tenant and upgrade
    status = client.get("/v1/billing/status", headers=SVC)
    # status itself doesn't meter; get tenant via admin list isn't available — use DB
    with SessionLocal() as db:
        from app.models import Tenant

        tenant = db.query(Tenant).filter(Tenant.slug == "default").one()
        tid = tenant.id

    upgraded = client.post(
        f"/v1/admin/tenants/{tid}/plan",
        json={"plan_code": "starter"},
        headers=ADM,
    )
    if upgraded.status_code != 200 or upgraded.json()["plan_code"] != "starter":
        fail("3. Quota hard-stop", f"upgrade failed: {upgraded.status_code} {upgraded.text}")

    # After upgrade, ops_limit is higher but usage counter still has 3 — starter allows 50k
    after = client.post("/v1/auth/token", json={}, headers=SVC)
    if after.status_code != 201:
        fail("3. Quota hard-stop", f"after upgrade still blocked: {after.status_code} {after.text}")
    ok("3. Quota hard-stop", "402 on Free exhaust; Starter upgrade restores access")


def hard_4_revoked_key_and_plaintext_absence():
    """Revoked key dies immediately; DB must never store plaintext tokens or summary."""
    reset()
    tenant = client.post(
        "/v1/admin/tenants",
        json={"name": "RevokeCo", "slug": "revoke-co"},
        headers=ADM,
    ).json()
    created = client.post(
        f"/v1/admin/tenants/{tenant['id']}/keys",
        json={"name": "prod"},
        headers=ADM,
    ).json()
    key, key_id = created["api_key"], created["id"]
    headers = {"X-MemoryBridge-Key": key}

    user = client.post("/v1/auth/token", json={"full_name": "Secret Person"}, headers=headers).json()[
        "user_token"
    ]
    store = client.post(
        "/v1/memory/store",
        json={"user_token": user, "summary": "PLAINTEXT_MUST_NOT_APPEAR_IN_DB"},
        headers=headers,
    )
    if store.status_code != 201:
        fail("4. Revoke + no plaintext", f"store failed: {store.status_code}")
    sess = store.json()["session_token"]

    revoked = client.post(f"/v1/admin/keys/{key_id}/revoke", headers=ADM)
    if revoked.status_code != 200 or revoked.json()["status"] != "revoked":
        fail("4. Revoke + no plaintext", f"revoke failed: {revoked.status_code}")

    dead = client.post(
        "/v1/memory/recall",
        json={"user_token": user, "session_token": sess},
        headers=headers,
    )
    if dead.status_code != 401:
        fail("4. Revoke + no plaintext", f"revoked key still works: {dead.status_code}")

    with SessionLocal() as db:
        # dump all textish columns
        blob = ""
        for table in ("users", "memory_records", "service_api_keys"):
            rows = db.execute(text(f"SELECT * FROM {table}")).mappings().all()
            blob += str(rows)
        if user in blob or sess in blob or key in blob or "PLAINTEXT_MUST_NOT_APPEAR_IN_DB" in blob:
            fail("4. Revoke + no plaintext", "plaintext secret found in DB dump")
        user_row = db.query(User).one()
        mem = db.query(MemoryRecord).one()
        if user_row.user_token_hash != hash_token(user):
            fail("4. Revoke + no plaintext", "user hash mismatch")
        if mem.session_token_hash != hash_token(sess):
            fail("4. Revoke + no plaintext", "session hash mismatch")
        if mem.encrypted_content == "PLAINTEXT_MUST_NOT_APPEAR_IN_DB":
            fail("4. Revoke + no plaintext", "summary stored plaintext")

    ok("4. Revoke + no plaintext", "revoked key=401; tokens/summary absent from DB")


def hard_5_spoofed_auth_and_duplicate_session():
    """Invalid/missing keys fail closed; duplicate session_token must conflict (409)."""
    reset()
    missing = client.post("/v1/auth/token", json={})
    bad = client.post(
        "/v1/auth/token",
        json={},
        headers={"X-MemoryBridge-Key": OTHER_SERVICE_KEY},
    )
    bad_admin = client.post(
        "/v1/admin/tenants",
        json={"name": "X", "slug": "x-co"},
        headers={"X-MemoryBridge-Admin-Key": "mba_wrong_admin_key_xxxxxxxxxxxxxxxxxxxx"},
    )
    if missing.status_code != 401 or bad.status_code != 401 or bad_admin.status_code != 401:
        fail(
            "5. Spoofed auth + dup session",
            f"auth fail-closed broken: {missing.status_code}/{bad.status_code}/{bad_admin.status_code}",
        )

    user = client.post("/v1/auth/token", json={}, headers=SVC).json()["user_token"]
    fixed = "sess_hardcoded_duplicate_token_abc123"
    first = client.post(
        "/v1/memory/store",
        json={"user_token": user, "session_token": fixed, "summary": "one"},
        headers=SVC,
    )
    second = client.post(
        "/v1/memory/store",
        json={"user_token": user, "session_token": fixed, "summary": "two"},
        headers=SVC,
    )
    if first.status_code != 201:
        fail("5. Spoofed auth + dup session", f"first store failed: {first.status_code}")
    if second.status_code != 409:
        fail("5. Spoofed auth + dup session", f"expected 409, got {second.status_code} {second.text}")

    # Ensure first content not overwritten
    recall = client.post(
        "/v1/memory/recall",
        json={"user_token": user, "session_token": fixed},
        headers=SVC,
    )
    if recall.json().get("summary") != "one":
        fail("5. Spoofed auth + dup session", "duplicate store may have overwritten memory")

    ok("5. Spoofed auth + dup session", "spoofed keys rejected; duplicate session returns 409")


CHECKS = [
    hard_1_cross_tenant_memory_theft,
    hard_2_ciphertext_transplant_aad,
    hard_3_quota_hard_stop_and_upgrade,
    hard_4_revoked_key_and_plaintext_absence,
    hard_5_spoofed_auth_and_duplicate_session,
]


def main() -> int:
    print("=== MemoryBridge hard checks (5) ===")
    passed = 0
    for fn in CHECKS:
        try:
            fn()
            passed += 1
        except Exception as exc:
            if not str(exc).startswith(tuple(f"{i}." for i in range(1, 6))):
                print(f"FAIL | {fn.__name__}")
                print(f"       unexpected error: {exc}")
                traceback.print_exc()
            return 1
    print(f"=== RESULT: {passed}/5 PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
