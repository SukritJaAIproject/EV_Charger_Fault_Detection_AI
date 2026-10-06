"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  CalendarClock,
  CheckCircle2,
  Database,
  FolderOpen,
  HardDrive,
  LoaderCircle,
  Lock,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from "lucide-react";

import {
  FaultDetectionApiError,
  MAX_DATASET_CAPTURE_BYTES,
  MAX_DATASET_UPLOAD_BYTES,
  completeTrainingDatasetImport,
  createTrainingDatasetImport,
  discardTrainingDatasetImport,
  getTrainingDatasetSummary,
  uploadTrainingDatasetFile,
  type TrainingDatasetImport,
  type TrainingDatasetSourceType,
  type TrainingDatasetSummary,
} from "./api";
import { snapshotDateLocale } from "./data";


const COPY = {
  th: {
    title: "คลัง Dataset สำหรับรอบ Retrain",
    subtitle: "นำเข้า PCAP จำนวนมากจาก ZIP หรือเลือกทั้งโฟลเดอร์ ระบบจะตรวจไฟล์ ทำ hash กันข้อมูลซ้ำ และจัดเป็น batch รายเดือน",
    guard: "การนำเข้าจะไม่เปลี่ยนโมเดลที่ใช้งานอยู่ โมเดลใหม่ต้องมี label ที่ตรวจทานแล้ว ผ่าน held-out evaluation และได้รับอนุมัติก่อน deploy",
    zipTitle: "นำเข้าไฟล์ ZIP",
    zipBody: "เลือก ZIP ที่มีไฟล์ .pcap หรือ .pcapng อยู่ภายใน รองรับโฟลเดอร์ย่อยและข้ามไฟล์อื่นให้อัตโนมัติ",
    zipButton: "เลือก ZIP",
    folderTitle: "เลือกโฟลเดอร์ PCAP",
    folderBody: "เลือกโฟลเดอร์ที่มี PCAP หลายไฟล์ ระบบจะอัปโหลดโครงสร้างโฟลเดอร์เป็น batch เดียว",
    folderButton: "เลือกโฟลเดอร์",
    batches: "Dataset batches",
    captures: "PCAP ที่รับแล้ว",
    stored: "พื้นที่จัดเก็บ",
    labeled: "ไฟล์ที่มี label",
    schedule: "รอบทบทวนรายเดือนที่แนะนำ",
    monthly: "รายเดือน · เริ่มเองเมื่อพร้อม ไม่มีการ retrain อัตโนมัติ",
    blockedTitle: "ยังไม่พร้อมสร้างโมเดลใหม่",
    readyTitle: "พร้อมสร้าง candidate model",
    blockedBody: "PCAP ใหม่ยังไม่มี ground-truth label กรุณาตรวจทุกไฟล์ในแท็บ Ground Truth Label ให้ครบ แล้วจึงเลือก batch นี้ในแท็บ Train Model",
    trainingOnlyBody: "Ground-truth label ครบแล้ว Dataset batch นี้พร้อมให้เลือกในแท็บ Train Model เพื่อสร้าง candidate โดยจะยังไม่แตะ production model",
    pipeline: "PCAP → ตรวจ label → train → ทดสอบ held-out → อนุมัติ → deploy",
    importing: "กำลังนำเข้า dataset",
    imported: "นำเข้า dataset สำเร็จ",
    recent: "Dataset ทั้งหมด",
    noImports: "ยังไม่มี dataset ที่นำเข้า",
    refresh: "รีเฟรช",
    storagePath: "จัดเก็บที่",
    ready: "นำเข้าแล้ว",
    uploading: "ยังไม่เสร็จ",
    importFailed: "ไม่สำเร็จ",
    files: "ไฟล์",
    duplicates: "ซ้ำ",
    rejected: "ไม่ผ่าน",
    warnings: "ข้อควรทราบ",
    invalidLabels: "label ที่อ่านไม่ได้ ต้องตรวจใหม่",
    finish: "ปิด batch ด้วยไฟล์ที่รับแล้ว",
    discard: "ลบ batch นี้",
    discardConfirm: "ลบ batch ที่ยังไม่เสร็จนี้และไฟล์ที่มีเฉพาะใน batch นี้? Label ที่บันทึกไว้จะยังอยู่",
    discarded: "ลบ batch แล้ว",
    unreadable: "batch ที่อ่าน manifest ไม่ได้",
    invalidZip: "กรุณาเลือกไฟล์ .zip หนึ่งไฟล์ ขนาดไม่เกิน 4 GiB",
    invalidFolder: "ไม่พบไฟล์ .pcap หรือ .pcapng ที่ใช้ได้ในโฟลเดอร์ที่เลือก",
    skipped: "ข้ามไฟล์ที่ใช้ไม่ได้ (ว่าง ใหญ่เกิน 512 MiB หรือชื่อ/path ไม่ผ่าน)",
    failed: "นำเข้า dataset ไม่สำเร็จ",
    actionFailed: "ทำรายการไม่สำเร็จ",
    notFinished: "batch นี้ปิดไม่ได้",
    reasons: {
      interrupted: "การนำเข้าหยุดก่อนเสร็จ (ปิดแอปหรือการอัปโหลดหยุด) กรุณาลบ batch นี้แล้วนำเข้าไฟล์ใหม่",
      empty: "ไม่มีไฟล์ PCAP หรือ PCAPNG ที่ใช้ได้ถูกนำเข้า",
    },
  },
  en: {
    title: "Dataset inbox for monthly retraining",
    subtitle: "Import many PCAPs from a ZIP or select a folder. Files are validated, hashed, deduplicated, and staged as a monthly batch.",
    guard: "Importing never changes the active model. A candidate model needs reviewed labels, held-out evaluation, and approval before deployment.",
    zipTitle: "Import a ZIP archive",
    zipBody: "Choose a ZIP containing .pcap or .pcapng files. Nested folders are supported and unrelated files are ignored.",
    zipButton: "Choose ZIP",
    folderTitle: "Select a PCAP folder",
    folderBody: "Choose a folder with multiple captures. Its relative folder structure is uploaded as one dataset batch.",
    folderButton: "Choose folder",
    batches: "Dataset batches",
    captures: "Accepted PCAPs",
    stored: "Stored data",
    labeled: "Labeled files",
    schedule: "Suggested monthly review",
    monthly: "Monthly · started by you when ready, never automatic",
    blockedTitle: "Not ready for a training run yet",
    readyTitle: "Ready for a candidate model",
    blockedBody: "The new PCAPs still need Ground Truth review. Label every file, then select this batch in the Train Model tab.",
    trainingOnlyBody: "Ground Truth review is complete. This batch is ready in the Train Model tab to create a candidate without changing the production model.",
    pipeline: "PCAP → label review → train → held-out gate → approval → deploy",
    importing: "Importing dataset",
    imported: "Dataset imported",
    recent: "All datasets",
    noImports: "No datasets have been imported yet.",
    refresh: "Refresh",
    storagePath: "Stored at",
    ready: "Imported",
    uploading: "Not finished",
    importFailed: "Failed",
    files: "files",
    duplicates: "duplicates",
    rejected: "rejected",
    warnings: "Notes",
    invalidLabels: "unreadable labels, review again",
    finish: "Finish with the files received",
    discard: "Discard batch",
    discardConfirm: "Discard this unfinished batch and the captures only it holds? Saved labels are kept.",
    discarded: "Batch discarded",
    unreadable: "batch(es) with an unreadable manifest",
    invalidZip: "Select one .zip file of at most 4 GiB.",
    invalidFolder: "The selected folder contains no usable .pcap or .pcapng files.",
    skipped: "Skipped unusable files (empty, over 512 MiB, or a name or path the importer refuses)",
    failed: "Dataset import failed",
    actionFailed: "The action failed",
    notFinished: "This batch could not be finished",
    reasons: {
      interrupted: "The import was interrupted before it finished (the app closed or the upload stopped). Discard it and import the files again.",
      empty: "No valid PCAP or PCAPNG files were imported.",
    },
  },
} as const;

