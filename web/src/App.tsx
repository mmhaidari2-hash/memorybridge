import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { apiUrl } from "./api";

type PlanId = "free" | "starter" | "growth";

type Plan = {
  id: PlanId;
  name: string;
  price: string;
  features: string[];
  cta: string;
};

type SignupResult = {
  tenant_id: string;
  slug: string;
  plan_code: string;
  api_key: string;
  checkout_url?: string | null;
  message: string;
};

const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    features: ["1,000 ops / month", "100 encrypted memories", "Single tenant"],
    cta: "Start free",
  },
  {
    id: "starter",
    name: "Starter",
    price: "$49",
    features: ["50,000 ops / month", "10,000 memories", "Revocable API keys"],
    cta: "Choose Starter",
  },
  {
    id: "growth",
    name: "Growth",
    price: "$199",
    features: ["500,000 ops / month", "100,000 memories", "Priority tenant isolation"],
    cta: "Choose Growth",
  },
];

function HeroVisual() {
  return (
    <div className="hero-visual" aria-hidden="true">
      <svg className="stream" viewBox="0 0 1200 420" preserveAspectRatio="none">
        <path className="s1" d="M-40 260 C 160 80, 320 380, 520 210 S 860 40, 1240 250" />
        <path className="s2" d="M-40 300 C 180 140, 360 360, 560 250 S 900 120, 1240 290" />
        <path className="s3" d="M-40 210 C 200 60, 380 300, 600 170 S 940 80, 1240 200" />
      </svg>
    </div>
  );
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

export default function App() {
  const path = typeof window !== "undefined" ? window.location.pathname : "/";
  if (path === "/billing/success") {
    return <BillingResult kind="success" />;
  }
  if (path === "/billing/cancel") {
    return <BillingResult kind="cancel" />;
  }
  return <Landing />;
}

function BillingResult({ kind }: { kind: "success" | "cancel" }) {
  const ok = kind === "success";
  return (
    <div className="site">
      <main className="section">
        <div className="wrap" style={{ maxWidth: 640 }}>
          <p className="section-label">{ok ? "Payment" : "Checkout"}</p>
          <h2>{ok ? "Payment received." : "Checkout canceled."}</h2>
          <p className="section-lead">
            {ok
              ? "Stripe confirmed the subscription. Your tenant plan upgrades automatically via webhook. Keep your API key safe."
              : "No charge was made. You can return to pricing and try again anytime."}
          </p>
          <div className="cta-row" style={{ marginTop: "1.4rem" }}>
            <a className="btn btn-signal" href="/#pricing">
              Back to pricing
            </a>
            <a className="btn btn-secondary" href="/">
              Home
            </a>
          </div>
        </div>
      </main>
    </div>
  );
}

function Landing() {
  const [activePlan, setActivePlan] = useState<PlanId>("starter");
  const [stripeEnabled, setStripeEnabled] = useState(false);
  const [signupOpen, setSignupOpen] = useState(false);
  const [company, setCompany] = useState("");
  const [slug, setSlug] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SignupResult | null>(null);

  useEffect(() => {
    fetch(apiUrl("/v1/billing/config"))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.stripe_enabled) setStripeEnabled(true);
      })
      .catch(() => undefined);
  }, []);

  function openSignup(plan: PlanId) {
    setActivePlan(plan);
    setError(null);
    setResult(null);
    setSignupOpen(true);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(apiUrl("/v1/billing/signup"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: company.trim(),
          slug: slug.trim(),
          email: email.trim(),
          plan_code: activePlan,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = data?.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail?.message || "Signup failed. Check details and try again.";
        throw new Error(message);
      }
      setResult(data as SignupResult);
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="site">
      <header className="hero">
        <HeroVisual />
        <div className="wrap" style={{ position: "relative", zIndex: 2, width: "100%" }}>
          <nav className="nav">
            <a className="brand" href="#top" style={{ color: "#fff" }}>
              MemoryBridge
            </a>
            <div className="nav-links">
              <a href="#product">Product</a>
              <a href="#security">Security</a>
              <a href="#pricing">Pricing</a>
              <button type="button" className="btn btn-signal" onClick={() => openSignup("starter")}>
                Get access
              </button>
            </div>
          </nav>

          <div className="hero-copy" id="top">
            <p className="hero-brand">MemoryBridge</p>
            <h1 className="hero-headline">
              Encrypted memory for AI products that must remember — privately.
            </h1>
            <p className="hero-sub">
              Persist user and session context for agents and assistants without storing plaintext
              summaries in your database.
            </p>
            <div className="cta-row">
              <button type="button" className="btn btn-signal" onClick={() => openSignup("starter")}>
                See plans
              </button>
              <a
                className="btn btn-secondary"
                href="#product"
                style={{ color: "#E8EEF4", borderColor: "rgba(232,238,244,0.28)" }}
              >
                How it works
              </a>
            </div>
          </div>
        </div>
      </header>

      <main>
        <section className="section" id="product">
          <div className="wrap">
            <p className="section-label">Product</p>
            <h2>A persistence layer your agents can trust.</h2>
            <p className="section-lead">
              MemoryBridge sits behind your AI app: store, recall, update, and delete encrypted
              memory with tenant isolation and metered billing built in.
            </p>
            <div className="product-grid">
              <div className="product-main">
                <h3 style={{ margin: 0, fontFamily: "var(--font-display)", letterSpacing: "-0.02em" }}>
                  Built for companies selling AI — not toy demos.
                </h3>
                <p>
                  Issue a tenant per customer, hand them a revocable API key, and let quotas enforce
                  Free → Starter → Growth upgrades when usage grows.
                </p>
              </div>
              <div className="product-aside">
                <div>
                  <strong>Store / recall / update</strong>
                  <span>Session memory encrypted before it hits Postgres.</span>
                </div>
                <div>
                  <strong>Multi-tenant by default</strong>
                  <span>Users and memories never cross tenant boundaries.</span>
                </div>
                <div>
                  <strong>Billable quotas</strong>
                  <span>Hard monthly limits with HTTP 402 when it’s time to upgrade.</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="section security" id="security">
          <div className="wrap">
            <p className="section-label">Security</p>
            <h2>Security that survives a sales call.</h2>
            <p className="section-lead">
              Designed so you can answer the hard questions from AI buyers without hand-waving.
            </p>
            <ul className="security-list">
              <li>AES-256-GCM with versioned keys and AAD bound to tenant + user</li>
              <li>Peppered HMAC hashing for user and session tokens</li>
              <li>Durable API keys with revoke, plus tenant suspend</li>
              <li>Audit events without logging secrets or memory bodies</li>
            </ul>
          </div>
        </section>

        <section className="section" id="pricing">
          <div className="wrap">
            <div className="pricing-head">
              <div>
                <p className="section-label">Pricing</p>
                <h2>Pick a plan. Start charging.</h2>
                <p className="section-lead">
                  {stripeEnabled
                    ? "Card checkout is live. Create a tenant and pay with Stripe."
                    : "Self-serve Free works now. Paid card checkout activates after Stripe keys are set on the server."}
                </p>
              </div>
            </div>

            <div className="plan-picker" role="listbox" aria-label="Pricing plans">
              {PLANS.map((plan) => {
                const selected = plan.id === activePlan;
                return (
                  <div
                    key={plan.id}
                    role="option"
                    aria-selected={selected}
                    className={`plan${selected ? " is-active" : ""}`}
                    onClick={() => setActivePlan(plan.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") setActivePlan(plan.id);
                    }}
                    tabIndex={0}
                  >
                    <p className="plan-name">{plan.name}</p>
                    <p className="plan-price">
                      {plan.price}
                      <span> / mo</span>
                    </p>
                    <ul>
                      {plan.features.map((feature) => (
                        <li key={feature}>{feature}</li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      className={`btn plan-cta ${selected ? "btn-signal" : "btn-secondary"}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        openSignup(plan.id);
                      }}
                    >
                      {plan.cta}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="section close">
          <div className="wrap">
            <div className="close-panel">
              <p className="section-label" style={{ color: "rgba(14,143,122,0.95)" }}>
                Next step
              </p>
              <h2>Put encrypted memory behind your AI product this week.</h2>
              <p className="section-lead" style={{ color: "rgba(232,238,244,0.72)" }}>
                Create a tenant, copy your API key once, and start metering. When Stripe is
                configured, paid upgrades go through Checkout automatically.
              </p>
              <div className="cta-row" style={{ marginTop: "1.4rem" }}>
                <button type="button" className="btn btn-signal" onClick={() => openSignup("growth")}>
                  Create tenant
                </button>
                <a
                  className="btn btn-secondary"
                  href="https://github.com/mmhaidari2-hash/memorybridge"
                  style={{ color: "#E8EEF4", borderColor: "rgba(232,238,244,0.28)" }}
                >
                  View repository
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="wrap footer">
        <span>© {new Date().getFullYear()} MemoryBridge</span>
        <span>Encrypted memory persistence for AI companies</span>
      </footer>

      {signupOpen && (
        <div className="modal-backdrop" role="presentation" onClick={() => !busy && setSignupOpen(false)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Create tenant"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>Create your MemoryBridge tenant</h3>
            <p>
              Plan: <strong>{activePlan}</strong>
              {!stripeEnabled && activePlan !== "free" ? " (card checkout needs Stripe keys on server)" : ""}
            </p>
            {result ? (
              <div className="signup-result">
                <p>{result.message}</p>
                <label>
                  API key (copy now)
                  <input readOnly value={result.api_key} />
                </label>
                <button type="button" className="btn btn-signal" onClick={() => setSignupOpen(false)}>
                  Done
                </button>
              </div>
            ) : (
              <form onSubmit={onSubmit} className="signup-form">
                <label>
                  Company name
                  <input
                    required
                    value={company}
                    onChange={(e) => {
                      setCompany(e.target.value);
                      if (!slug || slug === slugify(company)) setSlug(slugify(e.target.value));
                    }}
                  />
                </label>
                <label>
                  Slug
                  <input required pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$" value={slug} onChange={(e) => setSlug(e.target.value)} />
                </label>
                <label>
                  Work email
                  <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                </label>
                {error && <p className="form-error">{error}</p>}
                <div className="cta-row">
                  <button className="btn btn-signal" type="submit" disabled={busy}>
                    {busy ? "Working…" : activePlan === "free" ? "Create free tenant" : "Continue"}
                  </button>
                  <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => setSignupOpen(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
