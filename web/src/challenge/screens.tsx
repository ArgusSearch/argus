// Blind challenge screens: the big-screen pick and seal, the banner during the run, the reveal, and the
// phone page that recomputes the hash. Data: the recorded run in ./fixtures until the bench routes exist.

import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { dayLabel, hhmm, humanize, segmentLabel } from "../lib/format";
import { EmptyState } from "../ui";
import { isCommitment, normalizeCommitment, tamper, verifyCommitment, type Check } from "./commitment";
import { compareRows, passed, scenarioName, truthOf, verdictLabel, type Reveal } from "./model";
import { encodeQr, qrPath } from "./qr";
import { isLoopback, phoneLink, routeHref, type Route, type Screen } from "./route";
import { recordedChallenge, type Recorded } from "./sample";
import "./challenge.css";

function go(screen: Screen | null, extra: Record<string, string | null> = {}) {
  window.history.pushState(null, "", routeHref(window.location.search, screen, extra));
  window.dispatchEvent(new Event("argus:challenge"));
  window.scrollTo(0, 0);
}

function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <path d="M3 16c3.6-6 8-9 13-9s9.4 3 13 9c-3.6 6-8 9-13 9s-9.4-3-13-9Z" fill="none" stroke="var(--text)" strokeWidth="1.8" />
      <circle cx="16" cy="16" r="5.2" fill="none" stroke="var(--probe)" strokeWidth="1.8" />
      <circle cx="16" cy="16" r="1.9" fill="var(--text)" />
    </svg>
  );
}

