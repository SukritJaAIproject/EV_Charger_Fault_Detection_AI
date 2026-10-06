import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DESKTOP_API_TOKEN_HEADER,
  discardTrainingDatasetImport,
  faultDetectionApiHeaders,
  parseGroundTruthBatch,
  parseModelTrainingSummary,
  parseTrainingDatasetSummary,
  previewModelTraining,
  resolveDesktopApiToken,
} from "./api";
import { datasetImportName, selectFolderCaptures } from "./dataset-retrain-panel";

const TOKEN = "ab".repeat(32);

function stubWindow(search: string) {
  const values = new Map<string, string>();
  const mockWindow = {
    location: { search },
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    },
  };
  vi.stubGlobal("window", mockWindow);
  return mockWindow;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("desktop API launch token", () => {
  it("is sent to the desktop sidecar and kept across client navigation", () => {
    const mockWindow = stubWindow(`?desktop=1&desktopApiPort=43127&desktopApiToken=${TOKEN}`);
    expect(faultDetectionApiHeaders({ Accept: "application/json" })).toEqual({
      Accept: "application/json",
      [DESKTOP_API_TOKEN_HEADER]: TOKEN,
    });
    mockWindow.location.search = "";
    expect(resolveDesktopApiToken()).toBe(TOKEN);
    expect(faultDetectionApiHeaders({})[DESKTOP_API_TOKEN_HEADER]).toBe(TOKEN);
  });

  it("is never sent to the web API and ignores malformed values", () => {
    expect(faultDetectionApiHeaders({ Accept: "application/json" }, `?desktopApiToken=${TOKEN}`)).toEqual({
      Accept: "application/json",
    });
    stubWindow("?desktop=1&desktopApiPort=43127&desktopApiToken=not-a-token");
    expect(resolveDesktopApiToken()).toBeNull();
    expect(faultDetectionApiHeaders({})).toEqual({});
  });

  it("accompanies the preview and discard requests", async () => {
    stubWindow(`?desktop=1&desktopApiPort=43127&desktopApiToken=${TOKEN}`);
    const importId = "b27a3b5f27bd4d50a1d4b94e3b29daba";
    const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(
      url.endsWith("/preview")
        ? {
          schemaVersion: 1, importIds: [importId], fileCount: 1, normalFileCount: 1, faultFileCount: 0,
          excludedFileCount: 0, uniqueCaptureCount: 1, captureBytes: 24, maxCaptureBytes: 4294967296,
          withinLimit: true, hasNormal: true,
        }
        : { schemaVersion: 1, importId, discarded: true, removedContentFiles: 1 },
    ), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    expect((await previewModelTraining([importId])).normalFileCount).toBe(1);
    expect((await discardTrainingDatasetImport(importId)).discarded).toBe(true);
    for (const [, init] of fetchMock.mock.calls as unknown as Array<[string, RequestInit]>) {
      expect((init.headers as Record<string, string>)[DESKTOP_API_TOKEN_HEADER]).toBe(TOKEN);
    }
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:43127/ai/fault-detection/training/preview");
    expect(fetchMock.mock.calls[1][0]).toBe(`http://127.0.0.1:43127/ai/fault-detection/datasets/imports/${importId}/discard`);
  });
});

