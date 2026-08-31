# MemoryBridge — First Revenue Gate

Status: **Pre-revenue release checklist**

Purpose: define the shortest evidence-based path from the current commercial foundation to the first legitimate paid customer. This is intentionally narrower than a general production-readiness checklist.

## Revenue definition

The first revenue milestone is reached only when all of the following are evidenced:

1. a real external customer/developer has a workspace;
2. they successfully complete at least one MemoryBridge memory round-trip;
3. they intentionally choose a paid plan;
4. Stripe processes a real Live Mode payment;
5. a verified Stripe webhook grants the corresponding paid entitlement;
6. `GET /v1/account/status` reports the paid entitlement as active;
7. no manual database edit is required to make the customer paid.

A checkout redirect, test transaction, manually changed plan, verbal commitment, or internal founder account does **not** count as first revenue.

## Current product path

```text
Operator bootstrap of first workspace API key
  -> Landing
  -> First-run onboarding (verifies an already-provisioned key)
  -> Workspace verification
  -> Real store + recall activation
  -> Customer dashboard
  -> Usage / API-key management
  -> Pro or Team checkout
  -> Stripe
  -> Verified subscription webhook
  -> Paid entitlement
```

Public self-service signup does not currently exist. Landing, Onboarding, and Dashboard already exist as `/app` pages.

## Gate A — repository and CI

- [x] Commercial landing exists.
- [x] First-run onboarding exists.
- [x] Activation performs a real store/recall round-trip.
- [x] Dashboard reads authoritative plan and usage state.
- [x] Dashboard exposes server-created Stripe checkout.
- [x] API-key create/list/revoke lifecycle exists.
- [x] Commercial web flow has regression coverage.
- [x] CI is green after commercial-flow regression coverage.
- [ ] Branch receives final pre-release review before production cutover.

## Gate B — deployed customer path

These checks require the deployed environment and cannot be truthfully closed from repository code alone.

- [ ] Landing is publicly reachable over HTTPS.
- [ ] Onboarding can reach the production API without browser/CORS failures.
- [ ] A newly provisioned workspace key verifies successfully.
- [ ] First Successful Memory completes from a clean browser session.
- [ ] Dashboard loads account status and API-key metadata.
- [ ] No secret/API key appears in browser URL, public logs, analytics payloads, or repository files.
- [ ] Mobile and desktop smoke tests pass on the deployed customer path.

## Gate C — Stripe Test Mode

Complete and evidence every item in `docs/STRIPE_SANDBOX_RUNBOOK.md`.

Minimum evidence before Live Mode:

- [ ] authenticated checkout creates a Stripe-hosted session;
- [ ] arbitrary client Price IDs cannot be supplied;
- [ ] genuine signed webhook grants paid entitlement;
- [ ] unsigned/invalid webhook is rejected;
- [ ] redirect alone cannot grant entitlement;
- [ ] duplicate webhook is idempotent;
- [ ] cancellation removes paid entitlement;
- [ ] quota follows entitlement changes;
- [ ] CI remains green.

## Gate D — Live Mode cutover

Only after Gate C passes:

- [ ] create separate Stripe Live products/prices for Pro and Team;
- [ ] configure Live secret key, trusted Price IDs, and Live webhook signing secret in protected deployment configuration;
- [ ] use production HTTPS success/cancel URLs;
- [ ] perform one controlled low-risk Live subscription transaction;
- [ ] verify the Live webhook, subscription IDs, plan, and account-status entitlement;
- [ ] cancel the controlled subscription and verify lifecycle behavior;
- [ ] confirm no Test Mode identifier is used in Live configuration.

## Gate E — first external paid customer

- [ ] invite a real external developer/customer rather than an internal test account;
- [ ] observe onboarding without manually editing their database state;
- [ ] confirm they reach First Successful Memory;
- [ ] customer intentionally selects Pro or Team;
- [ ] payment succeeds in Stripe Live Mode;
- [ ] verified webhook grants paid entitlement automatically;
- [ ] account status reports `paid_entitlement_active=true`;
- [ ] record the date, selected plan, activation-to-payment time, and any onboarding friction without storing customer secrets;

When every Gate E item passes, MemoryBridge has crossed the **first real revenue** milestone.

## Stop conditions

Do not accept public paid traffic if any of these are true:

- Stripe sandbox lifecycle is not fully evidenced;
- entitlement can be granted without a verified webhook;
- production secrets are present in source control;
- a clean external user cannot complete activation;
- checkout requires manual database edits;
- cancellation does not remove entitlement correctly;
- production API is not served over HTTPS.

## After first revenue

Do not immediately broaden the roadmap. First capture evidence from the initial customers:

- activation completion rate;
- time to First Successful Memory;
- checkout-start to paid conversion;
- repeated memory usage after activation;
- quota pressure;
- cancellation/refund reasons;
- support friction.

Use those observations to decide whether the next unit of work should improve acquisition, activation, retention, pricing, reliability, or expansion. Revenue is evidence; the first payment is the start of product validation, not the end of it.
