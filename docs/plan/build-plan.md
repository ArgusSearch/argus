# Argus: Reverse Engineering, Feature-Liste und Bauplan bis zur Abgabe

Stand: v3, Sa 21.11.2026 13:44 (vollständig: Reverse Engineering, Feature-Liste, Bauplan, Antworten, Korrekturen, Technik-Probe, Board mit D1 bis D9).
Grundlage ist die Produktvision `Argus_Product_Vision.pdf` (Version 2, "vision only"), sie ist der Maßstab.
Abschnitt 12 des früheren Berichts `data/almedia-ideation/report.md` dient nur als Ergänzung.
Das Board zu diesem Bericht zeigt Zeitplan, Lanes, Architektur, Pakete und die neun offenen Entscheidungen (D1 bis D9) zum Anklicken.

## Zusammenfassung

**Was jetzt zu tun ist (die nächsten 60 Minuten).**

1. Alle vier: 30 Minuten Kickoff, die fünf Fragen der Vision entscheiden (Vorschlag unten), Rollen und Schlafschichten festlegen.
2. Zwei Agenten bauen sofort das Repo-Skelett (K1) und die sechs Verträge mit Fixtures (K2), siehe 4.3.
3. Danach startet jede Person zwei bis drei Agenten-Pakete ihrer Lane aus 4.8.

**Antworten auf die fünf offenen Fragen (Abschnitt 5).**

1. Agentik: Option A, feste Eröffnung mit sichtbarem Planer, Option B wird als Baseline in der Bench gemessen statt gebaut.
2. Rewards-Schicht: ja, aber klein, ein Cashback-Postback-Szenario, Cashback hängt als Teil von `discounts` im Graphen.
3. Eröffnung: Blind Challenge, mit Go/No-Go am Sonntag 10:30 und einer Rückfall-Leiter ohne Netz.
4. Kanäle: App plus MCP, Slack streichen, Rückfragen als Thread auf der Incident-Seite.
5. Name: Argus behalten.

**Der Plan in Kürze (Abschnitt 4).**

- Vier Lanes mit je einer Person und drei Agenten: Graph (P1), Welt und Beweis (P2), Gehirn (P3), Oberfläche und Auftritt (P4).
- Sechs Verträge in der ersten Stunde, danach rund 40 Arbeitspakete mit Abnahmetest, etwa 85 Agentenstunden für Must und Should.
- Checkpoints: Sa 18:45 laufendes Skelett, Sa 22:30 Fehler und harmlose Änderung ohne Sprachmodell, So 03:15 neue Metrik, So 08:00 Bench und Blind Challenge.
- Schlaf: P2 und P4 von Sa 22:45 bis So 03:15, P1 und P3 von So 03:30 bis 08:00, die Flotte arbeitet nachts Pakete mit Abnahmetest ab.
- Feature-Freeze So 11:00, Proben So 12:00 und 14:30, Video So 12:30 bis 14:00, Abgabe So 15:30.

**Frist.**
Die Vision nennt So 16:30, die öffentliche Luma-Seite nennt heute So 17:45, die Zeit 16:30 steht auf keiner öffentlichen Seite (6.1).
Der Plan rechnet mit 16:30, bitte einmal vor Ort klären.

**Korrekturen am Pitch (6.2).**
Mehrere Zahlen der Vision halten der Prüfung nicht stand: Resolve ist mit 1 Mrd. USD belegt, nicht 1,5 Mrd., die "verdoppelte Genauigkeit durch Verifier" ist so nicht belegt, die 40 % Halluzination auf ORCA-bench gelten nur für das schwächste Modell, und Snowflake CoWork kann laut Doku nur zeitgesteuerte Berichte.
Die Kernthese hält: Niemand prüft Graph-Kanten gegen Daten, niemand trennt exakte Zerlegung von Ursachenhypothese, kein Analytics-Anbieter veröffentlicht eine Trefferquote.

**Die wertvollsten Übernahmen aus dem Reverse Engineering (Abschnitt 2).**

1. Feste Eröffnung vor jedem Modellaufruf (Flow-of-Action), Skeptic mit An-Aus-Vergleich in der Bench (Resolve).
2. Gesunde Kontrollwochen und eine typisierte Antwort "nichts ist kaputt", dazu die Fehlalarmrate als eigene Zahl (Causely, ORCA-bench).
3. Segmentsuche nach Adtributor (Erklärungsanteil und Überraschung, Schwellen 67 % und 10 %), erschöpfend über alle Kombinationen, RiskLoc als zweite Wertung.
4. Volumen-Stufen für Segmente wie bei Uber uVitals, dort sanken die Anomalien eines Monitors von 232 auf 11.
5. Urteil trennt Datenverspätung, Datenbruch und echte Änderung, mit Frische-Prüfung zuerst, das verbindet kein untersuchter Anbieter mit Ursachenanalyse.
6. Kosten, Zeit und Abfragen je Untersuchung im Bericht (Datadog), SQL-Link an jeder Zahl.
7. Trichter sichtbar machen: beobachtete Reihen, ignorierte Wackler, Anomalien, Incidents (Anodot).
8. Vertrauen aus Prüfungen berechnen statt vom Modell vergeben lassen (Gegenstück zu Mixpanel).

**Vier Korrekturen aus der Technik-Probe (7.4), alle schon im Plan.**

1. Die Beispielmetrik der Vision (`refund_rate` mit Join über drei Schlüssel) liefert das 12-Fache des wahren Werts, sobald Bestellungen vier Dimensionen tragen, der Cartographer braucht einen Fan-out-Wächter.
2. Die Regel "einfachste Kombination, die 67 % erklärt" bleibt bei `country = DE` stehen, die Segmentsuche braucht eine Abstiegsregel.
3. Mit reinem Zählrauschen ist die Summe zu ruhig, der Simulator braucht Rauschen auf mehreren Ebenen, sonst verschwindet die Falle "total only -3 %".
4. Die Streuung je Wochenstunde aus vier Punkten ist zu schwach, sie wird aus den Residuen aller Stunden geschätzt.

Die Probe bestätigt zugleich die Kernbausteine: Belege mit festem Stand liefern beim Re-Run denselben Hash, LMDI zerlegt exakt (Rest 3e-13), die Segmentsuche über alle 15 Kombinationen dauert 0,4 Sekunden, der Holdout-Check verwirft das Release, und die gebrochene Identität zeigt den Datenstau.

**Was offen ist (6.3).**
Neun Entscheidungen, auf dem Board als D1 bis D9: die fünf Fragen der Vision (D1 bis D5), die Frist (D6), die Sichtbarkeit des Repos zur Abgabe (D7), Rollen und Schlafschichten (D8) und der Arbeitsmodus im Repo (D9).
Bis eine Antwort vorliegt, gilt im Plan jeweils die Empfehlung.

## 1. Auftrag, Vorgehen und Kern der Vision

### 1.1 Auftrag

Das Team will die beste Plattform im Almedia-Track bauen, über dem Durchschnitt, mit allem, was dazugehört, und orientiert an Firmen, die das Problem schon gelöst haben.
Es sind vier Personen und eine Flotte von Coding-Agenten, die Arbeitslast ist groß und muss durchgeplant werden.
Geliefert werden: Reverse Engineering realer Produkte (Abschnitt 2), eine priorisierte Feature-Liste (3), ein Bauplan mit Schnittstellen, Repo-Struktur, Tech-Stack und Zeitplan (4) und Antworten auf die fünf offenen Fragen der Vision (5).

### 1.2 Vorgehen

1. Vision vollständig gelesen: 38 Seiten, davon 30 mit Inhalt, die Seiten 31 bis 38 sind leer.
   Zusätzlich den Text mit `pdftotext -layout` gezogen, weil die Tabellen im Seitenbild rechts abgeschnitten sind.
2. Abschnitt 12 und die Befunde zu Zeitplan und Kairos (2.2, 6.2, 6.3) des früheren Berichts gelesen.
3. Sechs parallele Recherchen mit Websuche und Seitenabruf: Infrastruktur-AI-SRE, Anbieter für Geschäftsmetriken, Product Analytics und BI, Datenbeobachtung und Experimente, interne Systeme großer Tech-Firmen samt Algorithmen, sowie Frist und Tech-Stack.
   Jede Aussage trägt eine geöffnete Quelle oder ist als Annahme markiert.
4. Kairos nur lesend geprüft (`gh-axi api` auf `BatuCani/kairos-studio`): Lizenz, Chart-Dateien, Schnittstelle von `TimeChart`.
5. Technik-Probe im Wegwerf-Arbeitsverzeichnis für die riskantesten Bausteine (Abschnitt 7.4).
6. Plan, Feature-Liste und Antworten aus Vision, Rubrik und Recherche abgeleitet.

### 1.3 Kern der Vision

- **These.**
  Jeder Monitor sagt, dass sich etwas geändert hat, Argus sagt wo, warum, was es gekostet hat, wie sicher es ist und was es ausgeschlossen hat.
- **Fünf Rollen.**
  Watcher (nur Statistik), Investigator (festes Verfahren, dann Planer), Skeptic (eigener Kontext, sieht nur Belege), Cartographer (Platzierung, Kantentests, Drift), Narrator (Bericht mit Zahlenprüfung).
- **Graph.**
  Knoten sind additiv, Quotient oder abgeleitet.
  Vier Kantenarten tragen vier Arten von Schlüssen: Formel (exakte Zerlegung), Aufschlüsselung (wo), Ursache (nächster Schritt, immer nur möglich), Evidenz (Zustandsänderung als erste Ursache).
- **Selbst-Erweiterung.**
  Eine Metrik kommt als Datei oder Klartext und durchläuft sieben Schritte bis zum Zertifikat.
- **Beobachten.**
  `attention = business_weight × surprise × data_confidence × novelty`, Erwartung aus der gleichen Wochenstunde der letzten vier Wochen mal geplantem Effekt, robuste z-Werte, CUSUM.
- **Untersuchen.**
  Feste Eröffnung in fünf Schritten, dann Hypothesen-Ledger mit Vorhersage vor jeder Abfrage, dann Skeptic.
  Fünf Urteile: `SUPPORTED CAUSE`, `HYPOTHESIS`, `EXPECTED`, `DATA ISSUE`, `UNEXPLAINED`.
- **Welt.**
  MockMart, ein kausaler Simulator mit zehn Szenarien (sieben Fehler, zwei harmlose, ein Datenproblem) und getrennter Wahrheit.
- **Beweis.**
  Argus Bench mit Baselines, pass@1 und pass^k.
- **Acht Prinzipien.**
  Zahlen kommen aus Abfragen, Stille ist ein Feature, Daten vor Geschäft, jede Kante beweist sich, erst vorhersagen dann schauen, sagen was man nicht weiß, läuft ohne Sprachmodell, vorschlagen statt handeln.
- **Anti-Ziele.**
  Das Modell rechnet oder erfindet eine Zahl, ein einstudierter Glücksfall, dasselbe Problem jede Stunde, schöne Oberfläche auf flachem Kern, ungemessenes Vertrauen.

### 1.4 Was die Vision offen lässt und dieser Bericht ergänzt

| Lücke in der Vision | Ergänzung | Wo |
| --- | --- | --- |
| kein Bauplan ("vision only") | Lanes, Verträge, Pakete, Zeitplan | 4 |
| "re-runs it and shows the matching hash" bei verspäteten Daten | fester Stand `as_of` in jeder Abfrage, kanonischer Hash | 4.4 |
| verspätete und teilweise Daten ohne Mechanik | Mikro-Batches mit `ingested_at` | 4.4 |
| 360 Segmente mit kleinen Zählwerten | Volumen-Stufen und Varianzuntergrenze | 4.4 |
| Logs als Evidenz, aber keine Köder | laufend harmlose Deploys, Budgets, Experimente | 4.4 |
| Tempo x1800 gegen 90 Sekunden Untersuchung | Untersuchung auf `as_of`, Uhr bremst im Demo-Modus | 4.4 |
| Blind Challenge ohne Absicherung | Go/No-Go über die Bench, Commitment mit Nonce, Rückfall-Leiter | 5.3 |
| Zahlen im Landschaftsteil teils unbelegt | Korrekturliste | 6.2 |
| Beispielmetrik mit Join-Fan-out | Fan-out-Wächter mit Reparatur-Diff | 4.4, 7.4 |
| Segmentsuche stoppt zu früh | Abstiegsregel über ungleich betroffene Kinder | 4.4, 7.4 |
| Streuung aus vier Punkten je Wochenstunde | Residuen aller Stunden, Untergrenze aus Zählstatistik | 4.4 |

## 2. Reverse Engineering realer Produkte

Untersucht wurden 22 Produkte und interne Systeme in fünf Gruppen, dazu die veröffentlichten Algorithmen zur Segmentsuche.
Jede Aussage in 2.5 bis 2.9 trägt eine geöffnete Quelle oder ist als "Annahme" oder "nicht verifiziert" markiert.
Zahlen von Herstellern sind Herstellerangaben, fast keine ist unabhängig geprüft.

### 2.1 Überblick: was jedes Produkt kann und was Argus daraus macht

| Produkt | Was belegt ist | Für Argus übernehmen | Wo Argus besser ist |
| --- | --- | --- | --- |
| Datadog Bits AI SRE | Hypothesenbaum, dann ReAct, heute Code-Ausführung über MCP; rund 4 USD und 2 Minuten je Untersuchung (zum Start 25 USD und 11 Minuten) | Zähler für Kosten, Zeit und Abfragen; ein Werkzeug, das mehrere Abfragen korreliert; Regressionstest mit bekannten Ursachen | exakte Zerlegung statt Raten, Fehlgriffe offen gezeigt |
| Traversal | "Causal Search Engine" mit Evidenzkette; fünfstufige Bewertung, die sichere Fehlurteile mit 0 wertet | die fünf Stufen als Bewertung der Bench; Daten vor dem Modell verdichten | offen statt Black Box |
| Causely | kausales Modell über Topologie, abduktive Inferenz, Test auf gesunden Systemen | typisierte Antwort "keine aktive Ursache", ruhige Kontrollfälle | Graph erweitert sich selbst |
| Resolve.ai | parallele Hypothesen, Pflicht zum Evidenz-Zitat, Gegenprüfung durch zweiten Agenten; Werkzeuge auf den Alarmzeitpunkt eingefroren | Evidenzpflicht, Skeptic, fester Stand `as_of` | An-Aus-Vergleich des Prüfers live |
| Anodot | Modell je Metrik, Score 0 bis 100 aus Abweichung und Dauer, Korrelation zu Incidents, Trichter 4 Mio. Metriken zu 147 Incidents | Trichter im Ticker, Score gegen die eigene Geschichte, Residuen vor jeder Korrelation | geprüfte Kanten statt gelernter Topologie |
| Outlier | tägliche "Stories", 2022 eingestellt (Team zu SoundCommerce) | wenige, hart gerankte Befunde je Tag | Befund mit Prüfung und SQL |
| Sisu | Key-Driver-Analyse mit "Smart Waterfall", Methode der "statistischen Garantie" nicht offengelegt | Wasserfall ohne Überlappung, Segmentsuche nach dem Muster von BigQuery `AI.KEY_DRIVERS` | Mehrfachtest-Korrektur offen ausgewiesen |
| Pecan | Vorhersagen auf Kundenebene, für Monitoring kaum relevant | höchstens Prognose als Erwartung (Stretch) | anderer Fokus |
| Amplitude | Agentenfamilie seit 17.02.2026 mit Dashboard-Monitoring-Agent; Anomalien über Prophet-Bänder; RCA scannt Properties in 30er-Schritten | Erwartungsband, Feiertage und Releases als Kontext, Budget beim Scannen | Schwellen und Belege sichtbar, Formelzerlegung |
| Mixpanel | Metric Trees, KI-Entwurf ohne Projektdaten (17.03.2026), RCA in vier Schritten, Vertrauen als Modell-Etikett; die RCA nutzt die Trees laut Doku noch nicht | Anomalie-Gate, Beitragsfaktor, Lift | Kanten gegen Daten geprüft, Untersuchung läuft über den Graphen |
| Loops, Salesforce | KPI-Überwachung mit "causal models", Übernahme am 12.10.2026 angekündigt, am 02.11.2026 abgeschlossen; Methodik nicht öffentlich | Erklärung als nach Wirkung gerankte Faktoren, Gegenprobe "ohne Segment X" | Rechnung und Hypothese sichtbar getrennt |
| Tableau Pulse | Katalog von Insight-Typen, deterministische Modelle, Modell nur für die Zusammenfassung; "Concentrated Contribution" ab 50 % | Detektor-Katalog, Rang nach Wirkung vor dem Modell | geht bis zur geprüften Ursache |
| Monte Carlo | Monitore für Frische, Volumen, Schema; Troubleshooting Agent mit parallelen Hypothesen; Gruppierung über Lineage | feste Reihenfolge, Gruppierung über gemeinsame Quelltabelle, "als normal markieren" | Datenproblem und Geschäft im selben Urteil |
| Sifflet | drei Agenten (Sentinel, Sage, Forge), Rang nach Geschäftswirkung | Rollen trennen, Gedächtnis früherer Vorfälle | Skeptic und SQL je Zahl |
| Anomalo | Drift als Klassifikation "heute gegen früher", Gradient Boosting und SHAP, rund 10.000 Zeilen Stichprobe | Klassifikator als zweite Meinung zur Segmentsuche | Vollständigkeit vor Segmentursache |
| Snowflake | CoWork Automations sind zeitgesteuerte Berichte; Anomaly Detection mit Intervall 0,99; Top Insights mit Beitrag, relativem Beitrag, Wachstumsrate | Rückbestätigung bei Standing Orders, die drei Spalten, immer Ist, Erwartung und Band | bedingte Aufträge mit Daten-Gate |
| Eppo, Statsig | SRM-Prüfung (Chi-Quadrat, p < 0,01), sequenzielle Tests, CUPED, "Copy SQL" bei Datadog Experiments | SRM-Prüfung gegen Teil-Ladungen, sequenzieller Alarm, SQL an jeder Zahl | auf jede Geschäftsmetrik angewandt |
| Uber uVitals | Würfel über Millionen Kombinationen, Modell je Slice, Volumen-Stufen (232 auf 11 Anomalien), Feedback-Link | Volumen-Stufen, Zustand neu oder andauernd, Feedback erzeugt Regeln | ein Incident statt vieler Slices |
| LinkedIn ThirdEye | Heatmap mit drei Änderungsmaßen, Top-Contributor-Würfel, Feiertage nach Nähe gerankt | drei Maße je Segment, Rest "OTHER", Kalender je Land | exakte Zerlegung statt Score-Heuristik |
| Airbnb Minerva | Definitionen als geprüfter Code mit Pflichtangaben (nur aus Suchtreffern) | Knotenschema, Status Entwurf bis validiert | Kanten werden entdeckt und geprüft |
| Netflix Kayenta, Telltale | Mann-Whitney-U mit Toleranzband, Urteil Pass, Marginal, Fail, "Nodata" als Zustand | "keine Daten" als eigener Zustand, Urteil für die Wirkung einer Maßnahme | Ursache mit geprüfter Kante belegt |
| Meta DrP | rund 2.000 Analyzer, 50.000 Analysen je Tag, Backtesting vor dem Einsatz | Schritte als kleine Playbooks, Backtest neuer Monitore | Playbooks entstehen aus dem Graphen |

### 2.2 Belege für die Kernentscheidung "Verfahren vor Modell"

| Aussage | Befund | Quelle |
| --- | --- | --- |
| Festes Verfahren schlägt freies Planen | 64,01 % gegen 35,50 % für ReAct | Flow-of-Action, arXiv 2502.08224 |
| Frei planende Agenten finden Ursachen selten | beste Agenten 10,0 % (schwer) und 25,3 % (mittel), 1.079 Aufgaben, 195 Kontrollfälle | ORCA-bench, arXiv 2607.28545 |
| Agenten erfinden Vorfälle auf gesunden Systemen | ohne kausale Schicht 67 % erfundene Vorfälle bei einem Agenten, mit ihr 0 % (sehr kleine Stichprobe) | Causely, arXiv 2605.18327 |
| Kosten sind ein Qualitätsmerkmal | 25 USD auf rund 4 USD, 11 Minuten auf rund 2 Minuten | Datadog, Blog vom 02.11.2026 |
| Werkzeuge auf den Alarmzeitpunkt einfrieren | Training und Bewertung ohne Blick in die Zukunft | Resolve.ai SRE-1, 18.11.2026 |

### 2.3 Übernahmen, nach Wirkung je Stunde

| Rang | Übernahme | Vorbild | Paket | Aufwand |
| --- | --- | --- | --- | --- |
| 1 | Feste Eröffnung vor jedem Modellaufruf | Flow-of-Action, Monte Carlo | B3 | ohnehin geplant |
| 2 | Ruhige Kontrollwochen, Antwort "nichts ist kaputt", Fehlalarmrate als eigene Zahl | Causely, ORCA-bench | W7, B3 | 2 Ah |
| 3 | Segmentsuche: Erklärungsanteil und Überraschung, erschöpfend über alle Kombinationen, mit Abstiegsregel | Adtributor, RiskLoc | B2 | 2 bis 3 Ah |
| 4 | Volumen-Stufen für Segmente | Uber uVitals | B1 | 1 Ah |
| 5 | Urteil trennt Datenverspätung, Datenbruch und echte Änderung, Frische zuerst | Lücke bei allen | B1, B3 | 1 bis 2 Ah |
| 6 | Kosten, Zeit und Abfragen im Bericht, SQL an jeder Zahl | Datadog | B6, U5 | 1 bis 2 Ah |
| 7 | Skeptic mit An-Aus-Vergleich in der Bench | Resolve.ai | B5, W7 | 3 Ah |
| 8 | Trichter im Ticker: Reihen, Wackler, Anomalien, Incidents | Anodot | B1, U1 | 1 Ah |
| 9 | Vertrauen aus Prüfungen berechnen | Gegenstück zu Mixpanel | B3 | 1 Ah |
| 10 | Fünf Stufen in der Bench, sichere Fehlurteile zählen 0 | Traversal | W7 | 1 Ah |
| 11 | SRM-artige Prüfung der Segmentanteile | Statsig | B1 | 1 Ah |
| 12 | Standardspalten je Segment: Änderung in Prozent, Beitrag in Punkten, Anteil an der Gesamtänderung, Rest "OTHER" | ThirdEye, Snowflake Top Insights | B2, U5 | 1 Ah |
| 13 | Zustand neu, andauernd, wiederholt am Incident | uVitals | B7 | 0,5 Ah |
| 14 | Rückbestätigung des verstandenen Auftrags als JSON | Snowflake CoWork | G7 | 2 Ah |
| 15 | Gegenprobe "wie viel bliebe, wenn dieser Wert konstant wäre" | ThoughtSpot | B2 | 1 Ah |

### 2.4 Neue Belege für den Pitch

Diese Sätze sind durch geöffnete Quellen gedeckt und stärker als die Formulierungen der Vision.

1. Mixpanel hat einen Metric Tree und einen RCA-Agenten, aber laut eigener Doku nutzt die RCA den Tree noch nicht: "RCA reasons only over events and properties. It doesn't yet use annotations, session replays, experiments, or metric trees."
   Bei Argus ist die Untersuchung ein Lauf über den Graphen.
2. Mixpanels Vertrauensstufen sind laut Doku "labels the AI assigns, not calculated numbers".
   Bei Argus ist Vertrauen berechnet und kalibriert.
3. Der KI-Entwurf des Mixpanel-Baums nutzt laut Doku keine Projektdaten.
   Bei Argus trägt jede Kante einen Test gegen die Daten.
4. Tableau Pulse beantwortet laut Doku beschreibende Fragen ("designed to help users answer descriptive questions about their metrics").
5. Snowflake CoWork Automations sind laut Doku "Scheduled reports only".
6. Uber berichtet, dass 95 % der Anomalien eines Monitors Rauschen waren, bevor Volumen-Stufen eingeführt wurden.
7. Datadog hat die Kosten je Untersuchung in einem Jahr von 25 USD auf rund 4 USD gesenkt, Argus zeigt seine Kosten in jedem Bericht.
8. Der Segment-Schritt von Argus folgt demselben Muster wie BigQuery `AI.KEY_DRIVERS` und lässt sich deshalb auf ein BigQuery-Warehouse übertragen.

### 2.5 Wo Argus besser ist als alle untersuchten Produkte

1. Kanten werden gegen Daten geprüft und tragen einen Status.
   Mixpanel bietet optional eine Korrelation je Kante, sonst prüft keiner der untersuchten Anbieter.
2. Die exakte Zerlegung entlang der Formel ist von Ursachenhypothesen getrennt.
3. Datenverspätung, geplantes Ereignis und echte Änderung stehen im selben Urteil.
4. Vertrauen wird berechnet und kalibriert.
5. Die Trefferquote ist veröffentlicht und aus einem Seed reproduzierbar, einschließlich eines ehrlichen Fehlgriffs.
6. Eine neue Metrik bringt ihren Platz, ihre Tests und einen Fan-out-Befund selbst mit.

### 2.6 Einzelbefunde: Infrastruktur-AI-SRE und Benchmarks


Stand: 2026-11-21.
Alle Zahlen sind Herstellerangaben, sofern nicht anders vermerkt.
Zeitbudget war knapp: Es wurden nur die unten gelisteten Seiten geöffnet, keine PDFs im Volltext.

#### Datadog Bits AI SRE (Bits Investigation)

- **Was es ist:**
  Datadogs always-on AI SRE, der bei einem Alert Hypothesen bildet, Telemetrie abfragt und eine Ursache mit Evidenz liefert.
  Neueste Releases: Scout 1.0 (Blog vom 2026-10-15, Closed Preview) und der Kosten/Speed-Post vom 2026-11-02.
- **Architektur:**
  Generation 1 war ein koordiniertes Multi-Agent-System mit Hypothesenbaum: Kontext sammeln, initiale Untersuchung mit gezielten Telemetrie-Queries, Hypothesen iterativ erzeugen und testen, vielversprechende Hypothesen zu spezifischeren Kindern erweitern.
  Generation 2 war ein ReAct-Design (Agent wählt Tool, liest Ergebnis, entscheidet den nächsten Schritt), Kosten laut Post etwa $6.50.
  Aktuell schreibt und führt Bits über den Datadog MCP Server Code aus, der mehrere Datenquellen in einem Tool-Call abfragt und korreliert, damit weniger Kontext ans Modell geht.
  Zusätzlich gibt es Scout, ein SRE-Modell (Basis GLM-5.3 Flash, Reinforcement Learning in Simulationen mit historischen Incidents mit bekannter Ursache; Reward für Ursachenfund und evidenzgestützte Schlüsse).
  Der Post nennt weder parallele Ausführung noch Memory explizit; die Produktseite sagt nur, Bits "learns from each investigation over time".
- **Algorithmen:**
  Hypothesen erzeugen, Telemetrie abfragen, prüfen ob die Evidenz die Hypothese trägt, Baum erweitern (Gen 1).
  Stopp und Konfidenz sind nicht beschrieben (nicht verifiziert).
  Evaluation: interner Benchmark mit bekannten Root Causes vergangener Incidents; AlertEval mit tausenden expertenkuratierten Punkten, Score 0-100 als Übereinstimmung mit Experten-Erklärungen, nicht "Anteil gelöster Incidents".
  Drittbenchmark SREGym wird erwähnt.
- **UX-Muster:**
  Produktseite wirbt mit "transparent, verifiable investigations", Integration in Slack, Jira, ServiceNow, GitHub, und mit Multi-Alert-Handling.
  Investigation-View, Hypothesen-Anzeige, Inconclusive-Zustand und Feedback-Buttons sind auf den geöffneten Seiten nicht beschrieben (nicht verifiziert).
- **Genauigkeit und Fehler:**
  Exakt: Kosten $25 beim Launch (Dez 2025) auf etwa $4 (-84%), Zeit 11 Min auf etwa 2 Min (-82%), "investigation quality score" 44% höher als im März-2026-Release, Stand Oktober 2026.
  Die Pitch-Zahlen ($4, 2 Min) sind damit bestätigt.
  Der Qualitätsscore ist intern und nicht extern prüfbar.
  Scout 1.0 medium entspricht laut Datadog GPT-6.1 Sol high und Claude Opus 5.5 high bei 3-8x geringeren Kosten (AlertEval, intern).
  Fehlermodi und Halluzinationsraten werden nicht genannt.
- **Für Argus übernehmen:**
  1. Kosten- und Zeitzähler pro Investigation im Report (Tokens, Queries, Sekunden) als sichtbare Metrik; das Narrativ "$25 auf $4" zeigt, dass Kosten ein Qualitätsmerkmal sind.
  2. Ein Tool, das Code (SQL/Python) ausführt und mehrere Abfragen in einem Call korreliert, statt vieler kleiner Tool-Calls.
  3. Eigene Mini-Eval: vergangene Anomalien mit bekannter Ursache (seeded) als Regressionstest für den Agenten.
- **Besser machen:**
  Datadog ist telemetrie-zentriert; Argus zerlegt Business-Metriken exakt (LMDI, Mix vs. Rate), das ist deterministisch statt LLM-geraten.
  Argus macht jede Zahl per SQL-Link prüfbar und veröffentlicht Fehlerfälle offen.
- **Quellen:**
  https://www.datadoghq.com/blog/bits-investigations-cost-speed-accuracy/ (2026-11-02)
  https://www.datadoghq.com/blog/ai/introducing-scout-sre-specialized-model-bits-ai (2026-10-15)
  https://www.datadoghq.com/product/bits-ai-sre (kein Datum sichtbar)

#### Traversal

- **Was es ist:**
  AI-SRE-Plattform, gegründet aus kausaler-ML-Forschung (Anish Agarwal ist Co-Autor von ORCA-bench).
  Series B über $120M bei $1B Bewertung, angekündigt 2026-11-03 (laut Suchergebnis citybiz/Sacra; die Seite selbst wurde nicht geöffnet, daher nicht verifiziert).
- **Architektur:**
  Laut Traversal-Seite: agentless Datenerfassung (read-only), "Causal Indexer" komprimiert Telemetrie etwa 1000:1 unter Erhalt des kausalen Signals, "Production World Model" als live kausales Modell, "Knowledge Bank" mit Runbooks, Docs und vergangenen Incidents, "Causal Search Engine" testet parallel viele Hypothesen über 10 oder mehr Dependency-Hops und liefert "one causally consistent diagnosis with its evidence chain and a remediation path".
  Was deterministisch und was LLM ist, wird nicht beschrieben (nicht verifiziert).
- **Algorithmen:**
  Details zu Hypothesengenerierung, Stopp und Konfidenz sind nicht öffentlich auf den geöffneten Seiten.
  Es gibt eine fünfstufige, konfidenzgewichtete Bewertungs-Rubrik für AI-SREs: Bulls-Eye 100%, Directional 75%, Good Triage 50%, Partial Miss 25%, Misleading 0%; volle Punkte nur, wenn die Antwort "both correct and highly certain" ist.
  Das ist eine konkrete Scoring-Idee, die Falschheit mit Sicherheit bestraft.
- **UX-Muster:**
  Oberflächen: Web, Slack, Teams, MCP, API; Evidence Chain plus Remediation-Pfad; Menschen prüfen und entscheiden.
  Inconclusive-Zustand nicht beschrieben.
- **Genauigkeit und Fehler:**
  "Over 82% RCA accuracy in under 5 minutes" bei einem Fortune-100-Finanzkunden und "around a 40% reduction in MTTR" (Traversal-Seite, ohne Methodik).
  Suchzusammenfassungen nennen zusätzlich ">90%" und "85% MTTR-Reduktion"; auf geöffneten Seiten nicht bestätigt, nicht verifiziert.
  Traversal ist Mitautor von ORCA-bench, das zeigt, dass Frontier-Agenten ohne Spezialsystem schwach sind (siehe unten).
- **Für Argus übernehmen:**
  1. Die 5-Tier-Rubrik als Eval-Skala für Argus-Reports, inklusive Strafe für sichere Falschaussagen.
  2. "Causal Indexer"-Idee: vor dem LLM die Daten zu einem kompakten, kausal relevanten Digest verdichten (bei uns: LMDI-Beiträge, Top-Segmente).
  3. Evidence Chain als ein Pfad Symptom zu Ursache im Report.
- **Besser machen:**
  Traversal ist Black Box; Argus zeigt die Kante für Kante validierte Metrikgraph-Kette und einen Skeptic-Agent.
- **Quellen:**
  https://www.traversal.com/blog/how-should-you-evaluate-an-ai-sre-product (kein Datum sichtbar, Nov 2026 Umfeld)
  https://www.traversal.com/blog/ai-sre-accuracy-and-speed (kein Datum sichtbar)
  https://arxiv.org/abs/2607.28545 (2026-07-30)
  Nur über Suchergebnis (nicht geöffnet): https://www.citybiz.co/?p=929066

#### Causely