function Qr({ text, label }: { text: string; label: string }) {
  const code = useMemo(() => encodeQr(text), [text]);
  const side = code.size + 8;
  return (
    <svg className="ch-qr" viewBox={`0 0 ${side} ${side}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={side} height={side} fill="#fff" />
      <path d={qrPath(code)} fill="#0a0d13" />
    </svg>
  );
}

/** The 64 hex digits in four groups of sixteen, so a judge can compare them by eye. */
function Hash({ value, big = false }: { value: string; big?: boolean }) {
  const hex = normalizeCommitment(value).replace("sha256:", "");
  const groups = hex.match(/.{1,16}/g) ?? [hex];
  return (
    <div className={`ch-hash${big ? " big" : ""}`} aria-label={`sha256 ${hex}`}>
      <span className="ch-hash-alg">sha256</span>
      {groups.map((g, i) => (
        <span key={i}>{g}</span>
      ))}
    </div>
  );
}

function Shell({ step, children, aside }: { step: 1 | 2 | 3 | 4; children: ReactNode; aside?: ReactNode }) {
  const steps = ["A judge picks", "Argus commits", "Argus runs", "Reveal"];
  return (
    <div className="ch-page">
      <header className="ch-top">
        <a className="ch-brand" href={routeHref(window.location.search, null)} title="Back to Mission Control">
          <Mark />
          <span className="ch-brand-name">ARGUS</span>
          <span className="ch-brand-sub">Blind challenge</span>
        </a>
        <ol className="ch-steps" aria-label="steps">
          {steps.map((s, i) => (
            <li key={s} className={i + 1 < step ? "done" : i + 1 === step ? "now" : ""}>
              <b>{i + 1}</b>
              {s}
            </li>
          ))}
        </ol>
        {aside}
      </header>
      <main className="ch-main">{children}</main>
    </div>
  );
}

function RecordedChip({ rec }: { rec: Recorded }) {
  return (
    <span className="ch-chip" title={`Recorded with ${rec.command}; live sealing needs POST /challenge/commit (not built yet)`}>
      recorded run · seed {rec.reveal.seed} · {dayLabel(rec.sealedAt)} {hhmm(rec.sealedAt)}
    </span>
  );
}

function PhoneCard({ commitment, lan, title, screen }: { commitment: string; lan: string | null; title: string; screen: Screen }) {
  const [draft, setDraft] = useState(lan ?? "");
  const link = phoneLink(window.location.origin, lan, commitment);
  const unreachable = !lan && isLoopback(window.location.host);
  return (
    <div className="ch-phone">
      <Qr text={link} label="QR code: open the check on your phone" />
      <div className="ch-phone-text">
        <b>{title}</b>
        <span className="mono ch-link">{link}</span>
        {unreachable && (
          <form
            className="ch-lan"
            onSubmit={(e) => {
              e.preventDefault();
              go(screen, { lan: draft.trim() || null });
            }}
          >
            <span>
              A phone cannot open {window.location.host}. Run the API with <code>--host 0.0.0.0</code> and enter the laptop's
              address:
            </span>
            <span className="ch-lan-row">
              <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="192.168.1.20:8000" aria-label="laptop address" />
              <button className="btn" type="submit">
                Use
              </button>
            </span>
          </form>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 1 and 2: pick and seal

function PickScreen({ rec, route }: { rec: Recorded; route: Route }) {
  const [seed, setSeed] = useState("");
  const [sealed, setSealed] = useState(false);
  const [asked, setAsked] = useState<number | null>(null);

  const seal = (e: FormEvent) => {
    e.preventDefault();
    const n = Number.parseInt(seed, 10);
    setAsked(Number.isFinite(n) ? n : null);
    setSealed(true);
  };

  return (
    <Shell step={sealed ? 2 : 1} aside={<RecordedChip rec={rec} />}>
      {!sealed ? (
        <section className="ch-card ch-pick">
          <h1>A judge picks a number.</h1>
          <p className="ch-lede">
            The number seeds a hidden scenario: a real fault, a harmless change, a data problem or nothing at all. Argus commits to the
            answer key by hash before it looks at a single row.
          </p>
          <form className="ch-seed" onSubmit={seal}>
            <input
              inputMode="numeric"
              pattern="[0-9]*"
              value={seed}
              onChange={(e) => setSeed(e.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
              placeholder={String(rec.reveal.seed)}
              aria-label="seed"
              autoFocus
            />
            <button type="button" className="btn" onClick={() => setSeed(String(1 + Math.floor(Math.random() * 999)))}>
              Random
            </button>
            <button type="submit" className="btn primary ch-cta">
              Seal the scenario
            </button>
          </form>
        </section>
      ) : (
        <section className="ch-card ch-sealed">
          <div className="ch-sealed-main">
            <span className="ch-eyebrow">Committed before the run</span>
            <h1>Argus sealed the answer key.</h1>
            <Hash value={rec.commitment} big />
            <p className="ch-lede">
              This is the SHA-256 of a secret nonce and the hidden truth. Neither leaves the bench until the run is over; afterwards
              anyone can recompute this hash and see that the truth was not changed.
            </p>
            {asked !== null && asked !== rec.reveal.seed && (
              <p className="ch-note">
                Live sealing is not built yet, so this is the recorded challenge for seed {rec.reveal.seed}, not {asked}.
              </p>
            )}
            <div className="ch-actions">
              <button className="btn primary ch-cta" onClick={() => go("run")}>
                Start the run
              </button>
              <button className="btn" onClick={() => setSealed(false)}>
                Pick again
              </button>
            </div>
          </div>
          <PhoneCard commitment={rec.commitment} lan={route.lan} screen="pick" title="Scan now to keep the hash on your phone" />
        </section>
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------- 3: during the run

function RunBanner({ rec }: { rec: Recorded }) {
  const hex = rec.commitment.replace("sha256:", "");
  return (
    <div className="ch-banner" role="status">
      <span className="ch-banner-dot" />
      <span className="ch-banner-text">
        <b>Hidden scenario, committed</b>
        <span className="mono">
          sha256:{hex.slice(0, 12)}…{hex.slice(-6)}
        </span>
      </span>
      <span className="ch-banner-tag">recorded</span>
      <button className="btn primary" onClick={() => go("reveal")}>
        Reveal
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- 4: reveal

function useCheck(commitment: string, nonce: string, payload: string): Check | null {
  const [check, setCheck] = useState<Check | null>(null);
  useEffect(() => {
    let live = true;
    setCheck(null);
    if (isCommitment(commitment) && nonce && payload) verifyCommitment(commitment, nonce, payload).then((c) => live && setCheck(c));
    return () => {
      live = false;
    };
  }, [commitment, nonce, payload]);
  return check;
}

function CheckLine({ check, commitment }: { check: Check | null; commitment: string }) {
  if (!check) return <div className="ch-check">Recomputing the hash…</div>;
  const engine = check.engine === "webcrypto" ? "WebCrypto" : "built-in SHA-256 (no WebCrypto on this page)";
  return (
    <div className={`ch-check ${check.matches ? "ok" : "bad"}`} role="status">
      <span className="ch-check-mark" aria-hidden>
        {check.matches ? "✓" : "✗"}
      </span>
      <div>
        <b>{check.matches ? "The hash matches. The truth was sealed before the run." : "The hash does not match."}</b>
        <span>
          sha256(nonce + newline + payload), recomputed in this browser with {engine}
        </span>
        <div className="ch-check-pair mono">
          <span>
            <i>committed</i>
            {normalizeCommitment(commitment)}
          </span>
          <span className={check.matches ? "" : "differs"}>
            <i>computed</i>
            {check.computed}
          </span>
        </div>
      </div>
    </div>
  );
}

function Truth({ reveal }: { reveal: Reveal }) {
  const truth = truthOf(reveal);
  if (!truth) return <EmptyState title="The payload is not readable JSON" detail="The hash check above still holds or fails on its own." />;
  return (
    <ul className="ch-list">
      {truth.events.map((e) => (
        <li key={e.event_id}>
          <span className={`ch-kind ${e.kind}`}>{humanize(e.kind)}</span>
          <div>
            <b>{e.description}</b>
            {e.expected.verdict ? (
              <span>
                Expected <i className={`pill ${e.expected.verdict}`}>{verdictLabel(e.expected.verdict)}</i> on{" "}
                <span className="mono">{e.expected.root_node}</span>
                {e.expected.segment && ` · ${segmentLabel(e.expected.segment)}`}
                {e.expected.evidence && (
                  <>
                    , citing <span className="mono">{e.expected.evidence}</span>
                  </>
                )}
                {e.expected.ruled_out?.length ? (
                  <>
                    , ruling out <span className="mono">{e.expected.ruled_out.join(", ")}</span>
                  </>
                ) : null}
              </span>
            ) : (
              <span>Must not cause an alarm on its own.</span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Claims({ rec }: { rec: Recorded }) {
  if (!rec.claims.length) return <EmptyState title="Argus filed no incident" detail="On a quiet or harmless scenario that is the right answer." />;
  return (
    <ul className="ch-list">
      {rec.claims.map((c) => (
        <li key={c.id}>
          <span className="ch-kind claim">{c.id}</span>
          <div>
            <b>{c.title}</b>
            <span>
              <i className={`pill ${c.verdict}`}>{verdictLabel(c.verdict)}</i> on <span className="mono">{c.root_node}</span> ·{" "}
              {segmentLabel(c.segment)}
              {c.evidence && (
                <>
                  , citing <span className="mono">{c.evidence}</span>
                </>
              )}
            </span>
            {c.ruled_out.map((r) => (
              <span key={r.ref} className="ch-ruled">
                Ruled out <span className="mono">{r.ref}</span>: {r.reason}
              </span>
            ))}
            <span className="ch-when">
              opened {dayLabel(c.opened_at)} {hhmm(c.opened_at)}
              {c.resolved_at && ` · resolved ${dayLabel(c.resolved_at)} ${hhmm(c.resolved_at)}`}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function RevealScreen({ rec, route }: { rec: Recorded; route: Route }) {
  const { reveal, commitment } = rec;
  const [tampered, setTampered] = useState(false);
  const payload = tampered ? tamper(reveal.payload) : reveal.payload;
  const check = useCheck(commitment, reveal.nonce, payload);
  const ok = passed(reveal.grade);
  const rows = compareRows(reveal);
  const g = reveal.grade;

  return (
    <Shell
      step={4}
      aside={
        <span className={`ch-grade ${ok ? "pass" : "fail"}`} title="graded by the bench against the sealed truth">
          {ok ? "PASS" : "FAIL"}
        </span>
      }
    >
      <section className="ch-card ch-reveal">
        <div className="ch-reveal-head">
          <span className="ch-eyebrow">The hidden scenario was</span>
          <h1>{scenarioName(reveal.scenario)}</h1>
          <span className="ch-reveal-meta">
            {g.pages} {g.pages === 1 ? "page" : "pages"} · {g.false_alarms.length} false{" "}
            {g.false_alarms.length === 1 ? "alarm" : "alarms"} · <RecordedChip rec={rec} />
          </span>
        </div>

        <CheckLine check={check} commitment={commitment} />
        <div className="ch-tamper">
          <button className="btn" onClick={() => setTampered(!tampered)} aria-pressed={tampered}>
            {tampered ? "Restore the payload" : "Change one character of the payload"}
          </button>
          <span className="muted">{tampered ? "One digit changed: the hash no longer matches." : "Try it: any edit breaks the hash."}</span>
        </div>

        <div className="ch-cols">
          <div className="ch-col">
            <h2>The hidden truth</h2>
            <Truth reveal={{ ...reveal, payload }} />
          </div>
          <div className="ch-col">
            <h2>What Argus said, alone</h2>
            <Claims rec={rec} />
          </div>
        </div>

        <table className="ch-table">
          <thead>
            <tr>
              <th>Event</th>
              <th>The truth expected</th>
              <th>Argus claimed</th>
              <th>Grade</th>
              <th>Time to detect</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.event} className={r.hit ? "hit" : "miss"}>
                <td data-label="Event">{r.event}</td>
                <td data-label="The truth expected">{r.truth}</td>
                <td data-label="Argus claimed">{r.argus}</td>
                <td data-label="Grade">
                  <b>{r.grade}</b> {r.label}
                </td>
                <td className="mono" data-label="Time to detect">
                  {r.ttd}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <details className="ch-raw">
          <summary>Nonce and payload</summary>
          <label>nonce</label>
          <pre className="mono">{reveal.nonce}</pre>
          <label>payload (canonical JSON, hashed byte for byte)</label>
          <pre className="mono">{payload}</pre>
        </details>

        <div className="ch-foot">
          <PhoneCard commitment={commitment} lan={route.lan} screen="reveal" title="Check it on your phone" />
          <div className="ch-foot-side">
            <span className="muted">Or in a terminal:</span>
            <code>uv run argus-bench verify runs/bench/blind-{reveal.seed}</code>
            <button className="btn" onClick={() => go(null)}>
              Back to Mission Control
            </button>
          </div>
        </div>
      </section>
    </Shell>
  );
}

// ---------------------------------------------------------------- the phone page

function VerifyScreen({ rec, route }: { rec: Recorded; route: Route }) {
  const [commitment, setCommitment] = useState(route.commitment ? normalizeCommitment(route.commitment) : "");
  const [nonce, setNonce] = useState("");
  const [payload, setPayload] = useState("");
  const check = useCheck(commitment, nonce.trim(), payload);
  const wellFormed = isCommitment(commitment);

  return (
    <div className="ch-page ch-verify">
      <header className="ch-vtop">
        <Mark size={22} />
        <span className="ch-brand-name">ARGUS</span>
        <span className="ch-brand-sub">Check the commitment</span>
      </header>
      <main className="ch-vmain">
        <p className="ch-lede">
          Before the run Argus published a hash. After the run it reveals the nonce and the hidden truth. If they hash to the same value,
          the truth was fixed before Argus looked.
        </p>

        <label className="ch-field">
          <span>
            <b>1</b> The commitment, from the QR code before the run
          </span>
          <textarea
            className="mono"
            rows={3}
            value={commitment}
            onChange={(e) => setCommitment(e.target.value)}
            placeholder="sha256:…"
            spellCheck={false}
          />
          {commitment && <i className={wellFormed ? "ok" : "bad"}>{wellFormed ? "a well-formed SHA-256 hash" : "not a SHA-256 hash yet (64 hex digits)"}</i>}
        </label>

        <div className="ch-field">
          <span>
            <b>2</b> After the reveal: the nonce and the payload
          </span>
          <button
            className="btn"
            onClick={() => {
              setNonce(rec.reveal.nonce);
              setPayload(rec.reveal.payload);
            }}
          >
            Load the recorded reveal (seed {rec.reveal.seed})
          </button>
          <input className="mono" value={nonce} onChange={(e) => setNonce(e.target.value)} placeholder="nonce" aria-label="nonce" spellCheck={false} />
          <textarea
            className="mono"
            rows={6}
            value={payload}
            onChange={(e) => setPayload(e.target.value)}
            placeholder="payload (paste it exactly, byte for byte)"
            aria-label="payload"
            spellCheck={false}
          />
          {payload && (
            <button className="btn ch-small" onClick={() => setPayload(tamper(payload))}>
              Change one character of the payload
            </button>
          )}
        </div>

        {wellFormed && nonce && payload ? (
          <CheckLine check={check} commitment={commitment} />
        ) : (
          <div className="ch-check">The check runs as soon as all three are filled in.</div>
        )}
      </main>
    </div>
  );
}

export default function Screens({ route }: { route: Route }) {
  const rec = useMemo(() => recordedChallenge(), []);
  switch (route.screen) {
    case "run":
      return <RunBanner rec={rec} />;
    case "reveal":
      return <RevealScreen rec={rec} route={route} />;
    case "verify":
      return <VerifyScreen rec={rec} route={route} />;
    default:
      return <PickScreen rec={rec} route={route} />;
  }
}
