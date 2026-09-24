export type PipelineStageState = "active" | "complete" | "pending";
export type ModelEvaluationState = "awaiting_benchmark" | "evaluating" | "complete";
export type FaultDetectionModelId =
  | "traditional"
  | "rl"
  | "ai-agent"
  | "agentic-ai"
  | "multi-agent";

export type PipelineStage = {
  id: string;
  label: string;
  state: PipelineStageState;
  progress?: number;
};

export type FaultFamilyEvaluation = {
  family: string;
  nFaulty: number;
  recall: number | null;
  tp: number | null;
  late: number | null;
  miss: number | null;
  /** Family-level source data only separates early detections from all others. */
  notEarly: number | null;
};

export type ModelEvaluation = {
  id: FaultDetectionModelId;
  name: string;
  family: string;
  description: { th: string; en: string };
  color: string;
  state: ModelEvaluationState;
  rank: number | null;
  score: number | null;
  recall: number | null;
  falseAlarmRate: number | null;
  earlinessSeconds: number | null;
  meanLeadSeconds: number | null;
  f1: number | null;
  tp: number | null;
  late: number | null;
  miss: number | null;
  fp: number | null;
  wins: number | null;
  byFamily: FaultFamilyEvaluation[];
};

export type SourceDetectorEvaluation = {
  id: FaultDetectionModelId;
  name: string;
  score: number;
  recall: number;
  falseAlarmRate: number;
  earlinessSeconds: number;
  f1: number;
  tp: number;
  late: number;
  miss: number;
  fp: number;
  wins: number;
};

export type SourceAnalysis = {
  source: string;
  nFaulty: number;
  nClean: number;
  detectors: SourceDetectorEvaluation[];
};

export type StationRollupMetrics = {
  sessions: number;
  faultySessions: number;
  normalSessions: number;
  alertedSessions: number;
  faultRate: number;
  score: number;
  recall: number;
  falseAlarmRate: number;
  precision: number;
  f1: number;
  medianLeadSeconds: number;
  tp: number;
  late: number;
  miss: number;
  fp: number;
  topFaultFamily: string | null;
};

export type StationConnectorAnalysis = StationRollupMetrics & {
  connector: string;
};

export type StationFaultFamilyAnalysis = {
  family: string;
  faultySessions: number;
  tp: number;
  late: number;
  miss: number;
  recall: number;
  medianLeadSeconds: number;
  topEvidence: Array<{
    detail: string;
    count: number;
  }>;
};

/**
 * "test" = held-out station (the honest evaluation); "train" = a station the
 * models were fitted on, so its numbers are in-sample and optimistic.
 */
export type StationSplit = "test" | "train";

export type StationAnalysis = StationRollupMetrics & {
  station: string;
  /** Absent in summaries before 1.3.0, which only ever held held-out stations. */
  split?: StationSplit;
  group: string;
  connectors: number;
  byConnector: StationConnectorAnalysis[];
  byFaultFamily: StationFaultFamilyAnalysis[];
};

export type FaultDetectionAnalysis = {
  bySource: SourceAnalysis[];
  /** Held-out stations only; dataset totals and the leaderboard describe these. */
  byStation: StationAnalysis[];
  /** Training stations from an in-sample replay (desktop builds from 1.3.0). */
  byStationTrain?: StationAnalysis[];
  faultFamilies: string[];
};

export type DetectionPolicy = {
  schemaVersion?: number;
  id: string;
  label?: string | null;
  iso2Rules: boolean;
  slacRuleMode: string;
};

export const stationSplitOf = (station: Pick<StationAnalysis, "split">): StationSplit =>
  station.split ?? "test";

/** Held-out rows first, then training rows, each tagged with its split. */
export function allStationRows(analysis: Pick<FaultDetectionAnalysis, "byStation" | "byStationTrain">): StationAnalysis[] {
  return [
    ...analysis.byStation.map((station) => ({ ...station, split: "test" as const })),
    ...(analysis.byStationTrain ?? []).map((station) => ({ ...station, split: "train" as const })),
  ];
}