- **Was es ist:**
  Kausales Modell über Topologie für SRE; arXiv-Whitepaper 2605.18327 existiert, eingereicht 2026-05-18, "Causely: A Causal Intelligence Layer for Enterprise AI: A Benchmark Study on SRE and Reliability Workflows" (Dalal, Sara, Yemini, Miller, Kliger).
- **Architektur:**
  Vier Strukturen: Topology Graph (Entities mit Connectivity-, Layering-, Containment-Relationen), Causal Knowledge Base (umgebungsunabhängige Root-Cause/Symptom-Paare plus Propagationsregeln), Causality Graph (umgebungsspezifischer DAG, Kanten mit P(symptom | root cause)), Attribute Dependency Graph (Latenz, Durchsatz, Auslastung mit funktionalen Abhängigkeiten, vordefiniert oder gelernt).
  LLM-Agenten fragen dieses deterministische Modell ab; das Modell selbst ist proprietär.
- **Algorithmen:**
  Abduktive Inferenz: r* = argmax P(r | S+) über aktive Symptome S+, faktorisiert als P(S+ | r) P(r) unter bedingter Unabhängigkeit.
  Ownership als Projektion der betroffenen Entities auf Team-Besitz.
  Konfidenz: Formalismus mit Wahrscheinlichkeiten, aber keine Kalibrierung oder Margen im Benchmark berichtet.
- **UX-Muster:**
  Im Paper nicht Thema (nicht verifiziert).
- **Genauigkeit und Fehler:**
  Aktive-Fault-Szenario (24-Service-OTel-Demo, Kind-Cluster): Time-to-Diagnosis -63%, Tokens -60%, Tool-Calls -78%, API-Kosten -57%, Footprint 4.8x kleiner, Root-Cause-Accuracy 75% auf 100%.
  Healthy-Baseline (halluzinierte Incidents): HolmesGPT mit Sonnet 67% auf 0%, Codex 67% auf 33%, Claude Code und HolmesGPT mit Gemini 0% in beiden Bedingungen.
  Ohne Causely brauchten Baseline-Agenten bis zu 7.2x mehr Tokens auf dem gesunden Cluster als auf dem fehlerhaften.
  Eigene Grenzen laut Paper: nur eine Fehlerklasse (Application-Code-Bug), sehr kleine Stichprobe (6 Queries pro Active-Zelle, 3 pro Healthy-Zelle), keine Konfidenzintervalle, Herstellerautoren.
  Wichtig für den Pitch: Das Paper beschreibt keinen expliziten Abstain-Mechanismus; "no active root cause" ist ein typisiertes negatives Ergebnis.
  Die Annahme "Causely abstains when evidence is weak" ist damit nur indirekt gestützt.
- **Für Argus übernehmen:**
  1. Typisiertes "kein aktiver Root Cause"-Ergebnis plus Healthy-Baseline-Test (Anomalie-freie Tage als Kontrollfälle, False-Incident-Rate messen).
  2. Metrikgraph mit Kantenwahrscheinlichkeit P(Symptom | Ursache), gespeichert pro Kante und aus Daten geschätzt.
  3. Posterior-Ranking der Kandidaten statt Einzelantwort.
- **Besser machen:**
  Causely braucht Topologie und eine feste Wissensbasis; Argus erweitert den Graphen selbst (Self-Extension) und validiert jede neue Kante an Daten.
  Argus kann echte Abstention mit Begründung ausgeben ("inconclusive, weil Skeptic X nicht widerlegen konnte").
- **Quellen:**
  https://arxiv.org/abs/2605.18327 (2026-05-18)
  https://arxiv.org/html/2605.18327 (gleiche Arbeit, Volltext-Zusammenfassung)

#### Resolve.ai

- **Was es ist:**
  Multi-Agent-AI-SRE; Series A $125M bei $1B Bewertung (Lightspeed) laut VentureBeat vom 2026-05-21, nicht $1.5B.
  Neuestes Release: SRE-1, eigenes Modell, Pressemitteilung 2026-11-18.
- **Architektur:**
  Agenten verfolgen mehrere Hypothesen parallel, jeder muss Evidenz zitieren und "to another agent for independent review" vorlegen; Peer-Agenten versuchen die Theorie zu widerlegen (VentureBeat 2026-05-21).
  SRE-1: 27B-Modell auf offenen Gewichten, reines Reinforcement Learning, alle Trainings-Tools auf den Zeitpunkt des Alerts eingefroren, damit das Modell keine Zukunftsinfo sieht.
  Primary On-call untersucht Telemetrie, Infrastruktur, Code und Betriebswissen und protokolliert Untersuchungen und Entscheidungen für Review.
- **Algorithmen:**
  Hypothesen parallel, Evidenz-Zitat-Pflicht, Widerlegungsversuch durch Peer-Agent, Kausalkette von Root Cause bis Symptom.
  RL: Pass-Rate einer einzelnen Investigation stieg von 6.9% auf 38.8% (49 schwierige Live-Fälle, je 5 Läufe, gleiche Tools).
  Ein Ensemble aus 5 SRE-1-Läufen erreicht das stärkste getestete Frontier-Modell bei geringeren Kosten.
- **UX-Muster:**
  Investigations und Entscheidungen werden für Engineer-Review aufgezeichnet; Slack-Details nicht aus den geöffneten Seiten belegt (nicht verifiziert).
- **Genauigkeit und Fehler:**
  Der "Verifier verdoppelt Genauigkeit"-Claim ist so nicht sauber belegt.
  VentureBeat (2026-05-21): "more than a twofold improvement in root cause accuracy" auf internen Benchmarks, CEO Xanthos: "has improved quality by 2x"; es wird nicht gesagt, dass die Verifier allein die Ursache sind, und es ist keine Drittprüfung.
  SRE-1-Pressemitteilung (2026-11-18): "solved about twice as many incidents" wie General-Purpose-Coding-Agenten auf 178 Produktions-Alerts gegen verifizierte Root Causes, Baseline ist also ein anderer Vergleich als "vorherige Version".
  Auf dem härtesten Drittel 15-25% höherer Score; "up to 95% root-cause accuracy" in Produktion (Herstellerangabe).
  Die SRE-1-Meldung erwähnt Verifier-Agenten nicht.
- **Für Argus übernehmen:**
  1. Pflicht zur Evidenzzitierung pro Hypothese (Argus: SQL-Link), ohne Zitat keine Aufnahme ins Ledger.
  2. Skeptic als eigener Agent mit anderem Prompt und möglichst anderem Modell.
  3. "Tools auf Alert-Zeitpunkt einfrieren": Datenabfragen nur bis zum Anomalie-Zeitstempel, verhindert Leakage in Evals.
- **Besser machen:**
  Resolve nennt keine Ablation des Verifiers; Argus kann das live zeigen (Report mit und ohne Skeptic, Widerlegungsrate).
- **Quellen:**
  https://venturebeat.com/technology/resolve-ai-says-the-ai-coding-boom-is-breaking-production-systems-it-wants-to-fix-that (2026-05-21)
  https://venturebeat.com/business/resolveai-launches-sre-1-the-most-accurate-model-for-production-at-every-budget (2026-11-18)

#### Benchmark-Belege

- **OpenRCA (ICLR 2025), "bestes ca. 11%":**
  Bestätigt mit Einschränkung.
  Laut Suchergebnis zur Leaderboard liegt der Top-Wert bei 11.34% "Correct" (RCA-Agent mit Claude 3.5 Sonnet), 17.31% "Partial"; 335 Failures, 68 GB Telemetrie.
  Die Primärseite https://microsoft.github.io/OpenRCA lieferte beim Fetch keinen Inhalt, die Zahl stammt also aus einer Suchzusammenfassung (nicht selbst am Original gesehen).
  Das Leaderboard kann sich seit 2025 geändert haben; mit Datum "ICLR 2025" zitieren.
  Quelle: https://proceedings.iclr.cc/paper_files/paper/2025/file/d29b8d53678015079e1d245c023e49d2-Paper-Conference.pdf (nur in Suche gesehen)
- **ORCA-bench (2026), "10-25%, Halluzination über 40%":**
  Teilweise anders.
  Geöffnet: https://arxiv.org/abs/2607.28545, eingereicht 2026-07-30, v3 2026-09-29, Cornell Tech/Traversal/Columbia.
  Bester Wert: 25.3% RCA-Accuracy auf Medium und 10.0% auf Hard (1,079 Aufgaben, OTel-Demo).
  Halluzination: "der schwächste Modell" schlägt in 40% der Incident-Reports eine unplausible Ursache vor; laut Suchzusammenfassung reicht die Spanne von 7% bis 40%, also nicht "über 40%" und nicht für alle Modelle.
  Korrekte Formulierung: "beste Agenten 10% (hard) bis 25% (medium); das schwächste Modell halluziniert in 40% der Reports".
  Zusatzbefund: Ohne Source-Code-Zugriff sinkt die Accuracy für jedes Modell; Agenten "locken auf das lauteste Symptom" (Suchzusammenfassung).
  Es gibt 195 Kontrollfälle ohne Fehler, passend zu unserer Abstention-Story.
- **Flow-of-Action, "35% auf 64%":**
  Bestätigt.
  https://arxiv.org/abs/2502.08224, eingereicht 2025-02-12, WWW'25 Industry Track: 64.01% gegenüber 35.50% für ReAct.
  Einschränkung: gemessen auf Root-Cause-Lokalisierung in einem industriellen Setting (nicht OpenRCA); SOPs als feste Prozedur, Hilfsagenten für Rauschfilter, Suchraum-Einengung und Stopp-Urteil.

#### Top-Übernahmen für Argus

Rangfolge nach Wirkung pro Stunde.

1. **Evidenz-Zitat-Pflicht plus Skeptic als eigener Agent** (Resolve): jede Hypothese im Ledger braucht SQL-Link; Skeptic versucht Widerlegung; Ablation "mit/ohne Skeptic" als Demo-Slide (ca. 3 h).
2. **Healthy-Baseline-Kontrollfälle und typisiertes "nichts los"-Ergebnis** (Causely, ORCA-bench mit 195 Kontrollen): False-Incident-Rate messen und zeigen (ca. 2 h).
3. **Deterministische Eröffnung als feste SOP** (Flow-of-Action 35.50% auf 64.01%): Freshness, Planned Event, LMDI, Mix-vs-Rate fest verdrahtet, LLM nur danach (ohnehin geplant, Belegzahl für den Pitch).
4. **Konfidenzgewichtete 5-Tier-Rubrik** (Traversal): Eval-Skala mit Strafe für sichere Falschaussagen; Report gibt Tier und "inconclusive" aus (ca. 2 h).
5. **Kosten-, Zeit- und Query-Zähler pro Investigation** (Datadog $25 auf $4, 11 auf 2 Min): Footer im Report (ca. 1 h).
6. **Zeit-Einfrieren der Abfragen auf den Alert-Zeitpunkt** (Resolve SRE-1): verhindert Leakage, macht die Seeded-Eval glaubwürdig (ca. 1 h).
7. **Seeded-Anomalie-Regressionstest mit bekannter Ursache** (Datadog interner Benchmark, SRE-1 178 Alerts): 10-20 injizierte Fälle, Trefferquote live zeigen (ca. 4 h).
8. **Kantenwahrscheinlichkeit P(Symptom | Ursache) und Posterior-Ranking** (Causely): pro Graphkante aus Daten schätzen, Kandidaten nach Posterior ordnen (ca. 3 h).

### 2.7 Einzelbefunde: Anbieter für Geschäftsmetriken


Stand: 2026-11-21.
Zeitbudget war knapp (ca. 20 Minuten), daher sind einige Punkte als "nicht verifiziert" markiert.
Quellen mit "(geöffnet)" habe ich selbst abgerufen und gelesen.
Quellen mit "(nur Suchtreffer)" habe ich nur als Suchergebnis-Auszug gesehen, die Seite selbst nicht geöffnet.

#### Anodot

- **Was es ist:**
  Anodot ist ein Produkt für autonomes Business-Monitoring (Anomalieerkennung auf Zeitreihen, Incident-Korrelation).
  Glassbox hat Anodot am 4. November 2025 von Dancap Private Equity übernommen (Business Wire, nur Suchtreffer; die Seite lieferte beim Abruf HTTP 403).
  Anodots eigene Seiten zeigen laut Suchtreffer den Hinweis "Anodot is now a Glassbox company".
  Die Annahme "Übernahme 2026" aus der Aufgabenstellung stimmt nicht, es war 2025, und Glassbox ist der Käufer.
  Status: lebt weiter, jetzt unter Glassbox.
- **Architektur:**
  Das White Paper (Teil 2 und 3, geöffnet) beschreibt eine Kette: Normal Behavior Learning, dann Abnormal Behavior Learning (Scoring), dann Behavioral Topology Learning (Korrelation), dann Incidents.
  Zusätzlich gibt es Feedback-basiertes Lernen als fünften Baustein.
  Jede eingehende Metrik durchläuft zuerst eine Klassifikationsphase, die sie einem Modelltyp aus einer "bank of model types" zuordnet.
  Die Modelle lernen online und adaptiv (jeder Datenpunkt aktualisiert das Modell, kein Batch-Training), damit sofort Ergebnisse da sind und das Modell mit Veränderungen mitwandert.
  Das Teil-3-Paper beschreibt einen Trichter für eine Woche: 4 Millionen Metriken, 158.000 gefundene Anomalien, 910 mit hohem Significance Score, 147 korrelierte Incidents.
- **Algorithmen:**
  - Modellauswahl pro Metrik: "A single model does not fit all metrics".
    Open-Source-Methoden gehen von glatten, regelmäßig gesampelten, stationären Metriken aus.
    Auf anderen Metriken entstehen laut Paper viele False Positives oder False Negatives, weil das falsche Modell passt.
  - Saisonalität: Anodot nennt als Beobachtung über Millionen Metriken, dass etwa 14 Prozent eine Saison haben und 86 Prozent keine.
    Von den saisonalen hatten 70 Prozent ein 24-Stunden-Muster und 26 Prozent ein Wochenmuster (Teil 2, geöffnet).
    Das ist eine Eigenaussage des Herstellers.
    Mehrere Saisons gleichzeitig (täglich plus wöchentlich) kommen vor und müssen modelliert werden.
    Verglichen werden Fourier-Transformation (schnell, aber schwach bei mehreren Saisons, empfindlich bei fehlenden Daten) und Autokorrelation (genauer, robuster; Anodot beansprucht "smart subsampling").
    Falsch angenommene Saison (z. B. 24h statt 7h) führt zu vielen False Positives.
  - Significance Score: Statistiken über Abweichung (deviation) und Dauer (duration) eines Ausreißers gehen in ein Modell, Ausgabe ist ein Score von 0 bis 100.
    Der Score ist relativ zu früheren Ausreißern derselben Metrik, nicht absolut.
    Laut Paper mit probabilistischen Bayes-Modellen umgesetzt.
    Anodot sagt, der Ansatz mit absoluter Abweichung sei anfangs benutzt und verworfen worden.
  - Der Significance-Slider ändert das Basismodell nicht, er filtert nur, was der Nutzer sehen will (Beispiel im Paper: Slider auf 70).
  - Korrelation zu Incidents (Teil 3): drei Methoden, nämlich Namensähnlichkeit der Metriken (Dimension=Wert-Namensschema), Ähnlichkeit des Normalverhaltens (Pearson, nur nach Trend- und Saison-Entfernung, sonst Scheinkorrelation) und Ähnlichkeit des Abnormalverhaltens (gleichzeitige Anomalien).
    Normalverhalten-Ähnlichkeit nennt Anodot selbst die schwächste Methode.
    Für Skalierung wird Locality Sensitive Hashing genutzt, um Metriken vorab in Gruppen zu teilen.
  - Multiples Testen wird im Paper nicht als solches adressiert (nicht verifiziert).
- **UX-Muster:**
  Significance-Slider pro Alert-Regel.
  Korrelierte Anomalien erscheinen als ein Incident statt vieler Einzelalarme.
  Feedback-basiertes Lernen ist als Baustein genannt, die genaue UI (Daumen o. ä.) habe ich nicht verifiziert.
  "Anomap" und eine "Why not alerted"-Erklärung habe ich in den geöffneten Quellen nicht gefunden (nicht verifiziert).
- **Genauigkeit und Fehler:**
  Das Paper räumt ein, dass die LSH-Gruppierung eine gewisse Wahrscheinlichkeit für False Positives und False Negatives hat, einstellbar durch Gruppengröße.
  Zum Trichter sagt das Paper ausdrücklich, er zeige nicht die Genauigkeit der Anomalien, sondern warum jeder Schritt nötig ist.
  Eine Anodot-Seite behauptet laut Suchtreffer bis zu 99 Prozent weniger Alarmrauschen durch Korrelation (Herstellerangabe, nicht geprüft).
  Unabhängige Kritik habe ich in der Zeit nicht gefunden.
- **Für Argus übernehmen:**
  - Trichter-Metrik im Report und im Demo: "N Roh-Anomalien, M über Schwelle, K Incidents".
  - Significance-Score relativ zur eigenen Historie der Metrik (Rang gegen frühere Ausreißer, Deviation mal Duration), nicht nur z-Score.
  - Vor jeder Korrelation Saison und Trend entfernen (Residuen korrelieren), sonst Scheinkorrelationen.
  - Incident-Gruppierung über Metrik-Graph-Kanten (formula/breakdown) statt Namensähnlichkeit; der Graph ist die bessere Topologie.
  - Modellklasse pro Metrik wählen (saisonal ja/nein) statt ein Modell für alle.
- **Besser machen:**
  Anodot lernt Topologie statistisch und ungeprüft, Argus hat validierte Graph-Kanten.
  Anodot erklärt nicht das Warum mit exakter Dekomposition, Argus liefert LMDI-Zerlegung und SQL-Belege für jede Zahl.
  Argus kann "Warum nicht alarmiert" explizit ausweisen (Score, Schwelle, geplantes Event).
- **Quellen:**
  - https://www.anodot.com/wp-content/uploads/2-Ultimate-Guide-to-Building-a-Machine-Learning-Anomaly-Detection-System-Part-2-Normal-Behavior-of-Time-Series-Data-22-New-Logo-2020-v2.pdf (geöffnet, per pdftotext gelesen, Datum nicht sichtbar)
  - https://em360tech.com/sites/default/files/migration_image/ID%20431%20Anodot%20Ultimate%20Guide%20To%20Building%20A%20Machine%20Learning%20Outlier%20Detection%20System%20Part%20III.pdf (geöffnet, Teil 3, Datum nicht sichtbar)
  - https://www.kdnuggets.com/2017/05/anodot-machine-learning-anomaly-detection.html (geöffnet, 25.05.2017, nur Teaser)
  - https://www.businesswire.com/news/home/20251104734652/en/Glassbox-Strengthens-Anomaly-Detection-With-Acquisition-of-Anodot (nur Suchtreffer, 04.11.2025)

#### Outlier (outlier.ai)

- **Was es ist:**
  Outlier AI war ein Startup aus Oakland für automatische Business-Analyse mit einem kurzen täglichen Briefing ("Stories").
  Gründer laut Suchtreffer: Sean Byrnes.
  Status: eingestellt.
  Am 10. Mai 2022 übernahm SoundCommerce Team und Führung von Outlier.ai (geöffnet: privsource-Dealseite).
  Ein Suchtreffer behauptet zusätzlich, DataRobot habe Outlier im Juli 2021 übernommen und es sei dort "Automated Business Monitoring"; das ist nicht bestätigt, nicht verifiziert.
  Nicht verwechseln mit dem heutigen "Outlier" von Scale AI (anderes Geschäft).
- **Architektur:**
  Nicht verifiziert im Detail.
  Laut Suchtreffer (Software Engineering Daily, 2018, CTO Mike Kim) bestand das Kernproblem darin, zehntausende mögliche Ausreißer auf eine für Menschen handhabbare Menge zu reduzieren.
  Ein Profil beschreibt eine Sammlung von Lernsystemen für Zeitreihenmodelle, Clustering und Empfehlungen.
  Ein Interview von 2021 nennt Erklärbarkeit als Grund, kein Deep Learning zu nutzen (nur Suchtreffer).
- **Algorithmen:**
  Nicht verifiziert.
  Die Medium-Seite zu den "Auto-Generated Data Stories" lieferte HTTP 403, das SED-Transkript habe ich nicht geöffnet.
- **UX-Muster:**
  Kurzes tägliches Digest als Hauptkanal.
  Story als Karte pro Befund (Details nicht verifiziert).
- **Genauigkeit und Fehler:**
  Keine öffentlichen Zahlen gefunden.
  Das Scheitern als eigenständiges Produkt (Team-Übernahme 2022) ist ein Hinweis, dass reine Insight-Feeds ohne Handlungsbezug schwer zu verkaufen waren; das ist Annahme, keine Quelle.
- **Für Argus übernehmen:**
  - Ein täglicher Digest mit wenigen, hart gerankten Befunden als Standardausgabe (Attention Budget als Obergrenze pro Tag).
  - Erklärbare Methoden statt Black Box, auch im Demo betonen.
- **Besser machen:**
  Outlier lieferte Stories, Argus liefert Stories mit Skeptiker-Prüfung und SQL pro Zahl.
- **Quellen:**
  - https://www.privsource.com/acquisitions/deal/wySk7w (geöffnet, 10.05.2022)
  - Suchtreffer: https://www.unite.ai/sv/sean-byrnes-co-founder-and-ceo-at-outlier-interview-series/ und https://softwareengineeringdaily.com/wp-content/uploads/2018/06/SED620-Outlier.pdf (nur Suchtreffer)

#### Sisu Data

- **Was es ist:**
  Sisu war eine Plattform für automatische Key-Driver-Analyse ("warum hat sich meine Metrik verändert").
  CEO und Gründer war Peter Bailis (TechTarget, geöffnet).
  Smart Waterfall Charts wurden im Mai 2021 vorgestellt (Suchtreffer).
  Ein Suchtreffer (yespress.io, Seite nicht geöffnet) sagt, Sisu sei im Oktober 2023 zu Snowflake gegangen und das Standalone-Produkt eingestellt worden.
  Status: nicht verifiziert gegen Snowflake-Quellen, aber konsistent mit der Annahme der Aufgabe.
- **Architektur:**
  Ein "Decision Engine" prüft Faktoren (Dimensionen und Segmente) hinter einer Metrikänderung, wählt die wichtigsten aus und stellt sie als Waterfall dar.
  Sisu überwacht Datensätze automatisch auf Änderungen und will erklären, nicht nur alarmieren (TechTarget, geöffnet).
- **Algorithmen:**
  - Sisus eigene Pressemitteilung behauptet laut Suchtreffer nur "höchste Wirkung, statistisch gültige Treiber" mit "statistischer Garantie".
    Test, Intervallmethode oder Konfidenzniveau sind öffentlich nicht beschrieben (nicht verifiziert).
  - Waterfall zeigt laut Suchtreffer den inkrementellen Beitrag gerankter Treiber unter Berücksichtigung überlappender Populationen.
  - Vergleichbar dokumentiert ist Googles BigQuery `AI.KEY_DRIVERS` (geöffnet, siehe unten), als öffentliches Ersatzmodell für den Sisu-Algorithmus (Annahme, dass Sisu ähnlich arbeitet).
  - Akademische Verwandte: DIFF/MacroBase (VLDB 2019, Apriori-artige Suche nach Attributkombinationen) und Scorpion (VLDB 2013), beide nur als Suchtreffer.
- **UX-Muster:**
  Interaktiver Waterfall.
  Nutzer können einen zusätzlichen Faktor ziehen, dann sortiert sich das Diagramm neu (Zitat Bailis laut TechTarget).
- **Genauigkeit und Fehler:**
  Analyst David Menninger (Ventana Research) laut TechTarget: "Analysts still need to apply the 'does this make sense' filter."
  Bailis sagt, volle Automatisierung "could take 10 years".
  Die Aussage "Kundenbasis vervierfacht" ist eine Herstellerangabe.
- **Für Argus übernehmen:**
  - Segmentsuche nach dem BigQuery-Muster: Support-Schwelle (Apriori), Pruning von Segmenten mit identischen Werten und Obermenge-Dimensionen, "unexpected difference" gegenüber dem Rest der Daten.
  - Waterfall mit überlappungsfreiem Beitrag (erst Formel-Zerlegung, dann Segmente innerhalb eines Faktors).
  - Interaktives "füge Faktor hinzu" im Report (Argus kann das als Folgefrage an den Investigator abbilden).
- **Besser machen:**
  Sisu behauptet eine statistische Garantie ohne Detail; Argus kann Mehrfachtest-Korrektur (z. B. Benjamini-Hochberg über alle getesteten Segmente) offen ausweisen und Segment-Befunde durch den Skeptiker gegen Simpson-Effekte prüfen lassen.
- **Quellen:**
  - https://www.techtarget.com/searchbusinessanalytics/news/252504993/Startup-Sisu-adds-more-automation-to-its-analytics-platform (geöffnet, Datum nicht sichtbar, Inhalt ca. 2021)
  - https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-ai-key-drivers (geöffnet, Datum nicht sichtbar)
  - https://bigdatawire.com/this-just-in/sisu-data-announces-smart-waterfall-charts und https://yespress.io/products/sisu-data (nur Suchtreffer)

#### Pecan AI

- **Was es ist:**
  Plattform für Predictive Analytics.
  Im Januar 2026 wurde laut Suchtreffer ein "Predictive AI Agent" für frühe Prognosen von Umsatz, Nachfrage und Ähnlichem angekündigt (SiliconANGLE, nur Suchtreffer).
  Status: aktiv.
- **Architektur, Algorithmen, UX:**
  Für Monitoring und Erklären von KPI-Änderungen ist Pecan kaum relevant.
  Ich habe keine Funktion gefunden, die KPI-Änderungen in Treiber zerlegt (nicht verifiziert).
  Pecans Erklärbarkeit betrifft einzelne Vorhersagen auf Kundenebene.
- **Genauigkeit und Fehler:**
  Nichts Relevantes gefunden.
- **Für Argus übernehmen:**
  Höchstens Vorhersage als Erwartungswert (Forecast statt Wochenmedian) für Planned Events; nicht in 27 Stunden.
- **Besser machen:**
  Nicht zutreffend, anderer Fokus.
- **Quellen:**
  - https://www.pecan.ai/blog/explainable-ai-understand-predictive-models/ (nur Suchtreffer)

#### ThoughtSpot SpotIQ (Change Analysis)

- **Was es ist:**
  Feature in ThoughtSpot, das Trends, Korrelationen, Erklärungen von Anstiegen und Rückgängen sowie Ausreißer findet.
  Die aktuelle Doku existiert weiter; das Glossar sprach in der Vergangenheitsform, Umbenennung nicht verifiziert.
- **Architektur und Algorithmen (Change Analysis, geöffnet):**
  Zwei Datenpunkte werden verglichen und die Attributspalten gesucht, die den Unterschied treiben.
  Das Vorgehen hängt vom Messwerttyp ab.
  - Summe und Count: Ausreißer sind Änderungen jenseits von Schwellen aus den größten absoluten Änderungen.
  - Verhältnisse (Average, Sum/Sum): Für jeden Attributwert wird eine hypothetische prozentuale Änderung berechnet, also wie stark die Gesamtänderung schrumpfen würde, wenn dieser Wert konstant geblieben wäre.
  - Andere Maße (z. B. Unique Count): Z-Scores mit Schwellen-Multiplikator N zwischen 2.0 und 5.0 je nach Kardinalität des Attributs.
  - Anomalieerkennung im Allgemeinen (Suchtreffer zu den Docs): Z-Score oder Median-Z-Score, Seasonal Hybrid ESD, lineare Regression; Mindestwert N = 2.0 (95,45 Prozent).
- **UX-Muster:**
  Zwei Punkte im Diagramm wählen, Rechtsklick "Run change analysis".
  Standardmäßig Top 5 Attribute, Summary-Tab mit "View details", Ergebnis auf ein Liveboard legen, CSV-Export.
  Iterative Analyse: Attributwert als Filter anwenden und neu rechnen, Undo/Redo, KI schlägt Werte vor.
  Optional LLM-Narrative.
- **Genauigkeit und Fehler:**
  Doku nennt Einschränkungen: nicht unterstützt bei "growth of"/"versus", komplexen group_*-Formeln, Runtime-Filtern auf versteckten Spalten.
  Zahlen zur Genauigkeit gibt es nicht.
- **Für Argus übernehmen:**
  Ratio-Handling "Was wäre, wenn dieser Wert konstant geblieben wäre" als einfache Gegenprobe zur LMDI-Zerlegung.
  Iteratives Drill-down mit Filter als Investigationsschritt.
- **Besser machen:**
  Argus nutzt exakte Formelzerlegung statt hypothetischer Änderungen und prüft Mix gegen Rate explizit.
- **Quellen:**
  - https://docs.thoughtspot.com/cloud/latest/spotiq-change (geöffnet, Datum nicht sichtbar)

#### Power BI "Analyze: Explain the increase/decrease"

- **Was es ist:**
  Funktion im Power BI Service: Rechtsklick auf einen Datenpunkt, "Analyze, Explain the decrease".
  Doku-Seite zuletzt 2025-10-01 datiert (Metadaten), aktiv.
- **Architektur und Algorithmen (geöffnet):**
  Laut Doku nimmt der Algorithmus alle anderen Spalten des Modells, berechnet die Aufschlüsselung je Spalte für Vorher und Nachher und liefert die Spalten mit der größten Änderung des relativen Beitrags.
  Der Vergleich ist immer gegen den unmittelbar vorherigen Datenpunkt.
  Rangfolge: wichtigster Beitrag zuerst.
  Schwellen oder Tests nennt die Doku nicht.
- **UX-Muster:**
  Vier Visuals je Insight: Waterfall, Scatterplot (Wert in Periode 1 gegen Periode 2 mit Trendlinie), 100-Prozent-Stacked-Column und Ribbon-Chart.
  Daumen hoch/runter für Feedback.
  Plus-Icon, um den Insight als Visual in den Report zu übernehmen.
- **Genauigkeit und Fehler:**
  Nicht unterstützt: TopN-Filter, Include/Exclude-Filter, Measure-Filter, nicht-numerische Measures, "Show value as", RLS oder DirectQuery-Modelle.
  Nicht verfügbar für den ersten Datenpunkt.
  Der Forenhinweis "zu wenig Daten unter statistischer Signifikanz" ist keine Doku (nur Suchtreffer).
- **Für Argus übernehmen:**
  Scatter "Periode A gegen Periode B pro Segment" ist ein guter, günstiger Mix-gegen-Rate-Blick.
  Daumen-Feedback je Insight speichern und in das Attention Budget einfließen lassen.
- **Besser machen:**
  Power BI vergleicht nur mit dem Vorpunkt (saisonblind), Argus vergleicht gegen die Stunde-der-Woche-Baseline.
- **Quellen:**
  - https://learn.microsoft.com/power-bi/consumer/end-user-analyze-visuals (geöffnet, Doku-Datum 2025-10-01)

#### Tellius

- **Was es ist:**
  Kommerzielle Plattform mit "Agent Mode" für automatische Root-Cause-Analyse.
  Die Seite ist ein Herstellerblog (geöffnet) mit vielen unbelegten Superlativen.
- **Architektur und Algorithmen (laut Herstellerseite):**
  Dimensionstraversierung durch Hierarchien mit Signifikanztest je Knoten, Varianzzerlegung, Ranking über Shapley-Attribution, Tests laut FAQ Chi-Quadrat und t-Test.
  Ratio-Handling wird nicht erklärt.
  Dass dies wirklich so implementiert ist, ist nicht unabhängig verifiziert.
- **UX-Muster:**
  Fertige Artefakte (PowerPoint, Excel, PDF), Zustellung per Slack, Teams, Chrome-Extension und MCP.
- **Genauigkeit und Fehler:**
  Herstellerangaben: unter 60 Sekunden pro Untersuchung, "12x faster" bei PepsiCo, 85 Prozent weniger Vorbereitungsaufwand bei einem Pharmakonzern.
  Die Seite widerspricht sich bei der Magic-Quadrant-Angabe (fünf gegen vier Jahre in Body und FAQ).
  Keine unabhängige Validierung, nicht verifiziert.
- **Für Argus übernehmen:**
  Ausgabe dort, wo Leute sind (Slack-Nachricht als Alert-Kanal im Demo).
- **Besser machen:**
  Tellius belegt Zahlen nicht mit nachvollziehbarem SQL, Argus verlinkt jede Zahl.
- **Quellen:**
  - https://www.tellius.com/resources/blog/ai-powered-root-cause-analysis-from-what-happened-to-why-in-60-seconds (geöffnet, Datum nicht sichtbar)

#### Kausa und Sisense Explanations

- Kausa: Zu Produkt und Status habe ich keine Primärquelle gefunden (nicht verifiziert).
  Nur ein Towards-Data-Science-Artikel erwähnt Kausa als Bildquelle, mit dem Framing, die Haupttreiber einer Metrik zu priorisieren.
- Sisense Explanations: nicht recherchiert (nicht verifiziert).

#### Top-Übernahmen für Argus

Rangfolge nach Wirkung pro Stunde:

1. **Trichter-Anzeige im Report und Demo.**
   Zeige "N Roh-Anomalien, M nach Score-Schwelle, K Incidents" pro Lauf (Anodot Teil 3, 4 Mio Metriken, 158.000, 910, 147).
   Aufwand ca. 1 Stunde, hoher Demo-Effekt für das Attention-Budget-Konzept.
2. **Score relativ zur Metrik-Historie.**
   Significance 0 bis 100 als Rang von Deviation und Duration gegen frühere Ausreißer derselben Metrik, zusätzlich zum robusten z-Score.
   Aufwand ca. 3 Stunden.
3. **Segmentsuche nach dem Muster von `AI.KEY_DRIVERS`.**
   Support-Schwelle, Pruning identischer Obermengen, `unexpected_difference` gegen den Rest der Daten (`complement_change_ratio`).
   Aufwand ca. 4 Stunden, direkt für den Investigator.
4. **Residuen vor Korrelation.**
   Saison und Trend entfernen, bevor Metriken korreliert oder gruppiert werden (Anodot-Warnung vor Scheinkorrelationen); Incident-Gruppierung zusätzlich über Graph-Kanten.
   Aufwand ca. 2 Stunden.
5. **Ratio-Gegenprobe "Wert konstant halten".**
   Pro Segment berechnen, wie stark die Gesamtänderung schrumpfen würde (ThoughtSpot), als Plausibilitätscheck neben LMDI und Mix-gegen-Rate.
   Aufwand ca. 1 Stunde.
6. **Feedback-Daumen pro Befund.**
   Power BI und Anodot haben Feedback; Argus speichert es und senkt oder hebt Score-Schwellen je Metrik.
   Aufwand ca. 2 Stunden, gut für "Self-Extension".
7. **Modellklasse pro Metrik.**
   Saisonalität erkennen (Autokorrelation), nur dann Stunde-der-Woche-Baseline nutzen, sonst einfache robuste Baseline (Anodots 14/86-Beobachtung, Herstellerangabe).
   Aufwand ca. 3 Stunden.
8. **Scatter Periode A gegen B plus Waterfall.**
   Beide Ansichten aus Power BI für Segmentbeiträge im Report, mit SQL-Link je Balken.
   Aufwand ca. 3 Stunden.

### 2.8 Einzelbefunde: Product Analytics und BI


Alle Aussagen stammen aus Seiten, die tatsächlich geöffnet wurden.
Alles andere ist als "Annahme" oder "nicht verifiziert" markiert.
Die Recherche war auf ca. 20 Minuten begrenzt, es gibt also Lücken (siehe jeweils "nicht verifiziert").

#### Amplitude

- **Was es ist:**
  Amplitude hat am 17.02.2026 eine Familie von AI-Agenten gestartet: einen Global Agent und vier spezialisierte Agenten, darunter einen "Dashboard monitoring agent".
  Daneben existieren die älteren Features "Anomaly + Forecast" (Prophet-basiert) und "Root Cause Analysis" (RCA).
  Quellen: https://amplitude.com/blog/the-last-bottleneck (17.02.2026), https://www.nasdaq.com/press-release/amplitude-introduces-agentic-ai-analytics-next-era-product-experiences-2026-02-17
- **Architektur:**
  Metriken sind Charts und Dashboards innerhalb des Verhaltensanalyse-Systems, es gibt keinen expliziten Metrikgraphen.
  Der Dashboard-Agent erzeugt laut Blog automatisch Insights aus jedem Dashboard, vertieft "interesting trends and anomalies" und überwacht "proactive monitoring on a schedule".
  Die Statistik sitzt in Anomaly + Forecast, das LLM sitzt in der Agentenschicht darüber.
  Die Ergebnisse gehen an die Agents-Seite, per E-Mail oder Slack. Der Global Agent ist in Slack und Teams erreichbar.
  Amplitude bietet außerdem MCP-Anbindung für Claude, ChatGPT und Cursor.
  Quelle: https://amplitude.com/blog/the-last-bottleneck
- **Algorithmen:**
  Anomalie: Prophet-basiert. Laut Docs "an anomaly detection technique based on the extensively tested open source tool Prophet".
  Ein Punkt wird markiert, wenn er außerhalb des Konfidenzbands liegt ("Detected anomalies appear in orange outside the confidence band").
  Modi: Agile (95-Prozent-Intervall, 120 Tage Trainingsdaten, tägliche und wöchentliche Saisonalität), Robust (zusätzlich ein volles Jahr Training, monatliche und jährliche Saisonalität, "works best for stable metrics"), Custom (Intervall und Trainingsdauer frei).
  Quelle: https://www.amplitude.com/docs/analytics/anomaly-forecast
  RCA: Startet mit den 30 meistabgefragten Properties und scannt in 30er-Batches, danach "Continue Scanning".
  Es vergleicht die Properties des anomalen Punkts mit einer Baseline und zeigt "the most relevant properties first".
  RCA ergänzt Kontext wie länderspezifische Feiertage und Produkt-Releases.
  Wie Relevanz berechnet wird, steht nicht in der Doku (nicht verifiziert).
  Nur Event-Segmentation-Charts, keine Formeln, nur Growth- und Enterprise-Pläne.
  Quelle: https://amplitude.com/docs/analytics/root-cause-analysis
  "Meaningful change" für den neuen Agenten: nicht dokumentiert. Der Blog nennt weder Schwellen noch Kriterien.
- **UX-Muster:**
  RCA wird per Klick auf einen Datenpunkt (Microscope) gestartet und zeigt eine Zeitreihe pro Property.
  Thumbs up/down verbessert das Ranking "over time" (ohne Details).
  Slack-Nachricht: "summaries, opportunities and recommended actions". Das genaue Format ist nicht beschrieben (nicht verifiziert).
- **Genauigkeit und Fehler:**
  Öffentliche Aussage: Root Cause Analysis, die früher "days or weeks" dauerte, dauere jetzt Minuten, mit "higher accuracy than manual investigation".
  Außerdem "10x productivity gain over manual analytics".
  Der Blog liefert dafür weder Metriken noch Methodik.
  Quelle: https://amplitude.com/blog/the-last-bottleneck
  Eine unabhängige Genauigkeitsbewertung wurde nicht gefunden (nicht verifiziert).
- **Für Argus übernehmen:**
  Prophet-ähnliche Erwartungsbänder mit Saisonalität als Anomalie-Definition (statsmodels/Prophet, oder Wochentags-Baseline mit z-Score).
  Feiertage und Releases als "Kontext, der Ursachen ausschließt" - bei uns der Planned-Event-Check.
  Scan in Batches mit Budget (30 Properties) als Vorbild für unseren Attention Budget.
- **Besser machen:**
  Amplitude zeigt keine Schwellen und keine Beleg-Links, Argus verlinkt jede Zahl auf ihr SQL.
  Amplitude RCA ist ein Property-Scan ohne Formelzerlegung (Formeln werden gar nicht unterstützt), Argus zerlegt exakt per LMDI und trennt Mix von Rate.
- **Quellen:**
  https://amplitude.com/blog/the-last-bottleneck (17.02.2026)
  https://www.nasdaq.com/press-release/amplitude-introduces-agentic-ai-analytics-next-era-product-experiences-2026-02-17 (nur in Suchergebnis gesehen, nicht geöffnet)
  https://www.amplitude.com/docs/analytics/anomaly-forecast
  https://amplitude.com/docs/analytics/root-cause-analysis

#### Mixpanel

