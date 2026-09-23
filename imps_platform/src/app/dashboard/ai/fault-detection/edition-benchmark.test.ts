import { describe, expect, it } from "vitest";

import {
  detectionPolicyKind,
  heldOutFaultDistribution,
  heldOutStations,
  percentOf,
  researchModelRelation,
  researchProfileForBundled,
  selectResearchGrid,
} from "./edition-benchmark";
import {
  CURRENT_EDITION,
  ISO_EDITION,
  SNAPSHOT_EDITION,
  SNAPSHOT_FAMILIES,
  fixtureBundle,
  fixtureStation,
} from "./edition-fixtures";
import { RESEARCH_MODEL_ARTIFACT, RESEARCH_V4_ARTIFACT } from "./research-data";

const V4_PUBLISHED_BASELINE = fixtureBundle(957, SNAPSHOT_FAMILIES, [
  // the v4 models scored on the 2026-09-12 labels (research_grid_v4.json published.baseline)
  ["traditional", 67.3, 76.9, 28.0],
  ["agentic-ai", 70.2, 90.7, 33.0],
  ["multi-agent", 56.3, 62.6, 28.3],
  ["ai-agent", 51.3, 58.0, 35.9],
  ["rl", 41.3, 21.6, 5.8],
]);

describe("held-out fault distribution", () => {
  it("reads this edition's family counts and sums to its fault sessions", () => {
    const current = heldOutFaultDistribution(CURRENT_EDITION);
    expect(current.map((row) => row.family)).toEqual([
      "NO_POWER_DELIVERED",
      "PROTOCOL_FAILED",
      "SLAC_FAILURE",
      "SESSION_ABORT",
      "EVSE_FAULT",
      "EV_ERROR",
      "COMM_FREEZE",
    ]);
    expect(current.reduce((sum, row) => sum + row.sessions, 0)).toBe(1_326);

    const snapshot = heldOutFaultDistribution(SNAPSHOT_EDITION);
    expect(snapshot).toHaveLength(6);
    expect(snapshot.some((row) => row.family === "NO_POWER_DELIVERED")).toBe(false);
    expect(snapshot.reduce((sum, row) => sum + row.sessions, 0)).toBe(957);
  });

  it("is empty rather than invented when nothing is bundled", () => {
    expect(heldOutFaultDistribution(null)).toEqual([]);
    const unscored = {
      ...SNAPSHOT_EDITION,
      leaderboard: SNAPSHOT_EDITION.leaderboard.map((row) => ({ ...row, byFamily: [] })),
    };
    expect(heldOutFaultDistribution(unscored)).toEqual([]);
  });
});

describe("research profile matching", () => {
  it("maps each edition's labels to the research profile with the same counts", () => {
    expect(researchProfileForBundled(SNAPSHOT_EDITION)).toBe("published");
    expect(researchProfileForBundled(CURRENT_EDITION)).toBe("strict");
    expect(researchProfileForBundled(null)).toBeNull();
    expect(researchProfileForBundled(fixtureBundle(1_000, SNAPSHOT_FAMILIES, []))).toBeNull();
  });

  it("matches ISO-reviewed only when the 295 inconclusive sessions were actually dropped", () => {
    const reviewedDropped = {
      ...SNAPSHOT_EDITION,
      dataset: { sessions: 8_525, faultySessions: 1_317, normalSessions: 7_208, stations: 45 },
    };
    expect(researchProfileForBundled(reviewedDropped)).toBe("reviewed");
    // same faulty count, but the inconclusive sessions stayed in as clean
    const reviewedKeptAsClean = {
      ...SNAPSHOT_EDITION,
      dataset: { sessions: 8_820, faultySessions: 1_317, normalSessions: 7_503, stations: 45 },
    };
    expect(researchProfileForBundled(reviewedKeptAsClean)).toBeNull();
  });
});

describe("detection policy", () => {
  it("treats an absent policy as baseline and any rule layer as rules", () => {
    expect(detectionPolicyKind(undefined)).toBe("baseline");
    expect(detectionPolicyKind(null)).toBe("baseline");
    expect(detectionPolicyKind(ISO_EDITION.detectionPolicy)).toBe("rules");
    expect(detectionPolicyKind({ id: "x", iso2Rules: false, slacRuleMode: "off" })).toBe("baseline");
    expect(detectionPolicyKind({ id: "x", iso2Rules: false, slacRuleMode: "normative" })).toBe("rules");
  });
});

describe("held-out stations", () => {
  it("keeps summaries without a split and drops in-sample training rows", () => {
    const rows = [
      fixtureStation("001_A", 100, 10),
      fixtureStation("002_B", 50, 5, "test"),
      fixtureStation("900_T", 400, 80, "train"),
    ];
    expect(heldOutStations(rows).map((row) => row.station)).toEqual(["001_A", "002_B"]);
  });
});

