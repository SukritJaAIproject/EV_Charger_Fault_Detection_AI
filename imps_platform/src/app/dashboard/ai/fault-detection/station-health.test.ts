import { describe, expect, it } from "vitest";

import type { StationAnalysis } from "./data";
import { supportedFaultFamilies } from "./fault-catalog";
import {
  MIN_CONNECTOR_SESSIONS,
  STATION_FAULT_SEVERITY,
  calculateStationHealth,
  sortStationsByHealth,
  stationHealthBand,
} from "./station-health";

function station(
  name: string,
  sessions: number,
  faulty: number,
  family = "PROTOCOL_FAILED",
  connectors: Array<{ connector: string; sessions: number; faulty: number }> = [
    { connector: "connector1", sessions, faulty },
  ],
): StationAnalysis {
  const rollup = (rowSessions: number, rowFaulty: number) => ({
    sessions: rowSessions,
    faultySessions: rowFaulty,
    normalSessions: rowSessions - rowFaulty,
    alertedSessions: rowFaulty,
    faultRate: rowSessions ? (rowFaulty / rowSessions) * 100 : 0,
    score: 80,
    recall: rowFaulty ? 100 : 0,
    falseAlarmRate: 0,
    precision: rowFaulty ? 100 : 0,
    f1: rowFaulty ? 100 : 0,
    medianLeadSeconds: 4,
    tp: rowFaulty,
    late: 0,
    miss: 0,
    fp: 0,
    topFaultFamily: rowFaulty ? family : null,
  });
  return {
    station: name,
    split: "test",
    group: "main",
    connectors: connectors.length,
    ...rollup(sessions, faulty),
    byConnector: connectors.map((connector) => ({ connector: connector.connector, ...rollup(connector.sessions, connector.faulty) })),
    byFaultFamily: faulty
      ? [{ family, faultySessions: faulty, tp: faulty, late: 0, miss: 0, recall: 100, medianLeadSeconds: 4, topEvidence: [] }]
      : [],
  };
}

describe("PCAP-derived station health", () => {
  it("gives a well-covered clean station a healthy score without using AI metrics", () => {
    const clean = station("clean", 200, 0);
    clean.score = 5;
    clean.recall = 0;
    clean.falseAlarmRate = 99;

    expect(calculateStationHealth(clean)).toMatchObject({
      score: 100,
      band: "healthy",
      confidence: "high",
      weightedFaultRate: 0,
      components: { reliability: 100, severity: 100, connectorBalance: 100 },
    });
  });

  it("penalizes a charger-side safety fault more than an EV-side error", () => {
    const evseFault = calculateStationHealth(station("evse", 100, 20, "EVSE_FAULT"));
    const evError = calculateStationHealth(station("ev", 100, 20, "EV_ERROR"));

    expect(evseFault.score).toBe(63);
    expect(evseFault.band).toBe("plan_service");
    expect(evseFault.weightedFaultRate).toBe(20);
    expect(evError.score).toBe(72.8);
    expect(evError.band).toBe("watch");
  });

  it("detects a connector hotspot and lowers the connector-balance component", () => {
    const row = station("hotspot", 200, 20, "PROTOCOL_FAILED", [
      { connector: "connector1", sessions: 100, faulty: 0 },
      { connector: "connector2", sessions: 100, faulty: 40 },
    ]);
    const health = calculateStationHealth(row);

    expect(health.components.connectorBalance).toBe(40);
    expect(health.reasons).toContainEqual({ code: "connector_hotspot", connector: "connector2", value: 40 });
  });

  it("gives every supported fault family an explicit weight", () => {
    for (const family of supportedFaultFamilies) {
      expect(STATION_FAULT_SEVERITY[family], family).toBeTypeOf("number");
    }
  });

  it("weights an isolation fault as a charger safety fault and names it as a driver", () => {
    const isolation = calculateStationHealth(station("iso", 100, 20, "ISOLATION_FAULT"));
    const evseFault = calculateStationHealth(station("evse", 100, 20, "EVSE_FAULT"));

    expect(isolation.score).toBe(evseFault.score);
    expect(isolation.reasons).toContainEqual({ code: "high_severity_family", family: "ISOLATION_FAULT", count: 20 });
  });

  it("does not let a connector with a handful of sessions become the hotspot", () => {
    const row = station("sparse", 300, 16, "PROTOCOL_FAILED", [
      { connector: "connector1", sessions: 299, faulty: 15 },
      { connector: "connector2", sessions: 1, faulty: 1 },
    ]);
    const health = calculateStationHealth(row);

    expect(health.components.connectorBalance).toBe(100);
    expect(health.reasons.some((reason) => reason.code === "connector_hotspot")).toBe(false);
    expect(health.band).toBe("healthy");

    const enough = station("enough", 300, 25, "PROTOCOL_FAILED", [
      { connector: "connector1", sessions: 300 - MIN_CONNECTOR_SESSIONS, faulty: 15 },
      { connector: "connector2", sessions: MIN_CONNECTOR_SESSIONS, faulty: 10 },
    ]);
    expect(calculateStationHealth(enough).reasons).toContainEqual(
      expect.objectContaining({ code: "connector_hotspot", connector: "connector2" }),
    );
  });

  it("reports low confidence when only a few sessions are available", () => {
    const health = calculateStationHealth(station("small", 20, 1));
    expect(health.confidence).toBe("low");
    expect(health.reasons).toContainEqual({ code: "limited_sample", value: 20 });
  });

  it("returns N/A semantics when there are no labelled sessions", () => {
    expect(calculateStationHealth(station("empty", 0, 0))).toMatchObject({
      score: null,
      band: "no_data",
      confidence: "low",
      confidenceScore: 0,
    });
    expect(stationHealthBand(null)).toBe("no_data");
  });

  it("sorts the lowest health first and leaves the input unchanged", () => {
    const rows = [
      station("healthy", 200, 2),
      station("urgent", 200, 80, "EVSE_FAULT"),
      station("watch", 200, 15),
      station("empty", 0, 0),
    ];
    expect(sortStationsByHealth(rows).map((row) => row.station)).toEqual(["urgent", "watch", "healthy", "empty"]);
    expect(rows.map((row) => row.station)).toEqual(["healthy", "urgent", "watch", "empty"]);
  });
});
