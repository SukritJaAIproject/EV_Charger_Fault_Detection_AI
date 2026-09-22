import { z } from "zod";

import type { FaultDetectionSummary, StationRollupMetrics } from "./data";

export const FAULT_DETECTION_SUMMARY_PATH = "/ai/fault-detection/summary";
export const FAULT_DETECTION_JOBS_PATH = "/ai/fault-detection/jobs";
export const FAULT_DETECTION_HEALTH_PATH = "/health";
export const MAX_PCAP_UPLOAD_BYTES = 256 * 1024 * 1024;

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/+$/, "");
const DESKTOP_API_BASE = "http://localhost:18765";
const DESKTOP_API_PORT_STORAGE_KEY = "imps.faultDetection.desktopApiPort";

function isValidDesktopApiPort(value: number): boolean {
  return Number.isInteger(value) && value >= 1024 && value <= 65535;
}

export function resolveFaultDetectionApiBase(search?: string): string {
  const query = search ?? (typeof window === "undefined" ? "" : window.location.search);
  const params = new URLSearchParams(query);
  const desktopMode = params.get("desktop");
  const requestedPort = Number(params.get("desktopApiPort"));
  if (desktopMode === "1" && isValidDesktopApiPort(requestedPort)) {
    if (typeof window !== "undefined") {
      try {
        window.sessionStorage.setItem(DESKTOP_API_PORT_STORAGE_KEY, String(requestedPort));
      } catch {
        // Query-string configuration still works when storage is unavailable.
      }
    }
    return `http://127.0.0.1:${requestedPort}`;
  }

  // Next.js client navigation does not preserve the launch query string. Keep
  // the random loopback API port for the lifetime of this Electron tab so a
  // user can navigate away and return without silently falling back to :18765.
  if (desktopMode === null && typeof window !== "undefined") {
    try {
      const storedPort = Number(window.sessionStorage.getItem(DESKTOP_API_PORT_STORAGE_KEY));
      if (isValidDesktopApiPort(storedPort)) return `http://127.0.0.1:${storedPort}`;
    } catch {
      // Use the normal web API if storage is unavailable.
    }
  }

  return desktopMode === "1" ? DESKTOP_API_BASE : API_BASE;
}

/**
 * True when the page talks to the desktop sidecar (an Electron launch, or the
 * loopback port remembered from one) rather than the web backend. Only the
 * sidecar reports the edition identity shown in the dashboard header.
 */
export function isDesktopFaultDetectionApi(search?: string): boolean {
  return resolveFaultDetectionApiBase(search) !== API_BASE;
}

const finiteNumber = z.number().finite();
const nullableNumber = finiteNumber.nullable();
const nonNegativeNumber = finiteNumber.nonnegative();
const nullableNonNegativeNumber = nonNegativeNumber.nullable();
const nonNegativeInteger = z.number().int().nonnegative();
const nullableNonNegativeInteger = nonNegativeInteger.nullable();
const percentage = finiteNumber.min(0).max(100);
const nullablePercentage = percentage.nullable();

const modelIdSchema = z.enum([
  "traditional",
  "rl",
  "ai-agent",
  "agentic-ai",
  "multi-agent",
]);

const pipelineStageSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  state: z.enum(["active", "complete", "pending"]),
  progress: percentage.optional(),
});

const faultFamilyEvaluationSchema = z.object({
  family: z.string().min(1),
  nFaulty: nonNegativeInteger,
  recall: nullablePercentage,
  tp: nullableNonNegativeInteger,
  late: nullableNonNegativeInteger,
  miss: nullableNonNegativeInteger,
  notEarly: nullableNonNegativeInteger,
});