describe("1.7.0 dataset and training payloads", () => {
  it("defaults the review-fix fields when a payload predates them", () => {
    const summary = parseTrainingDatasetSummary({
      schemaVersion: 1,
      storagePath: "C:\\data",
      schedule: { cadence: "monthly", nextWindowAt: "2026-11-01T00:00:00Z", mode: "manual_approval" },
      totals: { imports: 0, files: 0, bytes: 0, duplicates: 0, rejected: 0, labeledFiles: 0 },
      readyForRetrain: false,
      blocker: "labels_and_training_pipeline_required",
      imports: [{
        schemaVersion: 1, importId: "b27a3b5f27bd4d50a1d4b94e3b29daba", name: "Interrupted", sourceType: "folder",
        status: "failed", createdAt: "2026-10-01T10:00:00Z", completedAt: "2026-10-01T10:01:00Z", fileCount: 0,
        bytes: 0, duplicateCount: 0, rejectedCount: 0, labelStatus: "unlabeled", labeledFileCount: 0,
        remainingFileCount: 0, normalFileCount: 0, faultFileCount: 0, excludedFileCount: 0, readyForRetrain: false,
        recommendedRetrainAt: "2026-11-01T00:00:00Z", warnings: [],
      }],
    });
    expect(summary.unreadableImports).toBe(0);
    expect(summary.imports[0].failureReason).toBeNull();
    expect(summary.imports[0].invalidLabelCount).toBe(0);

    const batch = parseGroundTruthBatch({
      schemaVersion: 1, importId: "b27a3b5f27bd4d50a1d4b94e3b29daba", name: "Batch", status: "ready", fileCount: 1,
      labelStatus: "unlabeled", labeledFileCount: 0, remainingFileCount: 1, normalFileCount: 0, faultFileCount: 0,
      excludedFileCount: 0, invalidLabelCount: 1,
      files: [{ sha256: "a".repeat(64), originalName: "a.pcap", relativePath: "a.pcap", sizeBytes: 24, captureFormat: "pcap", label: null, labelInvalid: true }],
    });
    expect(batch.files[0].labelInvalid).toBe(true);
  });

  it("reads the engine requirements and the settings file location", () => {
    const summary = parseModelTrainingSummary({
      schemaVersion: 1,
      engine: {
        available: false,
        mode: "external_pytorch",
        device: "auto_cuda_or_cpu",
        missing: ["G:\\artifacts"],
        requirements: [{ id: "baselineArtifacts", label: "Baseline checkpoints", path: "G:\\artifacts", ok: false }],
        configFile: "C:\\Users\\tester\\AppData\\Roaming\\iMPS Fault Detection\\model-training\\engine.json",
        configSource: { python: "default", aiProject: "config_file", baselineArtifacts: "environment" },
        configError: null,
        maxEpochs: 8,
      },
      eligibleImports: [],
      jobs: [],
    });
    expect(summary.engine.requirements[0].ok).toBe(false);
    expect(summary.engine.configSource?.aiProject).toBe("config_file");
  });
});

describe("dataset import helpers", () => {
  it("keeps generated batch names within the 120-character server limit", () => {
    const name = datasetImportName("2026-10", "x".repeat(300));
    expect(Array.from(name).length).toBeLessThanOrEqual(120);
    expect(name.startsWith("2026-10 · ")).toBe(true);
    expect(datasetImportName("2026-10", "  station   A  ")).toBe("2026-10 · station A");
  });

  it("keeps a name with emoji within 120 UTF-16 units and never splits a surrogate pair", () => {
    const name = datasetImportName("2026-10", "\u{1F50C}".repeat(80));
    expect(name.length).toBeLessThanOrEqual(120);
    expect(Array.from(name).length).toBeLessThanOrEqual(120);
    expect(name).not.toMatch(/[\uD800-\uDBFF]$/);
    expect(parseTrainingDatasetSummary({
      schemaVersion: 1,
      storagePath: "C:\\data",
      schedule: { cadence: "monthly", nextWindowAt: "2026-11-01T00:00:00Z", mode: "manual_approval" },
      totals: { imports: 0, files: 0, bytes: 0, duplicates: 0, rejected: 0, labeledFiles: 0 },
      readyForRetrain: false,
      blocker: null,
      imports: [{
        schemaVersion: 1, importId: "b27a3b5f27bd4d50a1d4b94e3b29daba", name: "\u{1F50C}".repeat(120), sourceType: "zip",
        status: "uploading", createdAt: "2026-10-01T10:00:00Z", completedAt: null, fileCount: 0, bytes: 0,
        duplicateCount: 0, rejectedCount: 0, labelStatus: "unlabeled", labeledFileCount: 0, remainingFileCount: 0,
        normalFileCount: 0, faultFileCount: 0, excludedFileCount: 0, readyForRetrain: false,
        recommendedRetrainAt: "2026-11-01T00:00:00Z", warnings: [],
      }],
    }).imports[0].name).toHaveLength(240);
  });

  it("skips files whose name or path the importer refuses", () => {
    const file = (name: string, relative: string) => ({ name, size: 24, webkitRelativePath: relative }) as File;
    const { files, skipped } = selectFolderCaptures([
      file("good.pcap", "root/good.pcap"),
      file(".pcap", "root/.pcap"),
      file("deep.pcap", `root/${"d".repeat(600)}/deep.pcap`),
      file(`${"n".repeat(260)}.pcap`, `root/${"n".repeat(260)}.pcap`),
    ]);
    expect(files.map((item) => item.name)).toEqual(["good.pcap"]);
    expect(skipped).toBe(3);
  });

  it("skips empty and oversized captures instead of refusing the whole folder", () => {
    const file = (name: string, size: number) => ({ name, size }) as File;
    const { files, skipped } = selectFolderCaptures([
      file("a.pcap", 24),
      file("empty.pcap", 0),
      file("huge.pcapng", 600 * 1024 * 1024),
      file("notes.txt", 10),
      file("b.PCAPNG", 100),
    ]);
    expect(files.map((item) => item.name)).toEqual(["a.pcap", "b.PCAPNG"]);
    expect(skipped).toBe(2);
  });
});
