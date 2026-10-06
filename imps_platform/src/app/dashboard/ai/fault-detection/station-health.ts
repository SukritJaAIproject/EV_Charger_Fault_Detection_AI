import type { StationAnalysis } from "./data";

export type StationHealthBand = "healthy" | "watch" | "plan_service" | "urgent" | "no_data";
export type StationHealthConfidence = "high" | "medium" | "low";
export type StationHealthReasonCode =
  | "stable_fault_rate"
  | "elevated_fault_rate"
  | "high_fault_rate"
  | "high_severity_family"
  | "connector_hotspot"
  | "limited_sample";

export type StationHealthReason = {
  code: StationHealthReasonCode;
  value?: number;
  family?: string;
  connector?: string;
  count?: number;
};

export type StationHealthAssessment = {
  /** PCAP-derived estimate. Null means there were no labelled sessions. */
  score: number | null;
  band: StationHealthBand;
  confidence: StationHealthConfidence;
  confidenceScore: number;
  weightedFaultRate: number;
  components: {
    reliability: number;
    severity: number;
    connectorBalance: number;
  };
  reasons: StationHealthReason[];
};

type StationHealthInput = Pick<
  StationAnalysis,
  "sessions" | "faultySessions" | "byFaultFamily" | "byConnector"
>;

/**
 * Relative impact of each labelled PCAP fault on charger health. EV-side errors
 * receive less station penalty; charger safety/power failures receive the most.
 */
export const STATION_FAULT_SEVERITY: Readonly<Record<string, number>> = {
  EVSE_FAULT: 1,
  // an isolation-monitor stop on the high-voltage path is a charger safety fault
  ISOLATION_FAULT: 1,
  NO_POWER_DELIVERED: 0.9,
  COMM_FREEZE: 0.85,
  SESSION_ABORT: 0.75,
  PROTOCOL_FAILED: 0.65,
  SLAC_FAILURE: 0.55,
  EV_ERROR: 0.35,
};

const DEFAULT_FAULT_SEVERITY = 0.65;
/**
 * A connector needs this many sessions before its fault rate can mark it as the
 * station's hotspot: one faulty session on a sparse connector is a 100% rate.
 */
export const MIN_CONNECTOR_SESSIONS = 20;

const clamp = (value: number, minimum = 0, maximum = 100) =>
  Math.min(maximum, Math.max(minimum, value));

const oneDecimal = (value: number) => Number(value.toFixed(1));

/**
 * True when a benchmark's labels have no NO_POWER_DELIVERED family, as in the
 * 2026-09-12 published labels: sessions that delivered no power were labelled
 * normal there, so Station Health cannot see power-delivery failures and reads
 * better than it would on the strict labels. Unknown families (not loaded yet)
 * report false.
 */
export function labelsOmitPowerDelivery(faultFamilies: readonly string[] | null | undefined): boolean {
  return Array.isArray(faultFamilies) && faultFamilies.length > 0 && !faultFamilies.includes("NO_POWER_DELIVERED");
}

export function stationHealthBand(score: number | null): StationHealthBand {
  if (score === null) return "no_data";
  if (score >= 85) return "healthy";
  if (score >= 70) return "watch";
  if (score >= 50) return "plan_service";
  return "urgent";
}

/**
 * Estimate station health from labelled PCAP sessions.
 *
 * Health = 55% session reliability + 30% severity-adjusted reliability
 *        + 15% connector balance.
 *
 * Fault rates are amplified because this is an evidence/maintenance indicator,
 * not a raw success percentage. The result intentionally excludes AI recall,
 * false alarms and benchmark score so model quality cannot inflate asset health.
 */
