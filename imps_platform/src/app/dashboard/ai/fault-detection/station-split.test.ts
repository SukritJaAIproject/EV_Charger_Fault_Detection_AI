import { describe, expect, it } from "vitest";

import { parseDesktopRuntimeStatus, parseFaultDetectionSummary } from "./api";
import { allStationRows, faultDetectionPreview, heldOutStationTotals, stationSplitOf, type StationAnalysis } from "./data";

function station(name: string, sessions: number, faulty: number, split?: "test" | "train"): StationAnalysis {
  const normal = sessions - faulty;
  const rollup = {
    sessions,
    faultySessions: faulty,
    normalSessions: normal,
    alertedSessions: faulty,
    faultRate: (faulty / sessions) * 100,
    score: 80,
    recall: 100,
    falseAlarmRate: 0,
    precision: 100,
    f1: 100,
    medianLeadSeconds: 4,
    tp: faulty,
    late: 0,
    miss: 0,
    fp: 0,
    topFaultFamily: faulty ? "EVSE_FAULT" : null,
  };
  return {
    station: name,
    ...(split ? { split } : {}),
    group: "main",
    connectors: 1,
    ...rollup,
    byConnector: [{ connector: "connector1", ...rollup }],
    byFaultFamily: faulty
      ? [{ family: "EVSE_FAULT", faultySessions: faulty, tp: faulty, late: 0, miss: 0, recall: 100, medianLeadSeconds: 4, topEvidence: [] }]
      : [],
  };
}

function summaryWith(byStation: StationAnalysis[], byStationTrain?: StationAnalysis[], dataset?: { sessions: number; faultySessions: number; normalSessions: number; stations: number }) {
  const base = structuredClone(faultDetectionPreview);
  return {
    ...base,
    dataset: dataset ?? base.dataset,
    analysis: { ...base.analysis, byStation, ...(byStationTrain ? { byStationTrain } : {}) },
  };
}

describe("training-station rows (byStationTrain)", () => {
  it("accepts held-out rows plus training rows and keeps both", () => {
    const summary = parseFaultDetectionSummary(
      summaryWith([station("held-a", 2, 1, "test")], [station("train-b", 5, 2, "train")], { sessions: 2, faultySessions: 1, normalSessions: 1, stations: 1 }),
    );
    const rows = allStationRows(summary.analysis);
    expect(rows.map((row) => [row.station, row.split])).toEqual([["held-a", "test"], ["train-b", "train"]]);
  });

  it("still parses a pre-1.3.0 summary with no split and no training rows", () => {
    const summary = parseFaultDetectionSummary(summaryWith([station("held-a", 2, 1)], undefined, { sessions: 2, faultySessions: 1, normalSessions: 1, stations: 1 }));
    expect(summary.analysis.byStationTrain).toBeUndefined();
    expect(stationSplitOf(summary.analysis.byStation[0])).toBe("test");
    expect(allStationRows(summary.analysis)).toHaveLength(1);
  });

  it("rejects a held-out row marked as training and a training row not marked", () => {
    expect(() => parseFaultDetectionSummary(summaryWith([station("held-a", 2, 1, "train")]))).toThrow(/invalid response/);
    expect(() => parseFaultDetectionSummary(summaryWith([station("held-a", 2, 1)], [station("train-b", 5, 2)]))).toThrow(/invalid response/);
    expect(() => parseFaultDetectionSummary(summaryWith([station("held-a", 2, 1)], [station("train-b", 5, 2, "test")]))).toThrow(/invalid response/);
  });

  it("rejects an unknown split value instead of treating it as held-out", () => {
    const row = { ...station("held-a", 2, 1), split: "validation" } as unknown as StationAnalysis;
    expect(() => parseFaultDetectionSummary(summaryWith([row]))).toThrow(/invalid response/);
  });

  it("rejects a station that appears in both arrays", () => {
    expect(() => parseFaultDetectionSummary(summaryWith([station("same", 2, 1, "test")], [station("same", 5, 2, "train")]))).toThrow(/invalid response/);
  });

  it("requires held-out rows to add up to the dataset, whatever the training rows hold", () => {
    const dataset = { sessions: 2, faultySessions: 1, normalSessions: 1, stations: 1 };
    expect(() => parseFaultDetectionSummary(summaryWith([station("held-a", 2, 1, "test")], [station("train-b", 5, 2, "train")], dataset))).not.toThrow();
    expect(() => parseFaultDetectionSummary(summaryWith([station("held-a", 2, 1, "test"), station("train-b", 5, 2, "test")], undefined, dataset))).toThrow(/invalid response/);
  });

  it("counts only held-out rows in the totals", () => {
    const rows = [station("held-a", 2, 1, "test"), station("train-b", 5, 2, "train"), station("held-c", 3, 0)];
    expect(heldOutStationTotals(rows)).toEqual({ stations: 2, sessions: 5, faultySessions: 1, alertedSessions: 1 });
  });
});

describe("detection policy", () => {
  it("reads the policy from the summary and from /health, and tolerates its absence", () => {
    const summary = parseFaultDetectionSummary({
      ...summaryWith([station("held-a", 2, 1, "test")], undefined, { sessions: 2, faultySessions: 1, normalSessions: 1, stations: 1 }),
      detectionPolicy: { schemaVersion: 1, id: "iso15118-standard", iso2Rules: true, slacRuleMode: "normative" },
    });
    expect(summary.detectionPolicy?.id).toBe("iso15118-standard");
    const status = parseDesktopRuntimeStatus({
      service: "fault-detection-portable",
      status: "ok",
      detectionPolicy: { id: "baseline", label: "Baseline", iso2Rules: false, slacRuleMode: "off" },
    });
    expect(status.detectionPolicy?.slacRuleMode).toBe("off");
    expect(parseDesktopRuntimeStatus({ service: "fault-detection-portable", status: "ok" }).detectionPolicy).toBeUndefined();
  });

  it("drops a malformed policy block instead of rejecting the payload", () => {
    const status = parseDesktopRuntimeStatus({ service: "fault-detection-portable", status: "ok", detectionPolicy: { id: 7 } });
    expect(status.detectionPolicy).toBeNull();
  });
});