- **Was es ist:**
  Mixpanel hat Metric Trees (Juni 2025 angekündigt laut Suchtreffer https://siliconangle.com/2025/06/18/mixpanel-expands-analytics-platform-metric-trees-ai-insights-experimentation-tools, nicht geöffnet), einen AI-RCA-Agenten und "Build with AI" für Metric Trees.
  Der Blogpost "AI Metric Trees" ist vom 17.03.2026 (zuletzt bearbeitet 09.06.2026), nur für Enterprise.
  DoubleLoop (AI-Metric-Trees-Startup) wurde am 07.10.2025 angekündigt als von Mixpanel übernommen.
  Quellen: https://mixpanel.com/blog/ai-metric-trees/, https://mixpanel.com/blog/doubleloop-joins-mixpanel/
- **Architektur:**
  Ein Metric Tree ist ein Canvas mit Metric Cards (Knoten), Strategy Cards (Initiativen) und Kanten, die "show the flow between inputs and outputs".
  Knotenrollen im AI-Blog: Bets, Input Metrics, Core Outcome (North Star), Output Metrics.
  Ein Baum kann vor der Datenanbindung als Platzhalter skizziert werden.
  "Build with AI" nutzt laut Doku keine Projektdaten, nur Firmenname, URL und eigene Anweisungen, und erzeugt "hypothesized input metrics, drivers, and connections".
  Der Blog nennt eine Outside-in-Analyse mit OpenAI (aus Suchzusammenfassung, nicht im geöffneten Blog verifiziert).
  Kanten haben optional eine Pearson-Korrelation (Tageswerte, Überlappungszeitraum), das ist die einzige datenbasierte Kantenvalidierung.
  Quelle: https://docs.mixpanel.com/docs/metric_tree
- **Algorithmen:**
  RCA in vier Schritten:
  1. Anomalie validieren: Baseline-Fenster vor dem Punkt (ca. 24 h stündlich, 14 Tage täglich, 9 Wochen wöchentlich, 6 Monate monatlich), z-Score >= 2, Saisonalitätscheck mit gleichen Wochentagen.
  2. LLM-Agent wählt Breakdown-Properties, streut über Ursachenkategorien, filtert High-Cardinality-IDs und Beinahe-Duplikate.
  3. Breakdowns laufen.
  4. LLM schreibt Interpretation mit Contribution Analysis, Dimensionsranking, wahrscheinlicher Ursache, Confidence und nächsten Schritten.
  Contribution Factor = Segmentbewegung / Gesamtbewegung (Beispiel: -500 gesamt, 400 aus einem Land = 80 Prozent).
  Lift = (Wert - Baseline) / Baseline.
  Confidence: High, Medium, Low. Das sind laut Doku "labels the AI assigns, not calculated numbers", abgeleitet aus z-Score und wie sauber ein Segment die Änderung erklärt.
  Quelle: https://docs.mixpanel.com/docs/root-cause-analysis
- **UX-Muster:**
  RCA startet aus einem Chart-Datenpunkt, einem Alert oder dem Agenten und erzeugt ein Board.
  Metric Tree zeigt pro Karte Zeitvergleiche (bis zu drei), Owner (nur gespeicherte Metriken), angeheftete Reports und Logbook-Einträge als Kontext.
  Konfidenzlabel High/Medium/Low am Ende der Erklärung.
- **Genauigkeit und Fehler:**
  Wichtige Selbstauskunft der Doku: "RCA reasons only over events and properties. It doesn't yet use annotations, session replays, experiments, or metric trees."
  Das heißt: RCA und Metric Tree sind noch nicht verbunden. Die Doku zum Tree beschreibt keine RCA-Integration.
  Nur Linien- und Säulencharts, Tageslimits pro Plan (Enterprise 300, Growth 70, Free 10).
  Der AI-Metric-Trees-Blog sagt zur Genauigkeit nichts, nur: "_You_ stay in control. AI accelerates the first draft."
  Quellen: https://docs.mixpanel.com/docs/root-cause-analysis, https://mixpanel.com/blog/ai-metric-trees/
- **Für Argus übernehmen:**
  Das exakte Anomalie-Gate (Baseline-Fenster pro Zeitgrain, z >= 2, Same-Weekday-Saisonalität) 1:1 als Schritt 1 der Untersuchung.
  Contribution Factor als einfachste Segmentzahl.
  Property-Auswahl mit Filter gegen High-Cardinality-IDs und Duplikate.
  Pearson pro Kante als billiger Evidenz-Wert zusätzlich zur Formelprüfung.
- **Besser machen:**
  Mixpanels Baum ist LLM-Hypothese ohne Datenabgleich ("uses no Mixpanel project data"), Argus validiert jede Kante numerisch und platziert neue Metriken selbst anhand von Definition + SQL.
  Mixpanels Confidence ist ein LLM-Label ohne Rechenvorschrift, Argus kann Confidence aus Prüfungen ableiten (Formel exakt = hoch, Hypothese mit Skeptic bestanden = mittel, usw.).
  RCA nutzt den Baum nicht, Argus läuft entlang der Graphkanten.
- **Quellen:**
  https://docs.mixpanel.com/docs/root-cause-analysis
  https://docs.mixpanel.com/docs/metric_tree
  https://mixpanel.com/blog/ai-metric-trees/ (17.03.2026)
  https://mixpanel.com/blog/doubleloop-joins-mixpanel/ (07.10.2025)

#### Loops (getloops.ai)

- **Was es ist:**
  KI-Analytics-Plattform, die Geschäftskennzahlen überwacht, erklärt, warum sie sich bewegen, und Chancen aufzeigt, per Slack und E-Mail ansprechbar.
  Salesforce hat am 12.10.2026 eine Übernahmevereinbarung bekanntgegeben, Loops geht in Tableau auf.
  Ein Hinweis in der Salesforce-Meldung nennt den Abschluss am 02.11.2026.
  Die Übernahme ist damit VERIFIZIERT (nicht nur "reportedly").
  Quelle: https://www.salesforce.com/news/stories/salesforce-signs-definitive-agreement-to-acquire-loops
  Kaufpreis ca. 30 Mio. USD laut Calcalist (nur Suchsnippet, nicht geöffnet, nicht verifiziert).
- **Architektur:**
  Nicht öffentlich beschrieben. Die Salesforce-Meldung erwähnt "machine learning models" und keine Kausalmethodik.
  Drittquelle: Loops "Ranks the factors behind a KPI change by estimated impact, using causal models" (https://www.beri.net/article/salesforce-loops-acquisition-tableau-agentic-analytics-causal-kpi-root-cause-customer-continuity, 12.10.2026, Sekundärquelle, die Loops-Webseite selbst wurde nicht geöffnet).
- **Algorithmen:**
  Nur Behauptungen: kausale Modelle statt Korrelationsdiagramm, vorgeschlagene Ursachen wie Traffic-Shift oder neues Release, simulierte A/B-Tests auch bei zu wenig Traffic für einen echten Test (laut beri.net).
  Release-Impact-Methode und Opportunity-Sizing: nicht verifiziert, keine Methodik gefunden.
  Das Launch-Material von 2022 (14 Mio. USD Seed) wirbt mit "causal inference AI models" (nur Suchtreffer https://www.businesswire.com/news/home/20221114006159/en/..., nicht geöffnet).
- **UX-Muster:**
  Slack- und E-Mail-getriggert. Details nicht verifiziert.
- **Genauigkeit und Fehler:**
  Es gibt keinen öffentlichen Genauigkeitsnachweis.
  beri.net: Weder Salesforce noch Loops haben einen direkten Vergleich mit Tableau Pulse veröffentlicht, der Vorteil gegenüber Pulses Driver-Erkennung ist ungetestet.
  Sinngemäß merkt beri.net an, dass Salesforce zu Bestandskunden ohne Tableau schweigt.
- **Für Argus übernehmen:**
  Die Verkaufsstory: Erklärung = gerankte Faktoren nach geschätztem Impact.
  Release/Deploy als Standardkandidat in der Hypothesenliste (bei uns planned events).
  "Simulierter Test" als Idee: Counterfactual (was wäre ohne Segment X gewesen) als billiger Plausibilitätscheck.
- **Besser machen:**
  Loops behauptet Kausalität ohne offenzulegen wie. Argus macht die Trennung sichtbar: exakte Zerlegung (Rechnung) vs. kausale Hypothese (Skeptic-geprüft, mit Label).
  Jede Zahl mit SQL-Link ist ein Transparenzvorteil gegenüber einer Black-Box.
- **Quellen:**
  https://www.salesforce.com/news/stories/salesforce-signs-definitive-agreement-to-acquire-loops (12.10.2026)
  https://www.beri.net/article/salesforce-loops-acquisition-tableau-agentic-analytics-causal-kpi-root-cause-customer-continuity (12.10.2026)

#### Salesforce / Tableau Pulse

- **Was es ist:**
  Tableau Pulse (gestartet 2024 laut Data School) liefert metrikzentrierte Insights und Digests.
  Q&A heißt jetzt "Tableau Agent in Pulse".
  Loops wird in Tableau integriert (siehe oben).
  Agentforce "Data Pro" und "Concierge": nicht verifiziert, keine Quelle geöffnet.
  Quellen: https://docs.salesforce.com/tableau/current/en-us/online/pulse_insights_platform_insight_types.md, https://thedataschool.co.uk/stephanie-pichardo/tableau-pulse-explained-what-it-is-who-its-for-and-where-it-falls-short/
- **Architektur:**
  Metrikdefinition = Measure + Zeitdimension + Dimensionen, Analyse ist auf Measures und Dimensionen der Definition und den Filterkontext des Nutzers begrenzt.
  Die Doku sagt, es werden "standardized, deterministic statistical models" genutzt, ohne Methodennamen.
  Das LLM schreibt nur die Zusammenfassung (Annahme, aus Doku-Formulierung "used in insight summaries" abgeleitet).
- **Algorithmen (Insight-Typen laut Doku):**
  Period over Period Change, Current Trend, Trend Change Alert, Unexpected Values (Wert außerhalb des erwarteten Bereichs aus Historie), Record-level Outliers, Forecast und Pace to Goal (nur Tableau+), Correlated Metrics (nur Tableau+, bis zu fünf Kandidaten).
  Top Drivers (Dimensionswerte, die sich am stärksten in gleiche Richtung bewegten), Top Detractors (Gegenrichtung), Top und Bottom Contributors.
  Concentrated Contribution Alert ("Risky Monopoly"): wenige Dimensionswerte machen 50 Prozent oder mehr des Metrikbeitrags aus. Das ist die einzige explizite Schwelle der Seite.
  Ranking: "Insights are scored by their impact on the metric value", wichtigste zuerst, plus Personalisierung durch Daumen hoch/runter (Standard an).
  "Unusual Change" kommt in der offiziellen Liste nicht als Name vor, nächstes Äquivalent ist Unexpected Values.
  Quelle: https://docs.salesforce.com/tableau/current/en-us/online/pulse_insights_platform_insight_types.md
- **UX-Muster:**
  Insight-Karten pro Metrik, Digests, Daumen hoch/runter, Follow-up-Fragen über Tableau Agent.
- **Genauigkeit und Fehler:**
  Kritik zur fehlenden RCA: Der Data-School-Artikel (Stephanie Pichardo, The Information Lab, ohne sichtbares Datum, Footer 2026) nennt den Begriff "root cause" nicht, beschreibt die Grenze aber so:
  "The Tableau Pulse insights platform is designed to help users answer descriptive questions about their metrics."
  Pulse "can point at a contributor or flag an outlier, but it can't hold the kind of open-ended, follow-the-thread investigation that a real dashboard supports."
  "But for everything past that 'what happened' moment, you're still going to want a dashboard, an analyst, or both."
  Eine Analystenquelle (Gartner, Forrester) mit der exakten Formulierung "lacks RCA" wurde NICHT gefunden (nicht verifiziert).
  Quelle: https://thedataschool.co.uk/stephanie-pichardo/tableau-pulse-explained-what-it-is-who-its-for-and-where-it-falls-short/
- **Für Argus übernehmen:**
  Das Insight-Typen-Vokabular als Katalog deterministischer Detektoren (Trend Change, Unexpected Value, Top Driver/Detractor, Concentrated Contribution).
  Impact-Score zum Ranken, bevor das LLM etwas sieht.
  Daumen hoch/runter als Feedbackschleife für den Attention Budget.
- **Besser machen:**
  Pulse bleibt bei "was ist passiert", Argus geht bis zur geprüften Ursache.
  Top Drivers sind nur Dimensionsranking, Argus zerlegt zuerst entlang der Formel und trennt dann Mix von Rate (Pulse nennt dazu nichts).
- **Quellen:**
  https://docs.salesforce.com/tableau/current/en-us/online/pulse_insights_platform_insight_types.md
  https://thedataschool.co.uk/stephanie-pichardo/tableau-pulse-explained-what-it-is-who-its-for-and-where-it-falls-short/
  https://www.salesforce.com/news/stories/salesforce-signs-definitive-agreement-to-acquire-loops

#### Count, DoubleLoop, LEVERS, Lightdash, Steep (nur Graph-relevantes)

- **Was es ist:**
  Metric Trees als Konzept: Abhi Sivasailam (Levers Labs) definiert sie laut Count-Blog als Modell gewichteter Beziehungen zwischen Metriken, Vorbild ist der DuPont-Baum (Quelle: Suchzusammenfassung, https://count.co/blog/intro-to-metric-trees nicht geöffnet).
  Lightdash startete Metric Trees am 31.01.2025.
  DoubleLoop ging im Oktober 2025 an Mixpanel (2.000+ Firmen, 6.500+ Bäume laut Mixpanel).
  Steep: nichts gefunden.
- **Architektur:**
  Lightdash: Canvas, in dem man "causal relationships between metrics" einzeichnet, ohne sie im Datenmodell zu modellieren. Jeder Knoten zeigt aktuellen Wert und prozentuale Änderung. Geplant: Korrelationsanalyse und AI-Beziehungsvorschläge.
  Quelle: https://www.lightdash.com/blogpost/metric-trees-how-top-data-teams-impact-growth
- **Algorithmen:**
  Max Halford: Ein Metrikbaum ist "essentially just a function". Totales Differential zerlegt die Änderung in Beiträge je Input (partielle Ableitung mal Änderung).
  Exakt nur für lineare Funktionen, bei Nichtlinearität bleibt ein Residuum. Integrated Gradients oder Shapley schließen die Lücke, aber "one possible allocation, rather than the unique allocation".
  Er bezweifelt, dass Metabase, Lightdash oder Steep das unterstützen.
  Quelle: https://maxhalford.github.io/blog/metric-tree-total-derivative
- **Für Argus übernehmen:**
  LMDI ist die saubere Antwort auf das Residuum-Problem bei Produkten und Quotienten (Annahme: LMDI ist für multiplikative Formeln residuumsfrei, gängiges Fachwissen, hier nicht per Quelle belegt).
  Knoten mit Wert + Delta wie in Lightdash.
- **Besser machen:**
  Alle genannten Bäume sind manuell gezeichnet oder LLM-Entwurf. Kantenvalidierung gegen Daten (Formel-Reproduktion, Residuum = 0 prüfen) macht Argus.
- **Quellen:**
  https://www.lightdash.com/blogpost/metric-trees-how-top-data-teams-impact-growth (31.01.2025)
  https://maxhalford.github.io/blog/metric-tree-total-derivative
  https://mixpanel.com/blog/doubleloop-joins-mixpanel/

#### Top-Übernahmen für Argus

Rangfolge nach Wirkung pro Stunde.

1. **Anomalie-Gate wie Mixpanel:**
   Baseline-Fenster pro Zeitgrain, z-Score >= 2, Same-Weekday-Vergleich, als Schritt 1 jeder Untersuchung (ca. 1 h).
   Verhindert Fehlalarme durch Saisonalität.
2. **Detektor-Katalog wie Tableau Pulse:**
   Unexpected Value, Trend Change, Top Driver/Detractor, Concentrated Contribution (>= 50 Prozent) als deterministische Detektoren mit Impact-Score (ca. 2 h).
3. **Confidence aus Prüfungen statt LLM-Gefühl:**
   Mixpanel vergibt High/Medium/Low per LLM. Argus leitet das Label aus z-Score, Formelresiduum, Segmentanteil und Skeptic-Ergebnis ab und zeigt die Herleitung (ca. 1 h).
4. **Contribution Factor + Lift als Standardzahlen:**
   Segmentbewegung / Gesamtbewegung, jeweils mit SQL-Link (ca. 1 h).
5. **Kontext-Ausschlüsse (Feiertage, Releases, geplante Events) zuerst:**
   Amplitude RCA und Loops nennen Releases und Feiertage als Kandidaten. Argus prüft sie vor der Hypothesenphase (ca. 1 h).
6. **Daumen hoch/runter speist den Attention Budget:**
   Pulse und Amplitude personalisieren so das Ranking. Einfache Tabelle (metric, detector, vote), Score-Gewicht anpassen (ca. 1 h).
7. **Property-Auswahl mit Filter:**
   High-Cardinality-IDs und Beinahe-Duplikate vor dem Segment-Search entfernen, in Batches mit Budget scannen (ca. 1 h).
8. **Kanten-Evidenz anzeigen:**
   Pro Graphkante Formel-Residuum und Pearson (wie Mixpanel optional) als Label am Rand, Kanten ohne Evidenz sichtbar als "Hypothese" (ca. 2 h).
   Das ist unser Alleinstellungsmerkmal gegenüber allen untersuchten Produkten.

#### Nicht verifiziert oder korrigiert

- Salesforce/Loops: Übernahme bestätigt (angekündigt 12.10.2026, abgeschlossen 02.11.2026 laut Editor-Hinweis in der Salesforce-Meldung). Loops-Kausalmethodik, Release-Impact und Opportunity Sizing sind nicht öffentlich belegt.
- Mixpanel AI Metric Trees: Blog vom 17.03.2026, nur Enterprise, Doku sagt "uses no Mixpanel project data". Die Variante mit OpenAI-Outside-in stammt aus einer Suchzusammenfassung.
- Amplitude: Kriterium für "meaningful change" im neuen Agenten und das Slack-Format sind nicht dokumentiert.
- Tableau "lacks RCA": keine Analystenquelle gefunden, nur die Data-School-Einschätzung ohne Datum.
- Agentforce "Data Pro" und "Concierge", Steep: nicht recherchiert beziehungsweise nichts gefunden.

### 2.9 Einzelbefunde: Datenbeobachtung, Warehouse-Agenten, Experimente


Stand: 2026-11-21.
Zeitbudget war 20 Minuten, daher sind einige Primärquellen nicht geöffnet worden (siehe "nicht verifiziert").
Zitate stammen aus den geöffneten Seiten; WebFetch liefert zusammengefasste Seiteninhalte, die Wörtlichkeit ist daher nur bei Zitaten in Anführungszeichen beabsichtigt.

#### Monte Carlo

- **Was es ist:**
  Datenobservability-Plattform mit Monitoren für Freshness, Volume und Schema sowie seit April 2025 "Observability Agents" (Monitoring Agent, Troubleshooting Agent).
  Quelle für das Launch-Datum: BigDATAwire-Artikel vom 2025-04-17 (nur in der Suchantwort gesehen, Seite selbst 403, daher teilweise nicht verifiziert).
- **Architektur:**
  Der Troubleshooting Agent läuft laut LangChain-Fallstudie (2025-09-10) auf LangGraph, getrennt vom Monolithen als "AI Agent Service" auf ECS Fargate, Foundation-Modelle über Amazon Bedrock.
  Der Ablauf ist "Alert → Check Code Changes → Analyze Timeline → Investigate Dependencies → Report Findings".
  Er baut einen dynamischen Graphen aus Untersuchungsknoten, jeder Knoten kann Unterknoten erzeugen (z.B. Code-Änderungen der letzten 7 Tage, dann eingegrenzt auf die betroffene Pipeline, dann Ereignisse Stunden vor dem Vorfall).
  Mehrere Ursachen werden parallel verfolgt: "hundreds of hypotheses concurrently" bzw. "launch hundreds of sub-agents".
  Wo genau das LLM im Graphen sitzt, sagt der Artikel nicht (nicht verifiziert).
  Lineage ist Field-Level: "Field-level lineage maps tables to the dashboards, models, and agents that depend on them."
  Incidents werden per Lineage gruppiert: "automated lineage grouping to collapse related incidents into one."
- **Algorithmen:**
  Freshness/Volume/Schema laufen "powered by AI" out of the box.
  Die Produktseite nennt keine Methode.
  Zu Trainingsfenster und Saisonalität gibt es in den geöffneten Quellen nichts Monte-Carlo-spezifisches (nicht verifiziert).
  Aus GitLab-Handbuch (nur Suchtreffer, nicht geöffnet): Modell lässt sich nur über "als normal markieren" und Trainingsdaten-Einstellungen beeinflussen (nicht verifiziert).
- **UX-Muster:**
  Incident als zusammengeführte Einheit über Lineage, Verfolgung "upstream to its source and downstream to everything it touches".
  Agenten sind read-only (Suchzusammenfassung, nicht verifiziert an Primärquelle).
- **Genauigkeit und Fehler:**
  "Automated monitoring reduces data downtime by 80% year over year." (Marketingbehauptung ohne Methodik, https://montecarlo.ai/product/detect)
  Kundenzitat: "We have 10% of the incidents we had a year ago." (anekdotisch, gleiche Seite).
  Die LangChain-Fallstudie nennt keine quantitativen Ergebnisse; Fokus sei Sichtbarkeit und Validierung, ob der Agent Ursachen findet.
  Keine Angaben zur False-Positive-Rate.
- **Für Argus übernehmen:**
  Deterministischer Untersuchungsgraph "Code/Deploy-Änderungen der letzten 7 Tage → Timeline → Abhängigkeiten" als feste Eröffnung, danach parallele Hypothesen-Subagenten (z.B. 4 bis 6 mit asyncio).
  Lineage-Gruppierung: Alerts auf Metriken mit gemeinsamer Upstream-Tabelle zu einem Incident zusammenfassen (im Metrikgraphen ein Join auf gemeinsame Quelltabelle).
  Ein Tag "als normal markieren" mit Rückfluss in Baseline.
- **Besser machen:**
  Monte Carlo erkennt Datenprobleme, trennt aber nicht im selben Urteil "Business-Drop vs. verspätete Daten".
  Argus gibt ein Urteil mit drei Klassen aus: DATA_LATE (erwartet nachgeliefert, Schätzung der Endmenge), DATA_BROKEN, BUSINESS_REAL, jeweils mit SQL-Belegen.
- **Quellen:**
  https://www.langchain.com/blog/customers-monte-carlo (2025-09-10)
  https://montecarlo.ai/product/detect (kein Datum sichtbar)
  https://www.bigdatawire.com/2025/04/17/monte-carlo-brings-ai-agents-into-the-data-observability-fold (nur Suchtreffer, Seite lieferte 403)

#### Sifflet

- **Was es ist:**
  Datenobservability mit drei KI-Agenten Sentinel, Sage, Forge, angekündigt im Mai 2025 als Private Beta (Suchzusammenfassung); der geöffnete Blog ist vom 2025-09-26.
  Allgemeine Verfügbarkeit nicht verifiziert.
- **Architektur:**
  Sentinel (Monitoring): wertet Metadaten-Signale wie Lineage, Schema-Drift und Nutzungsmuster aus, bewertet Assets nach Risiko und empfiehlt Monitoring vor Ausfällen.
  Sage (Untersuchung): nach einem Alert verfolgt es Lineage, prüft Code-Änderungen, nutzt frühere Lösungen und gruppiert zusammengehörige Alerts zu einer Incident-Erzählung.
  Forge (Behebung): entwirft Fixes nach früheren erfolgreichen Lösungen mit Begründung und Review-Hinweisen, Menschen behalten die Kontrolle.
  Katalog, Monitoring, Lineage und Agenten sind eine Plattform, Agenten seien "embedded directly into the platform, not as afterthought features".
- **Algorithmen:**
  Keine konkreten Algorithmen veröffentlicht in den geöffneten Quellen (nicht verifiziert).
- **UX-Muster:**
  Business-Kontext: Agenten "prioritize issues by their impact on critical business metrics" (Umsatz, Forecasting, Compliance); Sentinel fokussiert "business-critical dashboards and KPIs".
  Eine Incident-Erzählung statt vieler Alerts.
- **Genauigkeit und Fehler:**
  Keine quantifizierten Genauigkeitsangaben.
  Einzige Aussage: AI-native Architektur biete "immediate advantages in speed, accuracy, and scalability that bolt-on approaches can't match", und "Investigations move faster, repeat failures decline."
  Zahlen im Artikel (20 Prozent Wartungszeit, 12,9 Mio. USD Verlust) stammen aus Drittquellen, nicht von Sifflet-Messungen.
- **Für Argus übernehmen:**
  Drei Rollen sauber trennen: Sentinel-artig (Risikoscore je Metrik aus Graph: Geschäftsgewicht mal Fan-out), Sage-artig (Untersuchung), Forge-artig (Handlungsvorschlag im Report, nie automatisch ausgeführt).
  Priorisierung von Alerts nach Business-Gewicht als Teil des Attention Budget.
  Ein "Incident Memory": frühere Vorfälle mit bestätigter Ursache werden als Priors in die Hypothesenliste gegeben.
- **Besser machen:**
  Sifflet setzt Lineage und Code-Änderungen ein, aber keine Erwartung an verspätete Daten aus dem Ingestion-Log mit Zeitprognose.
  Argus liefert unabhängigen Skeptic-Agenten und SQL-Link je Zahl, wozu keine Quelle bei Sifflet etwas sagt.
- **Quellen:**
  https://www.siffletdata.com/blog/sifflet-ai-agents (2025-09-26)

#### Anomalo

- **Was es ist:**
  Unüberwachtes Data-Quality-Monitoring auf Tabellenebene; Methodik im Anomalo-Blog (Kapitel 4 aus ihrem Buch), kein Datum sichtbar.
  "Unstructured monitoring" wurde nicht geöffnet (nicht verifiziert).
- **Architektur:**
  Drift als Klassifikationsproblem: Zeilen von heute (Label 1) gegen Zeilen früherer Tage (Label 0), Gradient-Boosted Trees (XGBoost als Startvorschlag), Erklärung per SHAP.
- **Algorithmen:**
  Sampling: zufällige Zeilen aus mehreren Lookback-Tagen (heute, gestern, ein Tag der Vorwoche und weitere für Saisonalität), "about 10,000 rows, even for very large tables"; im Warehouse per TABLESAMPLE statt Zufallsscan.
  Feature-Encoding je Spalte automatisch: numeric, frequency, isNull, secondOfDay/timeDelta, OneHot.
  Modell: GBDT, trainiert auf kleinen Stichproben, wenige Parameter (Lernrate, Baumkomplexität).
  Erklärbarkeit: SHAP schätzt, wie stark jede Zeile-Spalte-Zelle zur Vorhersage "stammt von heute" beitrug; Schweregrad von "minimal" bis "extreme", wobei extreme eine strukturelle Änderung fast aller Tagesdaten bedeutet.
  False Positives: Ziel ist Spezifität; Saisonalität über Mehrtage-Lookback ("should not flag expected events like a Cyber Monday sales spike"); Empfindlichkeit so gesetzt, dass Probleme ab etwa 1 Prozent der Daten auffallen.
- **UX-Muster:**
  Aggregierte SHAP-Werte zeigen, wo (welche Spalte/welcher Wert) zu suchen ist, z.B. ein Wert verschwindet und ein anderer taucht auf, was auf falsch gelabelte Daten deutet.
- **Genauigkeit und Fehler:**
  Keine veröffentlichte False-Positive-Rate im geöffneten Artikel.
  Der Artikel sagt selbst, weitere Mechanismen stünden nur im Buchkapitel.
- **Für Argus übernehmen:**
  Segment-Root-Cause per Klassifikator: heutige Stunde vs. Baseline-Stunden (gleiche Wochentag/Stunde der letzten 4 Wochen), sklearn GradientBoosting oder LightGBM, Feature-Wichtigkeit (SHAP oder Permutation) nennt das Segment (Kategorie, Zahlungsanbieter, Region, App-Version).
  Das ist in 2 bis 3 Stunden baubar und besser erklärbar als reine Schwellen.
  Gleiche Baseline-Zeitpunkte (gleicher Wochentag) statt "gestern".
- **Besser machen:**
  Anomalo prüft Datenqualität, nicht Business-Ursachen; Argus nutzt denselben Klassifikator aber unterscheidet erst Vollständigkeit (Ingestion-Log, Partial-Flags) und dann Segmentursache.
  Der Event-Kalender (Black Friday) wird als Erwartung eingeplant statt nur über Mehrtage-Lookback.
- **Quellen:**
  https://www.anomalo.com/blog/chapter-4-how-to-build-a-machine-learning-model-for-data-quality-monitoring/ (kein Datum)

#### Snowflake (CoWork Automations, Cortex Agents/Analyst, Anomaly Detection, Top Insights)

- **Was es ist:**
  "Snowflake CoWork" existiert unter diesem Namen.
  Automations in CoWork: Private Preview 2026-07-15, Public Preview 2026-08-06, GA 2026-09-11 laut Release Notes (nur aus Suchergebnis; die Release-Note-Seiten lieferten nur Navigation, Inhalt nicht gelesen).
  Wichtig: Die Dokumentationsseite beschreibt Automations ausdrücklich als geplante Berichte, nicht als Schwellenwert-Standing-Orders.
- **Architektur:**
  Geplante Läufe nutzen denselben Agenten, Scope und dieselben Berechtigungen wie eine Live-Frage (Snowflake-Blog, Koreanische Version in Suchzusammenfassung, nicht direkt geöffnet).
  Jeder Lauf nutzt eigene Compute-Ressourcen und wird als Standard-Snowflake-Task abgerechnet.
- **Algorithmen:**
  Anomaly Detection ML-Funktion: GBM mit Differencing, autoregressiven Lags, gleitenden Mittelwerten und automatischen Kalendermerkmalen; Standard-prediction_interval 0.99; mindestens 12 Zeilen je Zeitreihe; bei 2 bis 11 Beobachtungen nur naive Prognose (letzter Wert); stündliche Daten nutzen Saisonlänge 24; Modelle sind nach dem Training unveränderlich ("Anomaly detection models, once trained, are immutable."); Ausgabe mit Ist, Prognose, Ober- und Untergrenze, Flag.
  Top Insights (Contribution Explorer): Boolean-Label trennt Kontrollgruppe (FALSE) und Testgruppe (TRUE); ein Entscheidungsbaum zerlegt in Segmente, Kandidatenkombinationen werden nach Signifikanz und Unterscheidbarkeit gefiltert, redundante Segmente entfallen.
  Ausgabe je Segment: METRIC_CONTROL, METRIC_TEST, CONTRIBUTION (absolute Wirkung), RELATIVE_CONTRIBUTION (Anteil an der Gesamtänderung), GROWTH_RATE (Änderung relativ zum eigenen Kontrollwert); Ergebnis nach CONTRIBUTION sortiert, negativ möglich.
  Grenzen: bei Kategorien mit mehr als 25 Werten nur die 25 einflussreichsten; ab etwa 1.000.000 Zeilen und 1.000 Spalten kann der Speicher ausgehen.
- **UX-Muster:**
  Automation entsteht im Chat: CoWork schlägt vor "This looks like a report you might want regularly. Want me to send it to you every Monday at 9 AM?"; der Nutzer bestätigt oder ändert; Bestätigung "Done. I'll email you this report every Monday at 8 AM PT. First delivery: February 24."
  Mail enthält Kurzfassung mit Kennzahlen und Link in den vollständigen Bericht zum Nachfragen.
- **Genauigkeit und Fehler:**
  Grenzen laut Docs: "Automations run on a fixed hourly, daily, weekly, or monthly schedule."; "Scheduled reports only"; höchstens stündlich; nur E-Mail; Lauf-Historie bis 60 Tage.
  Keine Angaben zu False Positives bei Top Insights im geöffneten Text.
  Cortex Agents und Cortex Analyst (Semantic Views) wurden nicht geöffnet (nicht verifiziert).
- **Für Argus übernehmen:**
  Standing Order mit Bestätigungsecho: das System gibt das verstandene Ergebnis zurück ("Ich überwache payout_per_user, Wochenvergleich, Schwelle -15 Prozent, ausgenommen geplante Events aus dem Kalender, Brief mit Root Cause. Richtig?"), als strukturiertes JSON gespeichert.
  Top-Insights-Algorithmus nachbauen: Segmentbeitrag = Delta des Segments / Gesamtdelta, sortiert nach absolutem Beitrag, plus Growth Rate, Segmentwerte auf Top 25 kappen. Als reine SQL (GROUP BY je Dimension) in einer Stunde baubar.
  Anomalie-Ausgabe immer mit Ist, Erwartung, Band (so wie DETECT_ANOMALIES), Saisonlänge 24 für Stundendaten und 168 für Wochenmuster.
- **Besser machen:**
  CoWork-Automations sind laut Doku nur zeitgesteuerte Berichte, keine bedingten Trigger; Argus Standing Orders sind ereignisgesteuert mit Bedingungsprüfung, Ausnahme für geplante Events und Datenvollständigkeits-Gate.
  Contribution Explorer weiß nichts über unvollständige Daten: ein "Segment trägt -90 Prozent bei" kann nur eine Region sein, deren Ingestion fehlt.
  Argus prüft das vor dem Segment-Beitrag.
- **Quellen:**
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/snowflake-cowork/automations
  https://docs.snowflake.com/en/user-guide/analysis-contribution-explorer
  https://docs.snowflake.com/en/user-guide/ml-functions/anomaly-detection
  https://docs.snowflake.com/release-notes/2026/other/2026-09-11-cowork-automations-ga (nur Titel und Datum gelesen)
  Datumsangaben der Previews: Suchergebnis-Titel auf docs.snowflake.com/release-notes/2026/other/2026-07-15-cowork-automations und 2026-08-06-cowork-automations (nicht geöffnet im Inhalt)

#### Statsig und Eppo (Experimentation)

- **Was es ist:**
  Statsig: Ankündigung des Beitritts zu OpenAI am 2025-09-02, Abschluss unter Vorbehalt behördlicher Zustimmung.
  Ein späterer Hinweis auf der Statsig-Seite sagt laut Fetch: "Statsig was acquired by Amplitude" am 2026-05-05, Team blieb bei OpenAI, Produkt, Marke und Kunden gingen an Amplitude. Das widerspricht der Annahme, Statsig sei bei OpenAI geblieben; nur aus einer Zusammenfassung, bitte vor Zitierung manuell prüfen.
  Eppo: von Datadog übernommen (Statsig-Blog nennt 2025-05-01, TechCrunch laut Suchzusammenfassung 220 Mio. USD, Primärseite nicht geöffnet).
  Datadog-Blog vom 2026-09-10 bestätigt: Eppo-Funktionen wurden zu Datadog Feature Flags und Datadog Experiments.
- **Architektur:**
  Warehouse-native: Metriken laufen als SQL im eigenen Warehouse.
  Datadog Experiments bietet "Copy SQL" für die Abfrage hinter jeder Zahl, mit dem Hinweis, Ergebnisse lägen sehr nah am Dashboard, "late-arriving data can cause small differences".
  CUPED von Datadog erweitert auf Segmente und Perzentile.
- **Algorithmen:**
  SRM: Statsig nutzt einen Chi-Quadrat-Test auf Expositionen; Warn- oder Fehlerzustand bei p unter 0.01; ein anhaltender Alarm gilt als Datenqualitätsproblem.
  Sequentieller Test (Statsig, mSPRT-artig): Intervall CI* = Delta ± Z* · sqrt(V), mit V = var(Xt)/Nt + var(Xc)/Nc, Mischparameter tau = Z²(α/2) · (var(Xt)+var(Xc))/(Nt+Nc), und Z* = sqrt( (V+tau)/tau · ( -2 ln(α/2) - ln(V/(V+tau)) ) ).
  p-Wert wird gegen eine breitere Normalverteilung N(0, σ²) mit σ = Z* / (sqrt(2) · erfinv(1-α)) ausgewertet.
  Statsig sagt: "early decisions can only increase the false positive rate", der Parameter halte den erwarteten Fehler ersten Grades; das Intervall schrumpft mit mehr Daten, daher sinkt die Strafe für frühe Blicke.
  CUPED: reduziert Varianz durch Anpassung mit Vorab-Daten pro Nutzer, Fenster bei Statsig Cloud immer 7 Tage, Warehouse Native frei wählbar, 7 empfohlen; nützlich bei autokorrelierten Metriken.
  Eppo-Docs (Sequential, SRM) lieferten 404; Eppo-Blog nennt group sequential, fully sequential und SRM-Checks mit Ursachen wie falsches Ramping, Variant-Bug, Logging-Probleme (nur Suchzusammenfassung, nicht geöffnet).
- **UX-Muster:**
  Health Checks im Experiment mit Warn-/Fehlerstatus, SRM als erster Check bevor Ergebnisse gelesen werden.
  "Copy SQL" neben jeder Metrik.
- **Genauigkeit und Fehler:**
  Statsig: "has validated that this parameter satisfies the expected false positive rate" (keine Zahlen im geöffneten Text).
  Sequenzielle Tests kosten Power gegenüber Festhorizont (allgemein bekannt; in den geöffneten Seiten nicht quantifiziert, nicht verifiziert).
- **Für Argus übernehmen:**
  SRM-artiger Sanity-Check für Daten: Erwartete Verteilung (z.B. Anteil der Regionen/Kanäle an Bestellungen laut Baseline) gegen beobachtete Stunde per Chi-Quadrat, p unter 0.01 heißt "Datenverdacht, kein Geschäftsvorfall".
  Das fängt partielle Ladungen (eine Region fehlt) ohne Ingestion-Log. 1 Stunde.
  Sequentieller Alarm: Für fortlaufende Überwachung mSPRT-Intervall statt wiederholter fester Tests, damit "alle Stunden prüfen" die Fehlalarmrate nicht aufbläht. Formel oben, 20 Zeilen Python.
  Experiment-Log als Erklärung: laufende Experimente (Holdout/Rollout) als Kandidaten-Hypothese mit SRM-Gate.
  "Copy SQL" an jeder Zahl, wie Datadog es macht, ist exakt das Argus-Prinzip.
- **Besser machen:**
  Experimentierplattformen prüfen SRM nur innerhalb eines Experiments; Argus wendet das auf jede Geschäftsmetrik an.
  Late-arriving data nennt Datadog nur als Fußnote; Argus macht es zum Urteil mit Nachlieferungsprognose.
- **Quellen:**
  https://statsig.com/blog/openai-acquisition (2025-09-02, Hinweis zu Amplitude 2026-05-05)
  https://docs.statsig.com/experiments/monitoring/srm
  https://docs.statsig.com/experiments-plus/sequential-testing
  https://docs.statsig.com/stats-engine/methodologies/cuped
  https://www.datadoghq.com/blog/how-we-built-datadog-experiments (2026-09-10)
  https://statsig.com/blog/datadog-acquires-eppo (nur Suchtreffer; Datum 2025-05-01 laut Zusammenfassung)

#### Top-Übernahmen für Argus

Rang nach Wirkung pro Stunde.

1. **Verdikt-Klassen mit Daten-Gate zuerst (1 bis 2 Stunden).**
   Jede Anomalie erhält DATA_LATE, DATA_BROKEN oder BUSINESS_REAL, geprüft über Ingestion-Log, Partial-Flags und historische Nachlieferkurve.
   Kein Wettbewerber in diesem Bereich kombiniert das mit Business-RCA im selben Urteil (nach geöffneten Quellen).
2. **SRM-artiger Chi-Quadrat-Check auf Segmentanteile (1 Stunde).**
   Statsig-Methode, p unter 0.01, erkennt Teilladungen ohne explizites Signal.
3. **Contribution-Explorer-Nachbau in SQL (1 bis 2 Stunden).**
   Beitrag, relative Beitrag, Growth Rate je Segment, Top 25, nach absolutem Beitrag sortiert, mit Kalender-Ausnahme.
4. **Standing-Order-Echo mit strukturiertem Parse (2 Stunden).**
   LLM parst in JSON (Metrik, Fenster, Schwelle, Ausnahmen, Aktion), Argus gibt das Verstandene zurück und lässt bestätigen; CoWork bietet das nur für Zeitpläne.
5. **Zahl-zu-SQL-Link ("Copy SQL") an jeder Zahl im Report (1 bis 2 Stunden).**
   Datadog Experiments zeigt, dass das Vertrauen schafft.
6. **Sequentieller Alarm (mSPRT) für Dauerüberwachung (1 bis 2 Stunden).**
   Hält Fehlalarme bei stündlichem Prüfen unter Kontrolle; Formel von Statsig übernehmbar.
7. **Parallele Hypothesen-Subagenten plus unabhängiger Skeptic (3 bis 4 Stunden).**
   Monte Carlos Muster, aber mit Skeptic, der die Belege per eigenem SQL prüft; deterministische Eröffnung (Deploys, Kalender, Provider-Status, Experimente).
8. **Segment-Klassifikator nach Anomalo (2 bis 3 Stunden).**
   GBDT: aktuelle Stunde vs. gleiche Wochentag-Stunde der Vorwochen, Feature-Wichtigkeit nennt das Segment; Empfindlichkeit auf etwa 1 Prozent der Daten, wie Anomalo.

#### Nicht verifiziert oder korrigiert

- "Snowflake CoWork" existiert; Automations sind aber nur zeitgesteuerte Berichte, keine bedingten Standing Orders ("Scheduled reports only").
- Statsig: OpenAI-Übernahme 2025-09-02 bestätigt, laut Hinweis auf Statsigs eigener Seite später Wechsel von Produkt und Kunden zu Amplitude (2026-05-05); nur aus Zusammenfassung.
- Eppo/Datadog 2025: Datum und Preis nur aus Suchtreffern, Primärquellen nicht geöffnet.
- Monte Carlo: Trainingsfenster, Saisonalität und Schwellen nicht öffentlich gefunden; "hundreds of hypotheses" ist Herstellerangabe ohne Messung.
- Sifflet: Verfügbarkeit (Private Beta Mai 2025) nur aus Suchtreffer; keine Algorithmen veröffentlicht.
- Anomalo "unstructured monitoring", Cortex Agents/Analyst, Eppo-Docs: nicht geöffnet.

### 2.10 Einzelbefunde: interne Systeme großer Tech-Firmen und Algorithmen


Stand: 2026-11-21, Recherche unter Zeitdruck (ca. 20 Minuten).
Konvention: "Annahme:" und "nicht verifiziert:" kennzeichnen alles, was ich nicht in einer geöffneten Quelle gesehen habe.
Quellen mit dem Zusatz "nur Suchsnippet" konnte ich nicht öffnen (HTTP 403 oder 404), die Aussagen dazu sind sekundär.

#### Uber uVitals (und Argos / uMonitor)

- **Was es ist:**
  uVitals ist Ubers unüberwachtes Anomalieerkennungs- und Alerting-System für mehrdimensionale Business-Zeitreihen, beschrieben im Engineering-Blog am 28.12.2023 (Appiah, Raulkar; Datum laut Suchergebnis).
  Argos (2018, Echtzeit-Anomalieplattform für Systemmetriken) und uMonitor wurden von mir nicht geöffnet: nicht verifiziert.
- **Architektur:**
  Pipeline aus Onboarder, Metric Cube Creator, Profiler (Lücken und Spikes), Seasonality Detector (pro Slice), Toolkit (Modell pro Slice je nach Saisonalität), Rules Engine, Significance Scorer, Publisher (Kontextfilter), Notifier, Feedback Listener, Feedback Processing and Learning, Quality Controller.
  Der Cube erzeugt "several million combinations" für die Payment-Success-Rate, Zielgröße bis 3 Millionen Zeitreihenpunkte.
  Wechsel von Pandas auf Spark brachte "an average reduction of 77%" Laufzeit.
- **Algorithmen:**
  Saisonalitätserkennung per FFT mit festen Perioden (Fehlerrate 8.63%, Precision 0.88, Recall 0.83, F1 0.85), knapp hinter ACF auf detrendeter Reihe (F1 0.86, Fehlerrate 9.14%).
  Modellvergleich: STL gewann als bestes Modell für den unüberwachten Multi-Dimensions-Fall, obwohl Prophet in zwei von drei Datensätzen höheres F1 hatte (z.B. Amount redeem USD: Prophet 0.94 Recall, 0.68 Precision, F1 0.79; STL 0.88, 0.52, 0.65).
  Stündliche Daten: "Multiple decomposition" RMSE 458 und MAPE 4.58%, Single decomposition RMSE 1841 und MAPE 18.81%, Prophet RMSE 1487 und MAPE 30.78%.
- **UX-Muster:**
  Anomalien nach Signifikanz priorisiert und als neu, laufend oder aufeinanderfolgend kategorisiert.
  Alert enthält Datum, mittlere Abweichung in Prozent, Beitrag in Prozent und Dashboard-Link.
  Jede Mail hat einen Feedback-Link (true/false positive), Feedback erzeugt Ausnahmeregeln.
  Zielgruppen-Routing pro Alert.
- **Genauigkeit und Fehler:**
  Gross Bookings über 2.000 Städte: "232 anomalies appeared in 10 days", "95% of these anomalies were mere noise".
  Ein City Classifier (Top/Middle/Bottom-Tier) senkte die Zahl "from 232 down to just 11".
  Wirkung laut Blog: Erkennung von "3 months to detect 100 issues" auf "one day or less".
  Lücken im Blog: Rules-Engine-Logik und Gruppierung/Dedup sind nicht beschrieben.
- **Für Argus übernehmen:**
  Segment-Tiering nach Volumen: Segmente mit kleinem Anteil am Gesamtvolumen bekommen strengere Schwellen oder werden nur im Rollup überwacht (Attention Budget).
  Alert-Zustand new/ongoing/consecutive im Incident-Objekt.
  Pro Alert: mean diff %, Beitrag %, Link auf SQL.
  Feedback-Buttons, die Ausnahmeregeln erzeugen.
  Profiler-Schritt für Datenlücken und unvollständige Stunden vor jeder Statistik.
- **Besser machen:**
  Uber meldet pro Slice und dedupliziert nicht erkennbar, Argus fasst Slices per Fingerprint und Metrikgraph zu einem Incident zusammen.
  Argus nutzt den Graphen, um Ursache und Wirkung zu verbinden, statt nur Signifikanz zu ranken.
- **Quellen:**
  https://www.uber.com/blog/uvitals-an-anomaly-detection-alerting-system (geöffnet, Dezember 2023).
  Suchsnippet zu Argos 2018 und Speaker-Deck-Talk: nur Suchsnippet, nicht verifiziert.

#### LinkedIn ThirdEye (Apache Pinot / StarTree)

- **Was es ist:**
  ThirdEye ist LinkedIns unternehmensweite Monitoring- und RCA-Plattform auf Pinot, vorgestellt am 9.1.2019, RCA-Tools am 20.2.2020 beschrieben.
- **Architektur:**
  "4 layer architecture", föderierte Verarbeitung über Batch und Streaming, Pinot und RocksDB, Pinot liefert "sub-second response times" bei Terabyte-Daten.
  Nutzer definieren einen Metric Scope (z.B. Signups eines Kontinents), ThirdEye liefert einen ersten Satz anomaler Bereiche.
  Detektoren laufen zusammen mit nutzerdefinierten Regeln als "insurance policy".
- **Algorithmen:**
  Dimension Heatmap: Vergleich mit Baseline (Standard: gleiche Periode eine Woche früher), drei Änderungsmaße: prozentuale Änderung, Änderung des Beitrags (Prozentpunkte), relativer Beitrag zur Gesamtänderung.
  Kleine Werte werden zu "OTHER" gruppiert, Heatmap rendert unter einer Sekunde.
  Top-Contributor-Algorithmus (Data Cube): Score pro Knoten aus change ratio, change difference zum Elternknoten (erwartete Rate r = v_parent,C / v_parent,B) und segment contribution.
  Dimensionswichtigkeit = Summe der Kinder-Scores, wichtigste Dimension wird Wurzel, pro Elternknoten top-k Kinder, bottom-up Merge mit top-k.
  Ausgabe: Difference-Summary-Tabelle mit "(ALL)" und "OTHER".
  Die exakte Kostenfunktion ist in den Docs nur als Bild enthalten: nicht verifiziert.
  Enterprise nutzt den Mehr-Dimensionen-Algorithmus, Community einen einfacheren ohne Kombinationen.
- **UX-Muster:**
  Heatmap (Blau Anstieg, Rot Rückgang, Zellgröße = Traffic-Anteil), Klick filtert live.
  RCA-Ergebnisse werden mit A/B-Tests und letzten Deployments verknüpft und als archivierbare Post-Mortem-Berichte exportiert.
  Feedback: Nutzer markieren Anomalien als relevant oder zeigen Auslassungen an, das verschiebt die Entscheidungsgrenzen.
  Die Labels true anomaly / expected / not anomaly habe ich in den geöffneten Quellen nicht gesehen: nicht verifiziert.
  Anomaly Merging und Alert Grouping stehen nicht in den geöffneten Posts: nicht verifiziert.
- **Genauigkeit und Fehler:**
  Keine Precision/Recall-Zahlen in den geöffneten Quellen.
  Erfolgsfälle: ca. 3% Traffic-Anstieg auf fehlendes Tracking-Tag in neuer iOS-Version zurückgeführt, Page-Views-Einbruch um 31.10. auf US-Traffic.
  Holiday-Handling: Feiertage werden nach zeitlicher Nähe und Kontext (Geografie) gerankt, Länderauswirkungen können ignoriert werden.
  Heatmap kann nur eine Dimension auf einmal aufklappen, das war der Grund für den Cube-Algorithmus.
- **Für Argus übernehmen:**
  Drei Änderungsmaße pro Segment (Prozent, Beitragsverschiebung, Anteil an Gesamtänderung) als Standardspalten im Report.
  Baseline-Auswahl (Vorwoche gleiche Stunde) und "OTHER"-Bucket.
  Eventkalender pro Land als Erwartungsverschiebung.
  Report als archivierbares Post-Mortem mit SQL-Links.
- **Besser machen:**
  ThirdEye rankt Dimensionen per Score-Heuristik, Argus nutzt exakte LMDI-Zerlegung entlang der Formelkanten plus Mix-vs-Rate-Split.
  Argus prüft jede Kante numerisch und generiert Hypothesen selbst, statt auf menschliche Heatmap-Navigation zu setzen.
- **Quellen:**
  https://www.linkedin.com/blog/engineering/analytics/introducing-thirdeye-linkedins-business-wide-monitoring-platfor (geöffnet, 9.1.2019).
  https://www.linkedin.com/blog/engineering/analytics/analyzing-anomalies-with-thirdeye (geöffnet, 20.2.2020).
  https://docs.startree.ai/thirdeye/concepts-data-alerts-notifications/concepts-top-contributor-algorithm (geöffnet).
  https://docs.startree.ai/thirdeye/concepts-data-alerts-notifications/concepts-heatmaps (nur Suchsnippet).
  Das GitHub-Repo startree-ai/thirdeye lieferte 404.

#### Airbnb Minerva

- **Was es ist:**
  Minerva ist Airbnbs Metrik-Plattform als Single Source of Truth für Erstellung, Berechnung, Auslieferung, Konsum und Deprecation von Metriken, Teil I von Robert Chang am 30.4.2021 (laut Suchergebnis), Teil II zur Compute-Infrastruktur von Amit Pahwa.
- **Architektur:**
  Nimmt normalisierte Fakten- und Dimensionstabellen, denormalisiert sie und liefert aggregierte Daten an Konsumenten (sekundär, Drittquelle).
  Definitionen sind versionierter Code mit Code-Review, statischer Validierung und Testläufen.
  Pflichtmetadaten in der Konfiguration: Ownership, Lineage, Beschreibung.
  Metrik- und Dimensionsspalten sind getrennt.
- **Algorithmen:**
  Keine Anomalieerkennung, Minerva ist die Definitionsebene.
  Zertifizierung gehört laut Suchsnippet zur Experimentation Platform: Data Engineering zertifiziert ca. 50% der ERF-Metriken mit SLA und auditierten Änderungen.
- **UX-Muster:**
  Metrik-Katalog mit Ownership und Zertifizierungsstatus, Deprecation als Lebenszyklusschritt.
- **Genauigkeit und Fehler:**
  Nicht anwendbar.
  Die genaue Minerva-YAML-Syntax habe ich nicht gesehen: nicht verifiziert.
- **Für Argus übernehmen:**
  Metrik-Knoten-Schema: id, Beschreibung, Owner, Einheit, Aggregationstyp (additiv, Verhältnis mit Zähler und Nenner), erlaubte Dimensionen, Quelltabelle/SQL, Grain, Zertifizierungsstatus (draft, validated, deprecated), Lineage-Kanten.
  Selbsterweiterung: Argus schlägt neue Metrik- oder Kantendefinitionen als Pull-Request-artige Änderung vor und aktiviert sie erst nach numerischer Validierung (Kante erklärt Wert innerhalb Toleranz).
- **Besser machen:**
  Minerva setzt menschliche Definition voraus, Argus entdeckt Kanten (formula, breakdown, cause, evidence) selbst, validiert sie numerisch und stuft sie automatisch auf "validated" hoch oder verwirft sie.
- **Quellen:**
  https://medium.com/airbnb-engineering/how-airbnb-achieved-metric-consistency-at-scale-f23cc53dea70 (nur Suchsnippet, WebFetch lieferte 404).
  https://medium.com/airbnb-engineering/airbnb-metric-computation-with-minerva-part-2-9afe6695b486 (nur Suchsnippet, 403).

#### Netflix: Kayenta, RAD, Telltale, Atlas

- **Was es ist:**
  Kayenta ist Netflix' und Googles offenes Automated-Canary-Analysis-System (Open Source 2018), der Judge ist NetflixACAJudge.
  Telltale ist Netflix' Application-Health-Monitoring-System (InfoQ 23.9.2020).
  RAD (RPCA), Atlas und "Sequential A/B testing keeps the world streaming" habe ich nicht geöffnet: nicht verifiziert.
- **Architektur:**
  Kayenta: zwei Phasen, Metrikabruf für Baseline und Canary, dann Judge-Vergleich mit Pass/Fail.
  Telltale: Application Health Model mit Signalen aus Mantis, Project Nimble (Failover), Streaming Supply Chain und bestehendem Alerting, Sicht je nach Signaltyp.
  Telltale ist laut Blog nicht Open Source.
- **Algorithmen (Kayenta, geöffnet):**
  Schritt 1 NaN-Behandlung (remove default, replace = 0), fehlende Daten ergeben Nodata oder NodataFailMetric.
  Schritt 2 optional IQR-Outlier-Filter mit Tukey-Faktor 3.0, erweitert um 1. und 99. Perzentil.
  Schritt 3 Klassifikation Pass/High/Low: Mann-Whitney U bei 98% Konfidenz muss das Intervall um den Hodges-Lehmann-Schätzer außerhalb eines Toleranzbands von ±25% legen, zusätzlich muss die Effektgröße (meanRatio = canary mean / baseline mean, oder cles für Nullzähler) allowedIncrease/allowedDecrease (Default 1.0) überschreiten.
  Kritische Metrik mit Überschreitung von criticalIncrease/criticalDecrease setzt den Score auf 0.
  Gruppenscore = Pass / (Pass + High + Low + NodataFailMetric) * 100, Nodata ausgeschlossen, reine Nodata-Gruppe = 100.
  Gesamtscore = gewichteter Mittelwert der Gruppen, Score >= passThreshold Pass, >= marginalThreshold Marginal, sonst Fail.
  Automatisch Score 0 bei 50% oder mehr Nodata.
- **UX-Muster:**
  Telltale: nur relevante Metriken plus Events (Deployments, Region-Evakuierungen), Severity farbig und numerisch, Incident-Updates im Slack-Thread, Application Incident Summary nach dem Incident.
  Telltale hebt "possible causes" hervor, der Mechanismus ist nicht erklärt.
  Deduplizierung wird im InfoQ-Artikel nicht erwähnt.
- **Genauigkeit und Fehler:**
  Telltale überwacht "over 100 production-facing Netflix applications".
  Keine Precision/Recall-Zahlen in den geöffneten Quellen.
  Kayenta-Detail: Effektgröße ist NaN, wenn ein Mittelwert 0 ist, dann entscheidet nur der Test.
- **Für Argus übernehmen:**
  Verdikt-Schema Pass/Marginal/Fail auch für "Ist der Rollout, die Kampagne oder der Fix wirksam?" (Vorher/Nachher-Vergleich per Mann-Whitney U mit Toleranzband).
  Nodata ist ein eigener Zustand mit Ausschlussregel, passt direkt zu "pending" bei unvollständigen Stunden.
  Events (Deployments, Kampagnen) als Kontext im Alert.
  Kritisch-Flag pro Metrik (z.B. Umsatz, Checkout-Erfolg) für Sofort-Eskalation.
- **Besser machen:**
  Telltale nennt "possible causes" ohne dokumentierten Mechanismus, Argus belegt jede Ursache mit validierter Kante und LMDI-Anteil.
  Kayenta ist für Canary-Vergleiche gebaut, Argus überträgt das auf Geschäftsmetriken mit Saisonalität über Stunde-der-Woche-Baselines.
- **Quellen:**
  https://www.spinnaker.io/guides/user/canary/judge/ (geöffnet).
  https://www.infoq.com/news/2020/09/netflix-presents-telltale/ (geöffnet, 23.9.2020).
  Kayenta-Ankündigung Google/Netflix, April 2018: nur Suchsnippet.

#### Meta DrP und Facebook Fast Dimensional Analysis

- **Was es ist:**
  DrP ist Metas Investigations-Plattform (Blog 19.12.2025, arXiv 2512.04250 vom 3.12.2025).
  Fast Dimensional Analysis (arXiv 1911.01225) ist Frequent-Itemset-Mining für RCA auf strukturierten Logs (Zuordnung zu Meta: Annahme, die Abstract-Seite nennt Facebook nicht).
- **Architektur:**
  DrP: SDK für "Analyzers" (Playbooks, verkettbar), Backend mit Request-Queue und Worker-Pool (mandantenfähig, isoliert), automatische Trigger aus Alerts und Incident-Tools, Ergebnisse als Annotation am Alert, Post-Processing (Tasks, Pull Requests), Backtesting im Code-Review, "DrP Insights" rankt die häufigsten Alert-Ursachen.
  Das SDK enthält Anomalieerkennung, Event-Isolation, Zeitreihenkorrelation und Dimension Analysis.
- **Algorithmen:**
  DrP-Blog erklärt die Algorithmen nicht.
  FDA: Apriori, dann FP-Growth, Scoring der Itemsets per Lift ("most unique to the target failures").
- **UX-Muster:**
  Analyse startet automatisch beim Alert, Befund hängt am Alert, Folgeaktion wird vorgeschlagen.
- **Genauigkeit und Fehler:**
  "Used by over 300 teams", "about 2,000 analyzers", "about 50,000 analyses per day", MTTR-Reduktion 20-80%, über fünf Jahre in Produktion (Blog); Paper: im Schnitt 20%, bei einigen Teams über 80%.
  Prophet-Nutzung bei Meta für KPI-Anomalien: nicht verifiziert.
- **Für Argus übernehmen:**
  Investigation als kleine, wiederverwendbare Playbooks (Analyzer) pro Kantentyp, die Argus bei Alerts automatisch startet und als Annotation an den Incident hängt.
  Backtesting neuer Playbooks gegen historische Anomalien (Selbsterweiterung mit Sicherheitsnetz).
  Lift-basiertes Itemset-Scoring als Fallback für kategoriale Log-Dimensionen.
- **Besser machen:**
  DrP-Analyzer werden von Menschen geschrieben, Argus erzeugt und testet sie selbst aus dem Metrikgraph.
- **Quellen:**
  https://engineering.fb.com/2025/12/19/data-infrastructure/drp-metas-root-cause-analysis-platform-at-scale/ (geöffnet).
  https://arxiv.org/abs/2512.04250 (nur Suchsnippet).
  https://arxiv.org/abs/1911.01225 (geöffnet).

#### Weitere (nicht recherchiert)

Microsoft SR-CNN, Pinterest, Lyft, Shopify und Booking.com wurden aus Zeitgründen nicht geprüft: nicht verifiziert.

#### LMDI (Log Mean Divisia Index), additive Zerlegung

- Standardformel (Mathematik, nicht aus geöffneter Quelle zitiert): für y = x1 * x2 * ... * xn, Änderung dy = y1 - y0, gilt dy = Sum_i L(y1, y0) * ln(xi1 / xi0) mit L(a, b) = (a - b) / (ln a - ln b) und L(a, a) = a.
  Die Effekte summieren sich exakt zu dy, ohne Residuum.
  Für Verhältnisse (Rate = Zähler / Nenner) ist ln-Zerlegung direkt möglich, für Segmentsummen (Mix vs. Rate) wird pro Segment zerlegt und summiert.
- Nullwerte (Ang und Liu 2007, Energy Policy 35, S. 238-246, laut Suchsnippet): zwei Strategien.
  "Small value" (SV) ersetzt Nullen durch eine kleine Zahl, die Ergebnisse konvergieren.
  "Analytical limit" (AL) nutzt analytische Grenzwerte und ist bei großen Änderungen vorzuziehen, SV geht dann mit sehr kleinem d (z.B. 10^-100).
  Die Grenzwertformeln habe ich nicht gesehen: nicht verifiziert.
- Annahme für Argus (Implementierung): wenn x0 = 0 oder x1 = 0 für einen Faktor, Effekt analytisch als "Neu/Weggefallen"-Beitrag separat ausweisen (Faktor ln-Term entfällt, Beitrag = Delta des Segments), sonst SV mit epsilon.
  Im Test numerisch prüfen, dass die Summe der Effekte dy auf 1e-9 trifft.
- Quelle: https://ideas.repec.org/a/eee/enepol/v35y2007i1p238-246.html (nur Suchsnippet).

#### Segment-Lokalisierung: Algorithmenvergleich

Notation: A = Ist, F = Forecast, EP = Explanatory Power.

| Algorithmus | Scoring-Formel (Klartext) | Stärken | Fehlermodi | Aufwand (4 Dim, 5x3x4x6) |
|---|---|---|---|---|
| Adtributor (NSDI 2014) | EP_ij = (A_ij - F_ij) / (A - F) für additive Maße. Surprise S_ij = 0.5 * (p * log(2p / (p + q)) + q * log(2q / (p + q))) mit p = F_ij / F, q = A_ij / A (JS-Divergenz). Pro Dimension: Elemente nach Surprise absteigend, Element in die Kandidatenmenge, wenn EP >= TEEP (Occam), Stopp wenn Summe EP > TEP. Paper-Werte: TEP 67%, TEEP 10%. Pro Dimension eine Menge, Rückgabe der Top 3 nach Surprise. Abgeleitete Maße x/y: EP = ((dA_ij(m1)) * F(m2) - dA_ij(m2) * F(m1)) / (F(m2) * (F(m2) + dA_ij(m2))) (Finite-Differenzen-Ableitung), normalisiert auf 100%. | Sehr schnell, einfach, erklärbar, behandelt Verhältnisse, Paper: Accuracy "over 95%" ((118+4)/128 = 95.3%) bei Strawman ohne Surprise 20% (Ad-System, eigene Daten). | Nur eine Dimension je Ergebnis, keine Kombinationen. Im RiskLoc-Vergleich F1 0.0650 auf A*, 0.0589 auf S, 0.0000 auf L (fein granulare Ursachen), nur auf Layer-1-Anomalien gut. Annahme: Ursache wirkt auf einer Dimension. | Sehr niedrig, ca. 1-2 Stunden. |
| R-Adtributor (Recursive Adtributor) | Adtributor rekursiv auf Teilräumen. Details nicht geöffnet: nicht verifiziert. | Tiefere Ursachen. | Im RiskLoc-Paper schlechter als Adtributor (A*: 0.00003). | Niedrig, aber nicht empfohlen. |
| iDice (Microsoft, 2016) | Nicht geöffnet: nicht verifiziert. Laut RiskLoc-Paper Mining von Attributkombinationen (Rule Mining), sensitiv für Support/Confidence-Parameter, fokussiert nicht-additive Maße. | Findet Kombinationen. | Parameterempfindlich. | Mittel. |
| HotSpot (Sun et al., 2018) | Potential Score = Anteil der Änderung, den eine Kandidatenmenge nach Ripple-Effect-Annahme erklärt, Suche per MCTS plus Hierarchie-Pruning (Details nicht geöffnet: nicht verifiziert). Ripple Effect: Änderung eines Elternknotens verteilt sich proportional zum Forecast auf seine Blätter. | Kombinationen, prinzipienfest. | Langsam (laut RiskLoc-Paper einer der langsamsten), F1 0.0127 auf A*, 0.1740 auf S, 0.1848 auf L. | Hoch, MCTS-Tuning. |
| Squeeze (ISSRE 2019) / PSqueeze (arXiv 2023) | Generalized Ripple Effect plus Generalized Potential Score (GPS). Bottom-up Clustering der Blätter nach Deviationsscore, dann top-down Suche je Cluster. Laut Suchsnippet im Schnitt F1 ca. 0.4 besser als frühere Ansätze, ca. 10 Sekunden. | Mehrere gleichzeitige Ursachen, Clustering unterscheidet Anomalien. | Laut RiskLoc-Paper: Annahme je Cluster eine Ursache, Ergebnis hängt von Clustering-Genauigkeit und schwer bestimmbaren Parametern ab, Ranking versagt bei feinstgranularen Elementen (viele False Positives). F1 0.2951 auf A*, 0.1283 auf S, 0.3524 auf L. | Hoch, Clustering plus GPS. |
| AutoRoot | Squeeze mit parameterfreiem Clustering, relativem Scoring, einfacherem Filtern (laut RiskLoc-Paper). | Weniger Parameter. | Weiterhin Clustering-Abhängigkeit, eine Ursache pro Cluster. F1 0.1802 (A*), 0.4478 (S), 0.5266 (L). | Mittel bis hoch. |
| RiskLoc (2022) | Blätter erhalten Deviationsscore ds(e) = 2 * (a - v) / (a + v) (a = Ist, v = Forecast; Formel aus Gleichung 7/10 des Papers). 2-Wege-Partition in normal/abnormal an einem Punkt, geschätzt aus der maximalen Abweichung normaler Daten, Gewicht = Abstand vom Partitionspunkt (abnormal: Gewicht = ds, normal: linear ab 0). Pro Element e_r: w_a = Summe der Gewichte abnormaler Blätter, w_n = Summe der Gewichte normaler Blätter. r1 = w_a / (w_n + w_a + 1). r2 = r_n / r_d mit r_n = Summe 2*(a - v)/(a + v) nach Ripple-Anpassung, r_d = Summe |ds(e)| (r2 nahe 0 heißt: Ripple-Effect befolgt). risk = r1 - r2, Element als Ursache wenn risk >= t_r (Default 0.5). Cuboid-weise Suche mit Pruning, Auswahl bis erklärende Menge ausreichend (Parameter t_pep). Blätter: r2 = 0, nur r1 zählt. | Beste F1 im Vergleich: A* 0.4640, S 0.6350, L 0.6767, H 0.4906 (Table 3 des Papers), "gains in F1-score up to 57% over the second-best approach with comparable running times". "RiskLoc runs in less than 3 seconds on average on the simpler datasets". Handhabt mehrere Elemente je Cuboid und verschiedene Layer, wenige Parameter. | Heuristischer Score. Partitionierung nimmt gleichverteilte Residuen um 0 und gleichgerichtete Anomalien an, bei gemischten Vorzeichen eingeschränkt (Annahme, Paper nennt Richtung als inferiert). Reine Verhältnis-Metriken: Paper evaluierte Datensatz D mit Quotienten, aber Details nicht geprüft. Benchmarks sind synthetisch, nicht Produktion. | Mittel: ca. 4-6 Stunden für 4 Dimensionen (15 Cuboids, 360 Blätter, trivial klein). |
| MID | Nicht gefunden und nicht geöffnet: nicht verifiziert. | n/a | n/a | n/a |
| Fast Dimensional Analysis (Facebook) | Frequent-Itemset-Mining (Apriori, FP-Growth), Lift-Score. | Kategoriale Logs, sehr skalierbar. | Nicht für Zeitreihen-Abweichungen gegenüber Forecast gebaut. | Mittel. |

Hinweis zur Größe: bei 5x3x4x6 gibt es nur 360 Blätter und 2^4 = 16 Cuboids inklusive Gesamt.
Damit ist eine exhaustive Suche über alle Cuboids ohne MCTS oder Pruning in Millisekunden machbar, das ist der entscheidende Hebel gegenüber den Papern, deren Heuristiken für Millionen Blätter gebaut sind.

#### Top-Übernahmen für Argus

Ranking nach Wirkung pro Stunde.

1. **Adtributor-Kern zuerst implementieren (ca. 1-2 h):**
   EP und JS-Surprise pro Dimension mit TEP 0.67 / TEEP 0.1, mit der Ratio-Variante der EP-Formel für Raten.
   Liefert sofort eine erklärbare "Welche Dimension, welche Werte"-Antwort für den Demo-Fluss.
2. **RiskLoc-artige Kombinationssuche als zweite Stufe (ca. 4-6 h):**
   Deviationsscore, 2-Wege-Partition, r1 - r2 pro Element über alle 16 Cuboids, exhaustiv statt MCTS.
   Deckt Fälle wie "nur DE + Mobile + Paid Search" ab, die Adtributor prinzipbedingt verpasst.
3. **Volumen-Tiering (Uber, ca. 1 h):**
   Segmente nach Anteil am Gesamtvolumen in Top/Mitte/Unten, untere Tiers nur mit strengeren Schwellen und Mindestvolumen.
   Uber: 232 auf 11 Anomalien, davon 95% Rauschen vorher.
4. **Standard-Alert-Anatomie (Uber + ThirdEye, ca. 1-2 h):**
   Status new/ongoing/consecutive, mean diff %, Beitrag %, Änderung in Prozentpunkten, relativer Anteil an Gesamtänderung, "OTHER"-Bucket, SQL-Link pro Zahl.
5. **Metrik-Knoten-Schema nach Minerva (ca. 2 h):**
   Owner, Einheit, Aggregationstyp, Dimensionen, Quell-SQL, Zertifizierungsstatus, Lineage.
   Selbsterweiterung bedeutet: neue Kante startet als draft, wird nach numerischer Validierung (Summe der Effekte = Delta, Toleranz) zu validated.
6. **Kayenta-artiges Verdikt für Maßnahmen-Wirksamkeit (ca. 2 h):**
   Mann-Whitney U plus Toleranzband und Effektgröße, Nodata als eigener Zustand, Pass/Marginal/Fail, Critical-Flag für Top-Metriken.
7. **Playbooks mit Backtesting (DrP, ca. 3 h):**
   Investigations-Schritte als kleine registrierte Analyzer, die auf Alerts auslösen, Ergebnis wird als Annotation am Incident gespeichert, neue Analyzer laufen erst gegen historische Anomalien.
8. **Feedback-Labels, die Regeln erzeugen (Uber + ThirdEye, ca. 2 h):**
   true / expected / not anomaly pro Incident, "expected" erzeugt eine Ausnahmeregel oder ein Planned-Event, Fingerprint-Dedup nutzt dieselben Labels.

**Empfehlung Segment-Suche:**
Zuerst Adtributor (Stufe 1, schnell, robust für einzelne Dimension, erklärbar) in Kombination mit der exakten LMDI-Zerlegung entlang der Formelkanten, dann RiskLoc als Kombinationssuche exhaustiv über die 16 Cuboids.
Als Fallback, falls RiskLoc nicht rechtzeitig sauber läuft: Adtributor rekursiv ohne Ripple-Annahme ist laut RiskLoc-Paper schwach (F1 0.00003 auf A*), daher besser ein einfacher exhaustiver Cuboid-Scan mit Potential-Score (Anteil der Änderung, den ein Kandidat erklärt, geteilt durch Elementzahl) als Eigenbau-Fallback.
Squeeze, HotSpot und MID würde ich nicht implementieren (Clustering- und MCTS-Aufwand ohne Nutzen bei nur 360 Blättern).


## 3. Feature-Liste "alles drin", priorisiert gegen die Rubrik

Must heißt: ohne das fehlt ein bewerteter Moment oder ein Versprechen der Vision bricht.
Should heißt: hebt uns über den Durchschnitt und ist bis zum Freeze realistisch.
Stretch heißt: nur, wenn die Checkpoints pünktlich stehen.
Die Paket-IDs verweisen auf 4.8, die Herkunft nennt das Vorbild aus Abschnitt 2.

### 3.1 Rubrik zu Feature zu Beweis

| Rubrik (Brief laut früherem Bericht 12.1) | Feature | Wo die Jury es sieht |
| --- | --- | --- |
| Graph mit klarer Bedeutung der Beziehungen (Formel, Aufschlüsselung, mögliche Ursache) | vier Kantenarten mit eigenem Test und eigener Farbe | Live-Graph, Legende, Klick auf eine Kante zeigt ihren Test |
| Neue Metrik ordnet sich selbst ein | Platzierungs-Pipeline, Ablageordner und Klartext-Feld | Knoten erscheint, Kantentests werden live grün |
| Formeln und Dimensionen geprüft | Residuum auf 28 Tagen, Summenprobe, neue Dimension | Zertifikat mit Zahlen und Belegen |
| Mehrdeutiges kenntlich | `PROBATION`, "ambiguous", Alternativen im Zertifikat | Fall `app_crash_rate` |
| Durchgehender Lauf ohne Fragen | Tick-Schleife, Aufmerksamkeitsbudget, Ticker | "Watched 214 series, 41 wiggles ignored, 1 anomaly opened" |
| Gute Wahl des nächsten Schritts | feste Eröffnung, danach Rang nach erwartetem Erkenntnisgewinn | Trail mit verworfenen Alternativen |
| Fehlende Daten | Frische zuerst, `pending`, `DATA_ISSUE`, Nachprüfung | Karte "Orders -65 %, not a business incident" |
| Harmlose Änderungen | Kalender verschiebt die Erwartung, Mix gegen Rate | Karte "why I didn't alert" mit Abstand zur Alarmlinie |
| Konkurrierende Erklärungen | Holdout-Check, Ledger, Skeptic | "Ruled out: android-app 8.3.0", Splitscreen |
| Beiträge beziffern | LMDI entlang der Formelkanten, Wirkung in Euro | Balken "Where the change came from", Euro-Wasserfall |
| Belegte Ursache von Hypothese trennen | fünf Urteile, Anteil `unexplained`, "still uncertain" | Kopf des Berichts, Abschnitt "Still uncertain" |
| Drei Momente, System reagiert allein | Chaos-Konsole oder Blind Challenge, Ablageordner | Mission Control, eine Seite |

### 3.2 Graph und Selbst-Erweiterung (40 %)

| Prio | Feature | Paket | Herkunft |
| --- | --- | --- | --- |
| Must | Metrik-Register mit rund 28 Knoten (additiv, Quotient, abgeleitet), Nordstern-Markierung | G1 | Vision 06, Knotenschema nach Airbnb Minerva |
| Must | Vier Kantenarten mit Test: Formel (Residuum), Aufschlüsselung (Summenprobe), Ursache (Lag-Korrelation, BH), Evidenz (Onset und Scope) | G3 | Vision 06 |
| Must | Kantenstatus `VALID`, `SUPPORTED`, `PROBATION`, `PROPOSED`, `BROKEN` und Changelog | G3 | Vision 06 |
| Must | Semantik-Schicht: jede Abfrage wird aus der Metrik-Definition kompiliert und liefert einen Beleg | G2 | Vision 09, Datadog "Copy SQL" |
| Must | Platzierung einer Definitionsdatei mit Zertifikat | G4 | Vision 07 |
| Must | Fan-out-Wächter: fehlerhafter Join in der Metrik-SQL wird mit Faktor und Reparatur-Diff gemeldet | G4 | Technik-Probe 7.4 |
| Must | Drei Musterfälle: EXACT `refund_rate`, NEW DIMENSION `gmv_by_seller_type`, AMBIGUOUS `app_crash_rate` | G4, U7 | Vision 07 |
| Must | Live-Graph mit Kantenfarben nach Status, neue Knoten erscheinen sichtbar | U2, U7 | Vision 11 |
| Should | Klartext-Metrik ("refund rate for new sellers") mit Prüfung und höchstens zwei Reparaturen | G5 | Vision 07 |
| Should | Alias-Erkennung ("this already exists as X") | G4 | Vision 07 |
| Should | Neuprüfung jeder Kante je Takt, Graph-Drift-Hinweis, gebrochene Identität als Datenindiz | G3, G6 | Vision 06 |
| Should | Monitor-Backtest bei der Registrierung ("would have fired twice in 28 days") | G6 | Vision 07, Meta DrP (Playbooks vor Einsatz rückgetestet) |
| Should | Kanten-Evidenz im Graphen anklickbar (Residuum, Korrelation, Beleg) | U2 | keiner der untersuchten Anbieter prüft Kanten gegen Daten |
| Stretch | Graph-Drift mit Reparatur-Diff auf der Bühne | G6 | Vision 14 |
| Stretch | Gelernte Monitore nach jedem Incident, Standing Orders in Klartext mit Rückbestätigung | G7 | Vision 10, Rückbestätigung als JSON-Echo |
| Stretch | Export im Format von dbt MetricFlow oder OSI | G1 | Vision 07 |

### 3.3 Autonomes Monitoring und Untersuchung (40 %)

| Prio | Feature | Paket | Herkunft |
| --- | --- | --- | --- |
| Must | Durchgehende Schleife auf der Simulationsuhr | B7 | Vision 16 |
| Must | Frische zuerst: `pending`-Stunden, Urteil `DATA_ISSUE`, Nachprüfung nach dem Nachladen | B1, B3 | Vision 08, Prinzip 3, Kayenta ("no data" als eigener Zustand) |
| Must | Erwartung mit Kalender: geplante Ereignisse verschieben das Band, Urteil `EXPECTED` | B1, B3 | Vision 08, Amplitude und Loops prüfen Ereignisse als Kandidaten |
| Must | Robuste z-Werte je Wochenstunde, z für Raten, CUSUM mit Onset-Datierung, Regeln für Öffnen und Schließen | B1 | Vision 08, Anodot (Abweichung mal Dauer) |
| Must | Aufmerksamkeitsbudget von oben nach unten mit Volumen-Stufen | B1 | Vision 08, Uber uVitals (232 auf 11 Anomalien durch Stufen) |
| Must | Feste Eröffnung: LMDI, Mix gegen Rate, Segmentsuche über alle 15 Kombinationen mit Abstiegsregel | B2, B3 | Vision 09, Adtributor (Schwellen 67 % und 10 %), RiskLoc, Technik-Probe 7.4 |
| Must | First-Cause-Test und Holdout-Check, Evidenz aus den Logs | B3 | Vision 09 |
| Must | Fünf Urteile, Stoppregel, Wirkung in Euro gegen die Erwartung | B3 | Vision 09 |
| Must | Ein Problem, ein Incident: Fingerabdruck, Zusammenführen, Zustände, Wiederöffnen | B7 | Vision 10, ThirdEye und uVitals (new, ongoing) |
| Must | Bericht mit Belegen, Zahlenprüfung, Rückfall auf Vorlage, läuft ohne Sprachmodell | U6, B6 | Vision 04, Prinzipien 1 und 7 |
| Should | Hypothesen-Ledger: Vorhersage zuerst, typisierte Werkzeuge, Rang nach Erkenntnisgewinn | B4 | Vision 09, Datadog Bits AI SRE |
| Should | Skeptic in eigenem Kontext: Placebo, Holdout, Köder, Rückwärts-Lag | B5 | Vision 09, Resolve.ai, Monte Carlo (parallele Hypothesen) |
| Should | Kostenanzeige je Untersuchung (Abfragen, Sekunden, Euro) | B6, U8 | Datadog (rund 4 USD und 2 Minuten) |
| Should | Vertrauen aus Prüfungen berechnet statt vom Modell vergeben | B3 | Gegenstück zu Mixpanel (High, Medium, Low als Modell-Etikett) |
| Should | Trichter im Ticker: Reihen beobachtet, Wackler ignoriert, Anomalien, Incidents | B1, U1 | Anodot (4 Mio. Metriken zu 147 Incidents) |
| Should | SRM-artige Prüfung der Segmentanteile gegen Teil-Ladungen (Chi-Quadrat) | B1 | Statsig |
| Should | Explorationsanteil von 10 % für leise Ecken, Urteils-Gedächtnis, Kalibrierung (Brier) | B8 | Vision 08 und 10 |
| Stretch | Aufteilung in Euro bei zwei Ursachen (Shapley) für den Margen-Fall | B2, W8 | Vision 12 |
| Stretch | Austauschbare Erwartung mit MSTL und konformen Intervallen | B1 | Vision 08 |
| Stretch | Sequenzieller Test für die stündliche Prüfung | B1 | Statsig |
| Stretch | Morning Brief, Red-Team-Agent | U6, W8 | Vision 11 und 14 |

### 3.4 Demo, Beweis und Auftritt (20 %)

| Prio | Feature | Paket | Herkunft |
| --- | --- | --- | --- |
| Must | Drei Momente auf einer Seite, ohne Eingriff eines Menschen | U1 bis U7 | Brief |
| Must | "Click the SQL": Beleg öffnen, neu ausführen, gleicher Hash | U5, G2 | Vision 14 |
| Must | Chaos-Konsole mit Seed auf dem Bildschirm, Uhr und Tempo | W6, U1 | Vision 11 |
| Must | Wiedergabemodus als Rückfallebene, Anzeige "live" oder "Wiedergabe" | U1 | Plan |
| Must | 3-Minuten-Video, README, Abgabetext | U12 | Vision 15 |
| Should | Blind Challenge mit Commitment und Nachrechnen auf dem Handy | W6, U9 | Vision 14 |
| Should | Argus Bench gegen zwei Baselines mit pass@1 und pass^k, ruhige Wochen, ein ehrlicher Fehlgriff | W7, U8 | Vision 13, Causely und ORCA-bench (gesunde Kontrollfälle) |
| Should | An-Aus-Vergleich "ohne Skeptic" und "ohne Graph" in der Bench | W7 | Resolve.ai (Verifier ohne veröffentlichte Ablation) |
| Should | Bewertung in fünf Stufen, ein sicheres Fehlurteil zählt 0 | W7 | Traversal |
| Should | Standardspalten je Segment: Änderung in Prozent, Beitrag in Punkten, Anteil an der Gesamtänderung, Rest "OTHER" | B2, U5 | LinkedIn ThirdEye, Snowflake Top Insights |
| Should | Skeptic-Splitscreen, animierter Lauf mit Kamera | U11, U2 | Vision 11 |
| Should | MCP-Server | U10 | Vision 11 |
| Should | Beleg auch im BigQuery-Dialekt (sqlglot-Transpile) | U11 | Almedia nutzt BigQuery |
| Should | Cashback-Postback-Szenario | W5 | Vision 12, Frage 2 |
| Stretch | Euro-Wasserfall mit Counterfactual-Regler, Vorher-Nachher-Streudiagramm | U11 | Vision 11, Power BI |
| Stretch | Slack-Vorschau, Sprachnotiz | U6 | Vision 11 |
| Stretch | SEO-Szenario (siehe 3.5) | W8 | Auftrag |

### 3.5 Optionaler Stretch: SEO-Szenario "noindex-Release"

Der Fall prüft, was die Kern-Szenarien nicht prüfen: eine schleichende Drift statt eines Sprungs und eine Ursache, die Tage vor der Wirkung liegt.

- **Ereignis.**
  Ein Web-Release setzt auf den Kategorieseiten eines Landes versehentlich `noindex` oder entfernt sie aus der Sitemap.
- **Wirkung.**
  Der organische Kanal verliert über mehrere Tage Sitzungen, etwa 3 bis 5 % je Tag, weil Seiten nach und nach aus dem Index fallen.
- **Falle.**
  Keine einzelne Stunde ist auffällig, die Gesamtbestellungen fallen nur leicht, und bezahlte Kanäle gleichen einen Teil aus, wodurch die Werbekosten steigen.
- **Was Argus zeigen muss.**
  CUSUM öffnet die Anomalie und datiert den Beginn auf den Tag des Releases.
  Die Zerlegung zeigt `sessions` als Träger, die Segmentsuche `channel=organic` im betroffenen Land.
  Die Evidenz ist der Deploy mit passendem Scope, der Holdout sind andere Länder mit demselben Release-Zug, aber ohne die Vorlagenänderung.
- **Verbindung zu Moment 3.**
  Die neue Metrik `indexed_pages` (aus einem Crawl-Log) bekommt eine Ursachenkante zu den organischen Sitzungen mit einem Lag von ein bis drei Tagen und erklärt den Fall beim nächsten Lauf.
- **Aufwand.**
  Rund 2 bis 3 Agentenstunden: `log_crawl_stats`, ein Szenario in W8, ein Lag-Fenster in Tagen statt Stunden.
- **Einordnung.**
  Nur bauen, wenn C4 pünktlich steht.
  Im Pitch reicht sonst ein Satz, dass dieselbe Mechanik den Fall trägt.

## 4. Bauplan für 4 Personen und die Agenten-Flotte

### 4.1 Leitlinien

1. **Drei Momente zuerst.**
   Die Demo zählt genau drei Momente (Fehler, harmlose Änderung, neue Metrik), und die übrigen 80 % bewerten die Tiefe dahinter.
   Bis Sa 22:30 laufen Moment 1 und 2 durchgehend ohne Sprachmodell, bis So 03:15 Moment 3.
2. **Verträge vor Code.**
   Sechs Verträge (4.3) werden in der ersten Stunde eingefroren.
   Danach arbeitet jede Lane gegen Verträge und Fixtures, nicht gegen den halbfertigen Code der anderen.
3. **Deterministischer Kern zuerst, Sprachmodell danach.**
   Das ist Prinzip 7 der Vision ("Works with the LLM switched off") und zugleich die Rückfallebene für die Bühne.
4. **Die Bench ist die Integrationsprüfung.**
   Jeder Fehler der Bench wird ein Ticket mit einem Test, der ihn reproduziert.
   Was die Bench nicht besteht, kommt nicht in das Menü der Blind Challenge.
5. **Schlaf wird nicht verschoben.**
   Ein verfehlter Checkpoint kostet Umfang (Streichliste 4.14), nicht Schlaf.
6. **Eine Lane, ein Mensch, ein Ordnerbereich, zwei bis vier Agenten.**
   Agenten ändern nur Dateien ihrer Lane.
   Eine Vertragsänderung braucht die Zustimmung von Erzeuger und Abnehmer.
7. **Ehrlichkeit ist ein Feature.**
   Seed auf dem Bildschirm, ein ehrlicher Fehlgriff in der Bench, "LLM aus" als Schalter, Anzeige "live" oder "Wiedergabe".

### 4.2 Architektur

```
 MockMart (Simulator)              Argus (ein Prozess: Laufzeit + API)                    Oberflächen
+-------------------+   C1    +---------------------------------------------------+  C5  +-------------------+
| sim   scenarios   |-------->| semantic (C2, C6)   graph (C3)   cartographer     |----->| Mission Control   |
| delivery   clock  | world   | watcher -> investigator -> skeptic -> narrator    | SSE  | (React, 1 Seite)  |
| truth (versteckt) | .duckdb | incidents   runtime (Tick-Schleife)   llm         | REST | Handy-Seite (QR)  |
+-------------------+         +---------------------------------------------------+      | MCP-Server        |
        |                                   ^                  | C4 (Befunde, Belege)    +-------------------+
        | truth.duckdb                      | HTTP             v
        +-------------------> bench (Läufe, Bewertung, Baselines, Ergebnis-JSON) -----> Bench-Tabelle im UI
```

Datenfluss je Takt (ein Takt ist eine Simulationsstunde):

1. `delivery` liefert die Batches, deren `ingested_at` erreicht ist, in `world.duckdb` und schreibt `log_ingestion`.
2. `cartographer` prüft ein Budget an Kanten neu (Formel und Aufschlüsselung) und meldet `BROKEN`.
3. `watcher` prüft Frische, verteilt das Aufmerksamkeitsbudget, bewertet Reihen und öffnet Anomalien.
4. `investigator` läuft je Anomalie auf einem festen Stand `as_of` (Eröffnung, dann Ledger), `skeptic` versucht zu widerlegen.
5. `incidents` vergibt Fingerabdruck und Zustand, `narrator` schreibt Bericht oder "why I didn't alert"-Notiz.
6. `runtime` schickt jeden Schritt als Ereignis (C5) an die Oberfläche.

### 4.3 Die sechs Verträge (Stunde 1, danach eingefroren)

Quelle der Wahrheit sind pydantic-Modelle in `src/argus/contracts/`.
Daraus entstehen JSON Schema und TypeScript-Typen (`make contracts`), CI bricht ab, wenn die erzeugten Dateien nicht aktuell sind.

| Vertrag | Inhalt | Erzeuger | Abnehmer |
| --- | --- | --- | --- |
| C1 Welt-Schema | `contracts/schema.sql`: Faktentabellen im Stundenraster und Logs, Namensregeln | P2 | P1, P3 |
| C2 Metrik-Definition | YAML mit `name`, `description`, `sql` (mehr gibt der Beitragende nie an) | P1 | alle |
| C3 Graph | `Node`, `Edge`, `EdgeTest`, Status, `GraphChange`, `Certificate` | P1 | P3, P4 |
| C4 Befunde | `Receipt`, `Anomaly`, `Findings`, `Incident`, `Note` | P3 | P4, P2 (Bench) |
| C5 Ereignisse und API | SSE-Ereignistypen, REST-Routen, OpenAPI | P4 | alle |
| C6 Werkzeuge | typisierte Werkzeuge für Investigator, Skeptic und MCP | P3 mit P1 | P3, P4 |

**C1 Welt-Schema (Pflichtregeln).**

- Rohtabellen `raw_*` haben `ts` (Stundenbeginn, UTC), die Dimensionsspalten, additive Messwerte, `batch` und `ingested_at`.
- Metriken fragen nur Sichten `fact_*` ab: eine Zeile je Rasterschlüssel, summiert über alle Batches mit `ingested_at <= getvariable('as_of')`.
  So bleibt das angezeigte SQL lesbar, und der Stand `as_of` steht im Beleg (in der Technik-Probe 7.4 so gebaut).
- Zu jeder Sicht ist der Rasterschlüssel dokumentiert, der Cartographer braucht ihn für die Fan-out-Prüfung.
- Dimensionsnamen sind überall gleich: `country` (DE, FR, UK, ES, NL), `platform` (android, ios, web), `channel` (organic, paid, email, direct), `category` (6 Werte).
- Zusatzdimensionen nur dort, wo sie fachlich leben: `provider` (PayCo, CardHub, WalletGo) an Zahlungen, `app_version` an App-Gesundheit, `seller_type` (1P, 3P) an Bestellungen, `device_cluster` an Rewards.
- Faktentabellen: `fact_funnel_hourly`, `fact_payments_hourly`, `fact_orders_hourly`, `fact_ads_hourly`, `fact_search_hourly`, `fact_inventory_hourly`, `fact_app_health_hourly`, `fact_refunds_hourly`, `fact_rewards_hourly`.
- Logs: `log_ingestion`, `log_deploys`, `log_calendar`, `log_provider_status`, `log_purchase_orders`, `log_ad_budgets`, `log_experiments`.
- Jeder Log-Eintrag hat `ts`, eine `scope`-Spalte als JSON (welche Segmente betroffen sind) und bei Kalenderereignissen `planned_uplift` als JSON.
- Die Wahrheit liegt nur in `truth.duckdb` (Tabelle `injected_events`), das Paket `argus` bekommt nie einen Pfad dorthin.

**C2 Metrik-Definition.**

```yaml
# metrics/refund_rate.yml
name: refund_rate
description: Share of orders refunded within the hour
sql: |
  SELECT ts, country, category,
         SUM(refunds)::DOUBLE / NULLIF(SUM(orders), 0) AS value
  FROM fact_refunds_hourly
  JOIN fact_orders_hourly USING (ts, country, category)
  GROUP BY ALL
```

Erlaubte SQL-Form in der Hackathon-Fassung: ein `SELECT` mit `ts`, Dimensionsspalten und genau einem Wertausdruck aus Aggregaten (`SUM`, `COUNT`, Quotient, Produkt, Differenz), `JOIN ... USING` auf Rasterschlüsseln, `WHERE`-Filter, `GROUP BY`.
Alles andere lehnt der Cartographer mit einer klaren Begründung ab, statt zu raten.

**C3 Graph.**

```json
{
  "node": {
    "id": "refund_rate", "kind": "ratio", "unit": "share", "north_star": false,
    "numerator": "SUM(refunds)", "denominator": "SUM(orders)",
    "tables": ["fact_refunds_hourly", "fact_orders_hourly"],
    "dims": ["country", "category"], "source": "metrics/refund_rate.yml", "state": "watching"
  },
  "edge": {
    "id": "e_gmv_formula", "kind": "formula", "target": "gmv", "sources": ["orders", "aov"],
    "expr": "orders * aov", "status": "VALID", "weight": 1.0, "provenance": "seed",
    "test": {"name": "identity_residual", "window_days": 28, "median_rel": 0.0003, "p95_rel": 0.004,
             "passed": true, "receipt": "r_000123"}
  }
}
```

- `kind` der Kante: `formula`, `breakdown`, `cause`, `evidence`.
- `status`: `VALID` (Formel, Aufschlüsselung) oder `SUPPORTED` (Ursache, Evidenz), `PROBATION` (halbes Gewicht), `PROPOSED` (Gewicht 0), `BROKEN`.
- `provenance`: `seed`, `lineage`, `arithmetic`, `llm`, `learned`.
- Jede Statusänderung ist ein `GraphChange` im angehängten Changelog (`state/graph_changelog.jsonl`).

**C4 Befunde und Belege.**

```json
{
  "receipt": {"id": "r21", "sql": "SELECT ...", "as_of": "2026-11-17T14:00:00Z",
              "result_hash": "sha256:9f2c...", "rows": 5, "ms": 12},
  "anomaly": {"id": "an_0091", "node": "orders", "segment": {"country": "DE"}, "direction": "down",
              "onset": "2026-11-17T11:00:00Z", "observed": 352, "expected": 387, "band": [371, 404],
              "z": -5.2, "cusum": 7.1, "eur_per_hour": -2100, "data_confidence": 1.0, "receipts": ["r17"]},
  "findings": {"incident_id": "INC-0042", "verdict": "SUPPORTED_CAUSE",
               "root": {"node": "pay_success", "segment": {"country": "DE", "platform": "android", "provider": "PayCo"},
                        "evidence": {"log": "log_provider_status", "ref": "ps_118"}},
               "decomposition": [{"node": "pay_success", "share": 0.88, "receipt": "r21"},
                                 {"node": "unexplained", "share": 0.02}],
               "impact": {"orders_per_hour": -35, "gmv_eur_per_hour": -2100, "eur_so_far": -6700, "receipt": "r29"},
               "ruled_out": [{"hypothesis": "release android-app 8.3.0", "prediction": "all countries drop",
                              "result": "refuted", "reason": "holdout normal", "receipts": ["r26"]}],
               "uncertain": ["fault inside PayCo or in our PayCo integration"],
               "trail": [{"step": 1, "kind": "freshness", "tool": "check_freshness", "result": "ok", "receipts": ["r12"]}],
               "skeptic": {"verdict": "upheld", "checks": [{"name": "placebo", "result": "0/8"}]},
               "cost": {"queries": 9, "seconds": 41, "eur": 0.38},
               "suggested_action": {"text": "Route DE-Android card payments to CardHub", "needs_approval": true}}
}
```

- `verdict`: `SUPPORTED_CAUSE`, `HYPOTHESIS`, `EXPECTED`, `DATA_ISSUE`, dazu immer der Anteil `unexplained`.
- Jede Zahl im Bericht trägt eine Beleg-ID, sonst fällt der Bericht durch die Zahlenprüfung.

**C5 Ereignisse und API.**

- SSE unter `/events` mit den Typen `tick`, `attention`, `edge_status`, `anomaly_opened`, `investigation_step`, `skeptic_step`, `incident_updated`, `note_logged`, `graph_changed`, `bench_progress`, `challenge_state`.
- REST: `GET /graph`, `GET /incidents`, `GET /incidents/{id}`, `GET /notes`, `GET /receipts/{id}`, `POST /receipts/{id}/rerun`, `POST /metrics` (Datei oder Klartext), `POST /chaos/inject`, `POST /challenge/commit`, `POST /challenge/reveal`, `GET /bench/results`, `POST /incidents/{id}/feedback`.
- Die Oberfläche hat einen Wiedergabemodus, der `fixtures/events.jsonl` oder eine Aufzeichnung abspielt.

**C6 Werkzeuge (alle liefern Ergebnis plus Belege, keines nimmt freies SQL an).**

`get_series`, `check_freshness`, `check_identities`, `decompose_formula`, `mix_rate_split`, `segment_search`, `list_events`, `holdout_check`, `placebo_test`, `lag_test`, `counterfactual_impact`.

### 4.4 Architekturentscheidungen, die späte Überraschungen verhindern

1. **Ein Laufzeitprozess.**
   DuckDB 2.0 erlaubt Schreibzugriff nur einem Prozess, mehrere Leser nur ohne Schreiber (Beleg in Abschnitt 7, Tech-Stack).
   Deshalb laufen Simulator-Lieferung, Argus und API in einem Prozess, MCP-Server und Bench sprechen über HTTP oder eigene Dateien.
2. **Fester Stand `as_of` für jede Abfrage.**
   Jede Abfrage läuft gegen Sichten, die `ingested_at <= as_of` filtern.
   Nur so liefert "Click the SQL, re-run, same hash" auch dann denselben Hash, wenn inzwischen verspätete Daten eingetroffen sind.
   In der Technik-Probe bestätigt: gleicher Hash beim Re-Run mit festem Stand, anderer Hash nach dem Nachladen ohne festen Stand.
   Resolve.ai friert aus demselben Grund alle Werkzeuge auf den Zeitpunkt des Alarms ein (Abschnitt 2.6).
3. **Verspätung über Mikro-Batches.**
   Der Simulator rechnet die volle Stunde und teilt sie in vier Batches, die einzeln eintreffen.
   Teilweise Daten sind dann einfach fehlende Batches, und `SUM` bleibt die einzige nötige Aggregation.
4. **Wahrheit strikt getrennt.**
   Ein Test stellt sicher, dass `argus` den Pfad zu `truth.duckdb` nicht kennt.
   Das ist die Grundlage der Aussage "It could not have peeked".
5. **Kanonischer Ergebnis-Hash.**
   Zeilen sortiert, Zahlen auf 10 signifikante Stellen gerundet, dann SHA-256.
   Ohne diese Regel scheitert der Hash-Vergleich an Gleitkomma-Rauschen.
6. **Köder im Log.**
   Der Simulator erzeugt laufend harmlose Deploys, Budgetänderungen und Experimente.
   Sonst ist "der einzige Deploy im Log" immer die Ursache, und der Holdout-Check beweist nichts.
7. **Kleine Segmente.**
   Viele der 360 Segmente haben nachts einstellige Zählwerte, MAD ist dann 0 und z unendlich.
   Regel: Mindestvolumen je Reihe, Varianzuntergrenze aus Poisson oder Binomial, Abstieg in Kinder nur bei genug Volumen (Volumen-Stufen wie bei Uber uVitals, Abschnitt 2).
8. **Uhr und Untersuchung.**
   Bei Tempo x1800 dauert eine Simulationsstunde 2 Sekunden, eine Untersuchung aber bis zu 90 Sekunden.
   Die Untersuchung arbeitet auf `as_of`, und im Demo-Modus bremst die Uhr auf x60, solange eine Untersuchung läuft.
9. **Sprachmodell hinter einer Hülle.**
   Ein Modul `llm` mit Modell je Rolle, JSON-Schema-Ausgabe, Zeitlimit, Kostenzähler, Aufzeichnung und Wiedergabe sowie globalem Aus-Schalter.
10. **Schwellen werden gemessen, nicht geraten.**
    Die Regeln aus der Vision (|z| > 4, 2 von 3 Stunden > 3, CUSUM > h) werden auf "nothing happened"-Wochen kalibriert, die Fehlalarmrate steht in der Bench.
11. **Fan-out-Wächter für jede neue Metrik.**
    Die Beispielmetrik der Vision (`fact_refunds_hourly JOIN fact_orders_hourly USING (ts, country, category)`) liefert in der Technik-Probe exakt das 12-Fache der wahren Quote, sobald Bestellungen zusätzlich `platform` und `channel` tragen (3 mal 4 Zeilen je Schlüssel).
    Der Cartographer prüft deshalb statisch, ob die Join-Schlüssel das Raster jeder Seite abdecken, und numerisch, ob der Wert ein konstantes ganzzahliges Vielfaches eines Formelkandidaten ist.
    Trifft das zu, lautet der Befund "join fan-out, factor 12" mit Reparatur-Diff (beide Seiten vor dem Join auf die Schlüssel aggregieren).
12. **Die Segmentsuche steigt ab, solange die Kinder ungleich betroffen sind.**
    Die Regel der Vision "einfachste Kombination, die 67 % erklärt" bleibt in der Technik-Probe bei `country = DE` stehen (Erklärungsanteil 0,99), obwohl nur Android betroffen ist (Android -29 %, iOS -1 %, Web 0 %).
    Richtig ist: die gröbste Zelle wählen, deren Kinder gleichmäßig abweichen, sonst in das abweichende Kind absteigen (der Ripple-Effect-Gedanke aus HotSpot und RiskLoc).
13. **Rauschen im Simulator auf mehreren Ebenen.**
    Mit reinem Poisson- und Binomial-Rauschen schwankt die Summe von 6.900 Bestellungen je Stunde nur um 1,2 %, ein Rückgang um 3 % wäre oben sofort sichtbar und die Falle der Vision ("total only -3 %, below the alert line") verschwindet.
    Der Simulator braucht zusätzlich multiplikative Faktoren je Stunde und je Land (lognormal, Variationskoeffizient 2 bis 4 %).
14. **Streuung aus vielen Punkten schätzen.**
    "MAD at this hour of week" über vier Wochen sind vier Punkte, das ist zu wenig und bei kleinen Zählwerten oft 0.
    Besser: Residuen gegen die Erwartung über alle Stunden der letzten vier Wochen bilden, je Reihe robust skalieren und nach unten durch die Poisson- oder Binomial-Streuung begrenzen.

### 4.5 Repo-Struktur (`argus-analyst/argus`, privat)

```
argus/
  README.md  Makefile  pyproject.toml  uv.lock  .env.example  CODEOWNERS
  contracts/                 # schema.sql, JSON Schemas (erzeugt)
  metrics/                   # eine YAML-Datei je Metrik, Ablageordner für neue Metriken
  graph/seed_edges.yml       # von Hand geschriebene Start-Kanten
  src/argus/
    contracts/               # pydantic-Modelle, einzige Quelle für C3 bis C6
    semantic/                # SQL-Compiler aus Metrik-Definitionen (sqlglot), Runner, Belege
    graph/                   # Register, Kantentests, Lebenszyklus, Changelog
    cartographer/            # Platzierung, Zertifikat, Drift, Klartext-Metrik
    watcher/                 # Frische, Erwartung, Bewertung, Aufmerksamkeitsbudget
    decompose/               # LMDI, Mix und Rate, Segmentsuche, Wirkung in Euro (reine Funktionen)
    investigator/            # feste Eröffnung, Ledger, Urteile, Stoppregel
    skeptic/                 # Widerlegungsprüfungen, Skeptic-Modell
    narrator/                # Bericht, Zahlenprüfung, Vorlagen
    incidents/               # Fingerabdruck, Zustände, Gedächtnis, gelernte Monitore
    llm/                     # Claude-Hülle: Budget, Zeitlimit, Aufzeichnung und Wiedergabe
    runtime/                 # Tick-Schleife, Ereignisbus, Zustand
    api/                     # FastAPI: REST und SSE
    mcp/                     # MCP-Server über die HTTP-API
  src/mockmart/
    sim/  scenarios/  delivery/  truth/
  src/bench/                 # Runner, Bewerter, Baselines, Bericht
  web/                       # Vite + React + TypeScript
    src/screens/             # mission-control, incident, graph-changes, bench, challenge
    src/components/          # graph, feed, trail, report, charts, ui
    src/vendor/kairos/       # kopierte Chart-Bausteine mit MIT-Hinweis
    src/contracts/           # erzeugte TypeScript-Typen
  fixtures/                  # kleines world.duckdb, graph.json, events.jsonl, findings.json
  tests/                     # unit, property, e2e (Szenario zu Urteil)
  docs/                      # research/, decisions.md, demo-script.md, pitch.md
  scripts/                   # make_world.py, record_replay.py, run_demo.sh
```

`make setup`, `make world`, `make check`, `make demo`, `make bench` und `make contracts` sind die einzigen Befehle, die jemand kennen muss.

### 4.6 Tech-Stack

| Schicht | Wahl | Version (Stand 21.11.) | Begründung |
| --- | --- | --- | --- |
| Daten | DuckDB (Python) | 2.0.1 | lokal, schnell, SQL nah an BigQuery, `GROUP BY ALL`, `EXPLAIN` |
| SQL-Analyse | sqlglot | 30.33.0 | Parsen, Lineage, Umschreiben mit zusätzlichem `GROUP BY`, Dialekt DuckDB zu BigQuery |
| Statistik | numpy, scipy | aktuell | robuste z-Werte, CUSUM, Korrelation, Benjamini-Hochberg |
| Verträge | pydantic v2 | aktuell | eine Quelle für JSON Schema und TypeScript-Typen |
| API | FastAPI | 0.165.0 | SSE ist eingebaut (`fastapi.sse.EventSourceResponse`), kein Zusatzpaket nötig |
| Sprachmodell | Anthropic SDK | 2.12.0 | Structured Outputs über `output_config.format`, Modelle je Rolle wie in der Vision |
| MCP | `mcp` (Python SDK) | 2.3.0 | README nutzt `MCPServer`, Transporte stdio und Streamable HTTP |
| Oberfläche | Vite, React, TypeScript | aktuell | eine Seite, Wiedergabemodus |
| Graph-Ansicht | React Flow (`@xyflow/react`) | 13.0.2 | eigene Knoten, Layout mit `@dagrejs/dagre` 3.1.3 (von React Flow empfohlen) |
| Charts | Kairos-Charts (kopiert) | Commit zum Zeitpunkt der Kopie | handgezeichnetes SVG ohne Chart-Bibliothek, siehe unten |
| Tests | pytest, hypothesis, ruff, vitest | aktuell | Eigenschaftstests für Zerlegung und Simulator |
| Optional | statsforecast | 2.1.1 | MSTL mit konformen Intervallen als austauschbare Erwartung (Stretch) |

**Modelle je Rolle** (wie in der Vision, Abschnitt 05): Planer `claude-sonnet-5-5`, Skeptic und Narrator `claude-opus-5-5`, Kanten-Vorschläge `claude-haiku-5-5`.
Agenten, die LLM-Aufrufe schreiben, lesen vorher die aktuelle Anthropic-Doku zu Structured Outputs und Tool Use.

**Kairos-Charts (nur lesen, nichts am Kairos-Repo ändern).**
Geprüft per `gh-axi api` am 21.11.: `BatuCani/kairos-studio` ist privat und MIT-lizenziert ("Copyright (c) 2026 BatuCani").
Der Ordner `src/renderer/screens/analytics/` enthält `TimeChart.tsx`, `CurveChart.tsx`, `BreakdownBars.tsx`, `HourHeatmap.tsx`, `Sparkline.tsx`, `chart-frame.ts` und `analytics.css`.
`TimeChart` nimmt `title`, `kind` (`line` oder `bars`), `days`, `values`, `format`, `today`, `label`, `head` und `axis`, ist per Tastatur bedienbar und führt dieselben Werte als Tabelle für Screenreader.

| Kairos-Baustein | Einsatz in Argus | Nötige Erweiterung |
| --- | --- | --- |
| `TimeChart.tsx` | Zeitreihe eines Knotens auf der Incident-Seite | Stunden statt Tage, Erwartungsband, Markierung für Onset, Ereignisse aus dem Log |
| `Sparkline.tsx` | Mini-Verlauf in Graph-Knoten und Feed-Karten | Farbzustand je Knotenstatus |
| `BreakdownBars.tsx` | LMDI-Balken "Where the change came from" und Segmentanteile | negative Werte, Rest "unexplained" |
| `HourHeatmap.tsx` | Aufmerksamkeit je Stunde und Wochentag, Tagesform für den Ad-Pacer-Fall | Skala für z-Werte |
| `chart-frame.ts`, `analytics.css` | gemeinsamer Rahmen und Stil | Farben der Vision |

Die Dateien hängen an `data/model/analytics.ts` (`chartScale`, `dayTicks`, `valueRuns`), `hooks/use-element-width`, `lib/utils` (`cn`) und `strings/en`, diese Helfer werden mitkopiert.
Ob vorhandener eigener Code erlaubt ist, war öffentlich nicht geregelt (früherer Bericht, 6.3), deshalb die Kopie in README und Abgabe offenlegen.
Rückfallebene, falls Vorab-Code nicht erlaubt ist: Die vier Charts sind zusammen wenige hundert Zeilen SVG und in rund 2 Agentenstunden neu geschrieben.

### 4.7 Lanes, Personen und Agenten

| Lane | Person | Verantwortet | Rubrik | Agenten gleichzeitig |
| --- | --- | --- | --- | --- |
| G Graph | P1 | `graph`, `semantic`, `cartographer`, `metrics/` | 40 % Graph | 3 |
| W Welt und Beweis | P2 | `mockmart`, `bench`, Chaos-API, Sealed Envelope, ab Sa abends Integration | Grundlage, Demo | 3 |
| B Gehirn | P3 | `watcher`, `decompose`, `investigator`, `skeptic`, `incidents`, `runtime`, `llm` | 40 % Autonomie | 3 bis 4 |
| U Oberfläche und Auftritt | P4 | `web`, `api`, `mcp`, `narrator`, Demo, Video, Pitch, Abgabe | 20 % Demo | 3 |

Die Zuordnung entspricht 12.5 des früheren Berichts, wer dort schon eine Rolle übernommen hat, behält sie.
P2 wird ab Samstagabend Integrator, weil die Bench ohnehin das ganze System von außen fährt.
Annahme: Die Flotte wird zentral gesteuert, die drei anderen Personen geben ihre Pakete als Issues mit Abnahmetest in das Repo.
Eigene Coding-Agenten der Teammitglieder sind zusätzlich möglich, solange sie die Lane-Grenzen einhalten.

**Vorlage für ein Agenten-Paket** (in jedes Issue kopieren):

```
Package: <ID> <title>
Lane / owner: <G|W|B|U> / <P1..P4>
Goal: <one sentence>
May touch: <folders>            Must not touch: contracts/ (ask the owner), other lanes
Contracts: <C1..C6 it reads or produces>   Fixtures: <files>
Done when: <named tests green>, `make check` green, no new dependency without a note in docs/decisions.md
Out of scope: <what to leave alone>
```

### 4.8 Arbeitspakete

Aufwand in Agentenstunden (Ah) ist meine Schätzung, keine Messung.
Priorität: M Must, S Should, X Stretch (Abschnitt 3).

| ID | Paket | Prio | Ah | Braucht | Fertig, wenn |
| --- | --- | --- | --- | --- | --- |
| K1 | Repo-Skelett: Monorepo, uv, Vite, Makefile, CI, CODEOWNERS, `.env.example` | M | 0,75 | - | frischer Klon: `make setup && make check` grün |
| K2 | Verträge C1 bis C6 als pydantic, JSON Schema, TS-Typen, Fixtures | M | 1,5 | K1 | Schema-Tests und TS-Typprüfung grün |
| W1 | Sim-Kern: kausaler Trichter, Saison, 360 Segmente, 35 Tage, Seed, Rauschen auf mehreren Ebenen | M | 2,5 | K2 | Identitäten exakt bei voller Lieferung, Summe schwankt 2 bis 4 % je Stunde, `make world` unter 60 s |
| W2 | Lieferung und Uhr: Batches, `ingested_at`, Verspätung, `log_ingestion`, Tick, Tempo | M | 1,5 | W1 | Stand `as_of` zeigt nur gelieferte Batches |
| W3 | Logs und Kalender mit Ködern: Deploys, Events mit `planned_uplift`, Provider-Status, Budgets, Experimente | M | 1,5 | W1 | je Tag mehrere harmlose Einträge, Scope als JSON |
| W4 | Kern-Szenarien: PayCo plus Release-Köder, FR-E-Mail-Aktion, Spanien-Mix, Orders-Stau | M | 2,5 | W1 bis W3 | Signatur-Tests je Szenario (zum Beispiel Gesamt-Orders nur -3 %) |
| W5 | Weitere Szenarien: Suche v2.14, NordElec, Cashback-Postbacks | S | 3 | W4 | Signatur-Tests, Wahrheit in `truth.duckdb` |
| W6 | Chaos-API und Sealed Envelope: Zufall oder Auswahl, Commit mit Nonce, Reveal | S | 1,5 | W4 | Hash aus Reveal stimmt, auch im Browser des Handys nachgerechnet |
| W7 | Bench: Runner, Bewerter (fünf Stufen, sichere Fehlurteile zählen 0), zwei Baselines, ruhige Wochen, pass@1 und pass^k, Ergebnis-JSON | S | 3,5 | W4, B3 | `make bench` liefert Tabelle, jeder Lauf aus Seed reproduzierbar |
| W8 | Stretch-Szenarien: Ad Pacer, Ranker, Marge mit zwei Ursachen, SEO-Drift | X | je 1,5 | W5 | Signatur-Tests |
| G1 | Register und Start-Graph: 28 Metriken in `metrics/`, `seed_edges.yml`, Export `graph.json`, Changelog | M | 2 | K2 | Graph lädt, alle Start-Kanten haben einen Test |
| G2 | Semantik-Compiler: `compile(metric, group_by, filters, window, as_of)`, Runner, Belege, kanonischer Hash | M | 2,5 | K2, W1 | gleiche Abfrage, gleicher Hash, auch nach späten Daten |
| G3 | Kantentests und Lebenszyklus: Formel-Residuum, Summenprobe, Evidenz-Abgleich, Lag-Korrelation mit BH, Neuprüfung je Takt | M | 2,5 | G1, G2 | Orders-Stau setzt `orders = payment_successes` auf `BROKEN` |
| G4 | Platzierungs-Pipeline mit Zertifikat: Parsen, Fan-out-Wächter, Kandidaten, Zahlenprüfung, Dimensionen, Alias, Registrierung | M | 3,5 | G2, G3 | `refund_rate` EXACT, `gmv_by_seller_type` NEW DIMENSION, `app_crash_rate` AMBIGUOUS, Metrik mit Fan-out wird mit Faktor und Reparatur-Diff gemeldet |
| G5 | Klartext-Metrik: Text zu YAML und SQL, Prüfen, höchstens zwei Reparaturen | S | 2 | G4, B6 | 8 von 10 Testsätzen platziert, Rest mit ehrlicher Absage |
| G6 | Graph-Drift und Reparatur-Diff, Monitor-Backtest | S | 2 | G3 | geänderte SQL färbt Kante rot, Diff schlägt Reparatur vor |
| G7 | Gelernte Monitore, Standing Orders in Klartext | X | 2,5 | G4, B7 | Monitor entsteht nach Incident, Rückfrage vor dem Scharfschalten |
| B1 | Watcher: Frische, Erwartung mit Kalender, robuste z-Werte, CUSUM, Regeln für Öffnen und Schließen, Budget, Ticker | M | 3 | K2, G2 | ruhige Woche: 0 Anomalien, PayCo: Anomalie binnen 3 Sim-Stunden |
| B2 | Zerlegungs-Bibliothek: LMDI, Mix und Rate, Segmentsuche mit Abstiegsregel, Wirkung in Euro | M | 2,5 | K2 | Anteile summieren zu 100 %, gepflanztes Segment `DE ∧ android` wird gefunden und nicht nur `DE` |
| B3 | Investigator Phase 1 und Urteile: feste Eröffnung, First-Cause-Test, Holdout, Stoppregel, Findings | M | 3,5 | B1, B2, G3 | E2E-1 und E2E-2 grün ohne Sprachmodell |
| B4 | Hypothesen-Ledger mit Planer: Kandidaten aus dem Graphen, Vorhersage zuerst, nur typisierte Werkzeuge | S | 3 | B3, B6 | Trail zeigt je Schritt Vorhersage, Werkzeug, Ergebnis, Entscheidung |
| B5 | Skeptic: Placebo über 8 Wochen, Holdout, Köder, Rückwärts-Lag, Modell in eigenem Kontext | S | 2,5 | B3, B6 | PayCo "upheld", ein gebauter Trugschluss "refuted" |
| B6 | LLM-Hülle: Modelle je Rolle, Schema-Ausgabe, Zeitlimit, Kosten, Aufzeichnung, Aus-Schalter | M | 1,5 | K2 | Wiedergabe ohne Netz, Kosten je Untersuchung im Findings-JSON |
| B7 | Incidents und Laufzeit: Fingerabdruck, Zusammenführen, Zustände, Wiederöffnen, Tick-Schleife, Ereignisbus | M | 3 | B1, K2 | derselbe Fehler erzeugt über 6 Stunden genau einen Incident |
| B8 | Lernen: Urteils-Gedächtnis, Kalibrierung (Brier), Explorationsanteil 10 % | S | 2,5 | B4, B7 | zweiter ähnlicher Fall nennt den früheren, Brier-Wert in der Bench |
| U1 | Mission-Control-Hülle: Layout der Vision, Design-Tokens, SSE-Client, Wiedergabemodus | M | 2 | K1, K2 | Fixture-Wiedergabe zeigt alle vier Regionen |
| U2 | Live-Graph: React Flow, dagre, Knotenzustände, Kantenstatus, Aufmerksamkeit als Wärme, animierter Lauf | M | 3 | U1 | Lauf folgt `investigation_step`, 40 Knoten flüssig |
| U3 | API und SSE: Routen aus C5, OpenAPI, TS-Client | M | 2 | K2 | Vertragstests gegen Fixtures |
| U4 | Feed mit drei Spuren und Karten: Incident, "didn't wake you", Datenproblem, Graph-Änderung | M | 2 | U1 | Karte zeigt Grund und Abstand zur Alarmlinie |
| U5 | Incident-Seite und Trail: Bericht, LMDI-Balken, Zeitreihe mit Band, Beleg-Schublade mit Re-Run und Hash | M | 3,5 | U3, B3 | Klick auf eine Zahl zeigt SQL, Re-Run, gleicher Hash |
| U6 | Narrator: Vorlage, Prosa per Modell, Zahlenprüfung mit Rückfall auf Vorlage, Notiztexte | M | 2,5 | B3, B6 | erfundene Zahl im Text lässt die Prüfung scheitern |
| U7 | Graph-Änderungen: Zertifikat-Karte, "Drop a metric"-Feld, Platzierung live | M | 2,5 | G4, U2 | E2E-3 sichtbar in der Oberfläche |
| U8 | Bench-Seite und Kostenanzeige | S | 1,5 | W7 | Tabelle mit Baselines, pass@1, pass^k, ein Fehlgriff |
| U9 | Blind Challenge: Handy-Seite, QR, Hash-Anzeige, Reveal | S | 2 | W6 | Ablauf mit fremdem Handy im WLAN und über Hotspot |
| U10 | MCP-Server: vier Werkzeuge, Graph als Ressource | S | 2 | U3 | Claude beantwortet "what's broken right now?" mit Belegen |
| U11 | Skeptic-Splitscreen, Euro-Wasserfall, Counterfactual-Regler, BigQuery-Dialekt in der Beleg-Schublade | S | 3 | U5, B5 | Einwände erscheinen live, je Einwand ein Ergebnis |
| U12 | Demo-Paket: Drehbuch, 3-Minuten-Video, 5-Minuten-Pitch, README, Abgabetext | M | Mensch | alle | zwei Proben mit Stoppuhr bestanden |

Summe: rund 85 Agentenstunden für Must und Should, verteilt auf 12 bis 13 gleichzeitige Agenten über etwa 19 Stunden.
Der Engpass ist nicht das Schreiben, sondern Durchsicht und Zusammenführen, deshalb die harten Abnahmetests je Paket.

### 4.9 Zeitplan Stunde für Stunde

Geplant wird gegen die frühere Frist So 16:30 (Vision), die öffentliche Frist ist So 17:45 (Abschnitt 6.1).
Feste Punkte der Veranstaltung: Sa 19:00 Abendessen, So 08:00 Frühstück, So 13:30 Mittagessen, So 18:00 Judging, So 19:00 Live-Pitches.

**Samstag**

| Zeit | Phase | P1 Graph | P2 Welt und Beweis | P3 Gehirn | P4 Oberfläche und Auftritt |
| --- | --- | --- | --- | --- | --- |
| 14:00-14:30 | Kickoff, alle | 5 offene Fragen entscheiden (Abschnitt 5), Rollen, Schlafschicht, Verträge durchgehen | wie P1 | wie P1 | wie P1 |
| 14:30-15:15 | Welle 0 | K2 prüfen, Liste der 28 Metriken und Start-Kanten | Trichter-Modell auf Papier: Raten, Volumen, Saison | Rechenbeispiele für LMDI, Mix und Rate als Tests | K1 prüfen, Layout aus der Vision |
| 15:15-17:00 | Welle 1 | G1, G2 starten | W1, W2 starten | B2, B6 starten, B1 gegen Fixture | U1, U3 starten |
| 17:00 | C1a | Graph lädt aus YAML | `make world` liefert 28 Tage | Zerlegungs-Tests grün | Fixture-Wiedergabe läuft |
| 17:00-18:45 | Welle 1 | G3 starten, G2 abschließen | W3, dann W4 starten | B1 auf echten Sim-Daten, B7 starten | U2, U4 starten |
| 18:45 | **C1 Laufendes Skelett** | Tick, Watcher auf Sim-Daten, SSE, Graph mit Wärme und Ticker | | | |
| 19:00-19:30 | Abendessen, gestaffelt | Agenten laufen weiter | | | |
| 19:30-21:00 | Welle 2 | G4 starten | W4 abschließen, W6 starten | B3 Eröffnung und Urteile | U5, U6 starten |
| 21:00 | C2a | Summenprobe und Formeltest je Takt | PayCo-Szenario mit Wahrheit | PayCo durchgehend in der Konsole | Incident-Seite mit Fixture |
| 21:00-22:30 | Welle 2 | drei Platzierungsfälle in G4 | Aktion, Mix, Orders-Stau, W5 anstoßen | Holdout, Evidenz, `EXPECTED`, `DATA_ISSUE` | Karten, Beleg-Schublade, U7 anstoßen |
| 22:30 | **C2 Zwei Momente** | Fehler und harmlose Änderung laufen in der Oberfläche, Sprachmodell aus | | | Bildschirmaufnahme "Sicherung 1" |
| 22:30-22:45 | Übergabe | Nachtpakete mit Abnahmetest einstellen | W7, W5 einstellen | - | U7, U8, U9, U10 einstellen |
| 22:45-03:15 | Nacht 1 | wach: G5, Moment 3 mit U7, G3 Ursachen-Tests | **schläft** | wach: B4, B5 | **schläft** |

**Sonntag**

| Zeit | Phase | P1 Graph | P2 Welt und Beweis | P3 Gehirn | P4 Oberfläche und Auftritt |
| --- | --- | --- | --- | --- | --- |
| 01:00 | C3a | `refund_rate` mit Zertifikat in der Oberfläche | schläft | Ledger zeigt Vorhersage vor Abfrage | schläft |
| 03:15 | **C3 Drei Momente** | neue Metrik platziert sich allein | | PayCo mit Ledger und Skeptic "upheld" | |
| 03:15-03:30 | Übergabe, alle vier kurz | Nachtpakete G6, Korrekturen | übernimmt Integration | Nachtpakete B8, Korrekturen | übernimmt Oberfläche |
| 03:30-08:00 | Nacht 2 | **schläft** | wach: W7 volle Läufe, Fehler als Tickets mit Test, W6 | **schläft** | wach: U9, U11, U2 Feinschliff, U10 prüfen, Drehbuch |
| 06:00 | C4a | schläft | erste Bench-Tabelle mit beiden Baselines | schläft | Blind Challenge mit fremdem Handy |
| 08:00-08:30 | Frühstück, Stand-up | Bench-Tabelle lesen, Fehlerliste verteilen, Kandidaten für das Challenge-Menü | | | |
| 08:30-10:30 | Welle 4 | Platzierungsfehler aus der Bench beheben | Bench neu fahren, ehrlichen Fehlgriff auswählen | Untersuchungsfehler aus der Bench beheben | Feinschliff, README, Folien-Gerüst |
| 10:30 | **Go/No-Go** | Klartext-Metrik auf die Bühne? | Blind Challenge als Eröffnung? Cashback im Menü? | Planer und Skeptic live oder Wiedergabe? | MCP zeigen? |
| 10:30-11:00 | Welle 4 | letzte Zusammenführungen | Zahlen für die Folie einfrieren | letzte Zusammenführungen | Demo-Rechner vorbereiten |
| **11:00** | **Feature-Freeze** | Tag `freeze`, ab jetzt nur Fehlerkorrekturen mit Test und Zweitblick | | | |
| 11:00-12:00 | Härtung | frischer Klon auf zwei Rechnern | Übung ohne Netz, Übung ohne API-Schlüssel | Aufzeichnung für Wiedergabe | Demo-Drehbuch final |
| 12:00-12:30 | **Probe 1** | alle, mit Stoppuhr und fremdem Handy, eine Person spielt Jury | | | |
| 12:30-14:00 | Video | Video mit P4 | nur P0-Fehler aus Probe 1 | nur P0-Fehler aus Probe 1 | Video aufnehmen und schneiden |
| 13:30 | Mittagessen, gestaffelt | | | | |
| 14:00-14:30 | Abgabe-Paket | README "How to run" | Bench-Ergebnisse mit Commit-Hash | Algorithmus in einem Bild | Text, Video-Upload, Teamangaben |
| 14:30-15:00 | **Probe 2** | alle, mit Ausfall-Übung (WLAN aus, API aus) | | | |
| 15:00-15:30 | Korrekturen | Tag `v1.0-submission` | | | |
| **15:30** | **Abgabe absenden** | 60 Minuten Puffer bis 16:30 | | | |
| 16:30 | Frist laut Vision | | | | |
| 16:30-18:00 | Puffer bis zur öffentlichen Frist 17:45 | Tisch aufbauen, Akkus, eigener Hotspot, Probe 3 um 17:00 | | | |
| 18:00 | Judging | | | | |
| 19:00 | Live-Pitches und Preisverleihung | | | | |

### 4.10 Checkpoints und Abnahmetests

| Checkpoint | Zeit | Bestanden, wenn | Sonst |
| --- | --- | --- | --- |
| C1 Laufendes Skelett | Sa 18:45 | `make demo` zeigt Takt, Wärme und Ticker auf echten Sim-Daten | Oberfläche bleibt auf Wiedergabe, Kern geht vor |
| C2 Zwei Momente | Sa 22:30 | E2E-1 und E2E-2 grün ohne Sprachmodell, sichtbar in der Oberfläche | W5, U8, U9 aus der Nacht streichen, Nacht 1 holt C2 nach |
| C3 Drei Momente | So 03:15 | E2E-3 grün, Ledger und Skeptic auf PayCo | Skeptic nur deterministisch, Klartext-Metrik streichen |
| C4 Beweis | So 08:00 | Bench-Tabelle mit Baselines, Blind Challenge im WLAN | Blind Challenge wird Tisch-Moment statt Eröffnung |
| Freeze | So 11:00 | drei Momente dreimal hintereinander fehlerfrei | Menü der Challenge auf bestandene Szenarien kürzen |

**E2E-1 Fehler.**
Szenario `payco_outage` mit zufälliger Startstunde und zufälligem Seed.
Spätestens 3 Simulationsstunden nach Beginn gibt es genau einen Incident mit Urteil `SUPPORTED_CAUSE`.
Wurzel ist `pay_success`, das Segment enthält `country=DE` und `platform=android`, der Provider ist PayCo.
Das Release steht unter "ruled out" mit Grund Holdout.
Jede Zahl im Bericht hat einen Beleg, und der Re-Run aller Belege liefert dieselben Hashes.

**E2E-2 Harmlose Änderung.**
`fr_email_promo` erzeugt keinen Incident, sondern eine Notiz `EXPECTED` mit Kalenderereignis, Band und Abstand zur Alarmlinie.
`es_traffic_surge` erzeugt `EXPECTED` mit Mix-Effekt und Raten-Effekt in Zahlen.
`orders_stall` erzeugt `DATA_ISSUE` mit Vollständigkeit und gebrochener Identität, die Nachprüfung nach dem Nachladen schließt ohne Incident.
Eine Woche ohne Ereignis erzeugt null Incidents.

**E2E-3 Neue Metrik.**
`metrics/refund_rate.yml` wird abgelegt und ist beim nächsten Takt platziert: Formelkante `refunds / orders` mit Residuum nahe 0, geerbte Aufschlüsselungen, Zertifikat.
`gmv_by_seller_type` führt die neue Dimension ein, und die Teile summieren zu `gmv`.
`app_crash_rate` landet auf `PROBATION` mit dem Vermerk "ambiguous" und ohne Ursachenkante zu `pay_success`.

### 4.11 Schlafschichten und Nachtbetrieb der Agenten

- Schicht A schläft Sa 22:45 bis So 03:15 (P2, P4), Schicht B schläft So 03:30 bis 08:00 (P1, P3), je 4,5 Stunden, immer zwei Personen wach.
- Begründung der Reihenfolge: Die beiden 40-%-Blöcke brauchen in Nacht 1 enge Führung durch P1 und P3 (Ledger, Skeptic, Platzierung), danach misst P2 das Ergebnis mit der Bench, und P1 und P3 wachen mit einer Fehlerliste auf.
- Wer schlafen geht, stellt vorher drei bis vier Pakete mit Abnahmetest ein.
  Die Flotte arbeitet sie in der Nacht ab, das wache Paar führt nur zusammen, was `make check` und den Abnahmetest besteht.
- Pakete für die Nacht sind bewusst die mit klarer Abnahme und wenig Urteilsbedarf: Bench-Runner, weitere Szenarien, Zertifikat-Karte, Bench-Seite, Handy-Seite, MCP-Server.
- Tausch der Schichten ist möglich, solange je ein Besitzer eines 40-%-Blocks wach ist.

### 4.12 Feature-Freeze, Proben, Abgabe

- **Freeze So 11:00**, fünfeinhalb Stunden vor der Frist der Vision.
  Danach nur Fehlerkorrekturen mit Test und Zweitblick, keine neuen Funktionen.
- **Probe 1 So 12:00**, **Probe 2 So 14:30** mit Ausfall-Übung, **Probe 3 So 17:00** für den Live-Pitch, falls die öffentliche Frist gilt.
- **Video So 12:30 bis 14:00** nach dem Drehbuch der Vision (kalter Einstieg auf dem fertigen Bericht, drei Takte, Bench, Schlusssatz), mit eingeblendeter Uhrzeit.
- **Abgabe So 15:30.**
  Gilt 17:45, bleibt der abgegebene Stand stehen und wird nur ersetzt, wenn eine neue Fassung eindeutig besser ist.
- Für die Abgabe zu klären: Das Repo ist privat, die Jury braucht entweder Zugriff oder ein öffentliches Repo (Abschnitt 6.3).

### 4.13 Risiken und Rückfallebenen

| Risiko | Anzeichen | Vorbeugung | Rückfallebene |
| --- | --- | --- | --- |
| Parallele Agenten erzeugen Code, der nicht zusammenpasst | rote CI nach dem Zusammenführen, Vertragsstreit | Verträge und Fixtures zuerst, CODEOWNERS, kleine PRs, P2 als Integrator | Lane arbeitet weiter gegen Fixtures, Zusammenführen in festen Fenstern |
| Sprachmodell langsam, teuer oder nicht erreichbar | Untersuchung über 90 s, Fehler der API | Kern ohne Modell, Zeitlimit, Aufzeichnung und Wiedergabe | Schalter "LLM aus" als gezeigtes Feature, Vorlagen-Bericht |
| Blind Challenge scheitert live | Bench pass^3 unter 90 % für ein Szenario | Menü nur aus bestandenen Szenarien, Go/No-Go So 10:30 | Eröffnung mit "Nennen Sie eine Zahl" als Seed, Challenge nur am Tisch |
| WLAN am Veranstaltungsort | Handy erreicht den Rechner nicht | alles läuft lokal, eigener Hotspot getestet | Jury wählt auf einem zweiten Gerät von uns, Bildschirm abgewandt |
| Simulator wirkt unecht oder verrät die Ursache | Ursache ist immer der einzige Log-Eintrag | Köder-Ereignisse, zufällige Segmente, ruhige Wochen | weniger Szenarien, dafür geprüfte |
| Frist ist früher als gedacht | Ansage vor Ort | Plan gegen 16:30, Abgabe 15:30 | Freeze-Stand von 11:00 ist jederzeit abgabefähig |
| Übermüdung | Fehler nach 03:00 | feste Schichten, Übergabe schriftlich | Umfang kürzen statt Schlaf |
| Freitext-Metrik der Jury erzeugt unbrauchbares SQL | Parse- oder Laufzeitfehler | Schema im Prompt, Prüfen, zwei Reparaturen, Vorschlagsliste | ehrliche Absage mit Grund, danach Datei-Weg zeigen |
| Schwellen feuern auf Rauschen | Incidents in ruhigen Wochen | Kalibrierung auf ruhigen Wochen, Volumen-Stufen | Top-down nur Nordstern und erste Ebene |
| Belege liefern beim Re-Run einen anderen Hash | Hash-Vergleich rot | `as_of`-Filter, kanonischer Hash | Re-Run zeigt Abweichung mit Grund "late data arrived" |
| Demo-Rechner fällt aus | - | zweiter Rechner mit frischem Klon, Aufzeichnung | Video der Sicherung |
| Vorab-Code (Kairos-Charts) nicht erlaubt | Regel vor Ort | Offenlegung in README | Charts neu schreiben, rund 2 Agentenstunden |
| Geheimnisse im Repo | API-Schlüssel im Commit | `.env`, `.env.example`, Secret-Scan in CI | Schlüssel sofort drehen |

### 4.14 Streichliste (in dieser Reihenfolge)

1. Sprachnotiz und Morning Brief, Slack, Red Team.
2. Standing Orders, gelernte Monitore, Counterfactual-Regler.
3. Kalibrierung (Brier), Urteils-Gedächtnis, austauschbare Erwartung mit MSTL.
4. Stretch-Szenarien (SEO, Marge, Ad Pacer, Ranker).
5. MCP-Server.
6. Cashback-Szenario.
7. Klartext-Metrik (der Datei-Weg bleibt).
8. Skeptic als Modell (die deterministischen Widerlegungsprüfungen bleiben).
9. Planer-Modell im Ledger (die feste Eröffnung und die berechnete Reihenfolge bleiben).

Nie gestrichen werden: die drei Momente, Belege mit Re-Run, "why I didn't alert", Zertifikat, ein Bench-Lauf gegen eine Baseline.

### 4.15 Stolpersteine je Lane

- **G Graph.**
  Der Vergleich "Formel hält" braucht dieselbe Körnung auf beiden Seiten, sonst entstehen Scheinfehler durch fehlende Segmente.
  Bei Quotienten werden Zähler und Nenner getrennt summiert, nie der Quotient.
  Brute-Force-Arithmetik nur über Knoten mit gemeinsamer Tabelle oder Lineage, sonst explodiert die Zahl der Kandidaten und der Zufallstreffer.
  Ein Join über weniger Schlüssel als das Raster vervielfacht Summen (Fan-out), in der Probe um den Faktor 12.
  Eine zusätzliche Dimension im `GROUP BY` läuft auch dann durch, wenn sie nur auf einer Seite des Joins existiert, die Summenprobe muss das abfangen.
- **W Welt.**
  Zählwerte per Binomial- und Poisson-Ziehung erzeugen, dazu Faktoren je Stunde und je Land, damit die Summe realistisch schwankt.
  Identitäten per Konstruktion sichern (`orders` entsteht aus `pay_successes`, nicht daneben).
  Jedes Szenario schreibt seine Wahrheit im selben Schritt, in dem es die Daten verändert.
  Mit pandas und DuckDB entstehen 31 Tage für 360 Segmente in vier Batches (1,07 Mio. Zeilen Bestellungen, 3,2 Mio. Zeilen Zahlungen) in rund 3 Sekunden, Leistung ist kein Risiko.
- **B Gehirn.**
  LMDI braucht eine Regel für Nullwerte (kleiner Ersatzwert oder additive Zerlegung), sonst gibt es `log(0)`.
  Die Segmentsuche läuft erschöpfend über alle 15 Kombinationen der vier Dimensionen (in der Probe 15 Abfragen, 839 Zellen, 0,4 Sekunden), bei 360 Blättern ist keine Heuristik nötig.
  Nicht bei der ersten Zelle mit 67 % Erklärungsanteil stoppen, sondern absteigen, solange die Kinder ungleich betroffen sind.
  Der Holdout-Check vergleicht den Geltungsbereich des Ereignisses ohne das auffällige Segment, nicht den Rest der Welt.
  Die Streuung für z-Werte nicht aus vier Punkten schätzen.
- **U Oberfläche.**
  Segmente sind Marken an Knoten, keine eigenen Knoten, sonst wird der Graph unlesbar.
  Die Oberfläche rechnet nie selbst, jede angezeigte Zahl kommt mit Beleg-ID aus der API.
  Der Wiedergabemodus ist von Anfang an derselbe Codepfad wie live.

## 5. Antworten auf die fünf offenen Fragen der Vision

Kurzfassung: Ich bestätige den Vorschlag (1 = A, 2 = ja, aber klein, 3 = Blind Challenge, 4 = App plus MCP, 5 = Argus) und ergänze je Frage eine Bedingung, die ihn absichert.

| Nr. | Frage | Empfehlung | Bedingung oder Ergänzung |
| --- | --- | --- | --- |
| 1 | Wie viel der Untersuchung ist agentisch? | **A**, mit sichtbarem Planer | Variante B wird Baseline in der Bench statt Produkt |
| 2 | Reiner Marktplatz oder mit Rewards-Schicht? | **ja, klein**: ein Cashback-Postback-Szenario | Cashback hängt als Teil von `discounts` im Graphen, kein eigenes System |
| 3 | Welcher Wow-Moment eröffnet? | **Blind Challenge** | nur wenn die Bench es trägt (Go/No-Go So 10:30), sonst Seed-Eröffnung |
| 4 | Wo spricht Argus? | **App plus MCP**, Slack streichen | Rückfragen als Thread auf der Incident-Seite |
| 5 | Name? | **Argus behalten** | Namensgleichheit mit Uber Argos und Salesforce Argus kennen |

### 5.1 Frage 1: Wie agentisch ist die Untersuchung?

**Empfehlung: Option A, die feste Eröffnung mit sichtbarem Planer in Phase 2.**

Gründe:

- Die Belege sprechen gegen ein frei planendes Modell.
  Auf OpenRCA liegt der beste Agent bei rund 11 %, auf ORCA-bench bei 10,0 % (schwer) und 25,3 % (mittel), und ein festes Verfahren hob die Genauigkeit bei Flow-of-Action von 35,50 % auf 64,01 % (Abschnitt 2.2).
- Die Rubrik bewertet Autonomie, nicht den Anteil an Modellaufrufen.
  Verlangt sind laut Brief ein durchgehender Lauf, eine gute Wahl des nächsten Schritts, der Umgang mit fehlenden Daten und harmlosen Änderungen, konkurrierende Erklärungen, bezifferte Beiträge und die Trennung von belegter Ursache und Hypothese.
  Jeder dieser Punkte ist in A ein eigener, sichtbarer Schritt.
- A ist die Voraussetzung für Prinzip 7 ("Works with the LLM switched off") und damit für die wichtigste Rückfallebene auf der Bühne.

Damit A nicht wie eine Regelmaschine wirkt, drei Ergänzungen:

1. Jede Entscheidung erscheint im Trail mit den verworfenen Alternativen und der Begründung in Zahlen ("next: provider status, expected gain 0.42, release 0.18").
2. Das Modell tut sichtbar, was nur ein Modell kann: Hypothesen vorschlagen, Vorhersagen formulieren, als Skeptic widersprechen.
3. Option B wird nicht verworfen, sondern gemessen: Die Bench-Baseline "LLM, no graph" ist ein Modell, das jeden Schritt selbst über dieselben Werkzeuge steuert.
   Die Tabelle beantwortet dann die Jury-Frage "warum nicht voll agentisch?" mit einer Zahl statt mit einer Meinung.

Aufwand: keiner zusätzlich, B6 und W7 sind ohnehin geplant.
Wenn die Entscheidung auf B fällt: B4 wird Must, B3 schrumpft, das Risiko für C2 steigt deutlich, und die Blind Challenge wird unsicher.

### 5.2 Frage 2: Reiner Marktplatz oder mit Rewards-Schicht?

**Empfehlung: ja, aber klein, als ein Szenario "duplicated cashback postbacks from one device cluster".**

Gründe:

- Der Brief verlangt einen Amazon-artigen Marktplatz, der Kern bleibt also Marktplatz.
- Die Jury kommt aus einem Rewards- und Ad-Tech-Geschäft, ein Fall in ihrer Sprache (Payout, Postback, "hold payouts" hinter einer Freigabe) zeigt Verständnis für ihr Problem.
- Klein bleibt es, weil Cashback kein eigenes System wird.
  `discounts = coupon_discounts + cashback_payout` ist eine Formelkante, `fact_rewards_hourly` eine Tabelle, `device_cluster` eine Dimension.
  Die Formel `contribution = commission - fees - discounts - ad_spend` aus der Vision bleibt unverändert.

Der Fall im Ablauf: Die Bestellungen sehen gut aus, der Deckungsbeitrag fällt.
Die Zerlegung zeigt `cashback_payout` als Träger, die Segmentsuche findet einen `device_cluster`, die Identität "Postbacks je bezahlter Bestellung höchstens 1" ist dort gebrochen.
Urteil `SUPPORTED_CAUSE` oder `HYPOTHESIS` mit dem Vorschlag "hold payouts for cluster X", hinter einer Freigabe (Prinzip 8).

Aufwand: rund 3 Agentenstunden in W5, eingeplant als Should nach den drei Momenten.
Grenze: keine Anspielung auf die App-Store-Episode von Freecash (so steht es in der Vision).
Wenn die Entscheidung "rein" lautet, entfällt nur W5-Teil 3, der Pitch-Abschnitt "Fit" stützt sich dann auf Ad Pacing und Datenfrische.

### 5.3 Frage 3: Welcher Wow-Moment eröffnet?

**Empfehlung: die Sealed-Envelope Blind Challenge, mit einem Go/No-Go am Sonntag um 10:30.**

Gründe:

- Sie widerlegt im ersten Satz den stärksten Einwand gegen jede Hackathon-Demo, nämlich "das ist ein einstudierter Glücksfall" (in der Vision ein Anti-Ziel).
- Sie deckt zwei der drei bewerteten Momente auf einmal ab, wenn das Menü auch harmlose Änderungen enthält: Wählt die Jury eine Aktion, zeigt Argus "why I didn't alert".
- Die Untersuchung läuft, während wir 60 Sekunden Problem und Identität erklären, die Wartezeit ist also verdeckt.

Bedingungen:

1. Go nur, wenn jedes Szenario im Menü in der Bench pass^3 von mindestens 90 % erreicht und Probe 1 dreimal hintereinander gelingt.
2. Das Commitment ist `SHA-256(nonce + canonical_json(truth))`, und das Handy der Jury rechnet den Hash beim Reveal selbst nach.
3. Rückfall-Leiter für das Netz: WLAN, eigener Hotspot, zweites Gerät von uns, zuletzt "Nennen Sie eine Zahl" als Seed auf unserem Rechner.
4. Im 3-Minuten-Video gibt es keine Jury, dort bleibt der kalte Einstieg auf dem fertigen Bericht (Drehbuch der Vision).

Bei No-Go eröffnet die von der Jury benannte Metrik, weil sie nur von G4 und G5 abhängt, und die Challenge wird ein Moment am Tisch.
Aufwand: W6 und U9, zusammen rund 3,5 Agentenstunden.

### 5.4 Frage 4: Wo spricht Argus?

**Empfehlung: App plus MCP, Slack streichen.**

Gründe:

- MCP ist eine dünne Schicht über der vorhandenen API (rund 2 Agentenstunden) und ein eigener Moment ("Ask your own Claude").
- Slack braucht Workspace, App-Installation, Token und Netz und zieht den Blick der Jury in ein zweites Fenster.
- Was Slack inhaltlich bringt, bleibt erhalten: Die Incident-Seite bekommt einen Thread, in dem Rückfragen wie "what about iOS?" mit denselben Werkzeugen und Belegen beantwortet werden.
  Das hält auch das Nicht-Ziel "kein allgemeiner Chat" ein, weil der Thread an einen Incident gebunden ist.

Einschränkung: "A judge can ask their own Claude" gelingt realistisch nur auf unserem Rechner mit verbundenem Claude, nicht auf einem Gerät der Jury.
Im Pitch-Abschnitt "Fit" heißt es deshalb "Slack-ready", gezeigt wird MCP.
Wenn doch Slack gewünscht ist: nur als gerenderte Vorschau der Nachricht in der App, rund 1 Agentenstunde, Stretch.

### 5.5 Frage 5: Name

**Empfehlung: Argus behalten.**

Gründe:

- Der Name trägt die Geschichte (hundertäugiger Wächter) und passt wörtlich zum Track "Eye of the System".
- Organisation `argus-analyst`, Vision und Pitch stehen schon darauf, ein Wechsel kostet Zeit ohne Punkte.

Zu wissen, falls jemand fragt: Uber betreibt ein Alarm-System namens Argos, und Salesforce hat 2016 eine Monitoring-Plattform namens Argus als Open Source veröffentlicht (Annahme aus meinem Wissen, heute nicht nachgeprüft).
Für den Hackathon ist das unerheblich, für ein späteres Produkt wäre eine Markenprüfung nötig.

## 6. Abweichungen, Korrekturen am Pitch und offene Punkte

### 6.1 Abgabefrist: 16:30 oder 17:45

| Quelle | Aussage |
| --- | --- |
| Vision (PDF, Titelseite) | "due Sun 22 Nov 16:30" |
| Öffentliche Luma-Seite, abgerufen am 21.11. | "17:45 - Submission Deadline - Hacking Ends", danach 18:00 Judging und 19:00 Live Pitches & Award Ceremony |
| Früherer Bericht, 2.2 und 7.3 | Frist 17:45, eigene Abgabe geplant für 17:15 |

Die Zeit 16:30 steht auf keiner der geprüften öffentlichen Seiten (Luma, `hacklabrobotics.com`, Artikel zur Edition 2).
Die ältere Angabe 17:15 war nie eine Frist, sondern der geplante eigene Abgabezeitpunkt mit 30 Minuten Puffer vor 17:45.
Ob 16:30 eine Ansage vor Ort für den Almedia-Track ist oder ein interner Zielwert des Teams, lässt sich von hier aus nicht klären.
Der Plan rechnet deshalb mit 16:30 und gibt um 15:30 ab.
Gilt 17:45, entstehen 75 Minuten zusätzlicher Puffer.
Empfehlung: einmal beim Veranstalter oder beim Almedia-Team vor Ort nachfragen und das Ergebnis im Repo unter `docs/decisions.md` festhalten.

### 6.2 Korrekturen an Zahlen der Vision, bevor sie in den Pitch gehen

| Aussage in der Vision | Befund der Recherche | Empfehlung |
| --- | --- | --- |
| "Resolve at $1.5B" | belegt ist 1 Mrd. USD (Series A, VentureBeat, 21.05.2026) | auf 1 Mrd. korrigieren oder Zahl weglassen |
| "Traversal at $1B" | nur als Suchtreffer gesehen, nicht auf einer geöffneten Seite | weglassen oder Quelle nachtragen |
| "Independent verifiers doubled accuracy at Resolve.ai" | belegt ist "more than a twofold improvement" auf internen Benchmarks, ohne Ablation der Verifier | als "Resolve reports more than twofold improvement" formulieren, nicht den Verifiern zuschreiben |
| "10-25% on the 2026 ORCA-bench, with hallucination rates above 40%" | beste Agenten 10,0 % (schwer) und 25,3 % (mittel), 40 % Halluzination gilt für das schwächste Modell | "up to 40%" statt "above 40%" |
| "11% on OpenRCA" | 11,34 % nur in Suchzusammenfassungen gesehen, die Projektseite lieferte keinen Inhalt | Zahl behalten, Quelle vor dem Pitch einmal öffnen |
| "35% to 64% (Flow-of-Action)" | bestätigt: 35,50 % auf 64,01 % | so lassen |
| Datadog "≈$4 and ≈2 min" | bestätigt, zum Start waren es 25 USD und 11 Minuten | so lassen, der Rückgang ist ein zusätzliches Argument |
| "Causely abstains when the evidence is weak" | kein ausdrücklicher Abstain-Mechanismus, nur eine typisierte Antwort "no active root cause" | als "returns a typed no-root-cause answer" formulieren |
| "Salesforce agreeing to buy Loops in October 2026" | bestätigt: Ankündigung 12.10.2026, Abschluss laut Salesforce-Meldung 02.11.2026 | "acquired" statt "agreeing to buy" |
| Mixpanel-Bäume "never touch your data" | bestätigt für "Build with AI" laut Doku, Blog vom 17.03.2026 | so lassen |
| "Analysts say Pulse lacks RCA" | keine Analystenquelle mit dieser Formulierung gefunden | weglassen oder als eigene Einschätzung kennzeichnen |
| Snowflake CoWork "standing orders: if X drops 20%, brief me with the root cause" | die Doku zu Automations nennt nur zeitgesteuerte Berichte, keine Schwellen-Auslöser | Zeile streichen oder auf "scheduled reports" korrigieren |
| Anodot | Übernahme durch Glassbox am 04.11.2025 (nur als Suchtreffer gesehen) | falls genannt, mit 2025 |

Diese Korrekturen kosten nichts und schützen vor einer Nachfrage der Jury.
Die Kernthese der Vision bleibt nach der Recherche stehen: Kein untersuchter Anbieter prüft die Kanten seines Metrik-Graphen gegen die Daten, keiner trennt exakte Zerlegung von Ursachenhypothese, und kein Analytics-Anbieter veröffentlicht eine Ursachen-Trefferquote.

### 6.3 Offene Entscheidungen (auf dem Board als D1 bis D9)

Das Board bündelt diese neun Entscheidungen in einer Karte, die Empfehlung ist jeweils vorausgewählt.
Bis eine Antwort vorliegt, gilt im Plan die Empfehlung.

| ID | Entscheidung | Empfehlung | Begründung |
| --- | --- | --- | --- |
| D1 | Wie agentisch ist die Untersuchung? | A: festes Verfahren mit sichtbarem Planer | 5.1 |
| D2 | Reiner Marktplatz oder mit Rewards-Schicht? | ja, klein: ein Cashback-Postback-Szenario | 5.2 |
| D3 | Welcher Wow-Moment eröffnet? | Blind Challenge mit Go/No-Go am So 10:30 | 5.3 |
| D4 | Wo spricht Argus? | App plus MCP, Slack streichen | 5.4 |
| D5 | Name | Argus behalten | 5.5 |
| D6 | Gegen welche Frist wird geplant? | gegen 16:30 planen, vor Ort klären | 6.1 |
| D7 | Repo zur Abgabe | zur Abgabe öffentlich schalten | unten |
| D8 | Rollen und Schlafschichten | wie vorgeschlagen | 4.7 und 4.11 |
| D9 | Arbeitsmodus im Repo | schneller Weg: automatische Tests plus Durchsicht durch den Lane-Besitzer | unten |

**Zu D7.**
Das Repo ist privat, das Video soll laut Vision mit dem Repo-Link enden.
Möglich sind ein öffentliches Repo zur Abgabe oder eine Einladung der Jury.
Empfehlung: öffentlich zur Abgabe, sofern die Kairos-Bausteine mit MIT-Hinweis offengelegt sind und kein Geheimnis im Verlauf steht.
Die Einladung braucht die GitHub-Namen der Jury vor der Abgabe.

**Zu D9.**
Eine vollständige Prüf-Pipeline je PR kostet bei rund 40 Paketen viele Stunden Wartezeit.
Empfehlung für dieses eine Repo: PR mit CI und Durchsicht durch den Lane-Besitzer, jedes Paket trägt seinen Abnahmetest.
Das ist eine Entscheidung über den Arbeitsmodus, die ich nicht treffe.

### 6.4 Annahmen und nicht verifizierte Punkte

- Der Wortlaut des Track-Briefs lag mir nur in der Wiedergabe des früheren Berichts (12.1) vor.
- Pitch-Länge, Abgabeformat und die Frage, ob alle Teams live pitchen oder nur Finalisten, sind öffentlich nicht dokumentiert.
- Ob vorhandener eigener Code erlaubt ist, war öffentlich nicht geregelt (früherer Bericht, 6.3).
- Alle Aufwandsangaben in Agentenstunden sind Schätzungen.
- Das Repo `argus-analyst/argus` gab es zum Zeitpunkt der Prüfung noch nicht (`gh-axi repo view`: `REPO_NOT_FOUND`), den Stand bereits geschriebenen Codes kenne ich nicht.
- Die Modellnamen stammen aus der Umgebung dieser Sitzung, die Verfügbarkeit im Hackathon-Konto ist nicht geprüft.
- In Abschnitt 2 sind einzelne Aussagen als "Annahme" oder "nicht verifiziert" markiert, dort konnte die Quelle nicht geöffnet werden.

## 7. Belege

### 7.1 Gelesene Dateien und ausgeführte Prüfungen

| Was | Befehl oder Datei | Ergebnis |
| --- | --- | --- |
| Vision | `data/almedia-ideation/Argus_Product_Vision.pdf`, Seiten 1 bis 38 als Bild und per `pdftotext -layout` | 30 Seiten Inhalt, 8 leere Seiten, 17 Abschnitte, 5 offene Fragen |
| Früherer Bericht | `data/almedia-ideation/report.md`, Abschnitte 2, 6 und 12 | Zeitplan mit Frist 17:45, Kairos-Bausteine, Track-Brief |
| Repo | `gh-axi repo view argus-analyst/argus` | `REPO_NOT_FOUND` (Stand Sa 13:10) |
| Kairos | `gh-axi repo view BatuCani/kairos-studio`, `gh-axi api repos/BatuCani/kairos-studio/contents/src/renderer/screens/analytics` | privat, MIT, Chart-Dateien wie in 4.6 |
| Zeitplan | Abruf `https://luma.com/h0mcaqio` am 21.11. | Sonntag: 08:00 Breakfast, 13:30 Lunch, 17:45 Submission Deadline, 18:00 Judging, 19:00 Live Pitches & Award Ceremony |
| Recherche | sechs parallele Recherchen mit Websuche und Seitenabruf, zusammen rund 150 Abrufe | Abschnitte 2.6 bis 2.10, 6.1, 7.2 |
| Technik-Probe | `spike.py` mit duckdb 2.0.1, sqlglot 30.33.0, numpy, pandas in einer Wegwerf-Umgebung | Abschnitt 7.4, Skript in Anhang A |
| Board | `board/index.html`, erzeugt aus den Plandaten mit `make_board.py`, geprüft im Browser bei 1440, 820 und 500 Pixel Breite | kein horizontaler Überlauf, Zeitplan als drei Diagramme, eine Entscheidungskarte mit D1 bis D9 |

Gestaltung des Boards: Farben, Schrift und Statusmarken folgen der Argus-Produktvision selbst (dunkelblauer Kopf, helle Karten, Mono-Marken), also dem Design des Projekts, um das es geht.
Das Board lädt keine externen Dateien.

### 7.2 Tech-Stack (Versionen von PyPI und npm, Stand 21.11.2026)

| Komponente | Version | Datum | Quelle |
| --- | --- | --- | --- |
| duckdb | 2.0.1 | 2026-11-20 | https://pypi.org/pypi/duckdb/json , https://duckdb.org/docs/2.0/connect/concurrency.html |
| sqlglot | 30.33.0 | 2026-11-17 | https://pypi.org/pypi/sqlglot/json , https://sqlglot.com/sqlglot/lineage.html |
| @xyflow/react | 13.0.2 | 2026-11-17 | https://registry.npmjs.org/@xyflow/react |
| @dagrejs/dagre | 3.1.3 | 2026-10-24 | https://registry.npmjs.org/@dagrejs/dagre , https://reactflow.dev/learn/layouting/layouting |
| mcp | 2.3.0 | 2026-10-02 | https://pypi.org/pypi/mcp/json , https://github.com/modelcontextprotocol/python-sdk |
| statsforecast | 2.1.1 | 2026-07-16 | https://pypi.org/pypi/statsforecast/json |
| fastapi | 0.165.0 | 2026-11-18 | https://pypi.org/pypi/fastapi/json , https://fastapi.tiangolo.com/tutorial/server-sent-events/ |
| anthropic | 2.12.0 | 2026-11-20 | https://pypi.org/pypi/anthropic/json , https://platform.claude.com/docs/en/build-with-claude/structured-outputs |

DuckDB-Doku zur Nebenläufigkeit im Wortlaut: "multiple processes can read from the database, but no processes can write".
Nicht verifiziert blieben: ob animierte Kanten in React Flow eingebaut sind, wie Claude Desktop den MCP-Server einbindet, und der Parameter für konforme Intervalle in statsforecast.
In der Technik-Probe selbst geprüft: `GROUP BY ALL`, `getvariable('as_of')` in Sichten, `find_all(exp.Table)`, `find_all(exp.AggFunc)`, `sqlglot.transpile(..., write="bigquery")`.

### 7.3 Quellen der Recherche

Die Quellen stehen je Produkt in den Abschnitten 2.6 bis 2.10 unter "Quellen", jeweils mit dem Vermerk, ob die Seite geöffnet oder nur als Suchtreffer gesehen wurde.

### 7.4 Technik-Probe: was läuft, was die Vision korrigiert

Die Probe baut eine kleine Welt (31 Tage, 360 Segmente, vier Batches je Stunde, Zahlungen je Provider, Erstattungen), pflanzt den PayCo-Fehler mit Release-Köder, den Spanien-Anstieg und den Orders-Stau, und rechnet die riskantesten Schritte von Argus nach.
Laufzeit insgesamt 3,6 Sekunden.

| Nr. | Prüfung | Ergebnis | Folge für den Plan |
| --- | --- | --- | --- |
| 0 | Welt erzeugen und laden | 1.071.360 Batch-Zeilen Bestellungen, 3.214.080 Batch-Zeilen Zahlungen in 3,0 s | Leistung ist kein Risiko |
| 1 | Beleg-Hash mit festem Stand | Re-Run mit Stand 05:30 liefert denselben Hash, Stand 12:00 einen anderen | `as_of` in jedem Beleg (4.4 Nr. 2) |
| 2 | Summe gegen Segment | Summe -4,9 % (z -4,1), DE -12,3 % (z -5,9), DE-Android -29,9 % (z -7,2), FR-Android +3,2 % (z 0,8) | von oben nach unten absteigen, Rauschen der Summe erhöhen (4.4 Nr. 13) |
| 3 | LMDI entlang der Formel | Effekte summieren exakt zur Änderung (Rest 2,6e-13), `pay_success` trägt 89,8 % | LMDI wie geplant |
| 4 | Segmentsuche über 15 Kombinationen | 15 Abfragen, 839 Zellen, 0,36 s, gewählt `country = DE ∧ platform = android` mit Erklärungsanteil 0,95 | erschöpfende Suche reicht |
| 4b | naive Regel der Vision | stoppt bei `country = DE` (Erklärungsanteil 0,99), Kinder ungleich: Android -29,2 %, iOS -1,3 %, Web +0,1 % | Abstiegsregel (4.4 Nr. 12) |
| 5 | Holdout gegen den Release-Köder | DE-Android -29,2 %, Android außerhalb DE -0,8 %, Release verworfen; PayCo 0,957 auf 0,433, CardHub und WalletGo unverändert | Holdout wie geplant |
| 6 | sqlglot an der Beispielmetrik | Tabellen, Aggregate, Dimensionen, `GROUP BY ALL`, Zähler und Nenner erkannt, Übersetzung nach BigQuery läuft | Platzierung wie geplant |
| 7a | Identität im Datenstau | `orders = pay_successes`: im Stau 3.299 gegen 4.692 (0,703), nach dem Nachladen 5.913 gegen 5.913 | gebrochene Identität als Datenindiz |
| 7b | Beispielmetrik der Vision | Wert ist in 5.389 Zellen exakt das 12,000-Fache von `refunds / orders` | Fan-out-Wächter (4.4 Nr. 11) |
| 8 | Mix gegen Rate beim Spanien-Anstieg | Änderung -0,590 Punkte = Mix -0,634 + Rate +0,044, Rest 1e-18 | Urteil "innocent mix shift" |

Ausgabe im Wortlaut:

```
[0] world built: 1,071,360 order batch rows, 3,214,080 payment batch rows, 3.0s, duckdb 2.0.1, sqlglot 30.33.0
[1] receipt hash as_of 05:30 = b55a8ddc963b18f6, as_of 12:00 = edafa970560b9c0e, re-run pinned to 05:30 = b55a8ddc963b18f6 -> reproducible: True, differs after late data: True
[7a] identity orders = pay_successes at 04:00: during stall (3299, 4692, 0.703), after backfill (5913, 5913, 1.0)
[2] orders total       actual     6559 expected     6899 change   -4.9%  robust z   -4.1
[2] orders DE          actual     2045 expected     2332 change  -12.3%  robust z   -5.9
[2] orders DE-android  actual      648 expected      924 change  -29.9%  robust z   -7.2
[2] orders FR-android  actual      630 expected      610 change    3.2%  robust z    0.8
[3] DE orders/h expected 2056 actual 1805 delta -251.0; LMDI effects sum -251.000000 (residual 2.56e-13)
    shares: pay_success  89.8%, sessions   7.8%, attempt_rate  -6.3%, cart_rate   4.8%, checkout_rate   2.3%, view_rate   1.7%
[4] segment search: 15 queries over 15 cuboids, 839 cells, 356 ms
    chosen cuboid ('country', 'platform') cells [{'country': 'DE', 'platform': 'android'}] EP 0.95 relative change [-0.292]
    naive rule (simplest cuboid with EP >= 0.67) would stop at {'country': 'DE'}: EP 0.99, rel -0.122; its platform children are not uniform: android -0.292, ios -0.013, web +0.001
    top by surprise: {'country': 'DE', 'platform': 'android'} EP 0.95 rel -0.29; {'country': 'DE', 'platform': 'android', 'channel': 'organic'} EP 0.35 rel -0.28; {'country': 'DE', 'platform': 'android', 'channel': 'paid'} EP 0.30 rel -0.30; {'country': 'DE', 'platform': 'android', 'category': 'beauty'} EP 0.17 rel -0.42
[5] release scope = android in all countries; anomalous segment DE-android -29.2%, holdout (android, not DE) -0.8% -> release rejected
    pay_success by provider in DE-android (before, after): [('CardHub', 0.949, 0.949), ('PayCo', 0.957, 0.433), ('WalletGo', 0.947, 0.949)]
[6] parsed: tables ['fact_orders_hourly', 'fact_refunds_hourly'], aggregates ['SUM(refunds)', 'SUM(orders)'], dims ['ts', 'country', 'category'], GROUP BY ALL = True
    ratio detected: numerator `CAST(SUM(refunds) AS DOUBLE)` / denominator `NULLIF(SUM(orders), 0)`
    BigQuery dialect: SELECT ts, country, category, CAST(SUM(refunds) AS FLOAT64) / NULLIF(SUM(orders), 0) AS value FROM fact_refunds_hourly JOIN fact_orders_hourly USING (ts, country, category) GROUP BY ALL
    extra GROUP BY platform: runs (platform exists only on the orders side)
[7b] metric SQL as written vs. refunds / orders at equal grain: median ratio 12.000, p5..p95 12.000..12.000 over 5389 cells
     -> a constant integer ratio is the signature of a join fan-out (refunds repeated per platform x channel row)
[8] blended conversion change -0.590 pts = mix -0.634 pts + rate 0.044 pts (residual 1.46e-18) -> innocent mix shift
[done] total runtime 3.6s
```

Einschränkungen der Probe: eine Welt mit einem Seed, keine Kalenderereignisse, keine Ursachenkanten, kein Sprachmodell.
Sie belegt, dass die Bausteine mit den aktuellen Bibliotheken funktionieren, nicht die Trefferquote des fertigen Systems.

## Anhang A: Skript der Technik-Probe

Das Arbeitsverzeichnis dieser Untersuchung wird verworfen, deshalb steht das Skript hier vollständig.
Es eignet sich als Startpunkt für W1 (Simulator), G2 (Sichten mit `as_of`, Hash), B2 (LMDI, Mix und Rate, Segmentsuche) und G4 (Parsen, Fan-out).
Voraussetzung: `uv pip install duckdb sqlglot numpy pandas`.

```python
"""Throwaway technical spike for the Argus build plan.

Checks the riskiest building blocks against the current library versions:
1. micro-batch delivery + as_of views -> reproducible receipt hashes
2. hour-of-week robust z: total vs. segment (the "-3% total hides -9% DE" trap)
3. exact LMDI split along the conversion formula
4. exhaustive segment search over all 15 cuboids (Adtributor EP + JS surprise)
5. holdout check that rejects the release red herring
6. sqlglot placement: parse, lineage facts, extra GROUP BY, BigQuery transpile
7. numeric formula check, join fan-out detection, broken identity on a stalled table
8. mix-vs-rate split on a Simpson's paradox traffic surge
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import time

import duckdb
import numpy as np
import pandas as pd
import sqlglot
from sqlglot import exp

rng = np.random.default_rng(42)
t_start = time.time()

COUNTRIES = ["DE", "FR", "UK", "ES", "NL"]
PLATFORMS = ["android", "ios", "web"]
CHANNELS = ["organic", "paid", "email", "direct"]
CATEGORIES = ["electronics", "fashion", "home", "beauty", "toys", "grocery"]
PROVIDERS = ["PayCo", "CardHub", "WalletGo"]
W = {
    "country": dict(zip(COUNTRIES, [0.30, 0.22, 0.22, 0.13, 0.13])),
    "platform": dict(zip(PLATFORMS, [0.40, 0.35, 0.25])),
    "channel": dict(zip(CHANNELS, [0.40, 0.30, 0.10, 0.20])),
    "category": dict(zip(CATEGORIES, [0.22, 0.24, 0.18, 0.12, 0.10, 0.14])),
}
# conversion differs by country so that a traffic-mix shift moves the blended rate
CVR_COUNTRY = {"DE": 1.10, "FR": 1.00, "UK": 1.05, "ES": 0.55, "NL": 1.00}
DAYS = 31
HOURS = pd.date_range("2026-10-19", periods=DAYS * 24, freq="h")  # starts on a Monday
T0 = pd.Timestamp("2026-11-17 11:00")  # PayCo fault onset (Tuesday)
T_SURGE = pd.Timestamp("2026-11-18 09:00")  # Spain traffic surge (innocent)
T_STALL = pd.Timestamp("2026-11-17 03:00")  # orders table stalls for 3 h (data issue)

# ---------------------------------------------------------------- 0. simulate
seg = pd.DataFrame(list(itertools.product(COUNTRIES, PLATFORMS, CHANNELS, CATEGORIES)),
                   columns=["country", "platform", "channel", "category"])
seg["w"] = (seg.country.map(W["country"]) * seg.platform.map(W["platform"])
            * seg.channel.map(W["channel"]) * seg.category.map(W["category"]))
how = HOURS.day_of_week * 24 + HOURS.hour
season = (1 + 0.45 * np.sin((HOURS.hour - 14) / 24 * 2 * np.pi)) * np.where(HOURS.day_of_week >= 5, 1.15, 1.0)
base = 120_000  # sessions per hour, whole marketplace

frames, pay_frames = [], []
for hi, ts in enumerate(HOURS):
    mu = base * season[hi] * seg.w.to_numpy()
    surge = (ts >= T_SURGE) & (seg.country.to_numpy() == "ES")
    mu = np.where(surge, mu * 3.0, mu)
    sessions = rng.poisson(mu)
    views = rng.binomial(sessions, 0.62)
    carts = rng.binomial(views, np.clip(0.24 * seg.country.map(CVR_COUNTRY).to_numpy(), 0, 1))
    checkouts = rng.binomial(carts, 0.52)
    attempts = rng.binomial(checkouts, 0.90)
    # provider split: PayCo carries half of the attempts everywhere
    a_payco = rng.binomial(attempts, 0.50)
    a_card = rng.binomial(attempts - a_payco, 0.60)
    a_wallet = attempts - a_payco - a_card
    p_payco = np.full(len(seg), 0.95)
    fault = (ts >= T0) & (seg.country.to_numpy() == "DE") & (seg.platform.to_numpy() == "android")
    p_payco = np.where(fault, 0.40, p_payco)
    s_payco = rng.binomial(a_payco, p_payco)
    s_card = rng.binomial(a_card, 0.95)
    s_wallet = rng.binomial(a_wallet, 0.95)
    orders = s_payco + s_card + s_wallet  # identity by construction: orders = payment successes
    f = seg[["country", "platform", "channel", "category"]].copy()
    f["ts"] = ts
    f["sessions"], f["views"], f["carts"], f["checkouts"], f["attempts"] = sessions, views, carts, checkouts, attempts
    f["orders"] = orders
    f["gmv"] = np.round(orders * rng.normal(58.0, 1.5, len(seg)), 2)
    frames.append(f)
    for prov, a, s in (("PayCo", a_payco, s_payco), ("CardHub", a_card, s_card), ("WalletGo", a_wallet, s_wallet)):
        p = seg[["country", "platform", "channel", "category"]].copy()
        p["ts"], p["provider"], p["pay_attempts"], p["pay_successes"] = ts, prov, a, s
        pay_frames.append(p)
full = pd.concat(frames, ignore_index=True)
pay = pd.concat(pay_frames, ignore_index=True)


def to_batches(df: pd.DataFrame, measures: list[str], table: str) -> pd.DataFrame:
    """Split every hourly row into 4 micro-batches that arrive 5/20/40/55 min after the hour ends."""
    out = []
    remaining = {m: df[m].to_numpy().copy() for m in measures}
    shares = [0.55, 0.25, 0.15, 0.05]
    left = 1.0
    for b, (share, lag) in enumerate(zip(shares, [5, 20, 40, 55])):
        part = df.drop(columns=measures).copy()
        for m in measures:
            if b == len(shares) - 1:
                take = remaining[m]
            elif np.issubdtype(remaining[m].dtype, np.integer):
                take = rng.binomial(remaining[m], share / left)
            else:
                take = np.round(remaining[m] * share / left, 2)
            part[m] = take
            remaining[m] = remaining[m] - take
        left -= share
        part["batch"] = b
        part["ingested_at"] = part["ts"] + pd.Timedelta(hours=1, minutes=lag)
        if table == "raw_orders":  # ETL stall: batches 1..3 of three hours arrive 190 min late
            stalled = (part["ts"] >= T_STALL) & (part["ts"] < T_STALL + pd.Timedelta(hours=3)) & (b >= 1)
            part.loc[stalled, "ingested_at"] += pd.Timedelta(minutes=190)
        out.append(part)
    return pd.concat(out, ignore_index=True)


raw_funnel = to_batches(full[["ts", "country", "platform", "channel", "category", "sessions", "views", "carts",
                              "checkouts", "attempts"]], ["sessions", "views", "carts", "checkouts", "attempts"], "raw_funnel")
raw_orders = to_batches(full[["ts", "country", "platform", "channel", "category", "orders", "gmv"]], ["orders", "gmv"], "raw_orders")
raw_payments = to_batches(pay, ["pay_attempts", "pay_successes"], "raw_payments")
ref = full.groupby(["ts", "country", "category"], as_index=False)["orders"].sum()
ref["refunds"] = rng.binomial(ref["orders"].to_numpy(), 0.04)
raw_refunds = to_batches(ref[["ts", "country", "category", "refunds"]], ["refunds"], "raw_refunds")

con = duckdb.connect(":memory:")
for name in ("raw_funnel", "raw_orders", "raw_payments", "raw_refunds"):
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM {name}")
con.execute("SET VARIABLE as_of = TIMESTAMP '2026-11-19 00:00:00'")
VIEWS = {
    "fact_funnel_hourly": ("raw_funnel", "ts, country, platform, channel, category", "sessions, views, carts, checkouts, attempts"),
    "fact_orders_hourly": ("raw_orders", "ts, country, platform, channel, category", "orders, gmv"),
    "fact_payments_hourly": ("raw_payments", "ts, country, platform, channel, category, provider", "pay_attempts, pay_successes"),
    "fact_refunds_hourly": ("raw_refunds", "ts, country, category", "refunds"),
}
for view, (raw, keys, measures) in VIEWS.items():
    sums = ", ".join(f"SUM({m}) AS {m}" for m in measures.split(", "))
    con.execute(f"CREATE VIEW {view} AS SELECT {keys}, {sums} FROM {raw} "
                f"WHERE ingested_at <= getvariable('as_of') GROUP BY ALL")
print(f"[0] world built: {len(raw_orders):,} order batch rows, {len(raw_payments):,} payment batch rows, "
      f"{time.time() - t_start:.1f}s, duckdb {duckdb.__version__}, sqlglot {sqlglot.__version__}")


# ---------------------------------------------------------------- 1. receipts
def run(sql: str, as_of: str) -> tuple[list[tuple], str]:
    con.execute(f"SET VARIABLE as_of = TIMESTAMP '{as_of}'")
    rows = con.execute(sql).fetchall()
    canon = sorted([[float(f"{v:.10g}") if isinstance(v, float) else str(v) for v in r] for r in rows], key=json.dumps)
    return rows, hashlib.sha256(json.dumps(canon).encode()).hexdigest()[:16]


q = "SELECT country, SUM(orders) AS orders FROM fact_orders_hourly WHERE ts = TIMESTAMP '2026-11-17 04:00:00' GROUP BY ALL"
_, h_early = run(q, "2026-11-17 05:30:00")   # during the stall: only batch 0 has arrived
_, h_late = run(q, "2026-11-17 12:00:00")    # after the backfill
_, h_rerun = run(q, "2026-11-17 05:30:00")   # re-run of the first receipt, pinned to its as_of
print(f"[1] receipt hash as_of 05:30 = {h_early}, as_of 12:00 = {h_late}, re-run pinned to 05:30 = {h_rerun} "
      f"-> reproducible: {h_early == h_rerun}, differs after late data: {h_early != h_late}")

# ---------------------------------------------------------------- 7a. broken identity during the stall
ident = """
SELECT o.orders, p.pay_successes, ROUND(o.orders * 1.0 / p.pay_successes, 3) AS ratio FROM
 (SELECT SUM(orders) AS orders FROM fact_orders_hourly WHERE ts = TIMESTAMP '2026-11-17 04:00:00') o,
 (SELECT SUM(pay_successes) AS pay_successes FROM fact_payments_hourly WHERE ts = TIMESTAMP '2026-11-17 04:00:00') p"""
r_stall, _ = run(ident, "2026-11-17 05:30:00")
r_ok, _ = run(ident, "2026-11-17 12:00:00")
print(f"[7a] identity orders = pay_successes at 04:00: during stall {r_stall[0]}, after backfill {r_ok[0]}")

# ---------------------------------------------------------------- 2. watcher: total vs. segment
AS_OF = "2026-11-17 15:00:00"
NOW = pd.Timestamp("2026-11-17 13:00")


def robust_z(where: str, metric_sql: str, table: str) -> tuple[float, float, float]:
    sql = f"""
    WITH s AS (SELECT ts, {metric_sql} AS v FROM {table} WHERE {where} GROUP BY ts)
    SELECT (SELECT v FROM s WHERE ts = TIMESTAMP '{NOW}') AS actual,
           median(v) AS expected, median(abs(v - (SELECT median(v) FROM s WHERE ts < TIMESTAMP '{NOW}'
                 AND dayofweek(ts) = dayofweek(TIMESTAMP '{NOW}') AND hour(ts) = hour(TIMESTAMP '{NOW}')))) AS mad
    FROM s WHERE ts < TIMESTAMP '{NOW}' AND dayofweek(ts) = dayofweek(TIMESTAMP '{NOW}') AND hour(ts) = hour(TIMESTAMP '{NOW}')"""
    (actual, expected, mad), _ = run(sql, AS_OF)[0][0], None
    floor = math.sqrt(max(expected, 1.0))  # Poisson variance floor: MAD over 4 points is unstable
    z = (actual - expected) / max(1.4826 * mad, floor)
    return actual, expected, z


for label, where in (("total", "TRUE"), ("DE", "country = 'DE'"), ("DE-android", "country = 'DE' AND platform = 'android'"),
                     ("FR-android", "country = 'FR' AND platform = 'android'")):
    a, e, z = robust_z(where, "SUM(orders)", "fact_orders_hourly")
    print(f"[2] orders {label:11s} actual {a:8.0f} expected {e:8.0f} change {100 * (a / e - 1):6.1f}%  robust z {z:6.1f}")

# ---------------------------------------------------------------- 3. LMDI along the formula
FACTORS = ["sessions", "view_rate", "cart_rate", "checkout_rate", "attempt_rate", "pay_success"]


def funnel(where: str, ts_filter: str) -> dict[str, float]:
    sql = f"""
    SELECT SUM(f.sessions), SUM(f.views), SUM(f.carts), SUM(f.checkouts), SUM(f.attempts), SUM(o.orders)
    FROM fact_funnel_hourly f JOIN fact_orders_hourly o USING (ts, country, platform, channel, category)
    WHERE {where} AND {ts_filter}"""
    s, v, c, ch, a, o = run(sql, AS_OF)[0][0]
    n = run(f"SELECT COUNT(DISTINCT ts) FROM fact_funnel_hourly WHERE {ts_filter}", AS_OF)[0][0][0]
    s, v, c, ch, a, o = (x / n for x in (s, v, c, ch, a, o))
    return {"sessions": s, "view_rate": v / s, "cart_rate": c / v, "checkout_rate": ch / c,
            "attempt_rate": a / ch, "pay_success": o / a, "orders": o}


def lmdi(x0: dict[str, float], x1: dict[str, float]) -> dict[str, float]:
    y0, y1 = x0["orders"], x1["orders"]
    L = (y1 - y0) / (math.log(y1) - math.log(y0)) if y1 != y0 else y1
    return {k: L * math.log(x1[k] / x0[k]) for k in FACTORS}


base_filter = (f"ts < TIMESTAMP '{T0}' AND dayofweek(ts) = dayofweek(TIMESTAMP '{NOW}') "
               f"AND hour(ts) BETWEEN 11 AND 13")
now_filter = f"ts BETWEEN TIMESTAMP '{T0}' AND TIMESTAMP '{NOW}'"
x0, x1 = funnel("country = 'DE'", base_filter), funnel("country = 'DE'", now_filter)
eff = lmdi(x0, x1)
delta = x1["orders"] - x0["orders"]
print(f"[3] DE orders/h expected {x0['orders']:.0f} actual {x1['orders']:.0f} delta {delta:.1f}; "
      f"LMDI effects sum {sum(eff.values()):.6f} (residual {abs(sum(eff.values()) - delta):.2e})")
print("    shares: " + ", ".join(f"{k} {100 * v / delta:5.1f}%" for k, v in sorted(eff.items(), key=lambda kv: -abs(kv[1]))))

# ---------------------------------------------------------------- 4. segment search over all 15 cuboids
DIMS = ["country", "platform", "channel", "category"]


def js(p: float, q: float) -> float:
    def t(a: float, b: float) -> float:
        return 0.0 if a == 0 else a * math.log(2 * a / (a + b))
    return 0.5 * (t(p, q) + t(q, p))


t4 = time.time()
cands = []
n_queries = 0
for r in range(1, len(DIMS) + 1):
    for cub in itertools.combinations(DIMS, r):
        keys = ", ".join(cub)
        sql = f"""
        SELECT {keys},
               SUM(CASE WHEN {base_filter} THEN orders END) / COUNT(DISTINCT CASE WHEN {base_filter} THEN ts END) AS f,
               SUM(CASE WHEN {now_filter} THEN orders END) / COUNT(DISTINCT CASE WHEN {now_filter} THEN ts END) AS a
        FROM fact_orders_hourly GROUP BY ALL"""
        rows, _ = run(sql, AS_OF)
        n_queries += 1
        F = sum(x[-2] or 0 for x in rows)
        A = sum(x[-1] or 0 for x in rows)
        for x in rows:
            f_, a_ = x[-2] or 0.0, x[-1] or 0.0
            ep = (a_ - f_) / (A - F)
            cands.append({"cuboid": cub, "cell": dict(zip(cub, x[:-2])), "ep": ep, "surprise": js(f_ / F, a_ / A),
                          "f": f_, "a": a_, "rel": (a_ - f_) / f_ if f_ else 0.0})
# simplest-first: smallest set of cells in the lowest-order cuboid that explains >= 67 %, ties broken by purity
best = None
for r in range(1, len(DIMS) + 1):
    for cub in itertools.combinations(DIMS, r):
        cells = sorted([c for c in cands if c["cuboid"] == cub], key=lambda c: -c["surprise"])
        chosen, total = [], 0.0
        for c in cells:
            if c["ep"] >= 0.10:
                chosen.append(c)
                total += c["ep"]
            if total >= 0.67:
                break
        if total >= 0.67:
            # purity: how concentrated the deviation is inside the chosen cells (relative drop), prefers DE^android over DE
            score = (sum(abs(c["rel"]) for c in chosen) / len(chosen)) / len(chosen)
            if best is None or score > best[0] * 1.15:
                best = (score, cub, chosen, total)
print(f"[4] segment search: {n_queries} queries over 15 cuboids, {len(cands)} cells, {1000 * (time.time() - t4):.0f} ms")
print(f"    chosen cuboid {best[1]} cells {[c['cell'] for c in best[2]]} EP {best[3]:.2f} "
      f"relative change {[round(c['rel'], 3) for c in best[2]]}")
de = next(c for c in cands if c["cell"] == {"country": "DE"})
kids = [c for c in cands if c["cuboid"] == ("country", "platform") and c["cell"]["country"] == "DE"]
print(f"    naive rule (simplest cuboid with EP >= 0.67) would stop at {de['cell']}: EP {de['ep']:.2f}, rel {de['rel']:.3f}; "
      f"its platform children are not uniform: " + ", ".join(f"{c['cell']['platform']} {c['rel']:+.3f}" for c in kids))
top = sorted(cands, key=lambda c: -c["surprise"])[:4]
print("    top by surprise: " + "; ".join(f"{c['cell']} EP {c['ep']:.2f} rel {c['rel']:.2f}" for c in top))

# ---------------------------------------------------------------- 5. holdout check for the release red herring
def seg_change(where: str) -> float:
    sql = f"""SELECT SUM(CASE WHEN {base_filter} THEN orders END) / COUNT(DISTINCT CASE WHEN {base_filter} THEN ts END),
                     SUM(CASE WHEN {now_filter} THEN orders END) / COUNT(DISTINCT CASE WHEN {now_filter} THEN ts END)
              FROM fact_orders_hourly WHERE {where}"""
    f_, a_ = run(sql, AS_OF)[0][0]
    return a_ / f_ - 1


hold = seg_change("platform = 'android' AND country <> 'DE'")
hit = seg_change("platform = 'android' AND country = 'DE'")
prov = run(f"""SELECT provider, ROUND(SUM(CASE WHEN {base_filter} THEN pay_successes END) * 1.0 / SUM(CASE WHEN {base_filter} THEN pay_attempts END), 3),
                      ROUND(SUM(CASE WHEN {now_filter} THEN pay_successes END) * 1.0 / SUM(CASE WHEN {now_filter} THEN pay_attempts END), 3)
               FROM fact_payments_hourly WHERE country = 'DE' AND platform = 'android' GROUP BY ALL ORDER BY 1""", AS_OF)[0]
print(f"[5] release scope = android in all countries; anomalous segment DE-android {100 * hit:.1f}%, "
      f"holdout (android, not DE) {100 * hold:.1f}% -> release {'rejected' if abs(hold) < 0.03 else 'kept'}")
print(f"    pay_success by provider in DE-android (before, after): {prov}")

# ---------------------------------------------------------------- 6. sqlglot placement of the vision's example metric
METRIC_SQL = """
SELECT ts, country, category,
       SUM(refunds)::DOUBLE / NULLIF(SUM(orders), 0) AS value
FROM fact_refunds_hourly
JOIN fact_orders_hourly USING (ts, country, category)
GROUP BY ALL
"""
tree = sqlglot.parse_one(METRIC_SQL, read="duckdb")
tables = sorted({t.name for t in tree.find_all(exp.Table)})
aggs = [a.sql(dialect="duckdb") for a in tree.find_all(exp.AggFunc)]
group = tree.args.get("group")
dims = [e.alias_or_name for e in tree.expressions if not e.find(exp.AggFunc)]
value = next(e for e in tree.expressions if e.find(exp.AggFunc))
div = value.find(exp.Div)
print(f"[6] parsed: tables {tables}, aggregates {aggs}, dims {dims}, GROUP BY ALL = {bool(group and group.args.get('all'))}")
print(f"    ratio detected: numerator `{div.left.sql(dialect='duckdb')}` / denominator `{div.right.sql(dialect='duckdb')}`")
bq = sqlglot.transpile(METRIC_SQL, read="duckdb", write="bigquery")[0]
print(f"    BigQuery dialect: {bq}")
with_dim = tree.copy()
with_dim.set("expressions", [exp.column("platform")] + with_dim.expressions)
try:
    con.execute(with_dim.sql(dialect="duckdb") + " LIMIT 1").fetchall()
    print("    extra GROUP BY platform: runs (platform exists only on the orders side)")
except Exception as e:  # noqa: BLE001
    print(f"    extra GROUP BY platform: rejected ({type(e).__name__})")

# ---------------------------------------------------------------- 7b. numeric formula check and join fan-out
got = run(f"SELECT ts, country, category, value FROM ({METRIC_SQL}) WHERE ts >= TIMESTAMP '2026-11-10'", AS_OF)[0]
truth = run("""
WITH r AS (SELECT ts, country, category, SUM(refunds) AS refunds FROM fact_refunds_hourly GROUP BY ALL),
     o AS (SELECT ts, country, category, SUM(orders) AS orders FROM fact_orders_hourly GROUP BY ALL)
SELECT ts, country, category, refunds * 1.0 / NULLIF(orders, 0) FROM r JOIN o USING (ts, country, category)
WHERE ts >= TIMESTAMP '2026-11-10'""", AS_OF)[0]
gd = {r[:3]: r[3] for r in got}
td = {r[:3]: r[3] for r in truth}
ratios = np.array([gd[k] / td[k] for k in td if td[k] and gd.get(k)])
print(f"[7b] metric SQL as written vs. refunds / orders at equal grain: median ratio {np.median(ratios):.3f}, "
      f"p5..p95 {np.percentile(ratios, 5):.3f}..{np.percentile(ratios, 95):.3f} over {len(ratios)} cells")
print("     -> a constant integer ratio is the signature of a join fan-out (refunds repeated per platform x channel row)")

# ---------------------------------------------------------------- 8. mix vs. rate on the Spain surge
def mix_rate(t_base: str, t_now: str) -> tuple[float, float, float]:
    sql = f"""
    SELECT country,
      SUM(CASE WHEN {t_base} THEN f.sessions END), SUM(CASE WHEN {t_base} THEN o.orders END),
      SUM(CASE WHEN {t_now} THEN f.sessions END), SUM(CASE WHEN {t_now} THEN o.orders END)
    FROM fact_funnel_hourly f JOIN fact_orders_hourly o USING (ts, country, platform, channel, category)
    WHERE f.platform <> 'android' OR f.country <> 'DE' GROUP BY ALL"""
    rows = run(sql, "2026-11-19 00:00:00")[0]
    s0, s1 = sum(r[1] for r in rows), sum(r[3] for r in rows)
    y0, y1 = sum(r[2] for r in rows) / s0, sum(r[4] for r in rows) / s1
    mix = rate = 0.0
    for _, bs, bo, ns, no in rows:
        w0, w1, r0, r1 = bs / s0, ns / s1, bo / bs, no / ns
        mix += (w1 - w0) * ((r0 + r1) / 2 - (y0 + y1) / 2)
        rate += (w0 + w1) / 2 * (r1 - r0)
    return y1 - y0, mix, rate


b8 = "f.ts < TIMESTAMP '2026-11-17 00:00:00' AND dayofweek(f.ts) = 3 AND hour(f.ts) BETWEEN 9 AND 12"
n8 = f"f.ts BETWEEN TIMESTAMP '{T_SURGE}' AND TIMESTAMP '2026-11-18 12:00:00'"
d, mix, rate = mix_rate(b8, n8)
print(f"[8] blended conversion change {100 * d:.3f} pts = mix {100 * mix:.3f} pts + rate {100 * rate:.3f} pts "
      f"(residual {abs(d - mix - rate):.2e}) -> {'innocent mix shift' if abs(rate) < 0.2 * abs(mix) else 'rate change'}")
print(f"[done] total runtime {time.time() - t_start:.1f}s")
```

