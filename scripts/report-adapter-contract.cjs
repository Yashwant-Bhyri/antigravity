const assert = require("node:assert/strict");

const { adaptProductionReport } = require("../app/report/report-adapter.ts");

const report = adaptProductionReport(
  {
    candidate_name: "Contract Candidate",
    overall_score: 6,
    hire_recommendation: "MAYBE",
    complete: false,
    history: [
      { question: "First question", answer: "First answer" },
      { question: "Second question", answer: "Second answer" },
    ],
    per_answer_scores: [{ overall_score: 7.5, rationale: "Directly scored." }],
  },
  "contract-session",
);

assert.equal(
  report.verdict,
  "MIXED INTERVIEW EVIDENCE",
  "Legacy employment recommendations must be presented as interview-evidence states.",
);
assert.equal(report.questions, 2, "Question count must come from the retained interview history.");
assert.equal(report.timeline[0].score, 7.5, "Retained per-turn scores must be preserved.");
assert.equal(report.timeline[0].scoreAvailable, true, "Retained per-turn scores must be marked available.");
assert.equal(
  report.timeline[1].scoreAvailable,
  false,
  "Missing per-turn scores must remain unavailable rather than inheriting the overall score.",
);
assert.equal(report.timeline[1].score, 0, "Unavailable per-turn scores must use a non-display sentinel.");

const emptyReport = adaptProductionReport({ overall_score: 9 }, "empty-contract-session");
assert.equal(emptyReport.questions, 0, "Missing history must not fabricate a question count.");
assert.equal(emptyReport.timeline[0].scoreAvailable, false, "Fallback timeline entries must remain unscored.");

console.log("report-adapter contract: 8/8 passed");
