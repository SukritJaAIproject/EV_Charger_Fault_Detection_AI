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

export type StationAnalysis = StationRollupMetrics & {
  station: string;
  group: string;
  connectors: number;
  byConnector: StationConnectorAnalysis[];
  byFaultFamily: StationFaultFamilyAnalysis[];
};

export type FaultDetectionAnalysis = {
  bySource: SourceAnalysis[];
  byStation: StationAnalysis[];
  faultFamilies: string[];
};

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
};

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
