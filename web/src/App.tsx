import { useState } from "react";

type Plan = {
  id: "free" | "starter" | "growth";
  name: string;
  price: string;
  blurb: string;
  features: string[];
  cta: string;
};

const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    blurb: "Prove the integration",
    features: ["1,000 ops / month", "100 encrypted memories", "Single tenant"],
    cta: "Start free",
  },
  {
    id: "starter",
    name: "Starter",
    price: "$49",
    blurb: "Ship to first customers",
    features: ["50,000 ops / month", "10,000 memories", "Revocable API keys"],
    cta: "Choose Starter",
  },
  {
    id: "growth",
    name: "Growth",
    price: "$199",
    blurb: "Scale a production fleet",
    features: ["500,000 ops / month", "100,000 memories", "Priority tenant isolation"],
    cta: "Choose Growth",
  },
];

function HeroVisual() {
  return (
    <div className="hero-visual" aria-hidden="true">
      <svg className="stream" viewBox="0 0 1200 420" preserveAspectRatio="none">
        <path
          className="s1"
          d="M-40 260 C 160 80, 320 380, 520 210 S 860 40, 1240 250"
        />
        <path
          className="s2"
          d="M-40 300 C 180 140, 360 360, 560 250 S 900 120, 1240 290"
        />
        <path
          className="s3"
          d="M-40 210 C 200 60, 380 300, 600 170 S 940 80, 1240 200"
        />
      </svg>
    </div>
  );
}

export default function App() {
  const [activePlan, setActivePlan] = useState<Plan["id"]>("starter");

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
              <a className="btn btn-signal" href="#pricing">
                Get access
              </a>
            </div>
          </nav>

          <div className="hero-copy" id="top">
            <p className="hero-brand">MemoryBridge</p>
            <h1 className="hero-headline">Encrypted memory for AI products that must remember — privately.</h1>
            <p className="hero-sub">
              Persist user and session context for agents and assistants without storing plaintext
              summaries in your database.
            </p>
            <div className="cta-row">
              <a className="btn btn-signal" href="#pricing">
                See plans
              </a>
              <a className="btn btn-secondary" href="#product" style={{ color: "#E8EEF4", borderColor: "rgba(232,238,244,0.28)" }}>
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
                  Simple commercial tiers that match how AI products grow.
                </p>
              </div>
            </div>

            <div className="plan-picker" role="listbox" aria-label="Pricing plans">
              {PLANS.map((plan) => {
                const selected = plan.id === activePlan;
                return (
                  <button
                    key={plan.id}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    className={`plan${selected ? " is-active" : ""}`}
                    onClick={() => setActivePlan(plan.id)}
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
                    <a
                      className={`btn plan-cta ${selected ? "btn-signal" : "btn-secondary"}`}
                      href="mailto:sales@memorybridge.dev?subject=MemoryBridge%20access"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {plan.cta}
                    </a>
                  </button>
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
                Self-host with Docker, create a tenant, issue a key, and start metering. Stripe
                checkout is ready when you are.
              </p>
              <div className="cta-row" style={{ marginTop: "1.4rem" }}>
                <a className="btn btn-signal" href="mailto:sales@memorybridge.dev">
                  Talk to sales
                </a>
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
    </div>
  );
}
