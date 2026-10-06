import { describe, expect, it, vi } from "vitest";

import {
  getDesktopRuntimeStatus,
  isDesktopFaultDetectionApi,
  parseDesktopRuntimeStatus,
  parseFaultDetectionSummary,
  parseGroundTruthBatch,
  parseGroundTruthLabel,
  parseModelTrainingJob,
  parseModelTrainingSummary,
  parsePcapAnalysisJob,
  parseTrainingDatasetImport,
  parseTrainingDatasetSummary,
  resolveFaultDetectionApiBase,
} from "./api";
import { faultDetectionPreview } from "./data";

describe("resolveFaultDetectionApiBase", () => {
  it("uses the loopback viewer only for explicit desktop mode", () => {
    expect(resolveFaultDetectionApiBase("?desktop=1")).toBe("http://localhost:18765");
    expect(resolveFaultDetectionApiBase("?tab=leaderboard&desktop=1")).toBe(
      "http://localhost:18765"
    );
    expect(resolveFaultDetectionApiBase("?desktop=1&desktopApiPort=43127")).toBe(
      "http://127.0.0.1:43127"
    );
    expect(resolveFaultDetectionApiBase("?desktop=1&desktopApiPort=80")).toBe(
      "http://localhost:18765"
    );
  });

  it("keeps the configured application API for normal web use", () => {
    expect(resolveFaultDetectionApiBase("")).toBe("http://localhost:8000");
    expect(resolveFaultDetectionApiBase("?desktop=0")).toBe("http://localhost:8000");
  });

  it("keeps the dynamic desktop API port across client-side navigation", () => {
    const values = new Map<string, string>();
    const mockWindow = {
      location: { search: "?desktop=1&desktopApiPort=43127" },
      sessionStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
    };
    vi.stubGlobal("window", mockWindow);
    try {
      expect(resolveFaultDetectionApiBase()).toBe("http://127.0.0.1:43127");
      mockWindow.location.search = "";
      expect(resolveFaultDetectionApiBase()).toBe("http://127.0.0.1:43127");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("parseFaultDetectionSummary", () => {
  it("accepts verified per-station Agentic AI metrics", () => {
    const payload = structuredClone(faultDetectionPreview);
    payload.analysis.byStation = [{
      station: "002_LatPhraoWangHin1",
      group: "main",
      connectors: 2,
      sessions: 625,
      faultySessions: 66,
      normalSessions: 559,
      alertedSessions: 257,
      faultRate: 10.56,
      score: 68.17,
      recall: 87.88,
      falseAlarmRate: 34.88,
      precision: 22.92,
      f1: 36.36,
      medianLeadSeconds: 2.67,
      tp: 58,
      late: 4,
      miss: 4,
      fp: 195,
      topFaultFamily: "PROTOCOL_FAILED",
      byConnector: [
        {
          connector: "connector1",
          sessions: 313,
          faultySessions: 30,
          normalSessions: 283,
          alertedSessions: 126,
          faultRate: 9.58,
          score: 67.1,
          recall: 86.67,
          falseAlarmRate: 34.28,
          precision: 21.14,
          f1: 34.0,
          medianLeadSeconds: 2.1,
          tp: 26,
          late: 3,
          miss: 1,
          fp: 97,
          topFaultFamily: "PROTOCOL_FAILED",
        },
        {
          connector: "connector2",
          sessions: 312,
          faultySessions: 36,
          normalSessions: 276,
          alertedSessions: 131,
          faultRate: 11.54,
          score: 69.0,
          recall: 88.89,
          falseAlarmRate: 35.51,
          precision: 24.62,
          f1: 38.58,
          medianLeadSeconds: 3.0,
          tp: 32,
          late: 1,
          miss: 3,
          fp: 98,
          topFaultFamily: "PROTOCOL_FAILED",
        },
      ],
      byFaultFamily: [
        { family: "PROTOCOL_FAILED", faultySessions: 40, tp: 36, late: 2, miss: 2, recall: 90, medianLeadSeconds: 2.8, topEvidence: [{ detail: "SessionStopRes:FAILED_SequenceError", count: 32 }] },
        { family: "SESSION_ABORT", faultySessions: 26, tp: 22, late: 2, miss: 2, recall: 84.62, medianLeadSeconds: 1.9, topEvidence: [{ detail: "TCP RST", count: 14 }] },
      ],
    }];

    const summary = parseFaultDetectionSummary(payload);
    expect(summary.analysis.byStation[0].station).toBe("002_LatPhraoWangHin1");
    expect(summary.analysis.byStation[0].tp).toBe(58);
    expect(summary.analysis.byStation[0].byConnector).toHaveLength(2);
    expect(summary.analysis.byStation[0].byFaultFamily[0].family).toBe("PROTOCOL_FAILED");
  });

  it("rejects inconsistent station drill-down totals", () => {
    const payload = structuredClone(faultDetectionPreview);
    const validStation = parseFaultDetectionSummary({
      ...payload,
      analysis: {
        ...payload.analysis,
        byStation: [{
          station: "station-a",
          group: "main",
          connectors: 1,
          sessions: 2,
          faultySessions: 1,
          normalSessions: 1,
          alertedSessions: 1,
          faultRate: 50,
          score: 80,
          recall: 100,
          falseAlarmRate: 0,
          precision: 100,
          f1: 100,
          medianLeadSeconds: 4,
          tp: 1,
          late: 0,
          miss: 0,
          fp: 0,
          topFaultFamily: "EVSE_FAULT",
          byConnector: [{
            connector: "connector1",
            sessions: 2,
            faultySessions: 1,
            normalSessions: 1,
            alertedSessions: 1,
            faultRate: 50,
            score: 80,
            recall: 100,
            falseAlarmRate: 0,
            precision: 100,
            f1: 100,
            medianLeadSeconds: 4,
            tp: 1,
            late: 0,
            miss: 0,
            fp: 0,
            topFaultFamily: "EVSE_FAULT",
          }],
          byFaultFamily: [{ family: "EVSE_FAULT", faultySessions: 1, tp: 1, late: 0, miss: 0, recall: 100, medianLeadSeconds: 4, topEvidence: [{ detail: "CurrentDemandRes:EVSE_EmergencyShutdown", count: 1 }] }],
        }],
      },
    });
    const inconsistent = structuredClone(validStation);
    inconsistent.analysis.byStation[0].byConnector[0].sessions = 3;
    expect(() => parseFaultDetectionSummary(inconsistent)).toThrow(/invalid response/);
  });
});

describe("parsePcapAnalysisJob", () => {
  it("accepts a completed one-capture inference result", () => {
    const job = parsePcapAnalysisJob({
      schemaVersion: 1,
      jobId: "b27a3b5f27bd4d50a1d4b94e3b29daba",
      status: "complete",
      stage: "complete",
      progress: 100,
      createdAt: "2026-09-13T14:00:00Z",
      completedAt: "2026-09-13T14:00:04Z",
      originalName: "ethlog12.pcap",
      sizeBytes: 113591,
      sha256: "3b932108938302dd772fe09772abbdf8823ac0311f852c1087a28dcec1deb77d",
      error: null,
      result: {
        schemaVersion: 1,
        file: {
          originalName: "ethlog12.pcap",
          sizeBytes: 113591,
          sha256: "3b932108938302dd772fe09772abbdf8823ac0311f852c1087a28dcec1deb77d",
          captureFormat: "pcap",
        },
        model: {
          id: "agentic-ai",
          name: "Agentic AI",
          benchmarkRank: 1,
          artifactVersion: "53b6f14244c2e633",
          coldStart: true,
        },
        capture: {
          extractedEvents: 1106,
          sessionCount: 1,
          alertedSessions: 1,
          completeSessions: 1,
          tStart: 969052806.434,
          tEnd: 969052868.815,
          durationSeconds: 62.381,
        },
        verdict: {
          status: "fault_detected",
          faultDetected: true,
          faultFamily: "PROTOCOL_FAILED",
          confidence: 1,
          reason: "goal 'dialog OK' failed: FAILED_SequenceError",
          severity: "critical",
          stopAnalysis: {
            triggeredBy: "vehicle",
            requestSender: "vehicle",
            confidence: "high",
            evidence: "EV sent SessionStopReq; EVSE then returned SessionStopRes:FAILED_SequenceError.",
          },
        },
        sessions: [{
          index: 1,
          eventCount: 466,
          tStart: 969052806.434,
          tEnd: 969052868.815,
          durationSeconds: 62.381,
          gracefulClose: true,
          firstMessage: "supportedAppProtocolReq",
          lastMessage: "SessionStopRes",
          alert: {
            timestamp: 969052853.702,
            offsetSeconds: 47.268,
            confidence: 1,
            reason: "goal 'dialog OK' failed: FAILED_SequenceError",
            faultFamily: "PROTOCOL_FAILED",
            stopAnalysis: {
              triggeredBy: "vehicle",
              requestSender: "vehicle",
              confidence: "high",
              evidence: "EV sent SessionStopReq; EVSE then returned SessionStopRes:FAILED_SequenceError.",
            },
          },
          stopAnalysis: {
            triggeredBy: "vehicle",
            requestSender: "vehicle",
            confidence: "high",
            evidence: "EV sent SessionStopReq; EVSE then returned SessionStopRes:FAILED_SequenceError.",
          },
        }],
        warnings: [],
        processing: {
          durationSeconds: 3.4,
          completedAt: "2026-09-13T14:00:04Z",
        },
      },
    });

    expect(job.result?.verdict.faultFamily).toBe("PROTOCOL_FAILED");
    expect(job.result?.capture.sessionCount).toBe(1);
    expect(job.result?.verdict.stopAnalysis?.triggeredBy).toBe("vehicle");
  });

  it("rejects an unsafe job id", () => {
    expect(() => parsePcapAnalysisJob({
      schemaVersion: 1,
      jobId: "../other-job",
      status: "queued",
      stage: "queued",
      progress: 3,
      createdAt: "2026-09-13T14:00:00Z",
      originalName: "capture.pcap",
      sizeBytes: 24,
    })).toThrow(/invalid response/i);
  });
});

describe("training dataset API schemas", () => {
  const imported = {
    schemaVersion: 1 as const,
    importId: "b27a3b5f27bd4d50a1d4b94e3b29daba",
    name: "October 2026",
    sourceType: "zip" as const,
    status: "ready" as const,
    createdAt: "2026-10-01T10:00:00Z",
    completedAt: "2026-10-01T10:01:00Z",
    fileCount: 18,
    bytes: 4096,
    duplicateCount: 2,
    rejectedCount: 1,
    labelStatus: "unlabeled" as const,
    labeledFileCount: 0,
    remainingFileCount: 18,
    normalFileCount: 0,
    faultFileCount: 0,
    excludedFileCount: 0,
    readyForRetrain: false,
    recommendedRetrainAt: "2026-11-01T00:00:00Z",
    warnings: ["Ignored 1 non-PCAP file(s) in the ZIP archive."],
  };

  it("accepts a staged monthly import and its aggregate inbox", () => {
    expect(parseTrainingDatasetImport(imported).fileCount).toBe(18);
    const summary = parseTrainingDatasetSummary({
      schemaVersion: 1,
      storagePath: "C:\\Users\\tester\\AppData\\Roaming\\iMPS Fault Detection\\training-datasets",
      schedule: {
        cadence: "monthly",
        nextWindowAt: "2026-11-01T00:00:00Z",
        mode: "manual_approval",
      },
      totals: {
        imports: 1,
        files: 18,
        bytes: 4096,
        duplicates: 2,
        rejected: 1,
        labeledFiles: 0,
      },
      readyForRetrain: false,
      blocker: "labels_and_training_pipeline_required",
      imports: [imported],
    });
    expect(summary.schedule.cadence).toBe("monthly");
    expect(summary.readyForRetrain).toBe(false);
    expect(summary.imports[0].status).toBe("ready");
  });

  it("rejects an import that claims retraining readiness without a valid label status", () => {
    expect(() => parseTrainingDatasetImport({ ...imported, labelStatus: "guessed" })).toThrow(/invalid response/i);
  });

  it("accepts a fully labelled inbox that is still blocked on the training pipeline", () => {
    const reviewed = {
      ...imported,
      labelStatus: "reviewed" as const,
      labeledFileCount: 18,
      remainingFileCount: 0,
      normalFileCount: 10,
      faultFileCount: 7,
      excludedFileCount: 1,
    };
    const summary = parseTrainingDatasetSummary({
      schemaVersion: 1,
      storagePath: "C:\\training-datasets",
      schedule: { cadence: "monthly", nextWindowAt: "2026-11-01T00:00:00Z", mode: "manual_approval" },
      totals: { imports: 1, files: 18, bytes: 4096, duplicates: 0, rejected: 0, labeledFiles: 18 },
      readyForRetrain: false,
      blocker: "training_pipeline_required",
      imports: [reviewed],
    });
    expect(summary.blocker).toBe("training_pipeline_required");
  });
});

describe("ground-truth API schemas", () => {
  const label = {
    classification: "fault" as const,
    faultFamily: "PROTOCOL_FAILED" as const,
    reviewer: "QA Operator",
    notes: "Sequence confirmed from packets.",
    revision: 2,
    createdAt: "2026-10-01T10:00:00Z",
    updatedAt: "2026-10-01T10:05:00Z",
  };

  it("accepts a revisioned label and batch progress", () => {
    expect(parseGroundTruthLabel(label).revision).toBe(2);
    const batch = parseGroundTruthBatch({
      schemaVersion: 1,
      importId: "b27a3b5f27bd4d50a1d4b94e3b29daba",
      name: "October 2026",
      status: "ready",
      fileCount: 1,
      labelStatus: "reviewed",
      labeledFileCount: 1,
      remainingFileCount: 0,
      normalFileCount: 0,
      faultFileCount: 1,
      excludedFileCount: 0,
      files: [{
        sha256: "a".repeat(64),
        originalName: "capture.pcap",
        relativePath: "station-a/capture.pcap",
        sizeBytes: 2048,
        captureFormat: "pcap",
        label,
      }],
    });
    expect(batch.files[0].label?.faultFamily).toBe("PROTOCOL_FAILED");
  });

  it("rejects an unsupported fault family", () => {
    expect(() => parseGroundTruthLabel({ ...label, faultFamily: "UNKNOWN_FAULT" })).toThrow(/invalid label/i);
  });
});

describe("model-training API schemas", () => {
  const reviewedImport = {
    schemaVersion: 1 as const,
    importId: "b27a3b5f27bd4d50a1d4b94e3b29daba",
    name: "October 2026",
    sourceType: "folder" as const,
    status: "ready" as const,
    createdAt: "2026-10-01T10:00:00Z",
    completedAt: "2026-10-01T10:01:00Z",
    fileCount: 18,
    bytes: 4096,
    duplicateCount: 0,
    rejectedCount: 0,
    labelStatus: "reviewed" as const,
    labeledFileCount: 18,
    remainingFileCount: 0,
    normalFileCount: 10,
    faultFileCount: 7,
    excludedFileCount: 1,
    readyForRetrain: false,
    recommendedRetrainAt: "2026-11-01T00:00:00Z",
    warnings: [],
  };
  const job = {
    schemaVersion: 1 as const,
    jobId: "b".repeat(32),
    name: "October candidate",
    status: "complete" as const,
    stage: "complete",
    progress: 100,
    detail: "Candidate model training completed.",
    createdAt: "2026-10-01T10:05:00Z",
    startedAt: "2026-10-01T10:05:01Z",
    completedAt: "2026-10-01T10:10:00Z",
    error: null,
    dataset: {
      importIds: [reviewedImport.importId],
      fileCount: 17,
      normalFileCount: 10,
      faultFileCount: 7,
      excludedFileCount: 1,
    },
    config: { epochs: 3, mode: "safe_fine_tune" as const },
    baseArtifactVersion: "53b6f14244c2e633",
    candidate: {
      artifactVersion: "0123456789abcdef",
      createdAt: "2026-10-01T10:10:00Z",
      approvalStatus: "manual_validation_required" as const,
      training: {
        device: "cuda" as const,
        deviceName: "NVIDIA GPU",
        epochs: 3,
        normalCaptures: 10,
        faultReserveCaptures: 7,
        normalSessions: 15,
        faultReserveSessions: 9,
        extractedEvents: 4000,
        aeWindows: 120,
        forecasterWindows: 240,
        aeLossInitial: 0.08,
        aeLossFinal: 0.04,
        forecasterLossInitial: 0.05,
        forecasterLossFinal: 0.03,
        durationSeconds: 298,
      },
      files: {
        "lstm_ae.npz": { sha256: "a".repeat(64), sizeBytes: 1024 },
        "gru_fore.npz": { sha256: "c".repeat(64), sizeBytes: 2048 },
      },
    },
  };

  it("accepts a completed candidate and eligible reviewed batches", () => {
    expect(parseModelTrainingJob(job).candidate?.training.device).toBe("cuda");
    const summary = parseModelTrainingSummary({
      schemaVersion: 1,
      engine: {
        available: true,
        mode: "external_pytorch",
        device: "auto_cuda_or_cpu",
        missing: [],
        maxEpochs: 8,
      },
      eligibleImports: [reviewedImport],
      jobs: [job],
    });
    expect(summary.eligibleImports).toHaveLength(1);
    expect(summary.jobs[0].candidate?.artifactVersion).toBe("0123456789abcdef");
  });

  it("rejects a candidate that bypasses manual validation", () => {
    expect(() => parseModelTrainingJob({
      ...job,
      candidate: { ...job.candidate, approvalStatus: "deployed" },
    })).toThrow(/invalid job/i);
  });
});

describe("isDesktopFaultDetectionApi", () => {
  it("is true only when the page talks to the desktop sidecar", () => {
    expect(isDesktopFaultDetectionApi("?desktop=1&desktopApiPort=43127")).toBe(true);
    expect(isDesktopFaultDetectionApi("?desktop=1")).toBe(true);
    expect(isDesktopFaultDetectionApi("")).toBe(false);
    expect(isDesktopFaultDetectionApi("?desktop=0")).toBe(false);
  });
});

describe("parseDesktopRuntimeStatus", () => {
  it("reads the edition identity reported by the sidecar", () => {
    const status = parseDesktopRuntimeStatus({
      service: "fault-detection-portable",
      status: "ok",
      source: "full_fleet",
      models: 5,
      sessions: 8820,
      inferenceReady: true,
      ready: true,
      missing: [],
      productName: "iMPS Fault Detection Snapshot 2026-09-12",
      appVersion: "1.1.1",
      artifactVersion: "41ded2cdd5c2ba3f",
      modelCreatedAt: "2026-09-19T08:04:53.267983Z",
      summarySnapshotAt: "2026-09-12T00:52:33.536343Z",
    });
    expect(status.productName).toBe("iMPS Fault Detection Snapshot 2026-09-12");
    expect(status.appVersion).toBe("1.1.1");
    expect(status.artifactVersion).toBe("41ded2cdd5c2ba3f");
    expect(status.summarySnapshotAt).toBe("2026-09-12T00:52:33.536343Z");
  });

  it("tolerates an older sidecar that reports no identity fields", () => {
    const status = parseDesktopRuntimeStatus({ service: "fault-detection-portable", status: "degraded", ready: false, missing: ["models"] });
    expect(status.productName).toBeUndefined();
    expect(status.artifactVersion).toBeUndefined();
  });

  it("rejects payloads without the service marker", () => {
    expect(() => parseDesktopRuntimeStatus({ status: "ok" })).toThrow(/unexpected shape/);
  });
});

describe("parseDesktopRuntimeStatus degradation", () => {
  it("drops a malformed optional identity field instead of rejecting the payload", () => {
    const status = parseDesktopRuntimeStatus({
      service: "fault-detection-portable",
      status: "ok",
      productName: "",
      appVersion: 121,
      artifactVersion: "53b6f14244c2e633",
    });
    expect(status.productName).toBeNull();
    expect(status.appVersion).toBeNull();
    expect(status.artifactVersion).toBe("53b6f14244c2e633");
  });
});

describe("getDesktopRuntimeStatus", () => {
  it("accepts a degraded sidecar's 503 body with explicit null identity fields", async () => {
    const body = JSON.stringify({
      service: "fault-detection-portable",
      status: "degraded",
      inferenceReady: false,
      ready: false,
      missing: ["models"],
      productName: null,
      appVersion: null,
      artifactVersion: null,
      modelCreatedAt: null,
      summarySnapshotAt: "2026-09-21T08:11:19.459039Z",
    });
    const fetchMock = vi.fn(async () => new Response(body, { status: 503, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    try {
      const status = await getDesktopRuntimeStatus();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/health$/), expect.objectContaining({ method: "GET" }));
      expect(status.status).toBe("degraded");
      expect(status.artifactVersion).toBeNull();
      expect(status.summarySnapshotAt).toBe("2026-09-21T08:11:19.459039Z");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("reports malformed JSON as an invalid response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 200 })));
    try {
      await expect(getDesktopRuntimeStatus()).rejects.toThrow(/malformed JSON/);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
