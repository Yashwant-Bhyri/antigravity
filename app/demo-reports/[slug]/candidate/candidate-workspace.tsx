"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { DemoReport } from "../../report-data";

type Track = "mirror" | "concepts" | "skills" | "practice";

type ConceptRow = {
  concept: string;
  understanding: number;
  application: number;
  proof: string;
  nextMove: string;
};

type SkillRow = {
  skill: string;
  score: number;
  pattern: string;
  upgrade: string;
};

type FocusPlan = {
  priority: "Now" | "Next" | "Later";
  area: string;
  why: string;
  exercise: string;
};

type TechnicalConcept = {
  concept: string;
  score: number;
  evidence: string;
  missing: string;
  better: string;
  eight: string;
  ten: string;
};

type RubricItem = {
  label: string;
  value: string;
  tone: "green" | "amber" | "red" | "cyan" | "slate";
};

const trackLabels: Record<Track, string> = {
  mirror: "Personal mirror",
  concepts: "Concept map",
  skills: "Interview skills",
  practice: "Practice plan",
};

const trackMeta: Record<Track, { description: string; outcome: string }> = {
  mirror: {
    description: "Start here to understand the main story the interview revealed: what you proved, what stayed vague, and how you should position yourself.",
    outcome: "Clarifies the personal narrative behind the score.",
  },
  concepts: {
    description: "Use this to inspect the exact technical and role concepts behind the report, including what evidence was missing and what stronger proof sounds like.",
    outcome: "Turns broad feedback into specific learning targets.",
  },
  skills: {
    description: "Use this to review answer structure, specificity, ownership, recovery, and presentation clarity with examples of better answers.",
    outcome: "Shows how to improve the way you communicate under interview pressure.",
  },
  practice: {
    description: "Use this to convert the report into a focused training plan with exercises and prompts for the next interview cycle.",
    outcome: "Turns reflection into a concrete practice loop.",
  },
};

const toneBadge = {
  elite: "border-emerald-200 bg-emerald-50 text-emerald-800",
  emerging: "border-cyan-200 bg-cyan-50 text-cyan-800",
  risk: "border-rose-200 bg-rose-50 text-rose-800",
  mixed: "border-amber-200 bg-amber-50 text-amber-800",
};

export function CandidateWorkspace({
  report,
  galleryHref = "/demo-reports",
  galleryLabel = "Demo reports",
}: {
  report: DemoReport;
  galleryHref?: string;
  galleryLabel?: string;
}) {
  const [track, setTrack] = useState<Track>("mirror");
  const [selectedConcept, setSelectedConcept] = useState(0);
  const [selectedSkill, setSelectedSkill] = useState(0);
  const [selectedPlan, setSelectedPlan] = useState(0);

  const concepts = useMemo(() => conceptMapFor(report), [report]);
  const technicalConcepts = useMemo(() => technicalConceptsFor(report), [report]);
  const skills = useMemo(() => behaviorMapFor(report), [report]);
  const focusPlan = useMemo(() => focusPlanFor(report), [report]);
  const productionEvidence = report.sourceKind === "production";

  return (
    <main className="min-h-screen bg-[linear-gradient(180deg,#f7faf9_0%,#eef4f6_48%,#fbfbfb_100%)] text-slate-950">
      <div className="mx-auto flex w-full max-w-[1540px] min-w-0 flex-col gap-5 px-4 py-5 md:px-8">
        <nav className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <Link href={galleryHref} className="group inline-flex items-center gap-3 hover:text-slate-950">
            <ProductMark />
            <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 group-hover:text-slate-950">{galleryLabel}</span>
          </Link>
          <span className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800">
            Candidate coaching view
          </span>
        </nav>

        <section>
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="grid gap-5 border-b border-slate-200 bg-[#f8fbfb] p-5 md:p-6 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-md border px-3 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] ${toneBadge[report.tone]}`}>
                    Candidate reflection
                  </span>
                  <span className="rounded-md border border-slate-200 bg-white px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
                    {report.targetRole}
                  </span>
                </div>
                <p className="mt-5 font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Personal assessment report</p>
                <h1 className="mt-2 text-4xl font-semibold text-slate-950 md:text-6xl">{report.candidate}</h1>
                <p className="mt-3 max-w-4xl text-base leading-7 text-slate-600">
                  A reflective report that separates what you proved, what stayed unproven, how your interview behavior landed,
                  and which practice loop will improve your next role-specific interview.
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Coaching status</p>
                <p className="mt-3 text-2xl font-semibold text-slate-950">
                  {productionEvidence
                    ? "Evidence-bound reflection"
                    : candidatePositioningLabel(report)}
                </p>
                <p className="mt-4 text-sm leading-6 text-slate-600">
                  {productionEvidence
                    ? "Use the retained strengths, gaps, and practice prompts below. This interview does not establish employer role readiness."
                    : candidateHeadline(report)}
                </p>
              </div>
            </div>

            <div className="grid border-b border-slate-200 bg-white md:grid-cols-3">
              <HeroStat label="What you proved" value={shorten(report.strongestSignal, 150)} />
              <HeroStat label="Most important gap" value={shorten(report.largestRisk, 150)} />
              <HeroStat
                label={productionEvidence ? "Evidence scope" : "Best positioning"}
                value={
                  productionEvidence
                    ? `${report.questions} retained probes · ${Math.round(report.coverageScore * 100)}% reported coverage`
                    : `${candidatePositioningLabel(report)}. ${report.archetype}.`
                }
              />
            </div>

            {productionEvidence ? (
              <section className="border-t border-slate-200 bg-white p-4 md:p-5">
                <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Evidence-bound coaching report
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  This live report shows only retained interview dimensions,
                  coverage, claims, risks, and practice actions. It does not
                  manufacture job-readiness or improvement-readiness scores.
                </p>
              </section>
            ) : (
              <CandidateTrackNavigation track={track} setTrack={setTrack} />
            )}
          </div>

        </section>

        <section className={productionEvidence ? "grid gap-5" : "grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]"}>
          <div className="min-w-0">
            <CandidateFullReport
              report={report}
              track={track}
              concepts={concepts}
              technicalConcepts={technicalConcepts}
              skills={skills}
              focusPlan={focusPlan}
              selectedConcept={selectedConcept}
              setSelectedConcept={setSelectedConcept}
              selectedSkill={selectedSkill}
              setSelectedSkill={setSelectedSkill}
              selectedPlan={selectedPlan}
              setSelectedPlan={setSelectedPlan}
            />
          </div>
          {!productionEvidence ? (
            <CandidateReflectionSideRail report={report} track={track} concept={concepts[selectedConcept]} skill={skills[selectedSkill]} plan={focusPlan[selectedPlan]} />
          ) : null}
        </section>
      </div>
    </main>
  );
}

