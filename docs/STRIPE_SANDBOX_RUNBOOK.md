# Stripe Sandbox Runbook

This runbook is the release gate for MemoryBridge subscription billing in Stripe Test Mode.

## Safety rules

- Use Stripe **Test Mode** only until every gate below passes.
- Never commit Stripe secret keys or webhook signing secrets.
- A browser redirect to the success URL is not proof of payment and must never grant a paid plan.
- Only a verified Stripe webhook may change subscription entitlement.
- Run database migrations before sending billing webhooks.

## 1. Create Stripe test products and recurring prices

Create two recurring subscription prices in Stripe Test Mode:

- MemoryBridge Pro
- MemoryBridge Team

Record their `price_...` IDs. Do not accept a Price ID from an API caller; MemoryBridge maps trusted server-side environment variables to plans.

## 2. Configure deployment secrets

Set these protected environment variables on the deployed API:

```text
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_TEAM=price_...
BILLING_SUCCESS_URL=https://YOUR-STAGING-HOST/app/dashboard.html?billing=success
BILLING_CANCEL_URL=https://YOUR-STAGING-HOST/app/dashboard.html?billing=cancel
```

Do not set `STRIPE_WEBHOOK_SECRET` until the webhook endpoint is created in step 4.

## 3. Apply migrations and verify readiness

Run:

```bash
alembic upgrade head
```

Then verify:

```text
GET /health -> 200 {"status":"ok"}
GET /ready  -> 200 {"status":"ready"}
```

The billing migration must exist before webhook traffic begins.

## 4. Create Stripe webhook endpoint

In Stripe Test Mode create a webhook destination pointing to:

```text
https://YOUR-STAGING-HOST/v1/billing/webhook
```

Subscribe to the subscription lifecycle events handled by MemoryBridge, including:

```text
checkout.session.completed
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
```

Copy the endpoint signing secret (`whsec_...`) into the deployment as:

```text
STRIPE_WEBHOOK_SECRET=whsec_...
```

Restart/redeploy the service if the platform requires it for environment changes.

## 5. Baseline the tenant

Before checkout, confirm the test tenant is on the free plan and has no active paid entitlement. Keep its tenant/workspace IDs available for database verification.

Expected state:

```text
plan=free
subscription_status is empty/inactive
```

## 6. Create checkout from MemoryBridge

Using a DB-backed workspace API key, call:

```text
POST /v1/billing/checkout
X-MemoryBridge-Key: <workspace-key>
Content-Type: application/json

{"plan":"pro"}
```

Expected result:

- HTTP 200
- a Stripe Checkout `session_id`
- a Stripe-hosted `checkout_url`

The API caller must not be able to supply an arbitrary Stripe Price ID.

## 7. Complete a Stripe test subscription

Open the returned Checkout URL and complete payment using Stripe's documented Test Mode payment method/card data.

Passing the browser success redirect is **not** the entitlement gate. Wait for Stripe webhook delivery.

## 8. Verify free -> pro

After verified subscription webhook delivery, confirm:

```text
plan=pro
subscription_status=active (or trialing when intentionally configured)
stripe_customer_id is populated
stripe_subscription_id is populated
```

Also verify the paid quota is effective by exercising usage above the Free limit in a controlled test.

## 9. Verify webhook security and idempotency

From Stripe's webhook tooling/dashboard:

1. Redeliver the same event. The event must not create a second entitlement transition or duplicate billing-event record.
2. A request without a valid Stripe signature must be rejected.
3. A checkout success redirect without a valid subscription webhook must not change `plan`.
4. Unknown/untrusted plan metadata must not grant a paid entitlement.

## 10. Verify cancellation: pro -> free

Cancel the test subscription in Stripe Test Mode and deliver the resulting subscription lifecycle webhook.

Expected final state after the cancellation becomes effective according to the event received:

```text
plan=free
subscription_status reflects the non-active/cancelled state
```

Verify Free quota enforcement applies again.

## 11. Release gate

Sandbox billing passes only when all of these are true:

- [ ] Checkout session is created by the authenticated MemoryBridge endpoint.
- [ ] Trusted server-side Price ID is used.
- [ ] Stripe webhook signature verification succeeds for genuine events.
- [ ] Invalid/unsigned webhook is rejected.
- [ ] Checkout redirect alone cannot grant Pro.
- [ ] Active/trialing subscription changes Free -> Pro/Team correctly.
- [ ] Duplicate webhook is idempotent.
- [ ] Cancellation/non-active subscription removes paid entitlement.
- [ ] Quota changes follow the resulting plan.
- [ ] No Stripe secret or full API key appears in logs or repository history.
- [ ] CI remains green.

Do not switch to Stripe Live Mode until every checkbox is evidenced in the deployed sandbox environment.

## Production cutover (after sandbox passes)

Production is a separate gate. Create Live Mode products/prices and a Live webhook endpoint, use only `sk_live_...`/Live `price_...`/Live `whsec_...` values in protected deployment secrets, run a low-risk real transaction, verify webhook-driven entitlement, then verify cancellation/refund operational procedures. Never reuse Test Mode identifiers in Live Mode.
