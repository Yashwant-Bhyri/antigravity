export type ReportTone = "elite" | "emerging" | "risk" | "mixed";

export type DimensionScore = {
  label: string;
  score: number;
  note: string;
};

export type CoverageItem = {
  label: string;
  state: "voluntary" | "recovered" | "missed" | "incorrect";
  detail: string;
};

export type EvidenceTurn = {
  turn: string;
  route: string;
  signal: string;
  question?: string;
  observation: string;
  score: number;
  scoreAvailable?: boolean;
};

export type ClaimFinding = {
  claim: string;
  status: "substantiated" | "partial" | "not_substantiated" | "untested";
  evidence: string;
};

export type WeaknessFinding = {
  area: string;
  severity: "low" | "medium" | "high";
  trigger: string;
  interpretation: string;
  followup: string;
};

export type DemoReport = {
  sourceKind?: "demo" | "production";
  slug: string;
  tone: ReportTone;
  candidate: string;
  headline: string;
  targetRole: string;
  experience: string;
  verdict: string;
  score: number;
  confidence: number;
  questions: number;
  duration: string;
  summary: string;
  executiveRead: string;
  strongestSignal: string;
  largestRisk: string;
  interviewQuality: number;
  coverageScore: number;
  claimRisk: "low" | "medium" | "high";
  roleFit: string;
  archetype: string;
  scores: DimensionScore[];
  radar: DimensionScore[];
  coverage: CoverageItem[];
  strengths: string[];
  risks: string[];
  claims: ClaimFinding[];
  weaknesses: WeaknessFinding[];
  timeline: EvidenceTurn[];
  transcriptEvidence: string[];
  recommendedFollowups: string[];
  hiringPanelNotes: string[];
};