/** Counts over whatever rows the caller passes; the caller decides which split they cover. */
export function stationRowTotals(rows: StationAnalysis[]) {
  return rows.reduce(
    (totals, row) => ({
      stations: totals.stations + 1,
      sessions: totals.sessions + row.sessions,
      faultySessions: totals.faultySessions + row.faultySessions,
      alertedSessions: totals.alertedSessions + row.alertedSessions,
    }),
    { stations: 0, sessions: 0, faultySessions: 0, alertedSessions: 0 },
  );
}

export type StationSortKey = "station" | "fault_rate" | "recall" | "far";

/**
 * Order station rows for the Stations tab. Name and fault-rate sorts run across every
 * row: fault rate comes from the labels, not the model, so a training station ranks
 * honestly next to a held-out one. The recall and false-alarm sorts rank model scores,
 * which are optimistic on training stations, so held-out rows stay in their own block first.
 */
export function sortStationRows(rows: StationAnalysis[], sort: StationSortKey): StationAnalysis[] {
  const byName = (left: StationAnalysis, right: StationAnalysis) =>
    left.station.localeCompare(right.station, undefined, { numeric: true });
  return [...rows].sort((left, right) => {
    if (sort === "recall" || sort === "far") {
      const bySplit = (stationSplitOf(left) === "train" ? 1 : 0) - (stationSplitOf(right) === "train" ? 1 : 0);
      if (bySplit) return bySplit;
    }
    if (sort === "fault_rate") return right.faultRate - left.faultRate || byName(left, right);
    if (sort === "recall") return left.recall - right.recall || byName(left, right);
    if (sort === "far") return right.falseAlarmRate - left.falseAlarmRate || byName(left, right);
    return byName(left, right);
  });
}

/** Totals over held-out rows only, so in-sample stations never reach a headline number. */
export function heldOutStationTotals(rows: StationAnalysis[]) {
  return stationRowTotals(rows.filter((row) => stationSplitOf(row) === "test"));
}

export type FaultDetectionSummary = {
  source: "preview" | "full_fleet";
  snapshotAt: string;
  run: {
    status: "paused" | "running" | "complete";
    stage: string;
    progress: number;
    processed: number;
    remaining: number;
    total: number;
    etaHours: [number, number];
  };
  dataset: {
    sessions: number | null;
    faultySessions: number | null;
    normalSessions: number | null;
    stations: number | null;
  };
  pipeline: PipelineStage[];
  leaderboard: ModelEvaluation[];
  analysis: FaultDetectionAnalysis;
  /** The detection policy the benchmark was measured under (absent = baseline). */
  detectionPolicy?: DetectionPolicy | null;
};

/**
 * Locale for benchmark snapshot dates. Thai UI uses the Gregorian calendar here
 * so the date matches the one embedded in product names ("Snapshot 2026-09-12").
 */
export const snapshotDateLocale = (lang: "th" | "en"): string =>
  lang === "th" ? "th-TH-u-ca-gregory" : "en-GB";

/**
 * The benchmark that ships inside this build of the app (data/summary.json in
 * the desktop package). It is what makes two editions differ, so the Overview
 * renders it instead of relying only on the fixed research constants.
 */
export type BundledBenchmark = Pick<
  FaultDetectionSummary,
  "source" | "snapshotAt" | "dataset" | "leaderboard"
> & { faultFamilies: string[]; detectionPolicy?: DetectionPolicy | null };

/**
 * Honest fallback shown while the live summary is loading or unavailable.
 * Evaluation fields stay null so an API outage can never surface invented
 * benchmark scores.
 */