export function calculateStationHealth(station: StationHealthInput): StationHealthAssessment {
  const sessions = Math.max(0, station.sessions);
  if (sessions === 0) {
    return {
      score: null,
      band: "no_data",
      confidence: "low",
      confidenceScore: 0,
      weightedFaultRate: 0,
      components: { reliability: 0, severity: 0, connectorBalance: 0 },
      reasons: [{ code: "limited_sample", value: 0 }],
    };
  }

  const faultySessions = clamp(station.faultySessions, 0, sessions);
  const faultRate = (faultySessions / sessions) * 100;
  let familySessions = 0;
  let weightedFaultSessions = 0;
  for (const family of station.byFaultFamily) {
    const count = clamp(family.faultySessions, 0, faultySessions);
    familySessions += count;
    weightedFaultSessions += count * (STATION_FAULT_SEVERITY[family.family] ?? DEFAULT_FAULT_SEVERITY);
  }
  const uncategorizedSessions = Math.max(0, faultySessions - familySessions);
  weightedFaultSessions += uncategorizedSessions * DEFAULT_FAULT_SEVERITY;
  const weightedFaultRate = (weightedFaultSessions / sessions) * 100;

  const reliability = clamp(100 - 2 * faultRate);
  const severity = clamp(100 - 2.5 * weightedFaultRate);
  const connectors = station.byConnector.filter((connector) => connector.sessions > 0);
  const rankedConnectors = connectors.filter((connector) => connector.sessions >= MIN_CONNECTOR_SESSIONS);
  const worstConnector = rankedConnectors.reduce<(typeof connectors)[number] | null>(
    (worst, connector) => (!worst || connector.faultRate > worst.faultRate ? connector : worst),
    null,
  );
  const connectorDelta = Math.max(0, (worstConnector?.faultRate ?? faultRate) - faultRate);
  const connectorBalance = clamp(100 - 2 * connectorDelta);
  const score = oneDecimal(0.55 * reliability + 0.3 * severity + 0.15 * connectorBalance);

  const sampleCoverage = clamp((sessions / 200) * 100);
  const connectorCoverage = connectors.length
    ? connectors.reduce((sum, connector) => sum + clamp((connector.sessions / 50) * 100), 0) / connectors.length
    : 0;
  const confidenceScore = oneDecimal(0.75 * sampleCoverage + 0.25 * connectorCoverage);
  const confidence: StationHealthConfidence = confidenceScore >= 80
    ? "high"
    : confidenceScore >= 50
      ? "medium"
      : "low";

  const reasons: StationHealthReason[] = [];
  if (faultRate >= 20) reasons.push({ code: "high_fault_rate", value: oneDecimal(faultRate) });
  else if (faultRate >= 10) reasons.push({ code: "elevated_fault_rate", value: oneDecimal(faultRate) });
  else reasons.push({ code: "stable_fault_rate", value: oneDecimal(faultRate) });

  const severeFamily = [...station.byFaultFamily]
    .filter((family) => family.faultySessions > 0 && (STATION_FAULT_SEVERITY[family.family] ?? DEFAULT_FAULT_SEVERITY) >= 0.8)
    .sort((left, right) => {
      const leftImpact = left.faultySessions * (STATION_FAULT_SEVERITY[left.family] ?? DEFAULT_FAULT_SEVERITY);
      const rightImpact = right.faultySessions * (STATION_FAULT_SEVERITY[right.family] ?? DEFAULT_FAULT_SEVERITY);
      return rightImpact - leftImpact;
    })[0];
  if (severeFamily) {
    reasons.push({ code: "high_severity_family", family: severeFamily.family, count: severeFamily.faultySessions });
  }
  if (worstConnector && connectorDelta >= 10) {
    reasons.push({
      code: "connector_hotspot",
      connector: worstConnector.connector,
      value: oneDecimal(worstConnector.faultRate),
    });
  }
  if (confidence === "low") reasons.push({ code: "limited_sample", value: sessions });

  return {
    score,
    band: stationHealthBand(score),
    confidence,
    confidenceScore,
    weightedFaultRate: oneDecimal(weightedFaultRate),
    components: {
      reliability: oneDecimal(reliability),
      severity: oneDecimal(severity),
      connectorBalance: oneDecimal(connectorBalance),
    },
    reasons,
  };
}

/** Lowest health first; stations without enough data are placed last. */
export function sortStationsByHealth(rows: StationAnalysis[]): StationAnalysis[] {
  return [...rows].sort((left, right) => {
    const leftScore = calculateStationHealth(left).score;
    const rightScore = calculateStationHealth(right).score;
    if (leftScore === null && rightScore === null) return left.station.localeCompare(right.station, undefined, { numeric: true });
    if (leftScore === null) return 1;
    if (rightScore === null) return -1;
    return leftScore - rightScore || left.station.localeCompare(right.station, undefined, { numeric: true });
  });
}