export const demoReports: DemoReport[] = [
  {
    slug: "riya-menon-strong",
    tone: "elite",
    candidate: "Riya Menon",
    headline: "Very strong systems candidate with real ownership and sharp failure-mode reasoning",
    targetRole: "Senior Backend Engineer - Realtime Infrastructure",
    experience: "6.5 years",
    verdict: "STRONG HIRE",
    score: 9.1,
    confidence: 0.91,
    questions: 16,
    duration: "31 min",
    summary:
      "Riya consistently converted resume claims into mechanism-level evidence. She explained how her team moved a websocket fanout service from best-effort delivery to observable at-least-once semantics, named the failure cases she initially missed, and corrected herself without losing structure. The interview found two real but scoped weaknesses: she is less crisp when prioritizing product-facing tradeoffs under ambiguous cost constraints, and she tends to discuss migration safety from an engineering lens before stakeholder rollout risk.",
    executiveRead:
      "This is the kind of candidate Antigravity should surface as high-confidence: not flawless, but unusually measurable. The report can say exactly where the strength lives and exactly where the remaining risk is.",
    strongestSignal:
      "Production reasoning under pressure: idempotency, replay safety, queue backpressure, and observability were all explained with concrete invariants and failure boundaries.",
    largestRisk:
      "Product prioritization under ambiguous cost pressure. She could compare reliability options, but needed prompting to rank user-visible impact versus operational spend.",
    interviewQuality: 0.94,
    coverageScore: 0.88,
    claimRisk: "low",
    roleFit: "Strong target-role fit",
    archetype: "Staff-track infrastructure builder",
    scores: [
      { label: "Technical depth", score: 9.4, note: "Concrete mechanisms, crisp invariants, and realistic tradeoffs." },
      { label: "Reasoning structure", score: 9.1, note: "Frames problem, names assumptions, then solves." },
      { label: "Production awareness", score: 9.5, note: "Excellent incident, rollout, and observability detail." },
      { label: "Communication", score: 8.6, note: "Dense but clear; occasionally over-indexes on implementation." },
      { label: "Adaptability", score: 8.9, note: "Recovered well from cost and stakeholder pressure." },
      { label: "Claim integrity", score: 9.3, note: "Ownership claims stayed bounded and consistent." },
    ],
    radar: [
      { label: "Mechanism", score: 9.5, note: "Deep" },
      { label: "Failure modes", score: 9.3, note: "Deep" },
      { label: "Metrics", score: 8.7, note: "Strong" },
      { label: "Ownership", score: 9.2, note: "Strong" },
      { label: "Product judgment", score: 7.7, note: "Good but tested weakness" },
      { label: "Recovery", score: 9.0, note: "Strong" },
    ],
    coverage: [
      { label: "Concurrency semantics", state: "voluntary", detail: "Named duplicate delivery, retry windows, and ordering degradation." },
      { label: "Backpressure design", state: "voluntary", detail: "Compared bounded queues, load shedding, and consumer lag metrics." },
      { label: "Observability", state: "voluntary", detail: "Defined saturation, replay age, and per-tenant delivery lag." },
      { label: "Migration safety", state: "recovered", detail: "Good after prompt; initially framed too internally." },
      { label: "Cost prioritization", state: "recovered", detail: "Could rank options only after interviewer forced business constraint." },
      { label: "Stakeholder rollout", state: "missed", detail: "No crisp customer-facing migration communication plan." },
    ],
    strengths: [
      "Explains distributed-systems behavior through invariants rather than buzzwords.",
      "Admits uncertainty quickly, then narrows the unknown into a testable boundary.",
      "Uses metrics as control signals, not decorative dashboards.",
      "Strong authorship evidence across design, implementation, and incident response.",
    ],
    risks: [
      "May need explicit product framing when reliability tradeoffs affect pricing or user segmentation.",
      "Could be coached to communicate migration risk to non-engineering audiences earlier.",
    ],
    claims: [
      {
        claim: "Led websocket fanout reliability redesign for enterprise tenants.",
        status: "substantiated",
        evidence: "Turn 4 and Turn 5 showed mechanism, incident trigger, rollout sequence, and ownership boundaries.",
      },
      {
        claim: "Reduced message loss and improved replay observability.",
        status: "substantiated",
        evidence: "Gave metric definitions, baseline caveats, and why loss reduction was not solely attributable to one patch.",
      },
      {
        claim: "Owned product rollout decisions.",
        status: "partial",
        evidence: "Owned technical rollout; product communication appeared shared with PM and SRE lead.",
      },
    ],
    weaknesses: [
      {
        area: "Business prioritization",
        severity: "medium",
        trigger: "Asked to choose between lower p99 latency and lower cloud spend for a small customer segment.",
        interpretation: "She initially optimized for system cleanliness before ranking customer and revenue impact.",
        followup: "Ask for a product-facing rollout memo or cost/benefit threshold.",
      },
      {
        area: "Stakeholder translation",
        severity: "low",
        trigger: "Asked how support and sales would explain replay semantics to customers.",
        interpretation: "Answer was correct technically but did not land in customer language.",
        followup: "Probe non-engineering communication during rollout.",
      },
    ],
    timeline: [
      { turn: "T1", route: "Trajectory map", signal: "Clear anchor", observation: "Selected the right project and scoped personal ownership.", score: 8.6 },
      { turn: "T4", route: "Implementation depth", signal: "High signal", observation: "Explained idempotent delivery ledger and replay compaction.", score: 9.4 },
      { turn: "T7", route: "Boundary pressure", signal: "Recovered", observation: "Corrected an overbroad exactly-once phrase into at-least-once plus dedupe.", score: 9.0 },
      { turn: "T11", route: "Application transfer", signal: "Strong", observation: "Transferred queue saturation reasoning to payment webhooks.", score: 9.3 },
      { turn: "T14", route: "Product tradeoff", signal: "Scoped weakness", observation: "Needed prompting to prioritize cost and customer impact.", score: 7.4 },
    ],
    transcriptEvidence: [
      "I would not call it exactly-once. The invariant was durable handoff plus idempotent consumer application.",
      "The alert that mattered was replay age by tenant, because aggregate queue depth hid one enterprise tenant getting stale updates.",
      "If cost is the hard constraint, I would protect paid enterprise tenants first and degrade free-tier fanout freshness before touching correctness.",
    ],
    recommendedFollowups: [
      "Give Riya a system design round with a customer-facing reliability budget.",
      "Ask her to write a rollout note for support and sales, not just an engineering migration plan.",
      "Reference-check whether her ownership extended to cross-functional prioritization.",
    ],
    hiringPanelNotes: [
      "Strong hire for backend infrastructure, platform reliability, eventing, or realtime systems.",
      "Likely overqualified for narrow feature-only backend roles.",
      "Pair with PM/EM interview focused on product communication and prioritization.",
    ],
  },
  {
    slug: "isha-kapoor-fresh",
    tone: "emerging",
    candidate: "Isha Kapoor",
    headline: "Fresh candidate with strong fundamentals and limited proof of production ownership",
    targetRole: "Junior Backend Engineer",
    experience: "0.8 years",
    verdict: "HIRE WITH RAMP",
    score: 6.8,
    confidence: 0.74,
    questions: 14,
    duration: "27 min",
    summary:
      "Isha has not yet proven production ownership, but she showed enough real reasoning to separate herself from a memorized junior candidate. She understands API boundaries, database indexing, retry basics, and test design. The key limitation is evidence depth: most examples came from internships, course projects, and small services, so the report should recommend a structured ramp rather than treating her as already production-independent.",
    executiveRead:
      "This report demonstrates Antigravity's fairness: it does not punish a fresh candidate for not having senior evidence, but it also refuses to inflate knowledge into ownership.",
    strongestSignal:
      "Learning velocity and fundamentals. She could explain why an index helps, when it does not, and how she would test a retry path.",
    largestRisk:
      "No tested evidence of operating a service under real load, incident pressure, or ambiguous ownership.",
    interviewQuality: 0.86,
    coverageScore: 0.69,
    claimRisk: "low",
    roleFit: "Strong junior fit, not mid-level yet",
    archetype: "High-upside apprentice engineer",
    scores: [
      { label: "Technical depth", score: 6.5, note: "Solid fundamentals, shallow production examples." },
      { label: "Reasoning structure", score: 7.2, note: "Usually decomposes before answering." },
      { label: "Production awareness", score: 5.6, note: "Knows the concepts, lacks lived operational detail." },
      { label: "Communication", score: 7.6, note: "Clear, honest, and easy to coach." },
      { label: "Adaptability", score: 7.1, note: "Improved after targeted follow-ups." },
      { label: "Claim integrity", score: 8.1, note: "Did not overstate internship ownership." },
    ],
    radar: [
      { label: "Mechanism", score: 6.8, note: "Good" },
      { label: "Failure modes", score: 5.9, note: "Developing" },
      { label: "Metrics", score: 5.6, note: "Developing" },
      { label: "Ownership", score: 4.8, note: "Limited" },
      { label: "Product judgment", score: 6.5, note: "Good for level" },
      { label: "Recovery", score: 7.6, note: "Strong" },
    ],
    coverage: [
      { label: "API design basics", state: "voluntary", detail: "Explained request validation, pagination, and error shapes." },
      { label: "Database indexing", state: "voluntary", detail: "Correctly distinguished selectivity from 'index everything' thinking." },
      { label: "Retry semantics", state: "recovered", detail: "Knew idempotency key after one prompt." },
      { label: "Operational monitoring", state: "recovered", detail: "Named logs and latency, but not ownership process." },
      { label: "Incident response", state: "missed", detail: "No real incident example; hypothetical only." },
      { label: "Scale tradeoffs", state: "missed", detail: "Could not reason past small-service traffic." },
    ],
    strengths: [
      "Clear mental model for request lifecycle and database query behavior.",
      "Honest about internship boundaries and what she did not own.",
      "Good response to correction; does not become defensive when challenged.",
      "Writes test plans that cover happy path and at least one failure path.",
    ],
    risks: [
      "Needs supervision for production incident handling.",
      "May underestimate the difference between local correctness and operational reliability.",
      "Should not be hired into a solo backend role yet.",
    ],
    claims: [
      {
        claim: "Built REST APIs during internship.",
        status: "substantiated",
        evidence: "Could describe endpoints, validation, DB tables, and test cases.",
      },
      {
        claim: "Improved query performance.",
        status: "partial",
        evidence: "Understood index rationale, but could not quantify before/after or production traffic.",
      },
      {
        claim: "Worked with deployment pipelines.",
        status: "untested",
        evidence: "Mentioned CI/CD in resume; interview budget focused on backend fundamentals.",
      },
    ],
    weaknesses: [
      {
        area: "Production ownership",
        severity: "medium",
        trigger: "Asked what she would do if a retry job duplicated user notifications.",
        interpretation: "She knew to stop the job, but did not naturally define blast radius, rollback, or customer impact.",
        followup: "Use a junior incident simulation during onsite.",
      },
      {
        area: "Metric specificity",
        severity: "medium",
        trigger: "Asked what metric proved her query improvement worked.",
        interpretation: "Started with generic 'faster response time' before narrowing to p95 query latency.",
        followup: "Ask for concrete dashboard or log examples from internship.",
      },
    ],
    timeline: [
      { turn: "T1", route: "Resume anchor", signal: "Honest scope", observation: "Separated internship task ownership from team-level design.", score: 7.4 },
      { turn: "T3", route: "Concept probe", signal: "Fundamental strength", observation: "Explained index selectivity correctly.", score: 7.2 },
      { turn: "T6", route: "Pressure follow-up", signal: "Recovered", observation: "Found idempotency key after retry challenge.", score: 6.8 },
      { turn: "T9", route: "Boundary probe", signal: "Experience gap", observation: "No real incident ownership evidence.", score: 5.3 },
      { turn: "T13", route: "Learning transfer", signal: "Positive", observation: "Applied testing framework to a new notification workflow.", score: 7.0 },
    ],
    transcriptEvidence: [
      "I should not say I owned the whole service. I built two endpoints and my mentor reviewed the schema.",
      "An index helps if the database can filter down meaningfully. If most rows match, it may not help much.",
      "For retries I would add an idempotency key, but I would want help deciding the storage and expiry policy.",
    ],
    recommendedFollowups: [
      "Run a small take-home or live exercise around API design plus retry safety.",
      "Ask her to explain one production incident article and what she would monitor.",
      "Offer a ramp plan with code review, on-call shadowing, and clear service ownership milestones.",
    ],
    hiringPanelNotes: [
      "Good junior hire if the team can mentor.",
      "Do not calibrate as mid-level based on polished communication alone.",
      "Likely to improve quickly in a high-feedback environment.",
    ],
  },
  {
    slug: "nikhil-verma-weak",
    tone: "risk",
    candidate: "Nikhil Verma",
    headline: "Weak evidence with repeated overclaiming and shallow recovery under pressure",
    targetRole: "Backend Engineer - Payments Platform",
    experience: "4 years",
    verdict: "NO HIRE",
    score: 2.9,
    confidence: 0.87,
    questions: 15,
    duration: "29 min",
    summary:
      "Nikhil's resume claims suggested payment reliability ownership, but the interview repeatedly found vocabulary without mechanism. He used terms like idempotency, exactly-once, distributed lock, and reconciliation, but could not connect them to concrete failure cases or implementation details. The strongest risk is not a single unknown; it is the pattern of confident language collapsing when asked for invariants, data model, or incident response.",
    executiveRead:
      "This is the report that makes the product valuable to hiring teams: it does not merely say 'weak'. It shows which claims failed, which probes caused the break, and why the risk is role-critical.",
    strongestSignal:
      "Basic familiarity with common backend terms; he has likely been near payments work even if he did not own the core reliability path.",
    largestRisk:
      "High claim credibility risk on role-critical payment safety. Multiple ownership and mechanism claims were not substantiated.",
    interviewQuality: 0.9,
    coverageScore: 0.76,
    claimRisk: "high",
    roleFit: "Weak target-role fit",
    archetype: "Peripheral contributor using senior vocabulary",
    scores: [
      { label: "Technical depth", score: 2.5, note: "Terms without implementation mechanism." },
      { label: "Reasoning structure", score: 3.2, note: "Answers drift under follow-up pressure." },
      { label: "Production awareness", score: 2.7, note: "No coherent incident or reconciliation plan." },
      { label: "Communication", score: 4.1, note: "Fluent at surface level; low precision." },
      { label: "Adaptability", score: 2.4, note: "Did not recover when given narrower prompts." },
      { label: "Claim integrity", score: 2.1, note: "Repeated broad claims narrowed only after confrontation." },
    ],
    radar: [
      { label: "Mechanism", score: 2.4, note: "Weak" },
      { label: "Failure modes", score: 2.7, note: "Weak" },
      { label: "Metrics", score: 3.3, note: "Weak" },
      { label: "Ownership", score: 2.0, note: "High risk" },
      { label: "Product judgment", score: 4.0, note: "Surface" },
      { label: "Recovery", score: 2.5, note: "Weak" },
    ],
    coverage: [
      { label: "Idempotency model", state: "incorrect", detail: "Described retries as exactly-once without dedupe boundary." },
      { label: "Payment reconciliation", state: "missed", detail: "Could not define ledger comparison or mismatch handling." },
      { label: "Concurrency control", state: "incorrect", detail: "Proposed global lock without contention or timeout plan." },
      { label: "Monitoring", state: "recovered", detail: "Named generic alerts but not payment-specific invariants." },
      { label: "Ownership boundary", state: "missed", detail: "Changed from owner to helper after direct probe." },
      { label: "Incident response", state: "missed", detail: "No clear freeze, rollback, customer impact, or audit sequence." },
    ],
    strengths: [
      "Can discuss high-level backend architecture vocabulary.",
      "Understands that duplicate charging is serious and should be prevented.",
    ],
    risks: [
      "Role-critical claims not substantiated under direct probing.",
      "High confidence before evidence, followed by vague correction.",
      "Unsafe misconception: treating distributed locks as a universal payment safety fix.",
      "Could not explain audit trail or reconciliation, which are core to payments work.",
    ],
    claims: [
      {
        claim: "Owned idempotency for payment retries.",
        status: "not_substantiated",
        evidence: "Could not describe key generation, persistence, expiry, or replay behavior.",
      },
      {
        claim: "Designed distributed locking for payment processing.",
        status: "not_substantiated",
        evidence: "No failure-mode awareness for lock timeout, partial success, or duplicate callbacks.",
      },
      {
        claim: "Led production incident response.",
        status: "partial",
        evidence: "Was present in war room but did not lead diagnosis or remediation.",
      },
    ],
    weaknesses: [
      {
        area: "Mechanism collapse",
        severity: "high",
        trigger: "Asked how idempotency behaves if the gateway times out after charging.",
        interpretation: "Answer confused client retry suppression with server-side payment outcome reconciliation.",
        followup: "No further interview loop needed for payments role; this is a core disqualifier.",
      },
      {
        area: "Ownership inflation",
        severity: "high",
        trigger: "Asked what code he personally changed in the reliability redesign.",
        interpretation: "Initial 'I owned it' became 'I helped test the endpoint' after two probes.",
        followup: "Reference-check if considering for non-payments backend role.",
      },
      {
        area: "Unsafe operational judgment",
        severity: "high",
        trigger: "Asked what to do after discovering double charges.",
        interpretation: "Focused on redeploying code before freezing writes, identifying affected customers, or preserving audit evidence.",
        followup: "Avoid ownership of financial correctness paths.",
      },
    ],
    timeline: [
      { turn: "T2", route: "Resume claim probe", signal: "Inflated claim", observation: "Could not name idempotency table or key lifecycle.", score: 2.6 },
      { turn: "T5", route: "Failure-mode pressure", signal: "Incorrect", observation: "Equated retry blocking with confirmed payment outcome.", score: 2.2 },
      { turn: "T8", route: "Ownership calibration", signal: "Claim narrowed", observation: "Admitted he tested rather than designed reliability path.", score: 3.0 },
      { turn: "T11", route: "Application transfer", signal: "Did not transfer", observation: "Suggested global lock for webhook duplicate problem.", score: 2.4 },
      { turn: "T14", route: "Incident response", signal: "Role-critical miss", observation: "No audit, freeze, or customer-impact sequence.", score: 2.8 },
    ],
    transcriptEvidence: [
      "We made it exactly-once by retrying only one time. If it failed again, the user could contact support.",
      "I was the owner in the sense that I knew the flow and helped QA test it.",
      "I would redeploy with a lock first, then later we can check which users were charged twice.",
    ],
    recommendedFollowups: [
      "Do not advance for payments platform ownership.",
      "If considered for a general backend role, run a hands-on debugging exercise with clear authorship checks.",
      "Reference-check resume claims before any offer conversation.",
    ],
    hiringPanelNotes: [
      "No hire for this role with high confidence.",
      "The issue is not lack of polish; it is role-critical mechanism risk.",
      "A different non-critical support/backend role would still require hands-on validation.",
    ],
  },
  {
    slug: "meera-rao-mixed",
    tone: "mixed",
    candidate: "Meera Rao",
    headline: "Mediocre-to-solid candidate: useful execution signal, uneven depth, coachable gaps",
    targetRole: "Product Engineer - B2B SaaS",
    experience: "3.5 years",
    verdict: "MAYBE",
    score: 5.8,
    confidence: 0.79,
    questions: 15,
    duration: "30 min",
    summary:
      "Meera presents as a capable feature engineer who can ship within a defined product surface. She gave credible examples around dashboard workflows, API integration, and customer feedback loops. The interview found moderate but important gaps in system boundaries, data correctness, and independent debugging under ambiguous failures. The right conclusion is not rejection by default; it is that she fits best where product scope is clear and senior engineers own the hardest platform decisions.",
    executiveRead:
      "This report is useful because it refuses a binary caricature. Meera is neither an obvious no nor a hidden superstar; the evidence points to a specific operating envelope.",
    strongestSignal:
      "Customer-aware feature execution. She can translate product asks into shippable UI/API work and incorporate feedback.",
    largestRisk:
      "Shallow ownership of backend correctness. She relies on platform teammates for consistency, data model, and failure-mode decisions.",
    interviewQuality: 0.88,
    coverageScore: 0.73,
    claimRisk: "medium",
    roleFit: "Mixed target-role fit",
    archetype: "Feature owner with platform dependency",
    scores: [
      { label: "Technical depth", score: 5.3, note: "Good at feature path, weaker at system boundary." },
      { label: "Reasoning structure", score: 6.2, note: "Coherent when problem is familiar." },
      { label: "Production awareness", score: 5.1, note: "Knows monitoring exists, less clear on invariants." },
      { label: "Communication", score: 7.0, note: "Clear and collaborative." },
      { label: "Adaptability", score: 5.7, note: "Recovers with hints, not independently." },
      { label: "Claim integrity", score: 6.0, note: "Mostly honest, a few broad ownership phrases." },
    ],
    radar: [
      { label: "Mechanism", score: 5.4, note: "Mixed" },
      { label: "Failure modes", score: 4.9, note: "Weak spot" },
      { label: "Metrics", score: 6.4, note: "Useful" },
      { label: "Ownership", score: 5.2, note: "Scoped" },
      { label: "Product judgment", score: 7.2, note: "Strongest" },
      { label: "Recovery", score: 5.8, note: "Moderate" },
    ],
    coverage: [
      { label: "Product workflow", state: "voluntary", detail: "Explained customer pain, workflow, and iteration loop." },
      { label: "API integration", state: "voluntary", detail: "Credible details on pagination, auth, and retries." },
      { label: "Data correctness", state: "recovered", detail: "Needed prompt to define source of truth." },
      { label: "Debugging ambiguous failures", state: "recovered", detail: "Eventually used logs and repro steps, but not first-principles." },
      { label: "Concurrency boundary", state: "missed", detail: "Could not reason through duplicate updates cleanly." },
      { label: "Platform ownership", state: "missed", detail: "Relied on platform team for core decisions." },
    ],
    strengths: [
      "Good user empathy and feature iteration discipline.",
      "Can connect frontend state, API response shape, and customer workflow.",
      "Collaborative; likely effective with clear technical mentorship.",
      "Does not become defensive when limitations are exposed.",
    ],
    risks: [
      "May overstate ownership of platform-level outcomes.",
      "Needs stronger debugging habits for ambiguous production issues.",
      "Would struggle in a small team where product engineer also owns backend correctness.",
    ],
    claims: [
      {
        claim: "Owned enterprise reporting dashboard.",
        status: "partial",
        evidence: "Owned UI workflows and API integration; data model and correctness owned by platform team.",
      },
      {
        claim: "Improved customer activation through analytics.",
        status: "substantiated",
        evidence: "Explained metric, segment, and product change with reasonable attribution caveats.",
      },
      {
        claim: "Designed backend architecture.",
        status: "not_substantiated",
        evidence: "Could describe API usage, but not schema, consistency boundary, or failure behavior.",
      },
    ],
    weaknesses: [
      {
        area: "Backend boundary depth",
        severity: "medium",
        trigger: "Asked what happens when two admins update the same dashboard filter set.",
        interpretation: "She described UI debounce, not server-side conflict behavior.",
        followup: "Run a practical API consistency exercise.",
      },
      {
        area: "Debugging autonomy",
        severity: "medium",
        trigger: "Asked how she would investigate a metric drop after release.",
        interpretation: "Started with asking analytics team before forming hypotheses from logs, cohorts, or rollout timing.",
        followup: "Probe structured incident debugging.",
      },
      {
        area: "Ownership language",
        severity: "low",
        trigger: "Claimed architecture ownership, then clarified platform team made data-model decisions.",
        interpretation: "Mostly calibration issue, not deception.",
        followup: "Clarify exact scope in reference call.",
      },
    ],
    timeline: [
      { turn: "T1", route: "Resume map", signal: "Credible product anchor", observation: "Explained enterprise dashboard workflow clearly.", score: 6.8 },
      { turn: "T4", route: "Implementation depth", signal: "Moderate", observation: "Good API integration detail, little data-model authority.", score: 5.9 },
      { turn: "T7", route: "Boundary pressure", signal: "Weakness", observation: "Concurrency question stayed at UI layer.", score: 4.7 },
      { turn: "T10", route: "Application transfer", signal: "Recovered", observation: "Applied cohort thinking to activation drop after prompt.", score: 6.1 },
      { turn: "T14", route: "Synthesis", signal: "Honest calibration", observation: "Accurately bounded her platform ownership.", score: 6.4 },
    ],
    transcriptEvidence: [
      "I owned the reporting experience end to end from the user's point of view, but the canonical data model was owned by platform.",
      "For activation I compared teams that used saved templates versus those that started from scratch. I would be careful calling it causal.",
      "I would first reproduce the issue in the dashboard, then check the API response. I probably need help on the database conflict piece.",
    ],
    recommendedFollowups: [
      "Use a practical exercise around conflicting updates and stale data.",
      "Probe debugging sequence: hypothesis, logs, cohort, rollback, customer impact.",
      "Hire if the role is product-feature heavy with senior platform support.",
    ],
    hiringPanelNotes: [
      "Maybe for product engineering, lean no for platform-heavy backend.",
      "Best environment: clear ownership boundaries, strong code review, customer-facing roadmap.",
      "Do not treat dashboard outcome claims as backend architecture proof.",
    ],
  },
];

export function getDemoReport(slug: string) {
  return demoReports.find((report) => report.slug === slug);
}
