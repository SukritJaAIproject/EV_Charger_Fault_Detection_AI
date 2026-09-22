export type ResearchProfileId = "published" | "strict" | "reviewed";
export type ResearchArmId = "baseline" | "iso2" | "empirical" | "normative";
export type ResearchModelId =
  | "TraditionalAI"
  | "RL"
  | "AIAgent"
  | "AgenticAI"
  | "MultiAgent";

export type ResearchMetric = {
  score: number;
  recall: number;
  far: number;
  lead: number;
};

export type ResearchProfile = {
  sessions: number;
  faulty: number;
  clean: number;
  censored: number;
  arms: Record<ResearchArmId, Record<ResearchModelId, ResearchMetric>>;
};

const metric = (
  score: number,
  recall: number,
  far: number,
  lead: number,
): ResearchMetric => ({ score, recall, far, lead });

export const RESEARCH_SNAPSHOT = "2026-09-18T06:16:43+07:00";

export const MODEL_ORDER: ResearchModelId[] = [
  "TraditionalAI",
  "RL",
  "AIAgent",
  "AgenticAI",
  "MultiAgent",
];

export const MODEL_META: Record<
  ResearchModelId,
  { short: string; name: string; family: string }
> = {
  TraditionalAI: {
    short: "TR",
    name: "Traditional AI",
    family: "XGBoost + Isolation Forest",
  },
  RL: { short: "RL", name: "RL / DQN", family: "Sequential policy" },
  AIAgent: { short: "AI", name: "AI Agent", family: "Model + diagnostic tools" },
  AgenticAI: { short: "AG", name: "Agentic AI", family: "Plan · verify · decide" },
  MultiAgent: { short: "MA", name: "Multi-Agent", family: "Specialist consensus" },
};

export const RESEARCH_PROFILES: Record<ResearchProfileId, ResearchProfile> = {
  published: {
    sessions: 8_820,
    faulty: 957,
    clean: 7_863,
    censored: 0,
    arms: {
      baseline: {
        TraditionalAI: metric(68.0, 76.7, 26.6, 57.5),
        RL: metric(49.5, 34.5, 5.4, 60.8),
        AIAgent: metric(52.2, 59.0, 39.3, 0.0),
        AgenticAI: metric(69.9, 90.7, 34.8, 16.8),
        MultiAgent: metric(56.3, 62.6, 28.3, 0.0),
      },
      iso2: {
        TraditionalAI: metric(69.1, 79.0, 26.9, 56.0),
        RL: metric(49.5, 34.5, 5.4, 60.8),
        AIAgent: metric(58.8, 72.7, 44.2, 4.3),
        AgenticAI: metric(69.9, 91.2, 35.7, 15.9),
        MultiAgent: metric(62.5, 74.2, 29.2, 0.0),
      },
      empirical: {
        TraditionalAI: metric(77.0, 92.2, 26.7, 49.5),
        RL: metric(49.5, 34.5, 5.4, 60.8),
        AIAgent: metric(62.3, 76.3, 39.3, 46.9),
        AgenticAI: metric(71.0, 91.6, 34.8, 21.8),
        MultiAgent: metric(65.7, 78.8, 28.5, 0.0),
      },
      normative: {
        TraditionalAI: metric(77.7, 93.0, 26.8, 58.7),
        RL: metric(49.5, 34.5, 5.4, 60.8),
        AIAgent: metric(63.0, 77.2, 39.4, 50.0),
        AgenticAI: metric(71.5, 92.2, 34.8, 21.8),
        MultiAgent: metric(66.4, 79.6, 28.7, 1.1),
      },
    },
  },
  strict: {
    sessions: 8_820,
    faulty: 1_326,
    clean: 7_494,
    censored: 0,
    arms: {
      baseline: {
        TraditionalAI: metric(62.1, 67.6, 24.6, 26.8),
        RL: metric(44.5, 26.7, 5.3, 53.7),
        AIAgent: metric(46.7, 50.1, 38.5, 0.0),
        AgenticAI: metric(66.7, 85.4, 32.8, 5.0),
        MultiAgent: metric(60.2, 70.1, 25.0, 1.1),
      },
      iso2: {
        TraditionalAI: metric(62.8, 69.2, 24.9, 25.4),
        RL: metric(44.5, 26.7, 5.3, 53.7),
        AIAgent: metric(61.0, 78.4, 41.6, 3.5),
        AgenticAI: metric(69.5, 91.0, 33.0, 3.9),
        MultiAgent: metric(65.3, 79.6, 25.9, 5.2),
      },
      empirical: {
        TraditionalAI: metric(68.7, 78.9, 24.7, 49.5),
        RL: metric(44.5, 26.7, 5.3, 53.7),
        AIAgent: metric(54.2, 63.0, 38.6, 5.7),
        AgenticAI: metric(67.5, 86.1, 32.8, 5.2),
        MultiAgent: metric(67.2, 82.2, 25.2, 1.2),
      },
      normative: {
        TraditionalAI: metric(69.2, 79.5, 24.8, 56.1),
        RL: metric(44.5, 26.7, 5.3, 53.7),
        AIAgent: metric(54.8, 63.7, 38.6, 5.8),
        AgenticAI: metric(67.9, 86.5, 32.9, 5.8),
        MultiAgent: metric(67.6, 82.8, 25.4, 1.2),
      },
    },
  },
  reviewed: {
    sessions: 8_525,
    faulty: 1_317,
    clean: 7_208,
    censored: 295,
    arms: {
      baseline: {
        TraditionalAI: metric(60.1, 63.3, 23.9, 25.1),
        RL: metric(42.3, 22.4, 5.4, 123.2),
        AIAgent: metric(48.6, 53.2, 38.8, 0.0),
        AgenticAI: metric(59.4, 71.5, 32.0, 2.7),
        MultiAgent: metric(61.0, 71.4, 24.8, 1.1),
      },
      iso2: {
        TraditionalAI: metric(61.1, 65.4, 23.9, 24.4),
        RL: metric(42.3, 22.4, 5.4, 123.2),
        AIAgent: metric(61.9, 79.0, 41.0, 3.3),
        AgenticAI: metric(62.3, 77.4, 32.1, 2.5),
        MultiAgent: metric(65.1, 78.3, 25.0, 5.2),
      },
      empirical: {
        TraditionalAI: metric(66.0, 74.9, 23.9, 9.1),
        RL: metric(42.3, 22.4, 5.4, 123.2),
        AIAgent: metric(54.8, 65.1, 38.8, 5.7),
        AgenticAI: metric(65.1, 82.7, 32.0, 4.4),
        MultiAgent: metric(67.1, 83.2, 25.0, 1.2),
      },
      normative: {
        TraditionalAI: metric(66.4, 75.3, 24.1, 18.3),
        RL: metric(42.3, 22.4, 5.4, 123.2),
        AIAgent: metric(55.1, 65.5, 38.9, 5.8),
        AgenticAI: metric(65.5, 83.0, 32.0, 4.4),
        MultiAgent: metric(67.4, 83.6, 25.2, 1.2),
      },
    },
  },
};

