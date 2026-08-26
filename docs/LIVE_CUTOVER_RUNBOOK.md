# MemoryBridge Stripe Live Cutover Runbook

Status: **Pre-launch operational checklist**

Use this only after the full Stripe Test Mode staging gate passes with a real Checkout Session, a genuine signed webhook delivery, entitlement synchronization, payment-failure behavior, duplicate delivery, and cancellation downgrade.

## Before cutover

- [ ] Deployed commit CI is green.
- [ ] `docs/DEPLOYMENT_SMOKE_RUNBOOK.md` passes on staging.
- [ ] Stripe Test Mode Pro checkout passes.
- [ ] Stripe Test Mode Team checkout passes.
- [ ] Genuine signed staging webhook passes.
- [ ] `checkout.session.completed` alone does not grant entitlement.
- [ ] Subscription created/updated grants only trusted Pro/Team entitlement.
- [ ] `invoice.payment_failed` cannot create paid access.
- [ ] `customer.subscription.deleted` returns account to Free.
- [ ] Duplicate webhook delivery is idempotent.
- [ ] Invalid signature produces HTTP 400 and zero DB mutation.
- [ ] First Successful Memory works from a clean browser session.

## Create Live Stripe resources

Create separate Live Mode Stripe resources; never reuse Test IDs:

- Live Pro product/price -> `STRIPE_PRICE_PRO=price_...`
- Live Team product/price -> `STRIPE_PRICE_TEAM=price_...`
- Live restricted/secret API key -> `STRIPE_SECRET_KEY=sk_live_...`
- Live webhook destination -> `https://YOUR-PRODUCTION-API/v1/billing/webhook`
- Copy the signing secret for that exact Live endpoint -> `STRIPE_WEBHOOK_SECRET=whsec_...`

Subscribe the Live webhook destination to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

## Production environment switch

Set protected deployment configuration to:

```text
APP_ENV=production
BILLING_MODE=live
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_LIVE_PRO
STRIPE_PRICE_TEAM=price_LIVE_TEAM
BILLING_SUCCESS_URL=https://YOUR-PRODUCTION-API/app/dashboard.html?billing=success
BILLING_CANCEL_URL=https://YOUR-PRODUCTION-API/app/dashboard.html?billing=cancel
CORS_ALLOWED_ORIGINS=https://YOUR-PRODUCTION-API
```

Keep `DATABASE_URL` and `ENCRYPTION_KEY` in protected production secret storage. Never paste any secret into repository files, support tickets, screenshots, shell history intended for sharing, or evidence records.

Deploy and require startup validation to pass. Do not weaken `APP_ENV=production` checks to force startup.

## Immediate post-deploy verification

Run the normal deployment smoke **without** Stripe checkout opt-in first:

```bash
MEMORYBRIDGE_API_KEY='mbs_DISPOSABLE_PRODUCTION_KEY' \
python scripts/deployment_smoke.py https://YOUR-PRODUCTION-API
```

Do not set `SMOKE_STRIPE_CHECKOUT=1` in Live Mode. The smoke script is intentionally fail-closed for live billing checkout probes.

Verify `/v1/billing/status` reports `mode=live`, `checkout_configured=true`, and `webhook_configured=true` without exposing secrets.

## Controlled Live transaction

Use one controlled low-risk internal subscription only after all previous checks pass:

1. Start from Dashboard using a disposable controlled workspace.
2. Choose one paid plan.
3. Complete the real Stripe-hosted payment.
4. Return to `dashboard.html?billing=success`.
5. Require Dashboard to wait for `paid_entitlement_active=true`; redirect alone is not success.
6. Confirm Stripe Live webhook delivery succeeded.
7. Confirm account status contains the expected plan and active paid entitlement.
8. Record only non-secret evidence: commit, timestamp, plan, webhook event type/status, and entitlement result.
9. Cancel the controlled subscription and require `customer.subscription.deleted` to return the account to Free.

Only after this controlled lifecycle passes may external paid traffic be invited.

## Fast rollback

Rollback is **fail closed**. If billing behavior is uncertain, stop creating new paid sessions before investigating.

Preferred rollback order:

1. Disable/withdraw the public upgrade CTA or route paid traffic away from checkout.
2. Restore the previous known-good application commit if the regression is application-side.
3. If Stripe configuration is suspect, restore the last known-good protected environment values and redeploy.
4. Keep webhook verification enabled; never bypass signatures to recover service.
5. Do not manually set customer plans in the database as a substitute for webhook recovery.
6. Re-run readiness, account status, and deployment smoke after rollback.
7. Reconcile any affected Stripe subscriptions against `BillingEvent` and account state before reopening checkout.

If an already-paid customer is affected, preserve their Stripe subscription evidence and repair synchronization through trusted subscription state rather than inventing entitlement manually.

## Stop conditions

Keep paid acquisition closed if any of these occur:

- production startup validation fails;
- billing status is not `live` or configuration is incomplete;
- checkout uses a Test Mode key or price;
- webhook endpoint/signing secret mismatch;
- success redirect grants or visually claims paid access before webhook confirmation;
- invalid webhook can mutate database state;
- payment failure creates paid entitlement;
- cancellation does not downgrade correctly;
- monitoring/logging exposes credentials, Stripe signatures, checkout URLs/session IDs, or memory content;
- controlled Live transaction lifecycle is incomplete.
