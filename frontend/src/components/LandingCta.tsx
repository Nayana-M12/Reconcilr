import { Link } from "react-router-dom";

export default function LandingCta() {
  return (
    <main className="landing-cta">
      <style>{`
        .landing-cta {
          --landing-ink: #f7f4ef;
          --landing-muted: rgba(247, 244, 239, 0.58);
          --landing-line: rgba(247, 244, 239, 0.14);
          --landing-coral: #f47668;
          min-height: 100vh;
          overflow: hidden;
          background: #000;
          color: var(--landing-ink);
          font-family: Inter, sans-serif;
        }

        .landing-shell {
          width: min(1120px, calc(100% - 48px));
          margin: 0 auto;
          padding: 32px 0 28px;
        }

        .landing-nav,
        .landing-footer-top,
        .landing-footer-bottom {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 24px;
        }

        .landing-brand {
          color: var(--landing-ink);
          font-size: 15px;
          font-weight: 600;
          letter-spacing: -0.02em;
          text-decoration: none;
        }

        .landing-brand span {
          color: var(--landing-coral);
        }

        .landing-nav-note {
          color: var(--landing-muted);
          font-size: 12px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .landing-hero {
          display: grid;
          grid-template-columns: minmax(0, 0.92fr) minmax(360px, 1.08fr);
          align-items: center;
          gap: clamp(48px, 8vw, 112px);
          min-height: 640px;
          padding: 88px 0 104px;
        }

        .landing-eyebrow {
          color: var(--landing-coral);
          font-size: 11px;
          font-weight: 600;
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }

        .landing-title {
          max-width: 620px;
          margin: 20px 0 22px;
          font-size: clamp(3.2rem, 7vw, 6.4rem);
          font-weight: 500;
          letter-spacing: -0.075em;
          line-height: 0.94;
        }

        .landing-subtitle {
          max-width: 440px;
          margin: 0;
          color: var(--landing-muted);
          font-size: 16px;
          line-height: 1.65;
        }

        .landing-action {
          display: inline-flex;
          align-items: center;
          gap: 12px;
          margin-top: 34px;
          border-radius: 999px;
          padding: 13px 20px 13px 22px;
          background: linear-gradient(110deg, #ff937c, var(--landing-coral) 55%, #ef5c50);
          box-shadow: 0 12px 32px rgba(255, 118, 95, 0.2);
          color: #24100d;
          font-size: 13px;
          font-weight: 700;
          text-decoration: none;
          transition: transform 180ms ease, box-shadow 180ms ease, filter 180ms ease;
        }

        .landing-action::after {
          content: "↗";
          font-size: 16px;
          line-height: 1;
          transition: transform 180ms ease;
        }

        .landing-action:hover {
          filter: saturate(1.08);
          transform: translateY(-3px);
          box-shadow: 0 16px 38px rgba(255, 118, 95, 0.3);
        }

        .landing-action:hover::after {
          transform: translate(2px, -2px);
        }

        .landing-visual {
          position: relative;
          isolation: isolate;
          min-height: 450px;
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 28px;
          padding: 12px;
          background:
            radial-gradient(circle at 78% 12%, rgba(255, 133, 111, 0.6), transparent 31%),
            radial-gradient(circle at 12% 92%, rgba(93, 72, 131, 0.8), transparent 42%),
            linear-gradient(145deg, #25202a 0%, #171719 52%, #321a21 100%);
          box-shadow: 0 28px 90px rgba(0, 0, 0, 0.36);
          transform: rotate(2deg);
          transition: transform 350ms ease;
        }

        .landing-visual::before {
          position: absolute;
          z-index: -1;
          inset: 18px -18px -18px 18px;
          border-radius: inherit;
          background: linear-gradient(145deg, rgba(255, 118, 95, 0.35), transparent 48%, rgba(102, 78, 141, 0.45));
          content: "";
          filter: blur(20px);
        }

        .landing-visual:hover {
          transform: rotate(0deg) translateY(-5px);
        }

        .landing-proof {
          display: flex;
          min-height: 424px;
          flex-direction: column;
          justify-content: space-between;
          overflow: hidden;
          border-radius: 18px;
          padding: 26px;
          background: linear-gradient(145deg, rgba(18, 18, 20, 0.9), rgba(28, 22, 27, 0.78));
        }

        .landing-proof-header,
        .landing-proof-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
        }

        .landing-proof-label {
          color: rgba(255, 255, 255, 0.48);
          font-size: 11px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }

        .landing-proof-status {
          border: 1px solid rgba(129, 220, 159, 0.28);
          border-radius: 999px;
          padding: 6px 9px;
          color: #9de0ac;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .landing-proof h2 {
          max-width: 300px;
          margin: 48px 0 0;
          font-size: clamp(2rem, 4vw, 3.2rem);
          font-weight: 500;
          letter-spacing: -0.065em;
          line-height: 0.98;
        }

        .landing-proof-list {
          display: grid;
          gap: 9px;
          margin-top: 30px;
        }

        .landing-proof-row {
          border-top: 1px solid rgba(255, 255, 255, 0.1);
          padding-top: 12px;
          color: rgba(255, 255, 255, 0.58);
          font-size: 12px;
        }

        .landing-proof-row strong {
          color: rgba(255, 255, 255, 0.9);
          font-weight: 500;
        }

        .landing-footer {
          border-top: 1px solid var(--landing-line);
          padding-top: 28px;
        }

        .landing-footer-top {
          align-items: flex-start;
        }

        .landing-footer-description {
          max-width: 260px;
          margin: 12px 0 0;
          color: var(--landing-muted);
          font-size: 12px;
          line-height: 1.6;
        }

        .landing-footer-links {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 22px;
        }

        .landing-footer-links a {
          color: var(--landing-muted);
          font-size: 12px;
          text-decoration: none;
          transition: color 160ms ease;
        }

        .landing-footer-links a:hover {
          color: var(--landing-ink);
        }

        .landing-footer-bottom {
          align-items: flex-end;
          margin-top: 74px;
          color: rgba(247, 244, 239, 0.38);
          font-size: 11px;
          line-height: 1.5;
        }

        .landing-footer-bottom p {
          margin: 0;
        }

        @media (max-width: 760px) {
          .landing-shell {
            width: min(100% - 32px, 560px);
            padding-top: 24px;
          }

          .landing-nav-note {
            display: none;
          }

          .landing-hero {
            display: block;
            min-height: auto;
            padding: 100px 0 88px;
          }

          .landing-title {
            font-size: clamp(3.2rem, 16vw, 5.3rem);
          }

          .landing-visual {
            min-height: 360px;
            margin: 72px 8px 0;
          }

          .landing-proof {
            min-height: 334px;
            padding: 20px;
          }

          .landing-proof h2 {
            margin-top: 34px;
            font-size: 2.45rem;
          }

          .landing-footer-top,
          .landing-footer-bottom {
            display: block;
          }

          .landing-footer-links {
            justify-content: flex-start;
            margin-top: 28px;
          }

          .landing-footer-bottom {
            margin-top: 42px;
          }

          .landing-footer-bottom p + p {
            margin-top: 8px;
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .landing-action,
          .landing-action::after,
          .landing-visual,
          .landing-footer-links a {
            transition: none;
          }
        }
      `}</style>

      <div className="landing-shell">
        <nav className="landing-nav" aria-label="Primary">
          <Link className="landing-brand" to="/">
            Reconcilr<span>.</span>
          </Link>
          <span className="landing-nav-note">Evidence-first reconciliation</span>
        </nav>

        <section className="landing-hero">
          <div>
            <p className="landing-eyebrow">A clearer close</p>
            <h1 className="landing-title">Reconcile every transaction, with proof</h1>
            <p className="landing-subtitle">
              Import invoices, POs and payments, then review each exception alongside the records that caused it.
            </p>
            <Link className="landing-action" to="/app">
              Open app
            </Link>
          </div>

          <div className="landing-visual" aria-label="Reconciliation proof preview">
            <div className="landing-proof">
              <div className="landing-proof-header">
                <span className="landing-proof-label">Reconciliation / 2024-06</span>
                <span className="landing-proof-status">Verified</span>
              </div>
              <div>
                <h2>Every number has a trail.</h2>
                <div className="landing-proof-list">
                  <div className="landing-proof-row">
                    <span>Invoices linked</span>
                    <strong>24</strong>
                  </div>
                  <div className="landing-proof-row">
                    <span>Payments matched</span>
                    <strong>11</strong>
                  </div>
                  <div className="landing-proof-row">
                    <span>Exceptions to review</span>
                    <strong>7</strong>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <footer className="landing-footer">
          <div className="landing-footer-top">
            <div>
              <Link className="landing-brand" to="/">
                /// <span>Reconcilr</span>
              </Link>
              <p className="landing-footer-description">
                Financial reconciliation that keeps the evidence close to every decision.
              </p>
            </div>
            <nav className="landing-footer-links" aria-label="Footer">
              <Link to="/app">Dashboard</Link>
              <Link to="/app/exceptions">Exceptions</Link>
              <Link to="/app/audit">Audit log</Link>
            </nav>
          </div>
          <div className="landing-footer-bottom">
            <p>Reconcilr. Built with FastAPI, SQLAlchemy and React.</p>
            <p>35 matches · 7 exceptions · 0 invented transactions</p>
          </div>
        </footer>
      </div>
    </main>
  );
}
