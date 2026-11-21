// Plain words for the first level of the workspace. Internal terms (|z|, LMDI, edge tests, series-hours, holdout)
// stay out of labels; the glossary below explains each one, and the sidebar shows it as a tooltip.
// Pure: no React, no DOM.

export interface GlossaryEntry {
  /** the term as the internal pages and the reports write it */
  term: string;
  /** the plain name the first level uses */
  plain: string;
  /** one or two sentences, no jargon */
  meaning: string;
}

/** Every internal term the first level avoids, with the words it uses instead. */
export const GLOSSARY: GlossaryEntry[] = [
  {
    term: "|z|",
    plain: "How unusual",
    meaning:
      "How far this hour is from the same hour in the last four weeks, counted in typical swings. Under 2 is ordinary, from 2 a little off, 5 or more raises an alarm.",
  },
  { term: "Wiggle", plain: "Small move", meaning: "A move between 2 and 5 on the unusualness scale: noted, never paged." },
  { term: "Alarm line", plain: "Alarm threshold", meaning: "5 on the unusualness scale, or 3.5 in two of the last three hours. Only then does Argus open an investigation." },
  { term: "Series-hours", plain: "Metric checks", meaning: "One metric checked for one hour. Seven key metrics for 120 hours are 840 checks." },
  {
    term: "Edge test",
    plain: "Formula check",
    meaning: "Every link in the metric map (orders = visits x conversion, ...) is re-tested against the data once a day; a link that stops holding is flagged before it is trusted.",
  },
  {
    term: "LMDI",
    plain: "Exact split",
    meaning: "A standard way to split a change into the factors of its formula so the shares add up to exactly 100%, with nothing left over.",
  },
  { term: "Segment search", plain: "Where it is", meaning: "Cutting the drop by country, platform and payment provider until it sits in the smallest group that still carries it." },
  {
    term: "Holdout",
    plain: "Comparison group",
    meaning: "The part of a suspect's reach that did not break. If the suspect were the cause, that part would have dropped too.",
  },
  { term: "Placebo test", plain: "Normal-week check", meaning: "The same test on earlier normal weeks; a real cause does not show up there." },
  {
    term: "Receipt",
    plain: "Evidence",
    meaning: "The SQL query behind a number, pinned to the moment it ran and hashed, so anyone can re-run it and get the same result.",
  },
  { term: "SUPPORTED_CAUSE", plain: "Cause found", meaning: "One logged change explains the drop and every rival suspect was tested and ruled out." },
  { term: "HYPOTHESIS", plain: "Likely cause", meaning: "The best explanation so far; at least one check could not rule the alternatives out." },
  { term: "EXPECTED", plain: "Planned change", meaning: "A plan or calendar entry explains the move, and delivery followed it: nobody was woken." },
  { term: "DATA_ISSUE", plain: "Late data", meaning: "The data had not fully arrived; Argus waited instead of raising a false alarm." },
  { term: "PROBATION", plain: "On trial", meaning: "A new link in the metric map that is used but not yet trusted until the data supports it." },
  {
    term: "Symptom",
    plain: "Knock-on effect",
    meaning: "A metric that moved only because the root metric moved (orders fall when payments fail); Argus files one incident, not one per symptom.",
  },
  {
    term: "pass@1",
    plain: "Runs right",
    meaning: "The share of sealed test runs Argus got right on its first and only try: the right page, the right cause, or rightly no page at all.",
  },
];

/** The glossary entry for a term (case-insensitive), for tooltips. */
export function gloss(term: string): GlossaryEntry | undefined {
  const key = term.toLowerCase();
  return GLOSSARY.find((g) => g.term.toLowerCase() === key || g.plain.toLowerCase() === key);
}
