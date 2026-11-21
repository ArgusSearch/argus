# Search Atlas und Footer-Konkurrenten: was Argus bis Sonntag übernehmen sollte

Stand: Sa 2026-11-21, ca. 13:50 UTC.
Scout-Auftrag `argus-searchatlas`, Zeitbudget 45 Minuten, parallel zum Build, blockiert nichts.

## Zusammenfassung (Deutsch)

**Die fünf Kernpunkte.**

1. **Search Atlas verkauft Autonomie als "über Nacht erledigt" plus Kontrolle.**
   Autopilot ist Standard, ein Freigabemodus und Rollback sind jederzeit da, und das Ergebnis wird als Morgenbericht erzählt ("vier Jobs liefen, während du geschlafen hast").
   Vertrauen entsteht dort aber nur über Social Proof (3.200+ Reviews, Testimonials, Fallstudien-Prozente) und eine Uptime-Statusseite, nicht über prüfbare Belege, Trefferquoten oder Fehlalarmraten.
   Genau diese Lücke füllt Argus mit Belegen, Bench und ehrlichem Fehlgriff.
2. **Footer "Competitors" nennt Ahrefs, Semrush, Surfer SEO, "All SEO Tools" (18 Tool-Kategorien) und eine Tool-Matrix mit 30 Tools.**
   Beim Monitoring bieten alle dasselbe Muster: Alarm, Dashboard, KI-Zusammenfassung ("was hat sich geändert und warum").
   Keiner trennt Datenverspätung von echter Änderung, keiner belegt das "Warum" mit einer nachrechenbaren Abfrage, keiner veröffentlicht, wie oft er recht hat.
3. **Übernehmen, klein und bis So 11:00 machbar:**
   ein "While you slept"-Morgenbericht mit ehrlichen Zahlen und Beleg-Link je Zeile (narrator + Mission Control, ca. 2 bis 3 Agentenstunden);
   eine sichtbare Autonomie-Grenze auf dem Bildschirm, also was Argus allein entscheidet und wann es fragt (`PROBATION`, "ambiguous"), ca. 1 Stunde;
   Statusübergänge als Vorher-Nachher-Karte im Graphen (z. B. `PROPOSED -> VALID, Residuum 0,0 %`, Fan-out x12 mit Reparatur-Diff), ca. 2 Stunden.
4. **Neue Szenario-Idee "Sind wir es oder der Markt?"** nach Semrush Sensor und Surfer Pulse:
   eine externe Markt-Volatilitätsreihe als Kontrollgruppe, die einen organischen Rückgang als harmlos (Algorithmus-Update, ganzer Markt fällt mit) erklärt.
   Stärkt den Moment "harmlose Änderung" und "konkurrierende Erklärungen" (Autonomie 40 %), ca. 3 bis 4 Agentenstunden, nur wenn Checkpoint C4 pünktlich steht, passt direkt zum SEO-Stretch "noindex-Release".
5. **Nicht übernehmen:** Auto-Fix und Ausführung im Zielsystem, Slack/Teams-Coworker (D4 sagt App plus MCP), gewichtete 0-100-Health-Scores (undurchsichtig, widerspricht "Vertrauen aus Prüfungen berechnet"), ROI- oder Zeitersparnis-Rechner, White-Label, Content-Generierung.
   Pitch-Satz als Idee: "Monitoring-Tools hören beim Alarm auf, Argus beendet die Untersuchung, mit Beleg."

Alles unten sind Empfehlungen innerhalb des bestehenden Bauplans und der Streichliste; die Lane-Owner können sie nach Checkpoint-Lage aufnehmen oder liegen lassen.

---

## 1. What I did