export const faultDetectionPreview: FaultDetectionSummary = {
  source: "preview",
  snapshotAt: "2026-09-10T07:31:00+07:00",
  run: {
    status: "paused",
    stage: "extract_pass1",
    progress: 55.7,
    processed: 23_782,
    remaining: 18_890,
    total: 42_672,
    etaHours: [18, 28],
  },
  dataset: {
    sessions: null,
    faultySessions: null,
    normalSessions: null,
    stations: null,
  },
  pipeline: [
    { id: "extract_pass1", label: "Extract 01", state: "active", progress: 55.7 },
    { id: "extract_pass2", label: "Extract 02", state: "pending" },
    { id: "sessionize", label: "Sessionize", state: "pending" },
    { id: "split", label: "Data split", state: "pending" },
    { id: "dataset", label: "Dataset", state: "pending" },
    { id: "train_traditional", label: "Traditional", state: "pending" },
    { id: "train_nn_tools", label: "NN + Tools", state: "pending" },
    { id: "train_rl", label: "RL / DQN", state: "pending" },
    { id: "benchmark", label: "Benchmark", state: "pending" },
    { id: "analyze", label: "Analysis", state: "pending" },
  ],
  leaderboard: [
    {
      id: "traditional",
      name: "Traditional AI",
      family: "Statistical & tree-based baseline",
      description: {
        th: "โมเดลฐานสำหรับเทียบความแม่นยำ ความเร็ว และต้นทุนการประมวลผล",
        en: "Baseline models for accuracy, latency, and compute-cost comparison.",
      },
      color: "#0284c7",
      state: "awaiting_benchmark",
      rank: null,
      score: null,
      recall: null,
      falseAlarmRate: null,
      earlinessSeconds: null,
      meanLeadSeconds: null,
      f1: null,
      tp: null,
      late: null,
      miss: null,
      fp: null,
      wins: null,
      byFamily: [],
    },
    {
      id: "rl",
      name: "RL / DQN",
      family: "Sequential decision policy",
      description: {
        th: "เรียนรู้นโยบายการแจ้งเตือนจากลำดับเหตุการณ์ใน charging session",
        en: "Learns an alerting policy from the charging-session event sequence.",
      },
      color: "#7c3aed",
      state: "awaiting_benchmark",
      rank: null,
      score: null,
      recall: null,
      falseAlarmRate: null,
      earlinessSeconds: null,
      meanLeadSeconds: null,
      f1: null,
      tp: null,
      late: null,
      miss: null,
      fp: null,
      wins: null,
      byFamily: [],
    },
    {
      id: "ai-agent",
      name: "AI Agent",
      family: "Detector with diagnostic tools",
      description: {
        th: "ใช้โมเดลร่วมกับเครื่องมือวิเคราะห์หลักฐานและระบุสาเหตุที่เป็นไปได้",
        en: "Combines a detector with evidence tools and probable-cause analysis.",
      },
      color: "#059669",
      state: "awaiting_benchmark",
      rank: null,
      score: null,
      recall: null,
      falseAlarmRate: null,
      earlinessSeconds: null,
      meanLeadSeconds: null,
      f1: null,
      tp: null,
      late: null,
      miss: null,
      fp: null,
      wins: null,
      byFamily: [],
    },
    {
      id: "agentic-ai",
      name: "Agentic AI",
      family: "Plan · verify · decide",
      description: {
        th: "วางแผนตรวจสอบ เรียกใช้เครื่องมือ และทบทวนหลักฐานก่อนตัดสินใจ",
        en: "Plans an investigation, calls tools, and verifies evidence before deciding.",
      },
      color: "#d97706",
      state: "awaiting_benchmark",
      rank: null,
      score: null,
      recall: null,
      falseAlarmRate: null,
      earlinessSeconds: null,
      meanLeadSeconds: null,
      f1: null,
      tp: null,
      late: null,
      miss: null,
      fp: null,
      wins: null,
      byFamily: [],
    },
    {
      id: "multi-agent",
      name: "Multi-Agent",
      family: "Specialists with consensus",
      description: {
        th: "รวมผลจาก agent ผู้เชี่ยวชาญหลายบทบาทด้วยกลไก consensus",
        en: "Combines specialist agents through an evidence-based consensus layer.",
      },
      color: "#db2777",
      state: "awaiting_benchmark",
      rank: null,
      score: null,
      recall: null,
      falseAlarmRate: null,
      earlinessSeconds: null,
      meanLeadSeconds: null,
      f1: null,
      tp: null,
      late: null,
      miss: null,
      fp: null,
      wins: null,
      byFamily: [],
    },
  ],
  analysis: {
    bySource: [],
    byStation: [],
    faultFamilies: [],
  },
};