describe("research grid choice", () => {
  it("shows each model set its own grid", () => {
    expect(selectResearchGrid(SNAPSHOT_EDITION).grid.artifact).toBe(RESEARCH_MODEL_ARTIFACT);
    expect(selectResearchGrid(CURRENT_EDITION).grid.artifact).toBe(RESEARCH_V4_ARTIFACT);
    expect(selectResearchGrid(CURRENT_EDITION, RESEARCH_V4_ARTIFACT).grid.artifact).toBe(RESEARCH_V4_ARTIFACT);
    // v4 weights under the old labels are still recognised as v4
    expect(selectResearchGrid(V4_PUBLISHED_BASELINE)).toMatchObject({ relation: "same" });
    expect(selectResearchGrid(V4_PUBLISHED_BASELINE).grid.artifact).toBe(RESEARCH_V4_ARTIFACT);
  });

  it("falls back to the first grid, marked different, for models with no grid", () => {
    const choice = selectResearchGrid(null, "0123456789abcdef");
    expect(choice.relation).toBe("different");
    expect(choice.grid.artifact).toBe(RESEARCH_MODEL_ARTIFACT);
  });

  it("falls back to the first grid when artifact and leaderboard disagree", () => {
    const choice = selectResearchGrid(SNAPSHOT_EDITION, RESEARCH_V4_ARTIFACT);
    expect(choice.relation).toBe("unknown");
    expect(choice.grid.artifact).toBe(RESEARCH_MODEL_ARTIFACT);
    // an unknown artifact next to a leaderboard that matches a known grid is a contradiction too
    expect(selectResearchGrid(CURRENT_EDITION, "0123456789abcdef").relation).toBe("unknown");
  });
});

describe("research model relation", () => {
  it("uses the sidecar's artifact id when the leaderboard agrees or cannot tell", () => {
    expect(researchModelRelation(SNAPSHOT_EDITION, RESEARCH_MODEL_ARTIFACT)).toBe("same");
    expect(researchModelRelation(CURRENT_EDITION, RESEARCH_V4_ARTIFACT)).toBe("same");
    expect(researchModelRelation(null, ` ${RESEARCH_MODEL_ARTIFACT.toUpperCase()} `)).toBe("same");
    // the ISO edition's leaderboard is rule-armed and proves nothing; the artifact decides
    expect(researchModelRelation(ISO_EDITION, RESEARCH_V4_ARTIFACT)).toBe("same");
  });

  it("says unknown when the artifact and the leaderboard contradict each other", () => {
    // research weights packaged with the v4 summary, and the reverse
    expect(researchModelRelation(CURRENT_EDITION, RESEARCH_MODEL_ARTIFACT)).toBe("unknown");
    expect(researchModelRelation(SNAPSHOT_EDITION, "53b6f14244c2e633")).toBe("unknown");
  });

  it("does not fingerprint a rule-armed benchmark against the baseline arm", () => {
    expect(researchModelRelation(ISO_EDITION)).toBe("unknown");
    const snapshotUnderRules = { ...SNAPSHOT_EDITION, detectionPolicy: ISO_EDITION.detectionPolicy };
    expect(researchModelRelation(snapshotUnderRules)).toBe("unknown");
  });

  it("recognises the research model set from the bundled leaderboard alone", () => {
    // Snapshot edition: its benchmark IS the 41ded2cd published-baseline arm,
    // and the v4 edition's is the v4 grid's strict-baseline arm.
    expect(researchModelRelation(SNAPSHOT_EDITION)).toBe("same");
    expect(researchModelRelation(CURRENT_EDITION)).toBe("same");
  });

  it("says unknown instead of guessing", () => {
    expect(researchModelRelation(null)).toBe("unknown");
    expect(researchModelRelation(fixtureBundle(1_000, SNAPSHOT_FAMILIES, []))).toBe("unknown");
    const partial = { ...SNAPSHOT_EDITION, leaderboard: SNAPSHOT_EDITION.leaderboard.slice(0, 4) };
    expect(researchModelRelation(partial)).toBe("unknown");
  });

  it("does not match on the score alone", () => {
    const sameScoresOtherRecall = {
      ...SNAPSHOT_EDITION,
      leaderboard: SNAPSHOT_EDITION.leaderboard.map((row) => ({ ...row, recall: (row.recall ?? 0) + 1 })),
    };
    expect(researchModelRelation(sameScoresOtherRecall)).toBe("different");
  });
});

describe("percentOf", () => {
  it("formats shares and refuses an empty whole", () => {
    expect(percentOf(39_142, 40_542)).toBe("96.5%");
    expect(percentOf(1, 0)).toBeNull();
  });
});