- Read the Argus build plan (`docs/plan/build-plan.md`, sections 3.1 to 3.5 and 4.1 to 4.2) to map every idea onto existing Argus modules and work packages (G = graph, B = brain/watcher/investigator, U = surface, W = world/bench).
- Drove a headless Chrome session (`chrome-devtools-axi`, isolated session name `argus-searchatlas`) and extracted `document.body.innerText` plus all footer links for each page.
- Footer extraction command: `chrome-devtools-axi eval 'JSON.stringify([...document.querySelectorAll("footer a")].map(a=>[a.innerText.trim(),a.href]))'` on `https://searchatlas.com/`.
- Pages read on Search Atlas (19): home, OTTO SEO, OTTO Pixel, Atlas Agent, AI Coworker, Report Builder, Portfolio Summary, Site Auditor, LLM Visibility, Smart Ads, the OTTO launch press release, the status page, the four footer "Competitors" comparison pages, and the Interactive SEO Tool Matrix.
- Competitor pages read (13): ahrefs.com, Ahrefs Alerts, Ahrefs Site Audit, Letaido (Ahrefs' agent workspace, linked from the Ahrefs header), semrush.com, Semrush Sensor, surferseo.com, Surfer Pulse (AI volatility tracker), Sitebulb, Lumar, AgencyAnalytics, AccuRanker.
- Not reachable: Semrush Copilot (`/features/copilot/` and the KB article both returned "We got lost"); claims about Semrush Copilot and Ahrefs "Agent A" below are therefore as stated on Search Atlas' comparison pages and are marked as such.
- No code or text was copied; everything below is paraphrased ideas with source URLs.

## 2. Search Atlas: product and how it sells autonomy

### 2.1 Product in one paragraph

Search Atlas is an SEO and marketing platform whose core claim is execution, not reporting.
OTTO SEO connects to a site through a header script ("OTTO Pixel"), a Cloudflare Worker, or CMS connectors, then deploys technical and on-page fixes itself and submits changed URLs for indexing ([otto-seo](https://searchatlas.com/otto-seo/), [otto-pixel](https://searchatlas.com/otto-pixel/)).
Atlas Agent is the conversational layer that turns a plain-language goal into planned workflows and "Playbooks" ([atlas-agent](https://searchatlas.com/atlas-agent/)).
Search Atlas Coworker runs the same work from Slack and Teams, on cron-like schedules, and posts results and proactive alerts ([ai-coworker](https://searchatlas.com/ai-coworker/)).
Reporting is Report Builder plus Portfolio Summary, a weighted 0-100 health score per account with buckets "Biggest Wins / Stable / At Risk" ([portfolio-summary](https://searchatlas.com/portfolio-summary/), [report-builder](https://searchatlas.com/report-builder/)).

### 2.2 How they sell autonomy

- **Outcome-in-the-morning framing.**
  The homepage hero promises being found "while you sleep" and that by morning it is handled; the Coworker page shows a "done overnight" panel listing jobs that ran unattended (rank drop detected, brief written, fix queued) ([home](https://searchatlas.com/), [ai-coworker](https://searchatlas.com/ai-coworker/)).
- **"Every other tool stops at the recommendation."**
  The stack-replacement page argues that for twenty years SEO tools crawled, showed a graph, and left execution to the user, and positions Search Atlas as the agent that finishes the job ([vs-all-seo-tools](https://searchatlas.com/search-atlas-vs-all-seo-tools/)).
  Every footer comparison page has an "Execution Type" row where the competitor "recommends" and Search Atlas "deploys" ([vs-ahrefs](https://searchatlas.com/search-atlas-vs-ahrefs/), [vs-semrush](https://searchatlas.com/search-atlas-vs-semrush/), [vs-surfer](https://searchatlas.com/search-atlas-vs-surfer-seo/)).
- **Autonomy paired with control.**
  Autopilot is the default; approval mode, per-change approve/edit, bulk actions, custom instructions, and rollback are always offered alongside ([otto-seo](https://searchatlas.com/otto-seo/), [otto-pixel](https://searchatlas.com/otto-pixel/)).
  Smart Ads offers "Fast mode" versus "Advanced mode" with step-by-step approvals ([smart-ads](https://searchatlas.com/smart-ads/)).
  Atlas Agent's five steps put "review planned actions" and "approve high-impact changes or let safe automations run" before execution ([atlas-agent](https://searchatlas.com/atlas-agent/)).
- **Visible before/after.**
  The OTTO hero shows head tags flipping from "Missing" to "Fixed" (title, schema, canonical, og:image) ([otto-seo](https://searchatlas.com/otto-seo/)).
  The comparison pages embed an "OTTO Grader" widget: flawless pages 43/153, issues fixed 1,520/4,565, four pillar scores ([vs-ahrefs](https://searchatlas.com/search-atlas-vs-ahrefs/)).
- **Quantified time saved with stated assumptions.**
  The OTTO page has a calculator that multiplies "production minutes per fix" by a fix mix and an hourly rate, with a "View assumptions" control and an explicit note that the example mix must be replaced ([otto-seo](https://searchatlas.com/otto-seo/)).
- **Playbooks and skills.**
  Repeatable multi-step workflows ("recover lost rankings") and a skills directory the agent picks from ([ai-coworker](https://searchatlas.com/ai-coworker/), [atlas-agent](https://searchatlas.com/atlas-agent/)).

### 2.3 How they build trust and evidence

- Social proof dominates: G2/Capterra/Gartner badges, "3,200+ reviews", many named testimonials, case-study headline numbers such as "380 % more inquiries" and "1 day to fix everything" ([home](https://searchatlas.com/)).
- Operational transparency: a public status page with 90-day uptime per component, including "AI Agent", "MCP Server" and "Co-Worker" ([status](https://status.searchatlas.com/)).
- Comparison pages quote competitor prices and limits with a dated check ("checked 2026-11-03" on the Adobe/Semrush note) ([vs-semrush](https://searchatlas.com/search-atlas-vs-semrush/)).
- The Tool Matrix presents itself as "30 independently evaluated platforms" with Search Atlas as "Top Pick" at 9.8 ([compare-seo-tools](https://searchatlas.com/compare-seo-tools/)).
- **What is missing:** no accuracy or false-positive rate for any automated decision, no link from a claim to the data that produced it, no distinction between "data is late" and "metric really moved", and health scores are weighted blends whose weights are not shown.
  This is the opening Argus' build plan already targets (receipts with hash, bench with pass@1 and quiet weeks, computed confidence, `DATA_ISSUE` verdict).

### 2.4 Onboarding

One-paste pixel or Cloudflare install, project auto-activates, free 30-minute onboarding call even on trial, 7-day trial ([otto-pixel](https://searchatlas.com/otto-pixel/), [site-auditor](https://searchatlas.com/site-auditor/)).
For Argus the transferable idea is only "zero-config start": point it at the warehouse and it begins watching, which the MockMart demo already shows.

## 3. The footer's competitors

### 3.1 What the footer lists

The footer has a section literally headed "Competitors" with five links ([home](https://searchatlas.com/), footer):

| Footer link | URL | What it compares |
| --- | --- | --- |
| Search Atlas vs Ahrefs | https://searchatlas.com/search-atlas-vs-ahrefs/ | Execution (OTTO) vs Ahrefs data lead; "Agent A" per SA |
| Search Atlas vs Semrush | https://searchatlas.com/search-atlas-vs-semrush/ | Execution vs Semrush Copilot recommendations; Semrush MCP read-only per SA |
| Search Atlas vs Surfer SEO | https://searchatlas.com/search-atlas-vs-surfer-seo/ | Content scoring vs live fixes and rank tracking |
| Search Atlas vs All SEO Tools | https://searchatlas.com/search-atlas-vs-all-seo-tools/ | 18 tool categories, about 40 named products, "$8,000 stack" |
| Interactive SEO Tool Matrix | https://searchatlas.com/compare-seo-tools/ | 30 tools with cards and filters |

The footer markup additionally contains unlabeled links to migration guides from AccuRanker, Morningscore, Screaming Frog, Seobility, SEOptimer and Supermetrics (empty link text in the extracted footer, so not visible as labeled links).

The "All SEO Tools" page groups competitors by category, the ones relevant to monitoring being: site crawlers and SEO monitoring (Sitebulb, DeepCrawl, Lumar), agency reporting (AgencyAnalytics, Databox, Looker Studio), daily rank tracking (AccuRanker, Nightwatch, Mangools), AI SEO recommendation engines (Alli AI, Profound, Searchable), enterprise SEO (BrightEdge, Conductor, seoClarity).
The 30-tool matrix lists: AccuRanker, AgencyAnalytics, Ahrefs, BrightEdge, BrightLocal, BuzzStream, Clearscope, cognitiveSEO, Conductor, Frase, KeywordTool.io, LowFruits, Majestic, Mangools, MarketMuse, Moz Pro, Nightwatch, Rank Ranger, Raven Tools, Screaming Frog, SE Ranking, Search Atlas, Semrush, Serpstat, Similarweb, Sitebulb, SpyFu, Surfer, Ubersuggest, WooRank.

### 3.2 What each relevant competitor does that matters for Argus

I looked at every footer-named competitor (Ahrefs, Semrush, Surfer) and the monitoring-relevant ones from the category page and matrix; content-writing, backlink and local-citation tools were skipped because nothing there touches the Almedia rubric.

- **Ahrefs** ([ahrefs.com](https://ahrefs.com/), [alerts](https://ahrefs.com/alerts)).
  Alerts notify on new or lost backlinks, web mentions, and notable ranking changes across keywords the user never added, because Ahrefs watches its whole keyword database.
  "Ask Ahrefs" is a built-in assistant that runs API queries for the user; Site Audit monitors site health around the clock.
  Per Search Atlas, "Agent A" applies Site Audit fixes through connectors after review (not verified on ahrefs.com).
- **Letaido** (by the Ahrefs team, linked from the Ahrefs header, [letaido.com](https://letaido.com/)).
  An always-on agent workspace with scheduled automations ("recaps, audits, alerts"), file storage and an audit trail; its demo shows a live console of agent steps ("Connected to Ahrefs", "Fetching keyword ideas").
  It frames a ladder: chat answers, agents act, an always-on agent workspace runs around the clock.
- **Semrush** ([semrush.com](https://www.semrush.com/), [sensor](https://www.semrush.com/sensor/)).
  Sensor is a market-wide Google volatility index per industry category, with a "Personal Score", "Deviations" and "Winners & Losers".
  Per Search Atlas, Copilot and Site Audit recommend while the user applies, and the Semrush MCP is read-only.
- **Surfer** ([surferseo.com](https://surferseo.com/), [Pulse](https://surfer.ai/ai-volatility-tracker/)).
  Pulse publishes one daily 0-100 volatility score per AI answer engine, described as a weather report for AI search: it tells you whether the answers changed for everyone before you look at your own drop.
  AI Tracker then shows what the shift did to you (visibility score, share of voice, cited sources, coverage gaps), and Surfer is reachable via MCP.
- **Lumar** ([lumar.io](https://www.lumar.io/)).
  Monitor: continuous change monitoring across sites with custom alerts.
  Protect: automated QA tests before deploy, with thresholds that halt builds when a metric dips, explicitly sold as catching redirect and indexing mistakes before release.
- **Sitebulb** ([sitebulb.com](https://sitebulb.com/)).
  Prioritized "Hints" that explain why an issue matters and how to fix it, copy-pasteable explanations, scheduled crawls.
- **AgencyAnalytics** ([agencyanalytics.com](https://agencyanalytics.com/)).
  "Ask AI" scans every account and surfaces trends and dips before anyone asks; metric alerts and goals; it promises to explain "what changed and why".
- **AccuRanker** ([accuranker.com](https://www.accuranker.com/)).
  Fast rank tracking with on-demand refresh, an MCP server for AI assistants, and an LLM-visibility product.

**Common pattern across all of them:** alert plus dashboard plus an AI summary.
Every one now ships an MCP endpoint or assistant that returns data.
None of the pages read shows a published hit rate, a typed "nothing is broken" answer, a data-delay verdict, or a link from an explanation to the query that proves it.

## 4. Feature table: fits Argus? effort until Sunday 11:00? stage/module

Effort is agent-hours with the existing contracts in place, measured against the feature freeze Sun 11:00.
"In plan" means the build plan already has the package and the idea only sharpens how it is shown.
Rubric: G = metric graph 40 %, A = autonomy 40 %, D = demo 20 %.

| # | Feature seen | Source | Fits Argus? | Effort until So 11:00 | Stage / module |
| --- | --- | --- | --- | --- | --- |
| 1 | Overnight digest: "jobs that ran while you slept", outcome first | SA Coworker, SA home | **Yes, strong (A, D).** Argus version: "Overnight: watched N series, ignored M wiggles, opened 1 incident, held back 1 data delay", every line links to its receipt | 2-3 h (ticker funnel and narrator exist) | `narrator` + Mission Control; promotes stretch "Morning Brief" (U6) |
| 2 | Autopilot by default with approval mode and rollback; Fast vs Advanced mode | SA OTTO, Pixel, Smart Ads, Atlas Agent | **Yes, as framing (A).** Show the autonomy boundary on screen: investigates, decides verdicts, places metrics alone; asks only on `PROBATION` or "ambiguous". No remediation actions | ~1 h (labels, one legend panel) | Mission Control U1/U2; `graph` edge states G3 |
| 3 | "Missing -> Fixed" before/after per change | SA OTTO hero | **Yes (G, D).** Edge transitions as cards: `PROPOSED -> VALID (residual 0.0 %)`, `BROKEN: fan-out x12 -> repair diff` | ~2 h if the certificate data is there | `cartographer` certificate G4/G6, graph view U2 |
| 4 | Playbooks: named, repeatable multi-step workflows | SA Atlas Agent, Coworker | **Yes, naming only (A).** Present the fixed opening as a visible playbook ("Revenue drop playbook: freshness -> LMDI -> mix vs rate -> segment search -> holdout") with step status | <1 h (labels on the existing trail) | `investigator` B2/B3, trail in UI |
| 5 | Market-wide volatility index vs your own score ("is it us or the market?") | Semrush Sensor, Surfer Pulse | **Yes, new scenario (A).** External market series as control: organic sessions fall, market index falls the same day, verdict `EXPECTED`/external with the index as evidence | 3-4 h (sim series + calendar event + expectation shift) | `scenarios` W8, `watcher` calendar B1, `investigator` holdout B3; only if C4 on time |
| 6 | Alerts on things nobody configured (whole-database keyword watch) | Ahrefs Alerts | **Yes, pitch line (A).** Argus watches every series top-down with an exploration share, not a user-picked list | 0 h (in plan, B8) | `watcher` attention budget B1/B8 |
| 7 | Crawl monitoring: bot crawl rate and indexation per engine | SA OTTO, Ahrefs Site Audit | **Yes as SEO stretch (G, A).** `indexed_pages` from a crawl log as the new metric with a day-lag cause edge to organic sessions | 2-3 h (already estimated in plan 3.5) | `scenarios` W8, `graph` cause edge with day lag |
| 8 | Pre-deploy QA gate that halts builds on metric dips | Lumar Protect | **Pitch only.** Contrast: a gate needs someone to write the test first; Argus finds the release break nobody wrote a test for (noindex case) | 0 h | deck U12 |
| 9 | Live agent console streaming each step | Letaido demo | **Yes (A, D), in plan.** Keep the trail streaming with rejected alternatives visible | 0 h (in plan) | `runtime` events C5, trail UI |
| 10 | Prioritized explanation of why an issue matters | Sitebulb Hints | **Yes, in plan (A).** "Why I didn't alert" card and € impact ordering already cover it | 0 h | `narrator`, incidents B7 |
| 11 | Cost and time with "View assumptions" | SA OTTO calculator | **Partly (D).** Show measured cost per investigation (queries, seconds, euro) with a "how computed" toggle; do not invent labor-value savings | ~1 h on top of B6/U8 | `narrator` B6, bench/cost U8 |
| 12 | Component status page with uptime per subsystem | SA status page | **Small (D).** One status chip: last tick, tick rate, LLM on/off, live vs replay | ~1 h (live/replay already planned) | `runtime`, Mission Control U1 |
| 13 | MCP endpoint for AI assistants | SA (MCP Server), Semrush, Surfer, AccuRanker | **Yes, in plan (D).** Differentiate: Argus MCP returns verified findings with SQL and hash, not raw rows | 0 h extra (U10 should) | MCP server U10 |
| 14 | Weighted 0-100 health score with Wins / Stable / At Risk buckets | SA Portfolio Summary | **No as a blended score**, it hides how it was computed. If wanted, show counts instead: edges VALID / PROBATION / BROKEN, series healthy / watching / incident | 1-2 h only for the counts variant | graph view U2 (optional) |
| 15 | Slack/Teams coworker with scheduled routines and "want me to ship them?" | SA Coworker, Ahrefs Agent A per SA | **No until Sunday.** D4 already decided App plus MCP, Slack stays a stretch preview | - | (stretch U6 Slack preview) |
| 16 | Auto-deploy fixes into CMS/edge, auto-indexing | SA OTTO | **No.** Argus is the analyst, not the actuator; rubric does not reward remediation | - | - |
| 17 | Feature-by-feature comparison table vs competitors | SA footer pages | **Yes for the deck (D).** One slide: rows = "verifies graph edges against data", "separates data delay from real change", "publishes hit rate", "evidence per claim"; columns = Argus vs the vendors from the build plan | ~1 h (deck) | deck U12 |
| 18 | ROI / stack-savings calculator, white label, content generation, local SEO, ads | SA vs-all, Pro plan | **No.** Not in the rubric | - | - |

**Recommended picks, in order, if the lanes have slack:** 1 (overnight digest), 2 (autonomy boundary on screen), 4 (playbook naming), 3 (before/after edge cards), then 5 only if checkpoint C4 is on time.
Items 6, 8, 9, 10, 13 and 17 cost nothing but pitch wording.

## 5. Pitch and UX ideas (ideas only, no copied text)

1. **Open or close the demo on the overnight brief.**
   Search Atlas' strongest emotional beat is "you wake up and it's handled".
   Argus can claim the same beat honestly: a short "overnight" card with the funnel (series watched, wiggles ignored, anomalies, incidents, alerts held back for late data), each number clickable to its receipt.
   This is autonomy the jury can see without anyone touching the keyboard.
2. **Position against "stops at the alert".**
   Search Atlas positions itself against tools that stop at the recommendation.
   The monitoring analogue is that alerting tools stop at "something moved" and BI assistants stop at a plausible story.
   Argus' line: it finishes the investigation and shows the receipt, including when the answer is "nothing is broken".
3. **Make the autonomy boundary explicit, not hidden.**
   Search Atlas sells autonomy and control together (autopilot plus approval plus rollback).
   For Argus, a small legend on Mission Control: "decides alone" (open/close anomaly, verdict, placement of verified metrics) vs "flags for a human" (`PROBATION` edge, ambiguous metric, still-uncertain share).
   That turns the ambiguous-metric case into proof of judgment rather than a gap.
4. **"Is it us or the world?" as the harmless-change moment.**
   Sensor and Pulse exist because everyone asks this first after a drop.
   Argus already has holdouts and a calendar; showing an external market series as one more control makes the "harmless change" verdict obvious to a non-specialist jury.
5. **Trust from tests, shown as transitions.**
   Search Atlas shows trust with badges and before/after tags.
   Argus can show trust with state changes that carry their test value (`PROPOSED -> VALID, residual 0.0 %`; `SUPPORTED, lag 2 days, BH-corrected`) and publish its own bench number including one honest miss, which none of the 30 matrix tools or Search Atlas publishes.

## 6. Shipping and decisions

- Nothing here needs to ship from this scout as a PR; the ideas map onto existing Argus lanes (narrator, Mission Control, investigator trail, scenarios) and can be picked up by those lane owners.

## 7. Sources

Search Atlas (all read 2026-11-21):
https://searchatlas.com/ ,
https://searchatlas.com/otto-seo/ ,
https://searchatlas.com/otto-pixel/ ,
https://searchatlas.com/atlas-agent/ ,
https://searchatlas.com/ai-coworker/ ,
https://searchatlas.com/report-builder/ ,
https://searchatlas.com/portfolio-summary/ ,
https://searchatlas.com/site-auditor/ ,
https://searchatlas.com/llm-visibility/ ,
https://searchatlas.com/smart-ads/ ,
https://searchatlas.com/blog/search-atlas-unveils-otto-seo-the-first-autonomous-ai-seo-agent/ ,
https://status.searchatlas.com/ ,
https://searchatlas.com/search-atlas-vs-ahrefs/ ,
https://searchatlas.com/search-atlas-vs-semrush/ ,
https://searchatlas.com/search-atlas-vs-surfer-seo/ ,
https://searchatlas.com/search-atlas-vs-all-seo-tools/ ,
https://searchatlas.com/compare-seo-tools/ .

Competitors (all read 2026-11-21):
https://ahrefs.com/ ,
https://ahrefs.com/alerts ,
https://ahrefs.com/site-audit ,
https://letaido.com/ ,
https://www.semrush.com/ ,
https://www.semrush.com/sensor/ ,
https://surferseo.com/ ,
https://surfer.ai/ai-volatility-tracker/ ,
https://www.lumar.io/ ,
https://sitebulb.com/ ,
https://agencyanalytics.com/ ,
https://www.accuranker.com/ .

Not reachable: https://www.semrush.com/features/copilot/ (error page "We got lost").

Internal reference: `docs/plan/build-plan.md` sections 3.1 to 3.5 (feature list and SEO stretch) and 4.2 (architecture and module names).