function CandidateFullReport({
  report,
  track,
  concepts,
  technicalConcepts,
  skills,
  focusPlan,
  selectedConcept,
  setSelectedConcept,
  selectedSkill,
  setSelectedSkill,
  selectedPlan,
  setSelectedPlan,
}: {
  report: DemoReport;
  track: Track;
  concepts: ConceptRow[];
  technicalConcepts: TechnicalConcept[];
  skills: SkillRow[];
  focusPlan: FocusPlan[];
  selectedConcept: number;
  setSelectedConcept: (index: number) => void;
  selectedSkill: number;
  setSelectedSkill: (index: number) => void;
  selectedPlan: number;
  setSelectedPlan: (index: number) => void;
}) {
  if (report.sourceKind === "production") {
    return (
      <div className="grid gap-5">
        <Panel title="Evidence boundary">
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-950">
            Scores below are interview-only dimensions from the saved evidence
            packet. They do not measure employer role fit and are not hiring
            outcomes. Raw transcript wording may contain speech-recognition
            errors; verify technical terms against audio before relying on
            exact phrasing.
          </div>
        </Panel>
        <MirrorTrack report={report} />
        <Panel title="Recorded interview dimensions">
          <div className="grid gap-3 md:grid-cols-2">
            {report.scores.map((item) => (
              <div key={item.label} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-950">{item.label}</p>
                  <span className="font-mono text-sm font-semibold text-slate-800">{item.score.toFixed(1)}/10</span>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-600">{item.note}</p>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Observed knowledge coverage">
          <div className="grid gap-3 md:grid-cols-2">
            {report.coverage.map((item) => (
              <div key={`${item.state}-${item.label}`} className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="text-sm font-semibold text-slate-950">{item.label}</p>
                <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{item.state}</p>
                <p className="mt-2 text-xs leading-5 text-slate-600">{item.detail}</p>
              </div>
            ))}
          </div>
        </Panel>
        <WeaknessRepairBoard report={report} />
        <PracticeTrack report={report} focusPlan={focusPlan} selected={selectedPlan} setSelected={setSelectedPlan} />
      </div>
    );
  }
  return (
    <div className="grid gap-5">
      <TrackFocusPanel
        report={report}
        track={track}
        concepts={concepts}
        technicalConcepts={technicalConcepts}
        skills={skills}
        focusPlan={focusPlan}
        selectedConcept={selectedConcept}
        selectedSkill={selectedSkill}
        selectedPlan={selectedPlan}
      />
      <CandidateGrowthAnalytics report={report} concepts={concepts} skills={skills} focusPlan={focusPlan} />
      <MirrorTrack report={report} />
      <ConceptTrack rows={concepts} selected={selectedConcept} setSelected={setSelectedConcept} />
      <TechnicalConceptBoard concepts={technicalConcepts} compact />
      <SkillTrack report={report} rows={skills} selected={selectedSkill} setSelected={setSelectedSkill} />
      <WeaknessRepairBoard report={report} />
      <PracticeTrack report={report} focusPlan={focusPlan} selected={selectedPlan} setSelected={setSelectedPlan} />
    </div>
  );
}

function ProductMark() {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-950 font-mono text-xs font-semibold text-white shadow-sm">AG</span>
      <span className="text-sm font-semibold text-slate-950">Antigravity</span>
    </span>
  );
}

function CandidateTrackNavigation({ track, setTrack }: { track: Track; setTrack: (track: Track) => void }) {
  return (
    <section className="border-t border-slate-200 bg-white p-4 md:p-5" aria-label="Candidate report navigation">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Reflection navigation</p>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            Choose a section to update the main reflection view and the coaching guide. The complete report stays below, so these cards help you explore the assessment without losing the full context.
          </p>
        </div>
        <span className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900">
          Currently viewing: {trackLabels[track]}
        </span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-4">
        {(Object.keys(trackLabels) as Track[]).map((item, index) => {
          const active = track === item;
          return (
            <button
              key={item}
              type="button"
              data-testid={`candidate-track-${item}`}
              onClick={() => setTrack(item)}
              className={`group min-h-[168px] rounded-lg border p-4 text-left transition ${
                active
                  ? "border-slate-950 bg-slate-950 text-white shadow-lg shadow-slate-950/10"
                  : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-400 hover:bg-white hover:shadow-sm"
              }`}
            >
              <span className={`flex h-8 w-8 items-center justify-center rounded-md font-mono text-xs font-semibold ${active ? "bg-white text-slate-950" : "bg-white text-slate-600"}`}>
                {index + 1}
              </span>
              <span className="mt-4 block text-base font-semibold">{trackLabels[item]}</span>
              <span className={`mt-2 block text-xs leading-5 ${active ? "text-slate-200" : "text-slate-600"}`}>{trackMeta[item].description}</span>
              <span className={`mt-3 block border-t pt-3 text-[11px] font-semibold leading-5 ${active ? "border-white/20 text-emerald-100" : "border-slate-200 text-slate-500"}`}>
                {trackMeta[item].outcome}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function MirrorTrack({ report }: { report: DemoReport }) {
  return (
    <div className="grid gap-5">
      <ReflectionScoreboard report={report} />
      <Panel title="Experience demonstration">
        <div className="grid gap-3 lg:grid-cols-3">
          {report.claims.map((claim) => (
            <div key={claim.claim} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-950">{claim.claim}</p>
                <span className={`rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${claimClass(claim.status)}`}>{claim.status.replace(/_/g, " ")}</span>
              </div>
              <div className="mt-4 grid gap-3">
                <ClaimField label="Evidence" value={claim.evidence} />
                <ClaimField label="Upgrade" value={claimUpgrade(claim.status)} />
              </div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Personal operating manual">
        <div className="grid gap-4 lg:grid-cols-3">
          <OperatingColumn report={report} label="Lead with" items={report.strengths.slice(0, 3)} tone="green" />
          <OperatingColumn report={report} label="Do not hide" items={report.risks.slice(0, 3)} tone="amber" />
          <OperatingColumn report={report} label="Say more clearly" items={communicationAdviceFor(report)} tone="cyan" />
        </div>
      </Panel>
    </div>
  );
}

function TrackFocusPanel({
  report,
  track,
  concepts,
  technicalConcepts,
  skills,
  focusPlan,
  selectedConcept,
  selectedSkill,
  selectedPlan,
}: {
  report: DemoReport;
  track: Track;
  concepts: ConceptRow[];
  technicalConcepts: TechnicalConcept[];
  skills: SkillRow[];
  focusPlan: FocusPlan[];
  selectedConcept: number;
  selectedSkill: number;
  selectedPlan: number;
}) {
  if (track === "concepts") {
    return (
      <Panel title="Concept focus view">
        <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
          <SignalCard label="Selected job concept" value={`${concepts[selectedConcept].concept}: ${concepts[selectedConcept].nextMove}`} tone="cyan" />
          <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-800">Technical concept map</p>
            <p className="mt-2 text-sm leading-6 text-slate-700">
              This section separates behavioral confidence from exact technical proof: mechanism, failure mode, ownership boundary, and what stronger evidence would sound like.
            </p>
          </div>
        </div>
        <div className="mt-4">
          <TechnicalConceptBoard concepts={technicalConcepts} shell={false} />
        </div>
      </Panel>
    );
  }

  if (track === "skills") {
    return (
      <Panel title="Interview skills improvement view">
        <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
          <SignalCard label="Selected behavior" value={`${skills[selectedSkill].skill}: ${skills[selectedSkill].pattern}`} tone="green" />
          <RubricDetails title="Why this score and how to improve it" items={skillRubricFor(skills[selectedSkill], report)} defaultOpen />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {skills.map((skill) => (
            <div key={skill.skill} className={`rounded-lg border p-4 ${toneSurface(skill.score >= 8 ? "green" : skill.score >= 6 ? "cyan" : skill.score >= 4.5 ? "amber" : "red")}`}>
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-semibold text-slate-950">{skill.skill}</p>
                <span className="font-mono text-sm font-semibold text-slate-800">{skill.score.toFixed(1)}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-700">{skill.upgrade}</p>
            </div>
          ))}
        </div>
      </Panel>
    );
  }

  if (track === "practice") {
    return (
      <Panel title="Practice execution view">
        <div className="grid gap-4 lg:grid-cols-3">
          <SignalCard label="Current loop" value={`${focusPlan[selectedPlan].priority}: ${focusPlan[selectedPlan].area}`} tone={focusPlan[selectedPlan].priority === "Now" ? "red" : "amber"} />
          <SignalCard label="Why it matters" value={focusPlan[selectedPlan].why} tone="cyan" />
          <SignalCard label="Proof standard" value="Repeat until the answer includes situation, mechanism, metric, ownership boundary, and failure case." tone="green" />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {practicePromptsFor(report).slice(0, 4).map((prompt, index) => (
            <div key={prompt} className="grid grid-cols-[34px_1fr] gap-3 rounded-lg border border-slate-200 bg-white p-4">
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-950 font-mono text-xs font-semibold text-white">{index + 1}</span>
              <p className="text-sm leading-6 text-slate-700">{prompt}</p>
            </div>
          ))}
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Personal mirror focus">
      <div className="grid gap-4 lg:grid-cols-3">
        <SignalCard label="The strongest story you should lead with in your next interview" value={report.strongestSignal} tone="green" />
        <SignalCard label="Do not let this stay vague" value={report.largestRisk} tone={report.tone === "risk" ? "red" : "amber"} />
        <SignalCard label="Positioning sentence" value={positioningAdvice(report)} tone="cyan" />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {report.claims.slice(0, 2).map((claim) => (
          <RubricDetails key={claim.claim} title={`Claim reflection: ${claim.claim}`} items={claimReflectionFor(claim)} />
        ))}
      </div>
    </Panel>
  );
}

function CandidateGrowthAnalytics({
  report,
  concepts,
  skills,
  focusPlan,
}: {
  report: DemoReport;
  concepts: ConceptRow[];
  skills: SkillRow[];
  focusPlan: FocusPlan[];
}) {
  const sequence = [
    { label: "Understand what landed", detail: "Start with the exact retained evidence and its limitations, not only the interview result." },
    { label: "Repair the weakest mechanism", detail: "Deepen the technical concepts that were only partially proven." },
    { label: "Package better answers", detail: "Practice structure, specificity, ownership, and recovery under pressure." },
    { label: "Prove it next time", detail: "Convert the practice plan into a runnable artifact, test, or evidence-backed example." },
  ];
  return (
    <Panel title="Growth trajectory and mirror analytics">
      <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Improvement trajectory</p>
              <h3 className="mt-2 text-xl font-semibold text-slate-950">A practical route from current interview signal to a stronger next interview.</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                This map turns the report into a sequence: understand the current evidence, repair the weakest concept, package the answer better, then prove it with a sharper example.
              </p>
            </div>
            <span className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 font-mono text-xs font-semibold text-emerald-800">
              Evidence-led practice sequence
            </span>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-4">
            {sequence.map((step, index) => (
              <div key={step.label} className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-950 font-mono text-[10px] font-semibold text-white">{index + 1}</span>
                </div>
                <p className="mt-3 text-sm font-semibold leading-5 text-slate-950">{step.label}</p>
                <p className="mt-2 text-xs leading-5 text-slate-600">{step.detail}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Concept application matrix</p>
            <div className="mt-4 grid gap-3">
              {concepts.map((concept) => (
                <div key={concept.concept}>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold text-slate-700">{concept.concept}</p>
                    <p className="font-mono text-[10px] text-slate-500">{concept.application.toFixed(1)} applied</p>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <MiniSignalBar label="Understanding" value={concept.understanding} />
                    <MiniSignalBar label="Application" value={concept.application} />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">30-day repair route</p>
            <div className="mt-3 grid gap-2">
              {focusPlan.map((item, index) => (
                <div key={`${item.priority}-${item.area}`} className="grid grid-cols-[34px_1fr] gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-md bg-white font-mono text-[10px] font-semibold text-slate-700">{index + 1}</span>
                  <div>
                    <p className="text-sm font-semibold text-slate-950">{item.priority}: {item.area}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-600">{item.exercise}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function MiniSignalBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-slate-500">{label}</p>
        <p className="font-mono text-[10px] font-semibold text-slate-700">{value.toFixed(1)}</p>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${value * 10}%`, background: scoreColor(value) }} />
      </div>
    </div>
  );
}

function ReflectionScoreboard({ report }: { report: DemoReport }) {
  const cards = [
    { label: "Merit signal", value: report.strengths[0], metric: "Proven", tone: "green" as const },
    { label: "Primary gap", value: report.risks[0], metric: report.tone === "risk" ? "Urgent" : "Focus", tone: report.tone === "risk" ? "red" as const : "amber" as const },
    report.sourceKind === "production"
      ? {
          label: "Evidence scope",
          value: `${report.questions} retained probes with ${Math.round(report.coverageScore * 100)}% reported coverage. Employer role fit was not assessed.`,
          metric: "Boundary",
          tone: "cyan" as const,
        }
      : { label: "Positioning", value: positioningAdvice(report), metric: "Narrative", tone: "cyan" as const },
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {cards.map((card) => (
        <div key={card.label} className={`rounded-lg border p-4 shadow-sm ${toneSurface(card.tone)}`}>
          <div className="flex items-center justify-between gap-3">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{card.label}</p>
            <span className="rounded-md border border-white/70 bg-white/70 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-slate-700">{card.metric}</span>
          </div>
          <p className="mt-4 text-sm font-semibold leading-6 text-slate-900">{card.value}</p>
        </div>
      ))}
    </div>
  );
}

function ClaimField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-2 text-xs leading-5 text-slate-700">{value}</p>
    </div>
  );
}

function WeaknessRepairBoard({ report }: { report: DemoReport }) {
  return (
    <Panel title="Weakness repair board">
      <div className="grid gap-3">
        {report.weaknesses.map((weakness) => (
          <div key={weakness.area} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-base font-semibold text-slate-950">{weakness.area}</p>
              <span className={`rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${severityClass(weakness.severity)}`}>
                {weakness.severity}
              </span>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <RepairCell label="Trigger" value={weakness.trigger} />
              <RepairCell label="Interpretation" value={weakness.interpretation} />
              <RepairCell label="Next answer move" value={weakness.followup} />
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function RepairCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-2 text-xs leading-5 text-slate-700">{value}</p>
    </div>
  );
}

function ConceptTrack({ rows, selected, setSelected }: { rows: ConceptRow[]; selected: number; setSelected: (index: number) => void }) {
  return (
    <Panel title="Concept to application map">
      <div className="grid gap-3">
        {rows.map((row, index) => (
          <button
            key={row.concept}
            type="button"
            data-testid={`concept-row-${slugify(row.concept)}`}
            onClick={() => setSelected(index)}
            className={`grid gap-4 rounded-lg border p-4 text-left transition lg:grid-cols-[190px_1fr_1fr] lg:items-center ${
              selected === index ? "border-slate-950 bg-slate-50" : "border-slate-200 bg-white hover:bg-slate-50"
            }`}
          >
            <div>
              <p className="text-base font-semibold text-slate-950">{row.concept}</p>
              <p className="mt-1 text-xs text-slate-500">understanding vs application</p>
            </div>
            <DualMeter leftLabel="Understanding" left={row.understanding} rightLabel="Application" right={row.application} />
            <div>
              <p className="text-xs leading-5 text-slate-600">{row.proof}</p>
              <p className="mt-2 text-xs leading-5 text-slate-800"><span className="font-semibold">Next:</span> {row.nextMove}</p>
            </div>
          </button>
        ))}
      </div>
    </Panel>
  );
}

function TechnicalConceptBoard({ concepts, compact = false, shell = true }: { concepts: TechnicalConcept[]; compact?: boolean; shell?: boolean }) {
  const content = (
      <div className="grid gap-3">
        {concepts.map((concept) => (
          <div key={concept.concept} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_150px] md:items-start">
              <div>
                <p className="text-base font-semibold text-slate-950">{concept.concept}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{concept.evidence}</p>
              </div>
              <ReadinessPill value={concept.score} />
            </div>
            <div className="mt-4">
              <RubricDetails
                title="Open technical read"
                items={[
                  { label: "Missing", value: concept.missing, tone: concept.score >= 7 ? "amber" : "red" },
                  { label: "Better answer", value: concept.better, tone: "cyan" },
                  { label: "8/10 answer", value: concept.eight, tone: "green" },
                  { label: "10/10 answer", value: concept.ten, tone: "green" },
                ]}
              />
            </div>
          </div>
        ))}
      </div>
  );
  return shell ? <Panel title={compact ? "Technical concept proof" : "Exact technical concepts"}>{content}</Panel> : content;
}

function ReadinessPill({ value }: { value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">Proof</p>
        <p className="font-mono text-sm font-semibold text-slate-800">{value.toFixed(1)}</p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${value * 10}%`, background: scoreColor(value) }} />
      </div>
    </div>
  );
}

function SkillTrack({ report, rows, selected, setSelected }: { report: DemoReport; rows: SkillRow[]; selected: number; setSelected: (index: number) => void }) {
  return (
    <Panel title="Interview behavior skills">
      <div className="grid gap-3">
        {rows.map((row, index) => (
          <div
            key={row.skill}
            data-testid={`skill-row-${slugify(row.skill)}`}
            className={`rounded-lg border p-4 text-left transition ${selected === index ? "border-slate-950 bg-slate-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
          >
            <button type="button" onClick={() => setSelected(index)} className="w-full text-left">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-base font-semibold text-slate-950">{row.skill}</p>
                  <p className="mt-1 text-sm leading-6 text-slate-600">{row.pattern}</p>
                </div>
                <p className="font-mono text-sm font-semibold text-slate-800">{row.score.toFixed(1)}</p>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full rounded-full" style={{ width: `${row.score * 10}%`, background: scoreColor(row.score) }} />
              </div>
              <p className="mt-3 text-xs leading-6 text-slate-800"><span className="font-semibold">Upgrade:</span> {row.upgrade}</p>
            </button>
            <div className="mt-3">
              <RubricDetails title="Why this score?" items={skillRubricFor(row, report)} />
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function PracticeTrack({ report, focusPlan, selected, setSelected }: { report: DemoReport; focusPlan: FocusPlan[]; selected: number; setSelected: (index: number) => void }) {
  return (
    <div className="grid gap-5">
      <Panel title="30-day focus plan">
        <div className="grid gap-3">
          {focusPlan.map((item, index) => (
            <button
              key={`${item.priority}-${item.area}`}
              type="button"
              data-testid={`plan-row-${slugify(item.area)}`}
              onClick={() => setSelected(index)}
              className={`rounded-lg border p-4 text-left transition ${selected === index ? "border-slate-950 bg-slate-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${priorityClass(item.priority)}`}>{item.priority}</span>
                <p className="text-sm font-semibold text-slate-950">{item.area}</p>
              </div>
              <p className="mt-2 text-xs leading-6 text-slate-600">{item.why}</p>
              <p className="mt-2 text-xs leading-6 text-slate-800"><span className="font-semibold">Exercise:</span> {item.exercise}</p>
            </button>
          ))}
        </div>
      </Panel>
      <Panel title="Practice prompts">
        <div className="grid gap-3 md:grid-cols-2">
          {practicePromptsFor(report).map((prompt) => (
            <div key={prompt} className="rounded-lg border border-slate-200 bg-white p-4 text-sm leading-7 text-slate-700">{prompt}</div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function ReflectionRail({
  report,
  concepts,
  skills,
  focusPlan,
  selectedConcept,
  selectedSkill,
  selectedPlan,
  track,
}: {
  report: DemoReport;
  concepts: ConceptRow[];
  skills: SkillRow[];
  focusPlan: FocusPlan[];
  selectedConcept: number;
  selectedSkill: number;
  selectedPlan: number;
  track: Track;
}) {
  const concept = concepts[selectedConcept];
  const skill = skills[selectedSkill];
  const plan = focusPlan[selectedPlan];
  return (
    <aside className="grid gap-4 lg:grid-cols-3 xl:grid-cols-1 xl:sticky xl:top-5 xl:self-start">
      <RailTile label="Report section currently guiding this reflection" value={trackLabels[track]} detail={candidateHeadline(report)} tone="slate" />
      <RailTile label="Role concept currently selected for deeper technical reflection" value={concept.concept} detail={`${concept.understanding.toFixed(1)} understanding / ${concept.application.toFixed(1)} application`} tone="cyan" />
      <RailTile label="Interview communication skill currently selected for coaching" value={skill.skill} detail={skill.upgrade} tone="green" />
      <RailTile label="Training loop currently selected for the candidate's next improvement cycle" value={`${plan.priority}: ${plan.area}`} detail={plan.exercise} tone={plan.priority === "Now" ? "red" : plan.priority === "Next" ? "amber" : "cyan"} />
    </aside>
  );
}

function CandidateReflectionSideRail({ report, track, concept, skill, plan }: { report: DemoReport; track: Track; concept: ConceptRow; skill: SkillRow; plan: FocusPlan }) {
  const selected = candidateSideContextFor(report, track, concept, skill, plan);
  return (
    <aside className="xl:sticky xl:top-5 xl:self-start">
      <div className="max-h-[calc(100vh-2.5rem)] overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Reflection guide</p>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">Review</span>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-600">
          The first block stays constant as your personal mirror. The second block changes with the selected report section, so you can review stable context and active coaching without losing the main report.
        </p>

        <section className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Always-visible reflection context</p>
          <div className="mt-3 grid gap-3">
            <RailTile label="How to position your current evidence" value={candidatePositioningLabel(report)} detail={candidateHeadline(report)} tone="slate" />
            <RailTile label="Strongest story to lead with when asked about your best evidence" value={report.strongestSignal} detail={positioningAdvice(report)} tone="green" />
            <RailTile label="Most important gap to name honestly before it becomes a trust problem" value={report.largestRisk} detail="Use this as a repair target, not as something to hide." tone={report.tone === "risk" ? "red" : "amber"} />
          </div>
        </section>

        <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Changes with selected reflection section</p>
            <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-emerald-800">{trackLabels[track]}</span>
          </div>
          <h2 className="mt-4 text-2xl font-semibold text-slate-950">{selected.value}</h2>
          <p className="mt-1 font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{selected.title}</p>
          <div className="mt-4 space-y-3">
            {selected.items.map((item) => (
              <p key={item} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700">{item}</p>
            ))}
          </div>
        </section>
      </div>
    </aside>
  );
}

function candidateSideContextFor(report: DemoReport, track: Track, concept: ConceptRow, skill: SkillRow, plan: FocusPlan) {
  const byTrack: Record<Track, { title: string; value: string; items: string[] }> = {
    mirror: {
      title: "How to read your personal mirror",
      value: candidatePositioningLabel(report),
      items: [
        report.strongestSignal,
        report.largestRisk,
        positioningAdvice(report),
        "Use this section to rewrite your interview narrative so it leads with proof, admits boundaries, and makes your next role fit easier to understand.",
      ],
    },
    concepts: {
      title: "Technical concept currently selected for deeper repair",
      value: concept.concept,
      items: [
        concept.proof,
        concept.nextMove,
        `Understanding ${concept.understanding.toFixed(1)} / Application ${concept.application.toFixed(1)}`,
        "Use this as a study target: explain the mechanism, failure mode, test, metric, and ownership boundary before your next interview.",
      ],
    },
    skills: {
      title: "Interview behavior currently selected for coaching",
      value: skill.skill,
      items: [
        skill.pattern,
        skill.upgrade,
        `Observed score ${skill.score.toFixed(1)}/10`,
        "Practice this skill aloud until the answer becomes easier to follow under challenge, not only when you have time to think.",
      ],
    },
    practice: {
      title: "Training loop currently selected for the next improvement cycle",
      value: `${plan.priority}: ${plan.area}`,
      items: [
        plan.why,
        plan.exercise,
        "Repeat until you can answer with proof, mechanism, metric, failure case, and an honest ownership boundary.",
      ],
    },
  };
  return byTrack[track];
}

function ActionPanel({ report, track, concept, skill, plan }: { report: DemoReport; track: Track; concept: ConceptRow; skill: SkillRow; plan: FocusPlan }) {
  const byTrack: Record<Track, { title: string; value: string; items: string[] }> = {
    mirror: { title: "Reflection anchor", value: candidatePositioningLabel(report), items: [report.strongestSignal, report.largestRisk, positioningAdvice(report)] },
    concepts: { title: "Concept drill-down", value: concept.concept, items: [concept.proof, concept.nextMove, `Understanding ${concept.understanding.toFixed(1)} / Application ${concept.application.toFixed(1)}`] },
    skills: { title: "Answer behavior drill-down", value: skill.skill, items: [skill.pattern, skill.upgrade, `Observed score ${skill.score.toFixed(1)}/10`] },
    practice: { title: "Selected practice loop", value: `${plan.priority}: ${plan.area}`, items: [plan.why, plan.exercise, "Repeat until you can answer with proof, mechanism, metric, and ownership boundary."] },
  };
  const selected = byTrack[track];
  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm xl:sticky xl:top-5 xl:self-start">
      <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{selected.title}</p>
      <h2 className="mt-3 text-2xl font-semibold text-slate-950">{selected.value}</h2>
      <div className="mt-4 space-y-3">
        {selected.items.map((item) => (
          <p key={item} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700">{item}</p>
        ))}
      </div>
    </aside>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{title}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-slate-200 px-5 py-4 md:border-r md:last:border-r-0">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm leading-6 text-slate-800">{value}</p>
    </div>
  );
}

function SignalCard({ label, value, tone }: { label: string; value: string; tone: "green" | "amber" | "red" | "cyan" }) {
  const cls =
    tone === "green"
      ? "border-emerald-200 bg-emerald-50"
      : tone === "red"
        ? "border-rose-200 bg-rose-50"
        : tone === "cyan"
          ? "border-cyan-200 bg-cyan-50"
          : "border-amber-200 bg-amber-50";
  return (
    <div className={`rounded-lg border p-4 ${cls}`}>
      <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-sm leading-7 text-slate-800">{value}</p>
    </div>
  );
}

function RailTile({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: "green" | "amber" | "red" | "cyan" | "slate" }) {
  const cls =
    tone === "green" ? "border-emerald-200 bg-emerald-50" : tone === "red" ? "border-rose-200 bg-rose-50" : tone === "cyan" ? "border-cyan-200 bg-cyan-50" : tone === "amber" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white";
  return (
    <div className={`rounded-lg border p-4 shadow-sm ${cls}`}>
      <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-2 text-base font-semibold text-slate-950">{value}</p>
      <p className="mt-1 text-xs leading-5 text-slate-600">{detail}</p>
    </div>
  );
}

function DualMeter({ leftLabel, left, rightLabel, right }: { leftLabel: string; left: number; rightLabel: string; right: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Meter label={leftLabel} value={left} />
      <Meter label={rightLabel} value={right} />
    </div>
  );
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
        <p className="font-mono text-xs font-semibold text-slate-800">{value.toFixed(1)}</p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full" style={{ width: `${value * 10}%`, background: scoreColor(value) }} />
      </div>
    </div>
  );
}

function RubricDetails({ title, items, defaultOpen = false }: { title: string; items: RubricItem[]; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="rounded-lg border border-slate-200 bg-white p-3">
      <summary className="cursor-pointer list-none text-sm font-semibold text-slate-950">
        <span className="inline-flex w-full items-center justify-between gap-3">
          {title}
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-400">Open</span>
        </span>
      </summary>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {items.map((item) => (
          <div key={`${item.label}-${item.value}`} className={`rounded-md border p-3 ${toneSurface(item.tone === "slate" ? "cyan" : item.tone)}`}>
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{item.label}</p>
            <p className="mt-2 text-xs leading-5 text-slate-700">{item.value}</p>
          </div>
        ))}
      </div>
    </details>
  );
}

function OperatingColumn({ report, label, items, tone }: { report: DemoReport; label: string; items: string[]; tone: "green" | "amber" | "cyan" }) {
  const color = tone === "green" ? "#059669" : tone === "cyan" ? "#0891b2" : "#d97706";
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <div className="mt-3 space-y-2">
        {items.map((item, index) => (
          <details key={item} className="rounded-md border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer list-none">
              <span className="grid grid-cols-[28px_1fr] gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-md font-mono text-[10px] font-semibold text-white" style={{ background: color }}>
                  {index + 1}
                </span>
                <span className="text-sm leading-6 text-slate-700">{item}</span>
              </span>
            </summary>
            <div className="mt-3 grid gap-2">
              {operatingDetailFor(label, item, report).map((detail) => (
                <div key={detail.label} className={`rounded-md border p-3 ${toneSurface(detail.tone === "slate" ? "cyan" : detail.tone)}`}>
                  <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{detail.label}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-700">{detail.value}</p>
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

function toneSurface(tone: "green" | "amber" | "red" | "cyan") {
  if (tone === "green") return "border-emerald-200 bg-emerald-50";
  if (tone === "red") return "border-rose-200 bg-rose-50";
  if (tone === "cyan") return "border-cyan-200 bg-cyan-50";
  return "border-amber-200 bg-amber-50";
}

function candidateHeadline(report: DemoReport) {
  if (report.tone === "elite") return "You are already showing role-ready signal; focus on sharpening executive tradeoff framing.";
  if (report.tone === "emerging") return "Your fundamentals are promising; your next step is turning knowledge into production proof.";
  if (report.tone === "risk") return "Your interview exposed role-critical gaps; rebuild from mechanism, evidence, and honest ownership boundaries.";
  return "You have usable strengths, but your role fit depends on a clear operating envelope and deeper system proof.";
}

function candidatePositioningLabel(report: DemoReport) {
  if (report.tone === "elite") return "Lead with verified strengths";
  if (report.tone === "emerging") return "Build proof with guidance";
  if (report.tone === "risk") return "Rebuild proof before role positioning";
  return "Strengthen the unresolved evidence";
}

function conceptMapFor(report: DemoReport): ConceptRow[] {
  const maps: Record<string, ConceptRow[]> = {
    "riya-menon-strong": [
      { concept: "Delivery semantics", understanding: 9.6, application: 9.4, proof: "Separated at-least-once delivery from idempotent consumer application.", nextMove: "Use the same precision when explaining tradeoffs to non-engineering audiences." },
      { concept: "Backpressure", understanding: 9.2, application: 9.0, proof: "Compared bounded queues, load shedding, and tenant-level lag.", nextMove: "Attach cost and customer impact thresholds to each option." },
      { concept: "Observability", understanding: 9.4, application: 9.3, proof: "Named replay age, saturation, and per-tenant freshness.", nextMove: "Translate technical metrics into customer-facing reliability language." },
      { concept: "Product prioritization", understanding: 7.7, application: 7.0, proof: "Recovered after direct cost constraint prompt.", nextMove: "Practice ranking engineering options by customer segment and revenue exposure." },
    ],
    "isha-kapoor-fresh": [
      { concept: "API boundaries", understanding: 7.4, application: 6.8, proof: "Explained validation, pagination, and error shapes.", nextMove: "Show one end-to-end API with schema, tests, and failure cases." },
      { concept: "Database indexes", understanding: 7.2, application: 6.4, proof: "Understood selectivity and why indexes are not magic.", nextMove: "Practice reading query plans and measuring p95 latency." },
      { concept: "Retry safety", understanding: 6.2, application: 5.8, proof: "Found idempotency key after prompt.", nextMove: "Build a small retry-safe job with duplicate request tests." },
      { concept: "Incident response", understanding: 4.8, application: 3.8, proof: "Mostly hypothetical; no real operational proof yet.", nextMove: "Study two incidents and write the exact timeline, impact, rollback, and monitoring plan." },
    ],
    "nikhil-verma-weak": [
      { concept: "Idempotency", understanding: 2.6, application: 2.0, proof: "Confused retry suppression with confirmed payment outcome safety.", nextMove: "Relearn idempotency through request key, persisted outcome, replay, and expiry." },
      { concept: "Reconciliation", understanding: 2.4, application: 1.8, proof: "Could not define ledger comparison or mismatch handling.", nextMove: "Implement a toy gateway ledger and write mismatch recovery notes." },
      { concept: "Concurrency control", understanding: 3.0, application: 2.2, proof: "Defaulted to global lock without failure boundaries.", nextMove: "Compare lock, unique constraint, transaction, and idempotency-key designs." },
      { concept: "Incident response", understanding: 3.2, application: 2.4, proof: "Wanted redeploy before freezing writes or preserving audit evidence.", nextMove: "Practice the first 15 minutes of a double-charge incident." },
    ],
    "meera-rao-mixed": [
      { concept: "Product workflow", understanding: 7.6, application: 7.4, proof: "Explained customer pain, workflow, and iteration loop.", nextMove: "Keep leading with product story; add stronger technical boundary proof." },
      { concept: "API integration", understanding: 6.8, application: 6.4, proof: "Credible pagination, auth, and response-shape detail.", nextMove: "Show how API contracts fail and how you debug them." },
      { concept: "Data correctness", understanding: 5.2, application: 4.5, proof: "Needed prompt to define source of truth.", nextMove: "Practice stale data, duplicate update, and conflict-resolution scenarios." },
      { concept: "Production debugging", understanding: 5.8, application: 5.1, proof: "Recovered with hints, not independently.", nextMove: "Use hypothesis, evidence, rollback, and customer impact structure." },
    ],
  };
  return maps[report.slug] ?? report.scores.slice(0, 5).map((item, index) => ({
    concept: item.label,
    understanding: item.score,
    application: Math.max(0, item.score - (index % 2 ? 0.5 : 0.2)),
    proof: item.note,
    nextMove: report.recommendedFollowups[index] || "Practice this dimension with a concrete mechanism, failure mode, test, and ownership boundary.",
  }));
}

function technicalConceptsFor(report: DemoReport): TechnicalConcept[] {
  const maps: Record<string, TechnicalConcept[]> = {
    "riya-menon-strong": [
      {
        concept: "Idempotent event consumers",
        score: 9.4,
        evidence: "Explained at-least-once delivery, persisted processed-event keys, replay behavior, and the difference between broker guarantees and application correctness.",
        missing: "Only minor gap was translating the engineering design into customer-facing reliability language.",
        better: "Lead with the invariant: every event can be replayed without changing the final customer-visible state twice.",
        eight: "An 8/10 answer names idempotency keys, persisted outcomes, retry replay, and duplicate suppression tests.",
        ten: "A 10/10 answer adds poison-message handling, tenant-level lag SLOs, replay dashboards, and rollout rollback criteria.",
      },
      {
        concept: "Backpressure and load shedding",
        score: 9.1,
        evidence: "Compared bounded queues, consumer saturation, tenant-level lag, and customer impact thresholds under pressure.",
        missing: "Commercial tradeoffs could be stated earlier: which traffic is protected, degraded, or paused.",
        better: "Frame the decision as protect paid workflow freshness first, degrade analytics second, and shed non-critical rebuild jobs last.",
        eight: "An 8/10 answer gives queue limits, lag thresholds, and alert ownership.",
        ten: "A 10/10 answer includes capacity modeling, cost ceiling, customer tier policy, and a tested fail-open/fail-closed decision.",
      },
      {
        concept: "Migration safety",
        score: 8.8,
        evidence: "Described shadow reads, dual writes, replay validation, and rollback windows.",
        missing: "Could quantify data drift acceptance thresholds more explicitly.",
        better: "Name the comparison job, acceptable mismatch rate, owner, and stop-the-line threshold.",
        eight: "An 8/10 answer covers dual-write risk and validation.",
        ten: "A 10/10 answer includes rehearsal, blast-radius limiter, backfill idempotency, and post-cutover monitoring.",
      },
    ],
    "isha-kapoor-fresh": [
      {
        concept: "API validation and error contracts",
        score: 7.2,
        evidence: "Gave credible request validation, pagination, and error-shape answers for a junior candidate.",
        missing: "Needs stronger proof through a real endpoint, schema tests, and failure-mode examples.",
        better: "Show one route with schema validation, typed responses, pagination bounds, and negative tests.",
        eight: "An 8/10 answer names validation layer, status codes, error body, pagination limits, and test cases.",
        ten: "A 10/10 junior answer adds versioning, backwards compatibility, contract tests, and observability for client errors.",
      },
      {
        concept: "Database indexing and query plans",
        score: 6.6,
        evidence: "Understood selectivity and why adding indexes is not automatically safe.",
        missing: "Did not independently read a query plan or discuss write overhead and cardinality tradeoffs.",
        better: "Explain baseline query, EXPLAIN output, chosen index, p95 impact, and rollback if writes slow down.",
        eight: "An 8/10 answer compares sequential scan vs index scan and measures latency before/after.",
        ten: "A 10/10 answer includes composite index order, cardinality, write amplification, and production rollout safety.",
      },
      {
        concept: "Retry and idempotency safety",
        score: 5.9,
        evidence: "Found idempotency after prompting, but did not lead with persisted outcomes.",
        missing: "Retry logic still sounded like transport retry rather than correctness design.",
        better: "Say: retry is safe only when the operation has a stable key and persisted response/outcome.",
        eight: "An 8/10 answer implements idempotency key storage and duplicate request tests.",
        ten: "A 10/10 answer adds expiry policy, partial-failure recovery, reconciliation, and audit logs.",
      },
    ],
    "nikhil-verma-weak": [
      {
        concept: "Payment idempotency",
        score: 2.2,
        evidence: "Confused suppressing repeated calls with guaranteeing one correct payment outcome.",
        missing: "No persisted idempotency key, outcome replay, expiry policy, or audit trail.",
        better: "Rebuild from first principles: client key, server persistence, atomic create, replay same outcome, reconcile uncertain provider states.",
        eight: "An 8/10 answer explains duplicate request replay and provider timeout handling.",
        ten: "A 10/10 answer includes ledger reconciliation, charge/refund audit, race handling, monitoring, and customer support path.",
      },
      {
        concept: "Reconciliation ledger",
        score: 1.9,
        evidence: "Could not describe comparing internal orders to provider settlement records.",
        missing: "No mismatch taxonomy, no recovery queue, no manual review boundary.",
        better: "Describe daily ledger comparison, mismatch categories, retry/void/refund actions, and escalation.",
        eight: "An 8/10 answer defines expected states and detects missing/extra/amount-mismatch records.",
        ten: "A 10/10 answer adds SLAs, customer notification policy, audit evidence, and financial controls.",
      },
      {
        concept: "Incident response sequencing",
        score: 2.8,
        evidence: "Wanted to redeploy before freezing risk and preserving evidence.",
        missing: "Missing first 15 minute safety sequence.",
        better: "Freeze risky writes, preserve logs, identify affected cohort, stop bleeding, communicate, reconcile, then patch.",
        eight: "An 8/10 answer orders mitigation before root-cause debate.",
        ten: "A 10/10 answer adds decision owner, comms cadence, rollback criteria, customer remedy, and postmortem prevention.",
      },
    ],
    "meera-rao-mixed": [
      {
        concept: "Source-of-truth modeling",
        score: 5.1,
        evidence: "Needed prompting to define which system owns dashboard state when UI, API, and analytics disagree.",
        missing: "Did not clearly separate cache, derived analytics, transactional record, and customer-visible truth.",
        better: "Say: the transactional API owns state, analytics is derived, cache is disposable, and conflicts resolve back to the owner.",
        eight: "An 8/10 answer names owner, cache invalidation, stale-read handling, and conflict resolution.",
        ten: "A 10/10 answer adds versioning, audit trail, repair job, customer impact policy, and tests for duplicate/stale updates.",
      },
      {
        concept: "API pagination, auth, and retry contracts",
        score: 6.7,
        evidence: "Credible on auth, pagination, and response shapes, but weaker on failure contracts.",
        missing: "Retry boundaries, rate limit handling, and partial-page consistency were under-specified.",
        better: "Describe cursor pagination, auth scopes, rate-limit backoff, idempotent retry, and monitoring for failed syncs.",
        eight: "An 8/10 answer shows cursor contract, error taxonomy, and retry/backoff rules.",
        ten: "A 10/10 answer includes data consistency guarantees, replay window, observability, and partner API degradation plan.",
      },
      {
        concept: "Analytics attribution and cohort validity",
        score: 5.8,
        evidence: "Strong product intuition, but attribution logic needed more denominator and cohort discipline.",
        missing: "Did not consistently name baseline, denominator, time window, and confounders.",
        better: "For every product metric, state user cohort, event definition, denominator, comparison period, and instrumentation risk.",
        eight: "An 8/10 answer defines the metric and shows how it can be wrong.",
        ten: "A 10/10 answer adds experiment design, safety metrics, segment bias, and decision threshold.",
      },
      {
        concept: "Production debugging sequence",
        score: 5.4,
        evidence: "Recovered with hints, but did not independently lead with hypothesis, evidence, rollback, and customer impact.",
        missing: "First move was not yet crisp enough for ambiguous production ownership.",
        better: "Start with scope the blast radius, inspect recent changes and logs, form hypotheses, mitigate customer impact, then root-cause.",
        eight: "An 8/10 answer gives a safe sequence and names the evidence needed at each step.",
        ten: "A 10/10 answer adds decision thresholds, comms owner, rollback path, post-fix validation, and prevention.",
      },
    ],
  };
  return maps[report.slug] ?? report.weaknesses.slice(0, 4).map((item, index) => ({
    concept: item.area,
    score: report.scores[index]?.score ?? report.score,
    evidence: item.trigger,
    missing: item.interpretation,
    better: item.followup,
    eight: `An 8/10 answer explains the mechanism behind ${item.area.toLowerCase()}, names a failure boundary, and gives verification evidence.`,
    ten: `A 10/10 answer adds tradeoffs, production metrics, ownership boundaries, and a tested recovery path for ${item.area.toLowerCase()}.`,
  }));
}

function behaviorMapFor(report: DemoReport): SkillRow[] {
  const score = (label: string) => report.scores.find((item) => item.label === label)?.score ?? report.score;
  const radar = (label: string) => report.radar.find((item) => item.label === label)?.score ?? report.score;
  return [
    { skill: "Answer structure", score: score("Reasoning structure"), pattern: "How well you framed the problem before solving.", upgrade: "Start with context, invariant, mechanism, tradeoff, and proof." },
    { skill: "Specificity", score: radar("Mechanism"), pattern: "How often you used concrete mechanisms instead of broad labels.", upgrade: "Name data shape, failure case, metric, and exact personal action." },
    { skill: "Ownership calibration", score: score("Claim integrity"), pattern: "How accurately you separated personal work from team outcomes.", upgrade: "Say 'I owned X, partnered on Y, observed Z' early instead of waiting for a probe." },
    { skill: "Recovery under pressure", score: score("Adaptability"), pattern: "How well you corrected or deepened answers after challenge.", upgrade: "When challenged, restate the corrected principle and give a sharper example." },
    { skill: "Presentation clarity", score: score("Communication"), pattern: "How easily a listener can follow your reasoning.", upgrade: "Use shorter signposted answers: premise, decision, why, risk." },
  ];
}

function skillRubricFor(row: SkillRow, report: DemoReport): RubricItem[] {
  const commonEight = "An 8/10 answer is structured, concrete, honest about ownership, and includes one failure mode or metric.";
  const commonTen = "A 10/10 answer adds tradeoff, boundary condition, measured impact, and what the candidate would do differently now.";
  const bySkill: Record<string, RubricItem[]> = {
    "Answer structure": [
      { label: "Why this score", value: row.pattern, tone: row.score >= 7 ? "cyan" : "amber" },
      { label: "What was missing", value: "Several answers had useful content, but the listener had to infer context, invariant, mechanism, and proof instead of receiving them in order.", tone: "amber" },
      { label: "Say it better", value: `For ${report.targetRole}, start with: problem, invariant, mechanism, tradeoff, evidence, then personal ownership.`, tone: "cyan" },
      { label: "8/10 answer", value: commonEight, tone: "green" },
      { label: "10/10 answer", value: commonTen, tone: "green" },
    ],
    Specificity: [
      { label: "Why this score", value: row.pattern, tone: row.score >= 7 ? "cyan" : "amber" },
      { label: "What was missing", value: "Some claims used role vocabulary without enough data shape, metric, failure case, or implementation boundary.", tone: row.score < 5 ? "red" : "amber" },
      { label: "Say it better", value: "Name the exact API/table/event, the baseline, the failure mode, and the test or monitoring signal.", tone: "cyan" },
      { label: "8/10 answer", value: "An 8/10 answer gives one concrete mechanism plus a metric or test.", tone: "green" },
      { label: "10/10 answer", value: "A 10/10 answer explains why that mechanism was chosen over alternatives and how it fails.", tone: "green" },
    ],
    "Ownership calibration": [
      { label: "Why this score", value: row.pattern, tone: row.score >= 7 ? "cyan" : "amber" },
      { label: "What was missing", value: "The ownership boundary sometimes arrived after probing instead of being stated upfront.", tone: "amber" },
      { label: "Say it better", value: "Use: I owned X decision and implementation; I partnered with Y on Z; I only observed A.", tone: "cyan" },
      { label: "8/10 answer", value: "An 8/10 answer separates personal work from team output before the interviewer asks.", tone: "green" },
      { label: "10/10 answer", value: "A 10/10 answer also names the tradeoff the candidate personally decided and the consequence they owned.", tone: "green" },
    ],
    "Recovery under pressure": [
      { label: "Why this score", value: row.pattern, tone: row.score >= 7 ? "cyan" : "amber" },
      { label: "What was missing", value: "Corrections sometimes sounded like compliance with the interviewer rather than a newly anchored principle.", tone: "amber" },
      { label: "Say it better", value: "When corrected, say the principle, explain the changed answer, and give one sharper example.", tone: "cyan" },
      { label: "8/10 answer", value: "An 8/10 answer accepts the challenge and repairs the mechanism without defensiveness.", tone: "green" },
      { label: "10/10 answer", value: "A 10/10 answer turns the challenge into a better design, stronger metric, or clearer boundary.", tone: "green" },
    ],
    "Presentation clarity": [
      { label: "Why this score", value: row.pattern, tone: row.score >= 7 ? "cyan" : "amber" },
      { label: "What was missing", value: "The content was sometimes stronger than the delivery; concise signposting would make it easier to trust.", tone: "amber" },
      { label: "Say it better", value: "Use short headings aloud: context, decision, proof, risk, next step.", tone: "cyan" },
      { label: "8/10 answer", value: "An 8/10 answer is easy to retell after one listen.", tone: "green" },
      { label: "10/10 answer", value: "A 10/10 answer helps the interviewer write the hiring note while listening.", tone: "green" },
    ],
  };
  return bySkill[row.skill] ?? [
    { label: "Why this score", value: row.pattern, tone: "cyan" },
    { label: "Upgrade", value: row.upgrade, tone: "green" },
  ];
}

function operatingDetailFor(label: string, item: string, report: DemoReport): RubricItem[] {
  const isRisk = label === "Do not hide";
  const isClarity = label === "Say more clearly";
  return [
    {
      label: "What this means",
      value: isRisk ? "This is not a disqualifier by itself; it becomes risky when the candidate lets the interviewer discover it late." : item,
      tone: isRisk ? "amber" : "cyan",
    },
    {
      label: "What to say better",
      value: isClarity
        ? `Say this directly in the first 30 seconds of the answer, then anchor it to a ${report.targetRole} example.`
        : isRisk
          ? "Name the boundary, explain what you do know, and show the next safe action instead of stretching the claim."
          : "Lead with this as evidence, then add mechanism, metric, and personal ownership so it does not sound like a generic strength.",
      tone: "green",
    },
    {
      label: "Example phrasing",
      value: isRisk
        ? "A stronger answer: 'I did not own that layer end-to-end; my part was X, the adjacent team owned Y, and I validated the handoff by Z.'"
        : "A stronger answer: 'The problem was X, I owned Y, the mechanism was Z, and the measured result was N.'",
      tone: "slate",
    },
  ];
}

function claimReflectionFor(claim: DemoReport["claims"][number]): RubricItem[] {
  return [
    { label: "Why it landed this way", value: claim.evidence, tone: claim.status === "substantiated" ? "green" : claim.status === "partial" ? "amber" : "red" },
    { label: "What to add", value: claimUpgrade(claim.status), tone: "cyan" },
    { label: "Stronger phrasing", value: "State exact scope, mechanism, metric, and who owned the adjacent decisions.", tone: "green" },
    { label: "Risk if unchanged", value: "The interviewer may treat a vague claim as overreach even when there is real work underneath it.", tone: "amber" },
  ];
}

function focusPlanFor(report: DemoReport): FocusPlan[] {
  const plans: Record<string, FocusPlan[]> = {
    "riya-menon-strong": [
      { priority: "Now", area: "Product-cost tradeoff framing", why: "This is the only meaningful weakness in an otherwise strong systems interview.", exercise: "Write a one-page reliability tradeoff memo with customer impact, cost, and rollout risk." },
      { priority: "Next", area: "Stakeholder translation", why: "Your technical answer is strong, but customer-facing language can improve.", exercise: "Explain replay semantics to support, sales, and a CTO in three different versions." },
      { priority: "Later", area: "Leadership packaging", why: "You have staff-track signal; make the leadership story explicit.", exercise: "Prepare one story about mentoring, one about incident ownership, and one about tradeoff disagreement." },
    ],
    "isha-kapoor-fresh": [
      { priority: "Now", area: "Production proof", why: "You know basics, but need evidence that survives realistic failure cases.", exercise: "Build a retry-safe API endpoint with idempotency tests and write the incident notes." },
      { priority: "Next", area: "Metrics specificity", why: "Generic metrics made good answers sound less proven.", exercise: "For every project, name baseline, p95/p99, denominator, and success threshold." },
      { priority: "Later", area: "On-call literacy", why: "You do not need to fake incident ownership, but you should understand the process.", exercise: "Review two postmortems and summarize impact, mitigation, root cause, and prevention." },
    ],
    "nikhil-verma-weak": [
      { priority: "Now", area: "Payment correctness fundamentals", why: "The core role gap is not polish; it is mechanism.", exercise: "Implement idempotency-key storage, persisted outcomes, retry replay, and reconciliation in a small toy service." },
      { priority: "Next", area: "Ownership honesty", why: "Overclaiming damaged trust faster than not knowing.", exercise: "Rewrite every resume bullet as 'I did / team did / I observed'." },
      { priority: "Later", area: "Incident response order", why: "You need a safe first-response sequence before owning reliability work.", exercise: "Practice freeze writes, preserve evidence, identify affected users, rollback, communicate, reconcile." },
    ],
    "meera-rao-mixed": [
      { priority: "Now", area: "System boundary depth", why: "Your product story is credible; backend correctness is the limiting factor.", exercise: "Model duplicate update, stale read, and source-of-truth problems for a dashboard feature." },
      { priority: "Next", area: "Debugging autonomy", why: "You recover with hints, but need a stronger first move.", exercise: "Use hypothesis, logs, cohort, rollout timing, rollback decision, customer impact for three incidents." },
      { priority: "Later", area: "Ownership language", why: "Your best fit depends on accurate scope.", exercise: "Prepare stories that separate UI ownership, API integration, and platform-team decisions." },
    ],
  };
  const priorities: FocusPlan["priority"][] = ["Now", "Next", "Later"];
  const exercises = report.recommendedFollowups.length
    ? report.recommendedFollowups.slice(0, 3)
    : ["Rehearse the largest unresolved risk using a concrete mechanism, failure boundary, test, and ownership statement."];
  return plans[report.slug] ?? exercises.map((exercise, index) => ({
    priority: priorities[index] || "Later",
    area: report.weaknesses[index]?.area || `Follow-up ${index + 1}`,
    why: report.weaknesses[index]?.interpretation || report.largestRisk,
    exercise,
  }));
}

function practicePromptsFor(report: DemoReport) {
  return [
    `Explain your strongest project for ${report.targetRole} using problem, invariant, mechanism, metric, and personal ownership.`,
    "Describe a failure case from that project. What broke, what signal revealed it, and what would you monitor now?",
    "Take one resume claim and separate exactly what you owned, what the team owned, and what you only observed.",
    "Answer the hardest weakness from this report in two minutes without becoming defensive.",
    "Map one concept you know to a real implementation, a test, a metric, and a tradeoff.",
    "Explain the same project to an engineer, a recruiter, and a product manager in three different levels of detail.",
  ];
}

function communicationAdviceFor(report: DemoReport) {
  if (report.sourceKind === "production")
    return [
      "State the exact mechanism you implemented.",
      "Separate what you owned from what the team owned.",
      "Name the failure case, test, and monitoring signal.",
    ];
  if (report.tone === "elite") return ["Make product tradeoffs earlier.", "Translate technical metrics into customer impact.", "Keep ownership boundaries as crisp as your mechanisms."];
  if (report.tone === "emerging") return ["Do not pretend to have senior ownership.", "Show tests and failure cases.", "Say what help you would ask for in production."];
  if (report.tone === "risk") return ["Stop using terms before you can explain mechanism.", "State exact personal contribution.", "Do not claim ownership you cannot defend."];
  return ["Lead with customer impact.", "Add backend correctness boundaries.", "Separate UI ownership from platform ownership."];
}

function positioningAdvice(report: DemoReport) {
  if (report.tone === "elite") return "Position yourself as a systems engineer with strong production reasoning; add product tradeoff language so the story feels leadership-ready.";
  if (report.tone === "emerging") return "Position yourself as a high-upside junior. Be proud of fundamentals, but be explicit that you want mentorship for production ownership.";
  if (report.tone === "risk") return "Positioning should pause until the fundamentals are rebuilt. The next interview should show honest scope and working mechanisms, not senior vocabulary.";
  return "Position yourself as a product-feature engineer who can own customer workflows while partnering with platform engineers on correctness boundaries.";
}

function claimUpgrade(status: DemoReport["claims"][number]["status"]) {
  if (status === "substantiated") return "Keep this story. Add the exact metric, your decision, and the tradeoff you accepted.";
  if (status === "partial") return "Narrow the claim. Say what you owned, who owned the rest, and what evidence proves your part.";
  if (status === "not_substantiated") return "Do not repeat this claim until you can explain the mechanism and personal contribution.";
  return "Either prepare proof for this claim or remove it from the lead story.";
}

function scoreColor(score: number) {
  if (score >= 8) return "#059669";
  if (score >= 6) return "#0891b2";
  if (score >= 4.5) return "#d97706";
  return "#e11d48";
}

function claimClass(status: DemoReport["claims"][number]["status"]) {
  if (status === "substantiated") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "partial") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "not_substantiated") return "border-rose-200 bg-rose-50 text-rose-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function priorityClass(priority: FocusPlan["priority"]) {
  if (priority === "Now") return "border-rose-200 bg-rose-50 text-rose-800";
  if (priority === "Next") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-cyan-200 bg-cyan-50 text-cyan-800";
}

function severityClass(severity: DemoReport["weaknesses"][number]["severity"]) {
  if (severity === "high") return "border-rose-200 bg-rose-50 text-rose-800";
  if (severity === "medium") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-cyan-200 bg-cyan-50 text-cyan-800";
}

function shorten(value: string, length: number) {
  return value.length > length ? `${value.slice(0, length - 3)}...` : value;
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}