type Lang = keyof typeof COPY;
const MAX_IMPORT_NAME = 120;

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
};

/**
 * The batch name the server stores: whitespace collapsed, at most 120
 * characters. Cut by code point and kept within 120 UTF-16 units as well, so
 * neither the sidecar nor the dashboard's schema can refuse it.
 */
export function datasetImportName(month: string, rootName: string): string {
  const name = `${month} · ${rootName}`.split(/\s+/).filter(Boolean).join(" ");
  let result = "";
  for (const character of Array.from(name)) {
    if (result.length + character.length > MAX_IMPORT_NAME) break;
    result += character;
  }
  return result.trim();
}

/** The sidecar's per-file checks (begin_upload): a refused file is skipped, not sent. */
function importerAcceptsPath(name: string, relativePath: string): boolean {
  if (!/^.+\.(pcap|pcapng)$/i.test(name) || Array.from(name).length > 255) return false;
  const path = (relativePath || name).replaceAll("\\", "/").trim();
  if (!path || path.includes("\u0000") || Array.from(path).length > 500 || path.startsWith("/")) return false;
  const parts = path.split("/");
  return !parts.some((part) => part === "" || part === "." || part === "..") && !parts[0].includes(":");
}

/** Folder captures the importer will accept, and how many were left out. */
export function selectFolderCaptures(incoming: File[]): { files: File[]; skipped: number } {
  const captures = incoming.filter((file) => /\.(pcap|pcapng)$/i.test(file.name));
  const files = captures.filter((file) => file.size > 0
    && file.size <= MAX_DATASET_CAPTURE_BYTES
    && importerAcceptsPath(file.name, file.webkitRelativePath || file.name));
  return { files, skipped: captures.length - files.length };
}

