import type {
  BundledBenchmark,
  FaultDetectionModelId,
  ModelEvaluation,
  StationAnalysis,
  StationSplit,
} from "./data";

/**
 * Test fixtures: the figures that matter from the two shipped data/summary.json
 * files, copied by hand so tests do not depend on a local build.
 *   CURRENT_EDITION  release 1.2.1, v4 weights, artifact 53b6f14244c2e633, snapshotAt 2026-09-21
 *   SNAPSHOT_EDITION "Snapshot 2026-09-12", artifact 41ded2cdd5c2ba3f, snapshotAt 2026-09-12
 * Imported only by *.test.ts(x); nothing in the app imports this file.
 */

export const V4_FAMILIES = {
  PROTOCOL_FAILED: 310,
  SESSION_ABORT: 230,
  SLAC_FAILURE: 237,
  EVSE_FAULT: 93,
  EV_ERROR: 91,
  COMM_FREEZE: 5,
  NO_POWER_DELIVERED: 360,
};

export const SNAPSHOT_FAMILIES = {
  PROTOCOL_FAILED: 310,
  SESSION_ABORT: 234,
  SLAC_FAILURE: 224,
  EVSE_FAULT: 93,
  EV_ERROR: 91,
  COMM_FREEZE: 5,
};

export const fixtureModel = (
  id: FaultDetectionModelId,
  score: number | null,
  recall: number | null,
  far: number | null,
  families: Record<string, number>,
): ModelEvaluation => ({
  id,
  name: id,
  family: "",
  description: { th: "", en: "" },
  color: "#000000",
  state: score === null ? "awaiting_benchmark" : "complete",
  rank: null,
  score,
  recall,
  falseAlarmRate: far,
  earlinessSeconds: null,
  meanLeadSeconds: null,
  f1: null,
  tp: null,
  late: null,
  miss: null,
  fp: null,
  wins: null,
  byFamily: Object.entries(families).map(([family, nFaulty]) => ({
    family,
    nFaulty,
    recall: null,
    tp: null,
    late: null,
    miss: null,
    notEarly: null,
  })),
});

export const fixtureBundle = (
  faulty: number,
  families: Record<string, number>,
  rows: Array<[FaultDetectionModelId, number, number, number]>,
  snapshotAt = "2026-09-21T08:11:19Z",
): BundledBenchmark => ({
  source: "full_fleet",
  snapshotAt,
  dataset: { sessions: 8_820, faultySessions: faulty, normalSessions: 8_820 - faulty, stations: 45 },
  leaderboard: rows.map(([id, score, recall, far]) => fixtureModel(id, score, recall, far, families)),
  faultFamilies: Object.keys(families),
});

export const CURRENT_EDITION = fixtureBundle(1_326, V4_FAMILIES, [
  ["traditional", 69.5623, 82.5038, 24.4863],
  ["agentic-ai", 66.8541, 85.1433, 31.0115],
  ["multi-agent", 60.1585, 70.1357, 25.0334],
  ["ai-agent", 46.4182, 49.3213, 34.9746],
  ["rl", 39.2242, 18.4766, 5.5911],
]);

/** The 1.3.0 ISO 15118 edition: v4 labels and weights, scored under the standard's rule layers. */
export const ISO_EDITION: BundledBenchmark = {
  ...CURRENT_EDITION,
  detectionPolicy: { schemaVersion: 1, id: "iso15118-standard", iso2Rules: true, slacRuleMode: "normative" },
};

export const fixtureStation = (
  station: string,
  sessions: number,
  faultySessions: number,
  split?: StationSplit,
): StationAnalysis => ({
  station,
  group: "main",
  connectors: 2,
  byConnector: [],
  byFaultFamily: [],
  sessions,
  faultySessions,
  normalSessions: sessions - faultySessions,
  alertedSessions: 0,
  faultRate: sessions > 0 ? (faultySessions / sessions) * 100 : 0,
  score: 0,
  recall: 0,
  falseAlarmRate: 0,
  precision: 0,
  f1: 0,
  medianLeadSeconds: 0,
  tp: 0,
  late: 0,
  miss: 0,
  fp: 0,
  topFaultFamily: null,
  ...(split ? { split } : {}),
});

export const SNAPSHOT_EDITION = fixtureBundle(
  957,
  SNAPSHOT_FAMILIES,
  [
    ["agentic-ai", 69.9433, 90.7001, 34.8086],
    ["traditional", 68.0141, 76.698, 26.6183],
    ["multi-agent", 56.3217, 62.5914, 28.3225],
    ["ai-agent", 52.2041, 59.0387, 39.2853],
    ["rl", 49.4997, 34.4828, 5.3923],
  ],
  "2026-09-12T00:52:33Z",
);