export const FULL_FLEET_LABELS = {
  sessions: 40_542,
  scoring: 39_142,
  faulty: 5_892,
  clean: 33_250,
  censored: 1_400,
  distribution: [
    { family: "NO_POWER_DELIVERED", sessions: 1_694 },
    { family: "PROTOCOL_FAILED", sessions: 1_389 },
    { family: "SLAC_FAILURE", sessions: 914 },
    { family: "SESSION_ABORT", sessions: 705 },
    { family: "COMM_FREEZE", sessions: 462 },
    { family: "EV_ERROR", sessions: 430 },
    { family: "EVSE_FAULT", sessions: 270 },
    { family: "ISOLATION_FAULT", sessions: 17 },
    { family: "EVSE_PROCESSING_STALL", sessions: 11 },
  ],
  censorReasons: [
    { reason: "non_graceful_without_evidence", sessions: 1_138 },
    { reason: "capture_before_setup_budget", sessions: 132 },
    { reason: "normal_stop_without_response", sessions: 84 },
    { reason: "shared_plc_unattributed", sessions: 46 },
  ],
} as const;

export const LABEL_LINEAGE = [
  { id: "published" as const, total: 8_820, faulty: 957, clean: 7_863, censored: 0 },
  { id: "strict" as const, total: 8_820, faulty: 1_326, clean: 7_494, censored: 0 },
  { id: "reviewed" as const, total: 8_820, faulty: 1_317, clean: 7_208, censored: 295 },
];

export const SLAC_RESEARCH = {
  responseWindowMs: 200,
  responseBudgetMs: 600,
  matchSessionSeconds: 10,
  empiricalSeconds: 10,
  normativeFires: 229,
  responseTimeoutFires: 221,
  missingRequestFires: 8,
  empiricalFires: 199,
  corroborated: 42,
  pending: 45,
  completedAgents: 64,
  quotaStoppedAgents: 29,
  replaySessions: 8_820,
  replayAgreement: 100,
} as const;