const modelEvaluationSchema = z.object({
  id: modelIdSchema,
  name: z.string().min(1),
  family: z.string().min(1),
  description: z.object({
    th: z.string().min(1),
    en: z.string().min(1),
  }),
  color: z.string().regex(/^#[0-9a-f]{6}$/i),
  state: z.enum(["awaiting_benchmark", "evaluating", "complete"]),
  rank: z.number().int().positive().nullable(),
  score: nullableNumber,
  recall: nullablePercentage,
  falseAlarmRate: nullablePercentage,
  earlinessSeconds: nullableNonNegativeNumber,
  meanLeadSeconds: nullableNonNegativeNumber,
  f1: nullablePercentage,
  tp: nullableNonNegativeInteger,
  late: nullableNonNegativeInteger,
  miss: nullableNonNegativeInteger,
  fp: nullableNonNegativeInteger,
  wins: nullableNonNegativeNumber,
  byFamily: z.array(faultFamilyEvaluationSchema),
});

const sourceDetectorEvaluationSchema = z.object({
  id: modelIdSchema,
  name: z.string().min(1),
  score: finiteNumber,
  recall: percentage,
  falseAlarmRate: percentage,
  earlinessSeconds: nonNegativeNumber,
  f1: percentage,
  tp: nonNegativeInteger,
  late: nonNegativeInteger,
  miss: nonNegativeInteger,
  fp: nonNegativeInteger,
  wins: nonNegativeNumber,
});

const sourceAnalysisSchema = z.object({
  source: z.string().min(1),
  nFaulty: nonNegativeInteger,
  nClean: nonNegativeInteger,
  detectors: z.array(sourceDetectorEvaluationSchema),
});

const stationRollupShape = {
  sessions: nonNegativeInteger,
  faultySessions: nonNegativeInteger,
  normalSessions: nonNegativeInteger,
  alertedSessions: nonNegativeInteger,
  faultRate: percentage,
  score: percentage,
  recall: percentage,
  falseAlarmRate: percentage,
  precision: percentage,
  f1: percentage,
  medianLeadSeconds: nonNegativeNumber,
  tp: nonNegativeInteger,
  late: nonNegativeInteger,
  miss: nonNegativeInteger,
  fp: nonNegativeInteger,
  topFaultFamily: z.string().min(1).nullable(),
};

const validateStationRollup = (
  rollup: StationRollupMetrics,
  context: z.RefinementCtx,
) => {
  const checks: Array<[boolean, string, string]> = [
    [rollup.sessions === rollup.faultySessions + rollup.normalSessions, "Sessions must equal faulty plus normal sessions", "sessions"],
    [rollup.faultySessions === rollup.tp + rollup.late + rollup.miss, "Faulty sessions must equal TP plus late plus missed sessions", "faultySessions"],
    [rollup.alertedSessions === rollup.tp + rollup.late + rollup.fp, "Alerted sessions must equal TP plus late plus false alarms", "alertedSessions"],
  ];
  checks.forEach(([valid, message, path]) => {
    if (!valid) {
      context.addIssue({ code: z.ZodIssueCode.custom, message, path: [path] });
    }
  });
};

const stationConnectorAnalysisSchema = z.object({
  connector: z.string().min(1),
  ...stationRollupShape,
}).superRefine(validateStationRollup);

const stationFaultFamilyAnalysisSchema = z.object({
  family: z.string().min(1),
  faultySessions: nonNegativeInteger,
  tp: nonNegativeInteger,
  late: nonNegativeInteger,
  miss: nonNegativeInteger,
  recall: percentage,
  medianLeadSeconds: nonNegativeNumber,
  topEvidence: z.array(z.object({
    detail: z.string().min(1).max(500),
    count: z.number().int().positive(),
  })).max(3),
}).superRefine((family, context) => {
  if (family.faultySessions !== family.tp + family.late + family.miss) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Fault-family sessions must equal TP plus late plus missed sessions",
      path: ["faultySessions"],
    });
  }
  const evidenceDetails = family.topEvidence.map(({ detail }) => detail);
  if (new Set(evidenceDetails).size !== evidenceDetails.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Fault-family evidence details must be unique",
      path: ["topEvidence"],
    });
  }
  if (family.topEvidence.reduce((total, item) => total + item.count, 0) > family.faultySessions) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Fault-family evidence counts cannot exceed its sessions",
      path: ["topEvidence"],
    });
  }
});

const stationAnalysisSchema = z.object({
  station: z.string().min(1),
  group: z.string().min(1),
  connectors: nonNegativeInteger,
  ...stationRollupShape,
  byConnector: z.array(stationConnectorAnalysisSchema).min(1),
  byFaultFamily: z.array(stationFaultFamilyAnalysisSchema),
}).superRefine((station, context) => {
  validateStationRollup(station, context);

  const connectorNames = station.byConnector.map(({ connector }) => connector);
  if (new Set(connectorNames).size !== connectorNames.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Station connector names must be unique", path: ["byConnector"] });
  }
  if (station.connectors !== station.byConnector.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Connector count must match connector details", path: ["connectors"] });
  }

  const familyNames = station.byFaultFamily.map(({ family }) => family);
  if (new Set(familyNames).size !== familyNames.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Station fault families must be unique", path: ["byFaultFamily"] });
  }

  const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
  (["sessions", "faultySessions", "normalSessions", "alertedSessions", "tp", "late", "miss", "fp"] as const).forEach((key) => {
    if (sum(station.byConnector.map((connector) => connector[key])) !== station[key]) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: `Connector ${key} totals must match the station`, path: ["byConnector"] });
    }
  });
  (["faultySessions", "tp", "late", "miss"] as const).forEach((key) => {
    if (sum(station.byFaultFamily.map((family) => family[key])) !== station[key]) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: `Fault-family ${key} totals must match the station`, path: ["byFaultFamily"] });
    }
  });
});