/** A per-file refusal (bad name, size or content) skips that file; anything else stops the import. */
const isPerFileRefusal = (error: unknown) =>
  error instanceof FaultDetectionApiError && error.kind === "http" && [400, 413, 415].includes(error.status ?? 0);

const inputDirectoryAttributes = {
  webkitdirectory: "",
  directory: "",
} as unknown as React.InputHTMLAttributes<HTMLInputElement>;

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 tw-shadow-sm">
      <div className="tw-flex tw-items-center tw-gap-2 tw-text-[11px] tw-font-bold tw-text-slate-500">
        <span className="tw-flex tw-h-7 tw-w-7 tw-items-center tw-justify-center tw-rounded-lg tw-bg-blue-50 tw-text-blue-700">{icon}</span>
        {label}
      </div>
      <div className="ai-mono tw-mt-2 tw-text-xl tw-font-black tw-text-slate-950">{value}</div>
    </div>
  );
}

function failureText(reason: string, c: (typeof COPY)[Lang]): string {
  if (reason === COPY.en.reasons.interrupted) return c.reasons.interrupted;
  if (reason === COPY.en.reasons.empty) return c.reasons.empty;
  return reason;
}

function statusBadge(item: TrainingDatasetImport, c: (typeof COPY)[Lang]) {
  if (item.status === "ready") return { text: c.ready, tone: "tw-bg-emerald-100 tw-text-emerald-800" };
  if (item.status === "failed") return { text: c.importFailed, tone: "tw-bg-red-100 tw-text-red-800" };
  return { text: c.uploading, tone: "tw-bg-blue-100 tw-text-blue-800" };
}

