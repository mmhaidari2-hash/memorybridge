# MemoryBridge Deployment Smoke Runbook

Use this immediately after every staging or production deployment and before sending a customer to the onboarding flow.

## 1. Runtime startup gate

Production must start with:

```text
APP_ENV=production
BILLING_MODE=test   # staging / Stripe sandbox
# or
BILLING_MODE=live   # production only after sandbox passes
```

If production configuration validation fails, fix the environment. Do not bypass it.

## 2. Apply migrations

Before application traffic:

```bash
alembic upgrade head
```

Do not point the new application version at an older schema and wait for webhooks to expose the problem.

## 3. Public API smoke

Run from a machine outside the deployment network:

```bash
python scripts/deployment_smoke.py https://YOUR-API.example
```

Expected:

```text
health      PASS
readiness   PASS
root        PASS
account     skipped unless a workspace key is supplied
```

Then verify the customer control plane with a disposable DB-backed workspace key:

```bash
MEMORYBRIDGE_API_KEY='mbs_...' \
python scripts/deployment_smoke.py https://YOUR-API.example
```

Never paste the key into a URL or commit it to a shell script.

## 4. Browser-origin check

From the deployed web origin, open onboarding in a clean/private browser session and verify:

- `/v1/account/status` succeeds with a valid workspace key;
- no browser CORS error appears;
- an invalid key fails without leaking credential material;
- the API key is not present in the URL/history;
- reloading the same tab/session can continue through `sessionStorage`;
- closing the browser session removes the convenience copy of the key.

`CORS_ALLOWED_ORIGINS` must contain the exact deployed HTTPS web origin. Wildcard CORS is intentionally unsupported.

## 5. First Successful Memory

Using a disposable external-style test workspace:

1. verify the workspace in onboarding;
2. click **Run first successful memory**;
3. require the round-trip success state;
4. verify usage increased in the dashboard/account status;
5. confirm no plaintext memory, user token, session token, or workspace API key appears in application logs.

A page-load success is not activation. The store/recall round trip must pass.

## 6. Dashboard smoke

Verify:

- plan and subscription state load from the API;
- usage and remaining quota render correctly;
- API-key list loads;
- a new API key can be created and its secret is shown once;
- the new key authenticates;
- revoking the new key causes it to stop authenticating;
- a Free account exposes upgrade controls;
- a paid account does not expose a duplicate self-serve checkout path when `can_upgrade=false`.

## 7. Billing smoke — staging only until sandbox passes

With `BILLING_MODE=test` and Stripe Test Mode configuration:

- Pro checkout returns a Stripe-hosted URL;
- Team checkout returns a Stripe-hosted URL;
- client cannot choose an arbitrary Price ID;
- browser redirect does not change entitlement;
- signed subscription webhook changes entitlement;
- account status reflects the webhook result.

Then complete `docs/STRIPE_SANDBOX_RUNBOOK.md` in full.

## 8. Release evidence

Record for each deployment:

```text
commit SHA:
deployment environment:
API origin:
web origin:
migration result:
smoke script result:
first-memory result:
dashboard result:
billing mode:
Stripe sandbox gate status:
operator/date:
```

Do not store API keys, Stripe secrets, webhook secrets, user/session tokens, or memory content in the evidence record.

## Stop conditions

Do not invite external customers if any of these fail:

- `/ready` is not 200/ready;
- browser CORS blocks onboarding;
- First Successful Memory fails;
- API-key revoke does not take effect;
- account status and quota disagree with backend state;
- checkout is available but webhook entitlement is not trustworthy;
- production is not HTTPS;
- CI for the deployed commit is not green.