const faultDetectionSummarySchema = z.object({
  source: z.enum(["preview", "full_fleet"]),
  snapshotAt: z.string().refine((value) => Number.isFinite(Date.parse(value)), {
    message: "Expected an ISO-8601 timestamp",
  }),
  run: z.object({
    status: z.enum(["paused", "running", "complete"]),
    stage: z.string().min(1),
    progress: percentage,
    processed: nonNegativeInteger,
    remaining: nonNegativeInteger,
    total: nonNegativeInteger,
    etaHours: z.tuple([nonNegativeNumber, nonNegativeNumber]),
  }),
  dataset: z.object({
    sessions: nullableNonNegativeInteger,
    faultySessions: nullableNonNegativeInteger,
    normalSessions: nullableNonNegativeInteger,
    stations: nullableNonNegativeInteger,
  }),
  pipeline: z.array(pipelineStageSchema).min(1),
  leaderboard: z.array(modelEvaluationSchema).length(5),
  analysis: z.object({
    bySource: z.array(sourceAnalysisSchema),
    byStation: z.array(stationAnalysisSchema),
    faultFamilies: z.array(z.string().min(1)),
  }),
}).superRefine((summary, context) => {
  const modelIds = summary.leaderboard.map(({ id }) => id);
  if (new Set(modelIds).size !== modelIds.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Leaderboard model ids must be unique",
      path: ["leaderboard"],
    });
  }

  summary.analysis.bySource.forEach((source, sourceIndex) => {
    const detectorIds = source.detectors.map(({ id }) => id);
    if (new Set(detectorIds).size !== detectorIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Detector ids for source ${source.source} must be unique`,
        path: ["analysis", "bySource", sourceIndex, "detectors"],
      });
    }
  });

  const stationNames = summary.analysis.byStation.map(({ station }) => station);
  if (new Set(stationNames).size !== stationNames.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Station analysis names must be unique",
      path: ["analysis", "byStation"],
    });
  }
});

const warningSchema = z.union([
  z.string().min(1).transform((message) => ({ code: "warning", message })),
  z.object({
    code: z.string().min(1),
    message: z.string().min(1),
  }),
]);

const stopAnalysisSchema = z.object({
  triggeredBy: z.enum(["vehicle", "charger", "communication", "unknown", "not_applicable"]),
  requestSender: z.literal("vehicle").nullable(),
  confidence: z.enum(["high", "medium", "low"]),
  evidence: z.string().min(1).max(1000),
});

const inferenceAlertSchema = z.object({
  timestamp: finiteNumber.nullable().optional(),
  t: finiteNumber.nullable().optional(),
  offsetSeconds: nonNegativeNumber.nullable().optional(),
  confidence: finiteNumber.min(0).max(1),
  reason: z.string().min(1),
  faultFamily: z.string().nullable().optional(),
  faultGuess: z.string().nullable().optional(),
  stopAnalysis: stopAnalysisSchema.optional(),
});

const inferenceSessionSchema = z.object({
  index: nonNegativeInteger,
  eventCount: nonNegativeInteger,
  tStart: finiteNumber.nullable(),
  tEnd: finiteNumber.nullable(),
  durationSeconds: nonNegativeNumber,
  gracefulClose: z.boolean(),
  firstMessage: z.string().nullable().optional(),
  lastMessage: z.string().nullable().optional(),
  alert: inferenceAlertSchema.nullable(),
  stopAnalysis: stopAnalysisSchema.optional(),
});

const inferenceResultSchema = z.object({
  schemaVersion: z.literal(1),
  file: z.object({
    originalName: z.string().min(1),
    sizeBytes: nonNegativeInteger,
    sha256: z.string().regex(/^[0-9a-f]{64}$/i),
    captureFormat: z.string().min(1).optional(),
  }),
  model: z.object({
    id: z.string().min(1),
    name: z.string().min(1),
    benchmarkRank: z.number().int().positive().nullable().optional(),
    artifactVersion: z.string().nullable().optional(),
    coldStart: z.boolean(),
  }),
  capture: z.object({
    extractedEvents: nonNegativeInteger,
    sessionCount: nonNegativeInteger,
    alertedSessions: nonNegativeInteger,
    completeSessions: nonNegativeInteger,
    tStart: finiteNumber.nullable(),
    tEnd: finiteNumber.nullable(),
    durationSeconds: nonNegativeNumber,
  }),
  verdict: z.object({
    status: z.enum(["fault_detected", "no_fault_detected", "inconclusive"]),
    faultDetected: z.boolean().nullable(),
    faultFamily: z.string().nullable(),
    confidence: finiteNumber.min(0).max(1).nullable(),
    reason: z.string().nullable(),
    severity: z.enum(["critical", "high", "medium", "low"]).nullable(),
    stopAnalysis: stopAnalysisSchema.nullable().optional(),
  }),
  sessions: z.array(inferenceSessionSchema),
  warnings: z.array(warningSchema),
  processing: z.object({
    durationSeconds: nonNegativeNumber,
    completedAt: z.string().min(1),
  }),
});

const pcapAnalysisJobSchema = z.object({
  schemaVersion: z.literal(1),
  jobId: z.string().regex(/^[0-9a-f]{32}$/),
  status: z.enum(["queued", "processing", "complete", "failed"]),
  stage: z.string().min(1),
  progress: percentage,
  createdAt: z.string().min(1),
  startedAt: z.string().nullable().optional(),
  completedAt: z.string().nullable().optional(),
  originalName: z.string().min(1),
  sizeBytes: nonNegativeInteger,
  sha256: z.string().regex(/^[0-9a-f]{64}$/i).nullable().optional(),
  error: z.string().nullable().optional(),
  result: inferenceResultSchema.nullable().optional(),
});

export type PcapAnalysisJob = z.infer<typeof pcapAnalysisJobSchema>;
export type PcapInferenceResult = z.infer<typeof inferenceResultSchema>;

export type FaultDetectionApiErrorKind = "http" | "network" | "invalid_response";

export class FaultDetectionApiError extends Error {
  readonly kind: FaultDetectionApiErrorKind;
  readonly status: number | null;
  readonly details: unknown;

  constructor(
    message: string,
    options: {
      kind: FaultDetectionApiErrorKind;
      status?: number | null;
      details?: unknown;
    }
  ) {
    super(message);
    this.name = "FaultDetectionApiError";
    this.kind = options.kind;
    this.status = options.status ?? null;
    this.details = options.details;
  }
}

function describeValidationIssues(error: z.ZodError): string {
  return error.issues
    .slice(0, 5)
    .map((issue) => `${issue.path.join(".") || "response"}: ${issue.message}`)
    .join("; ");
}

function extractHttpErrorMessage(status: number, statusText: string, body: string): string {
  if (body) {
    try {
      const payload: unknown = JSON.parse(body);
      if (payload && typeof payload === "object") {
        const detail = (payload as { detail?: unknown }).detail;
        const message = (payload as { message?: unknown }).message;
        if (typeof detail === "string" && detail.trim()) return detail;
        if (typeof message === "string" && message.trim()) return message;
      }
    } catch {
      const compactBody = body.replace(/\s+/g, " ").trim();
      if (compactBody) return compactBody.slice(0, 240);
    }
  }

  return statusText || `Request failed with status ${status}`;
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "name" in error && error.name === "AbortError");
}

export function parseFaultDetectionSummary(payload: unknown): FaultDetectionSummary {
  const result = faultDetectionSummarySchema.safeParse(payload);
  if (!result.success) {
    throw new FaultDetectionApiError(
      `Fault-detection API returned an invalid response: ${describeValidationIssues(result.error)}`,
      { kind: "invalid_response", details: result.error.issues }
    );
  }

  return result.data;
}

export function parsePcapAnalysisJob(payload: unknown): PcapAnalysisJob {
  const result = pcapAnalysisJobSchema.safeParse(payload);
  if (!result.success) {
    throw new FaultDetectionApiError(
      `PCAP analysis API returned an invalid response: ${describeValidationIssues(result.error)}`,
      { kind: "invalid_response", details: result.error.issues }
    );
  }
  return result.data;
}

async function readJsonResponse(response: Response, label: string): Promise<unknown> {
  const body = await response.text();
  if (!response.ok) {
    throw new FaultDetectionApiError(
      extractHttpErrorMessage(response.status, response.statusText, body),
      { kind: "http", status: response.status, details: body }
    );
  }

  try {
    return JSON.parse(body);
  } catch (error) {
    throw new FaultDetectionApiError(`${label} returned malformed JSON.`, {
      kind: "invalid_response",
      status: response.status,
      details: error,
    });
  }
}

// A malformed identity value degrades to null instead of rejecting the whole payload.
const optionalText = z.string().min(1).nullable().optional().catch(null);

/**
 * Subset of the desktop sidecar's /health payload that identifies the running
 * edition. Every identity field is optional so older sidecars still parse.
 */
const desktopRuntimeStatusSchema = z.object({
  service: z.string().min(1),
  status: z.string().min(1),
  inferenceReady: z.boolean().optional(),
  productName: optionalText,
  appVersion: optionalText,
  artifactVersion: optionalText,
  modelCreatedAt: optionalText,
  summarySnapshotAt: optionalText,
});

export type DesktopRuntimeStatus = z.infer<typeof desktopRuntimeStatusSchema>;

export function parseDesktopRuntimeStatus(payload: unknown): DesktopRuntimeStatus {
  const parsed = desktopRuntimeStatusSchema.safeParse(payload);
  if (!parsed.success) {
    throw new FaultDetectionApiError("Desktop runtime status has an unexpected shape.", {
      kind: "invalid_response",
      details: parsed.error.issues,
    });
  }
  return parsed.data;
}

/** Reads /health from the desktop sidecar. A degraded sidecar answers 503 with the same JSON body. */
export async function getDesktopRuntimeStatus(options: { signal?: AbortSignal } = {}): Promise<DesktopRuntimeStatus> {
  let response: Response;
  try {
    response = await fetch(`${resolveFaultDetectionApiBase()}${FAULT_DETECTION_HEALTH_PATH}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new FaultDetectionApiError("Unable to connect to the desktop runtime.", {
      kind: "network",
      details: error,
    });
  }

  const body = await response.text();
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch (error) {
    throw new FaultDetectionApiError("Desktop runtime returned malformed JSON.", {
      kind: "invalid_response",
      status: response.status,
      details: error,
    });
  }
  return parseDesktopRuntimeStatus(payload);
}

export async function getFaultDetectionSummary(options: { signal?: AbortSignal } = {}): Promise<FaultDetectionSummary> {
  let response: Response;

  try {
    response = await fetch(`${resolveFaultDetectionApiBase()}${FAULT_DETECTION_SUMMARY_PATH}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new FaultDetectionApiError("Unable to connect to the fault-detection API.", {
      kind: "network",
      details: error,
    });
  }

  const body = await response.text();
  if (!response.ok) {
    throw new FaultDetectionApiError(
      extractHttpErrorMessage(response.status, response.statusText, body),
      { kind: "http", status: response.status, details: body }
    );
  }

  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch (error) {
    throw new FaultDetectionApiError("Fault-detection API returned malformed JSON.", {
      kind: "invalid_response",
      status: response.status,
      details: error,
    });
  }

  return parseFaultDetectionSummary(payload);
}

export async function createPcapAnalysisJob(
  file: File,
  options: { signal?: AbortSignal } = {}
): Promise<PcapAnalysisJob> {
  let response: Response;
  try {
    response = await fetch(`${resolveFaultDetectionApiBase()}${FAULT_DETECTION_JOBS_PATH}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
      credentials: "include",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new FaultDetectionApiError("Unable to upload the PCAP to the analysis API.", {
      kind: "network",
      details: error,
    });
  }

  return parsePcapAnalysisJob(await readJsonResponse(response, "PCAP analysis API"));
}

export async function getPcapAnalysisJob(
  jobId: string,
  options: { signal?: AbortSignal } = {}
): Promise<PcapAnalysisJob> {
  if (!/^[0-9a-f]{32}$/.test(jobId)) {
    throw new FaultDetectionApiError("Invalid PCAP analysis job id.", {
      kind: "invalid_response",
    });
  }

  let response: Response;
  try {
    response = await fetch(
      `${resolveFaultDetectionApiBase()}${FAULT_DETECTION_JOBS_PATH}/${jobId}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "include",
        cache: "no-store",
        signal: options.signal,
      }
    );
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new FaultDetectionApiError("Unable to read the PCAP analysis status.", {
      kind: "network",
      details: error,
    });
  }

  return parsePcapAnalysisJob(await readJsonResponse(response, "PCAP analysis API"));
}