export default function DatasetRetrainPanel({ lang, active = true }: { lang: Lang; active?: boolean }) {
  const c = COPY[lang];
  const zipInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [summary, setSummary] = useState<TrainingDatasetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [activeImportId, setActiveImportId] = useState<string | null>(null);
  const [busyImportId, setBusyImportId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ current: 0, total: 0, name: "" });

  // keepMessages: a refresh after an action must not erase that action's error.
  const loadSummary = useCallback(async (signal?: AbortSignal, keepMessages = false) => {
    setLoading(true);
    if (!keepMessages) setError(null);
    try {
      setSummary(await getTrainingDatasetSummary({ signal }));
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : c.failed);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [c.failed]);

  // The panel stays mounted while other tabs are open so an import keeps
  // running; refresh the list whenever the tab is shown again.
  useEffect(() => {
    if (!active || importing) return undefined;
    const controller = new AbortController();
    void loadSummary(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, loadSummary]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const nextWindow = useMemo(() => {
    if (!summary) return "—";
    const date = new Date(summary.schedule.nextWindowAt);
    return Number.isNaN(date.getTime())
      ? summary.schedule.nextWindowAt
      : date.toLocaleDateString(snapshotDateLocale(lang), { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }, [lang, summary]);

  const importFiles = useCallback(async (sourceType: TrainingDatasetSourceType, incoming: File[]) => {
    setError(null);
    setSuccess(null);
    let files: File[];
    let skipped = 0;
    if (sourceType === "zip") {
      files = incoming.filter((file) => file.name.toLowerCase().endsWith(".zip"));
      if (incoming.length !== 1 || files.length !== 1 || files[0].size <= 0 || files[0].size > MAX_DATASET_UPLOAD_BYTES) {
        setError(c.invalidZip);
        return;
      }
    } else {
      ({ files, skipped } = selectFolderCaptures(incoming));
      if (files.length === 0) {
        setError(c.invalidFolder);
        return;
      }
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setImporting(true);
    setProgress({ current: 0, total: files.length, name: files[0]?.name ?? "" });
    try {
      const now = new Date();
      const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
      const rootName = sourceType === "zip"
        ? files[0].name.replace(/\.zip$/i, "")
        : (files[0].webkitRelativePath.split("/")[0] || "PCAP folder");
      const created = await createTrainingDatasetImport(datasetImportName(month, rootName), sourceType, { signal: controller.signal });
      setActiveImportId(created.importId);
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        setProgress({ current: index, total: files.length, name: file.webkitRelativePath || file.name });
        try {
          await uploadTrainingDatasetFile(
            created.importId,
            file,
            file.webkitRelativePath || file.name,
            { signal: controller.signal },
          );
        } catch (caught) {
          // a ZIP is the whole batch; in a folder one refused file is skipped
          if (sourceType === "zip" || !isPerFileRefusal(caught)) throw caught;
          skipped += 1;
        }
      }
      const completed = await completeTrainingDatasetImport(created.importId, { signal: controller.signal });
      setProgress({ current: files.length, total: files.length, name: completed.name });
      const skippedNote = skipped > 0 ? ` · ${c.skipped}: ${skipped.toLocaleString("en-US")}` : "";
      setSuccess(`${c.imported}: ${completed.fileCount.toLocaleString("en-US")} ${c.files}${skippedNote}`);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : c.failed);
    } finally {
      setImporting(false);
      setActiveImportId(null);
      abortRef.current = null;
      if (zipInputRef.current) zipInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
      if (!controller.signal.aborted) void loadSummary(undefined, true);
    }
  }, [c, loadSummary]);

  const finishImport = useCallback(async (importId: string) => {
    setError(null);
    setSuccess(null);
    setBusyImportId(importId);
    try {
      const completed = await completeTrainingDatasetImport(importId);
      // the sidecar answers with the batch's current state when it was no longer uploading
      if (completed.status === "ready") setSuccess(`${c.imported}: ${completed.fileCount.toLocaleString("en-US")} ${c.files}`);
      else setError(`${c.notFinished}: ${failureText(completed.failureReason ?? "", c) || completed.status}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : c.actionFailed);
    } finally {
      setBusyImportId(null);
      void loadSummary(undefined, true);
    }
  }, [c, loadSummary]);

  const discardImport = useCallback(async (importId: string) => {
    if (!window.confirm(c.discardConfirm)) return;
    setError(null);
    setSuccess(null);
    setBusyImportId(importId);
    try {
      await discardTrainingDatasetImport(importId);
      setSuccess(c.discarded);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : c.actionFailed);
    } finally {
      setBusyImportId(null);
      void loadSummary(undefined, true);
    }
  }, [c, loadSummary]);

  const readyForTraining = summary?.blocker === "training_pipeline_required";

  return (
    <section className="fd-panel tw-overflow-hidden tw-border-t-[3px] tw-border-t-blue-600" data-testid="fd-dataset-retrain-panel">
      <div className="tw-border-b tw-border-slate-100 tw-p-4 sm:tw-p-6">
        <div className="tw-flex tw-flex-col tw-gap-4 sm:tw-flex-row sm:tw-items-start sm:tw-justify-between">
          <div className="tw-flex tw-items-start tw-gap-3">
            <span className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-blue-50 tw-text-blue-700 tw-ring-1 tw-ring-blue-100">
              <Database className="tw-h-5 tw-w-5" />
            </span>
            <div>
              <h2 className="tw-text-lg tw-font-black tw-text-slate-950 sm:tw-text-xl">{c.title}</h2>
              <p className="tw-mt-1.5 tw-max-w-3xl tw-text-[13px] tw-font-medium tw-leading-6 tw-text-slate-500 sm:tw-text-sm">{c.subtitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void loadSummary()}
            disabled={loading || importing}
            className="tw-inline-flex tw-min-h-11 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3.5 tw-text-[12px] tw-font-bold tw-text-slate-700 hover:tw-bg-slate-50 disabled:tw-opacity-50"
          >
            <RefreshCw className={`tw-h-4 tw-w-4 ${loading ? "tw-animate-spin" : ""}`} /> {c.refresh}
          </button>
        </div>
        <div className="tw-mt-4 tw-flex tw-items-start tw-gap-2 tw-rounded-xl tw-bg-emerald-50 tw-p-3 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-emerald-900 tw-ring-1 tw-ring-emerald-100">
          <ShieldCheck className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0" /> {c.guard}
        </div>
      </div>

      <div className="tw-bg-slate-50/60 tw-p-4 sm:tw-p-6">
        <div className="tw-grid tw-grid-cols-2 tw-gap-3 lg:tw-grid-cols-4">
          <StatCard icon={<Archive className="tw-h-4 tw-w-4" />} label={c.batches} value={(summary?.totals.imports ?? 0).toLocaleString("en-US")} />
          <StatCard icon={<Database className="tw-h-4 tw-w-4" />} label={c.captures} value={(summary?.totals.files ?? 0).toLocaleString("en-US")} />
          <StatCard icon={<HardDrive className="tw-h-4 tw-w-4" />} label={c.stored} value={formatBytes(summary?.totals.bytes ?? 0)} />
          <StatCard icon={<CheckCircle2 className="tw-h-4 tw-w-4" />} label={c.labeled} value={(summary?.totals.labeledFiles ?? 0).toLocaleString("en-US")} />
        </div>

        <div className="tw-mt-4 tw-grid tw-gap-4 lg:tw-grid-cols-2">
          <input
            ref={zipInputRef}
            type="file"
            accept=".zip,application/zip"
            className="tw-hidden"
            disabled={importing}
            onChange={(event) => void importFiles("zip", Array.from(event.target.files ?? []))}
          />
          <button
            type="button"
            onClick={() => zipInputRef.current?.click()}
            disabled={importing}
            className="tw-flex tw-min-h-[180px] tw-flex-col tw-items-start tw-rounded-2xl tw-border tw-border-dashed tw-border-blue-300 tw-bg-white tw-p-5 tw-text-left tw-shadow-sm tw-transition hover:tw-border-blue-500 hover:tw-bg-blue-50/40 disabled:tw-cursor-not-allowed disabled:tw-opacity-60"
          >
            <span className="tw-flex tw-h-11 tw-w-11 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-50 tw-text-blue-700"><Archive className="tw-h-5 tw-w-5" /></span>
            <span className="tw-mt-4 tw-text-base tw-font-black tw-text-slate-950">{c.zipTitle}</span>
            <span className="tw-mt-1 tw-text-[12px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.zipBody}</span>
            <span className="tw-mt-auto tw-pt-4 tw-text-[12px] tw-font-black tw-text-blue-700">{c.zipButton} →</span>
          </button>

          <input
            {...inputDirectoryAttributes}
            ref={folderInputRef}
            type="file"
            multiple
            accept=".pcap,.pcapng,application/vnd.tcpdump.pcap,application/octet-stream"
            className="tw-hidden"
            disabled={importing}
            onChange={(event) => void importFiles("folder", Array.from(event.target.files ?? []))}
          />
          <button
            type="button"
            onClick={() => folderInputRef.current?.click()}
            disabled={importing}
            className="tw-flex tw-min-h-[180px] tw-flex-col tw-items-start tw-rounded-2xl tw-border tw-border-dashed tw-border-violet-300 tw-bg-white tw-p-5 tw-text-left tw-shadow-sm tw-transition hover:tw-border-violet-500 hover:tw-bg-violet-50/40 disabled:tw-cursor-not-allowed disabled:tw-opacity-60"
          >
            <span className="tw-flex tw-h-11 tw-w-11 tw-items-center tw-justify-center tw-rounded-xl tw-bg-violet-50 tw-text-violet-700"><FolderOpen className="tw-h-5 tw-w-5" /></span>
            <span className="tw-mt-4 tw-text-base tw-font-black tw-text-slate-950">{c.folderTitle}</span>
            <span className="tw-mt-1 tw-text-[12px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.folderBody}</span>
            <span className="tw-mt-auto tw-pt-4 tw-text-[12px] tw-font-black tw-text-violet-700">{c.folderButton} →</span>
          </button>
        </div>

        {importing && (
          <div className="tw-mt-4 tw-rounded-2xl tw-border tw-border-blue-200 tw-bg-blue-50 tw-p-4" role="status">
            <div className="tw-flex tw-items-center tw-justify-between tw-gap-3 tw-text-[12px] tw-font-bold tw-text-blue-950">
              <span className="tw-flex tw-min-w-0 tw-items-center tw-gap-2"><LoaderCircle className="tw-h-4 tw-w-4 tw-flex-shrink-0 tw-animate-spin" /> <span className="tw-truncate">{c.importing}: {progress.name}</span></span>
              <span className="ai-mono tw-flex-shrink-0">{progress.current}/{progress.total}</span>
            </div>
            <div className="tw-mt-3 tw-h-2 tw-overflow-hidden tw-rounded-full tw-bg-blue-100">
              <div className="tw-h-full tw-rounded-full tw-bg-blue-600 tw-transition-all" style={{ width: `${progress.total ? (progress.current / progress.total) * 100 : 0}%` }} />
            </div>
          </div>
        )}
        {error && <div role="alert" className="tw-mt-4 tw-rounded-xl tw-bg-red-50 tw-p-3 tw-text-[12px] tw-font-semibold tw-text-red-800 tw-ring-1 tw-ring-red-100">{error}</div>}
        {success && <div role="status" className="tw-mt-4 tw-rounded-xl tw-bg-emerald-50 tw-p-3 tw-text-[12px] tw-font-semibold tw-text-emerald-800 tw-ring-1 tw-ring-emerald-100">{success}</div>}

        <div className="tw-mt-5 tw-grid tw-gap-4 lg:tw-grid-cols-[minmax(0,1fr)_360px]">
          <div className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 sm:tw-p-5">
            <div className="tw-flex tw-items-center tw-justify-between tw-gap-3">
              <div>
                <h3 className="tw-text-sm tw-font-black tw-text-slate-950">{c.recent}{summary ? ` (${summary.imports.length.toLocaleString("en-US")})` : ""}</h3>
                {summary && <p className="tw-mt-1 tw-break-all tw-text-[10px] tw-font-medium tw-text-slate-400"><span className="tw-font-bold">{c.storagePath}:</span> {summary.storagePath}</p>}
              </div>
              {loading && <LoaderCircle className="tw-h-4 tw-w-4 tw-animate-spin tw-text-blue-600" />}
            </div>
            {summary && summary.unreadableImports > 0 && (
              <p className="tw-mt-3 tw-flex tw-items-center tw-gap-1.5 tw-text-[11px] tw-font-semibold tw-text-amber-800">
                <AlertTriangle className="tw-h-3.5 tw-w-3.5" /> {summary.unreadableImports.toLocaleString("en-US")} {c.unreadable}
              </p>
            )}
            {!summary?.imports.length ? (
              <div className="tw-py-10 tw-text-center tw-text-[12px] tw-font-semibold tw-text-slate-400">{c.noImports}</div>
            ) : (
              <div className="tw-mt-4 tw-max-h-[520px] tw-space-y-2.5 tw-overflow-y-auto tw-pr-1">
                {summary.imports.map((item) => {
                  const badge = statusBadge(item, c);
                  const unfinished = item.status !== "ready" && item.importId !== activeImportId;
                  const busy = busyImportId === item.importId;
                  return (
                    <div key={item.importId} className="tw-rounded-xl tw-border tw-border-slate-100 tw-bg-slate-50 tw-p-3">
                      <div className="tw-flex tw-items-start tw-justify-between tw-gap-3">
                        <div className="tw-min-w-0">
                          <div className="tw-truncate tw-text-[12px] tw-font-black tw-text-slate-900" title={item.name}>{item.name}</div>
                          <div className="tw-mt-1 tw-text-[10px] tw-font-semibold tw-text-slate-500">
                            {item.fileCount.toLocaleString("en-US")} {c.files} · {formatBytes(item.bytes)} · {item.duplicateCount} {c.duplicates} · {item.rejectedCount} {c.rejected}
                            {item.invalidLabelCount > 0 && <span className="tw-text-amber-700"> · {item.invalidLabelCount} {c.invalidLabels}</span>}
                          </div>
                        </div>
                        <span className={`tw-flex-shrink-0 tw-rounded-full tw-px-2.5 tw-py-1 tw-text-[9px] tw-font-black ${badge.tone}`}>{badge.text}</span>
                      </div>
                      {item.failureReason && <p className="tw-mt-2 tw-text-[10px] tw-font-semibold tw-leading-4 tw-text-red-700">{failureText(item.failureReason, c)}</p>}
                      {item.warnings.length > 0 && <p className="tw-mt-2 tw-text-[10px] tw-font-medium tw-leading-4 tw-text-amber-700">{c.warnings}: {item.warnings.join(" · ")}</p>}
                      {unfinished && (
                        <div className="tw-mt-2.5 tw-flex tw-flex-wrap tw-gap-2">
                          {item.status === "uploading" && item.fileCount > 0 && (
                            <button
                              type="button"
                              disabled={busy || importing}
                              onClick={() => void finishImport(item.importId)}
                              className="tw-inline-flex tw-min-h-9 tw-items-center tw-gap-1.5 tw-rounded-lg tw-border tw-border-emerald-200 tw-bg-white tw-px-3 tw-text-[11px] tw-font-bold tw-text-emerald-800 hover:tw-bg-emerald-50 disabled:tw-opacity-50"
                            >
                              <CheckCircle2 className="tw-h-3.5 tw-w-3.5" /> {c.finish}
                            </button>
                          )}
                          <button
                            type="button"
                            disabled={busy || importing}
                            onClick={() => void discardImport(item.importId)}
                            className="tw-inline-flex tw-min-h-9 tw-items-center tw-gap-1.5 tw-rounded-lg tw-border tw-border-red-200 tw-bg-white tw-px-3 tw-text-[11px] tw-font-bold tw-text-red-700 hover:tw-bg-red-50 disabled:tw-opacity-50"
                          >
                            {busy ? <LoaderCircle className="tw-h-3.5 tw-w-3.5 tw-animate-spin" /> : <Trash2 className="tw-h-3.5 tw-w-3.5" />} {c.discard}
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <aside className="tw-rounded-2xl tw-border tw-border-amber-200 tw-bg-amber-50 tw-p-5">
            <div className="tw-flex tw-items-center tw-gap-2 tw-text-[11px] tw-font-black tw-uppercase tw-tracking-wider tw-text-amber-800">
              <CalendarClock className="tw-h-4 tw-w-4" /> {c.schedule}
            </div>
            <div className="ai-mono tw-mt-2 tw-text-xl tw-font-black tw-text-amber-950">{nextWindow}</div>
            <div className="tw-mt-1 tw-text-[11px] tw-font-bold tw-text-amber-700">{c.monthly}</div>
            <div className="tw-mt-5 tw-rounded-xl tw-bg-white/70 tw-p-4 tw-ring-1 tw-ring-amber-200/70">
              <div className="tw-flex tw-items-start tw-gap-2">
                {readyForTraining
                  ? <CheckCircle2 className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0 tw-text-emerald-700" />
                  : <Lock className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0 tw-text-amber-700" />}
                <div>
                  <div className="tw-text-[12px] tw-font-black tw-text-amber-950">{readyForTraining ? c.readyTitle : c.blockedTitle}</div>
                  <p className="tw-mt-1.5 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-amber-900/80">{readyForTraining ? c.trainingOnlyBody : c.blockedBody}</p>
                </div>
              </div>
            </div>
            <div className="tw-mt-4 tw-flex tw-items-center tw-gap-2 tw-text-[10px] tw-font-bold tw-text-amber-800">
              <UploadCloud className="tw-h-4 tw-w-4 tw-flex-shrink-0" /> {c.pipeline}
            </div>
          </aside>
        </div>
      </div>
    </section>
  );
}
