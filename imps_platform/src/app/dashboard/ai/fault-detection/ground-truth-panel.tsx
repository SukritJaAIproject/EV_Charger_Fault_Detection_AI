"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileCheck2,
  LoaderCircle,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Tags,
  UserRound,
} from "lucide-react";

import {
  getGroundTruthBatch,
  getTrainingDatasetSummary,
  saveGroundTruthLabel,
  type GroundTruthBatch,
  type GroundTruthClassification,
  type GroundTruthFaultFamily,
  type GroundTruthFile,
  type TrainingDatasetSummary,
} from "./api";
import { snapshotDateLocale } from "./data";
import { getFaultExplanation, supportedFaultFamilies } from "./fault-catalog";

const PAGE_SIZE = 25;
const CLASSIFICATION_ORDER: GroundTruthClassification[] = ["normal", "fault", "exclude"];

const COPY = {
  th: {
    title: "Ground Truth Label",
    subtitle: "ตรวจและกำหนดผลจริงให้ PCAP แต่ละไฟล์ก่อนนำไปสร้าง training dataset รอบถัดไป",
    guard: "Ground truth ต้องอ้างอิง packet, เหตุการณ์หน้างาน หรือผลตรวจที่เชื่อถือได้ ไม่ควรคัดลอกคำตอบจาก AI โดยไม่ตรวจหลักฐาน",
    batch: "Dataset batch",
    reviewer: "ชื่อผู้ตรวจ",
    reviewerPlaceholder: "เช่น ทีม EV AI / ชื่อผู้ตรวจ",
    total: "ไฟล์ทั้งหมด",
    labeled: "ตรวจแล้ว",
    remaining: "รอตรวจ",
    faults: "Fault",
    search: "ค้นหาชื่อไฟล์หรือ path",
    all: "ทั้งหมด",
    pending: "รอตรวจ",
    reviewed: "ตรวจแล้ว",
    noDatasets: "ยังไม่มี dataset ที่พร้อมทำ label กรุณานำเข้าและปิด batch ในแท็บ Dataset & Retrain ก่อน",
    noFiles: "ไม่พบไฟล์ที่ตรงกับตัวกรอง",
    selectFile: "เลือก PCAP จากรายการเพื่อเริ่มกำหนด Ground Truth",
    normal: "Normal",
    normalBody: "ไม่พบ fault ตามเกณฑ์ที่ตรวจทาน",
    fault: "Fault",
    faultBody: "ยืนยัน fault และระบุประเภทหลัก",
    exclude: "Exclude",
    excludeBody: "ข้อมูลไม่ครบ เสีย หรือไม่เหมาะกับการฝึก",
    faultFamily: "ประเภท Fault",
    notes: "หลักฐานและหมายเหตุ",
    notesPlaceholder: "บันทึก packet/sequence, ticket หน้างาน หรือเหตุผลที่ใช้ตัดสิน...",
    saveNext: "บันทึกและไปไฟล์ถัดไป",
    saved: "บันทึก Ground Truth แล้ว",
    revision: "Revision",
    lastReviewer: "ผู้ตรวจล่าสุด",
    updated: "แก้ไขล่าสุด",
    refresh: "รีเฟรช",
    loading: "กำลังโหลด Ground Truth",
    failed: "โหลดหรือบันทึก Ground Truth ไม่สำเร็จ",
    reviewerRequired: "กรุณาระบุชื่อผู้ตรวจก่อนบันทึก",
    progress: "ความคืบหน้า",
    reused: "Label นี้ผูกกับ SHA-256 และจะใช้ร่วมกับไฟล์ซ้ำอัตโนมัติ",
    classification: "ผลการตรวจ",
    chooseClassification: "เลือก Normal, Fault หรือ Exclude ก่อนบันทึก",
    chooseFamily: "— เลือกประเภท Fault —",
    familyRequired: "เลือกประเภท Fault ก่อนบันทึก",
    invalidLabel: "ไฟล์ label เดิมอ่านไม่ได้ กรุณาตรวจและบันทึกใหม่",
    unreadable: "อ่าน label ไม่ได้",
    previousPage: "หน้าก่อนหน้า",
    nextPage: "หน้าถัดไป",
    fileFilter: "กรองไฟล์",
    retry: "ลองอีกครั้ง",
  },
  en: {
    title: "Ground Truth Label",
    subtitle: "Review and assign the verified outcome for each PCAP before it enters the next training dataset.",
    guard: "Ground truth must come from packets, site events, or trusted investigation results. Do not copy an AI answer without reviewing the evidence.",
    batch: "Dataset batch",
    reviewer: "Reviewer name",
    reviewerPlaceholder: "e.g. EV AI team / reviewer name",
    total: "Total files",
    labeled: "Reviewed",
    remaining: "Remaining",
    faults: "Faults",
    search: "Search filename or path",
    all: "All",
    pending: "Pending",
    reviewed: "Reviewed",
    noDatasets: "No dataset is ready for labeling. Import and complete a batch in Dataset & Retrain first.",
    noFiles: "No files match the current filter.",
    selectFile: "Select a PCAP from the list to assign ground truth.",
    normal: "Normal",
    normalBody: "No reviewed fault under the labeling policy",
    fault: "Fault",
    faultBody: "Confirm a fault and choose its primary family",
    exclude: "Exclude",
    excludeBody: "Incomplete, corrupt, or unsuitable for training",
    faultFamily: "Fault family",
    notes: "Evidence and notes",
    notesPlaceholder: "Record packet/sequence evidence, a site ticket, or the reason for this decision...",
    saveNext: "Save & next file",
    saved: "Ground truth saved",
    revision: "Revision",
    lastReviewer: "Last reviewer",
    updated: "Updated",
    refresh: "Refresh",
    loading: "Loading ground truth",
    failed: "Unable to load or save ground truth",
    reviewerRequired: "Enter the reviewer name before saving.",
    progress: "Progress",
    reused: "This label is keyed by SHA-256 and is reused automatically for duplicate captures.",
    classification: "Review outcome",
    chooseClassification: "Choose Normal, Fault or Exclude before saving.",
    chooseFamily: "— Choose a fault family —",
    familyRequired: "Choose the fault family before saving.",
    invalidLabel: "The saved label for this capture cannot be read. Review it and save again.",
    unreadable: "unreadable label",
    previousPage: "Previous page",
    nextPage: "Next page",
    fileFilter: "File filter",
    retry: "Try again",
  },
} as const;

type Lang = keyof typeof COPY;
type FileFilter = "all" | "pending" | "reviewed";

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
};

const labelTone = (file: GroundTruthFile) => {
  if (file.labelInvalid) return "tw-bg-orange-100 tw-text-orange-800";
  if (!file.label) return "tw-bg-slate-100 tw-text-slate-600";
  if (file.label.classification === "normal") return "tw-bg-emerald-100 tw-text-emerald-800";
  if (file.label.classification === "fault") return "tw-bg-red-100 tw-text-red-800";
  return "tw-bg-amber-100 tw-text-amber-800";
};

function Metric({ label, value, tone = "blue" }: { label: string; value: number; tone?: "blue" | "green" | "amber" | "red" }) {
  const tones = {
    blue: "tw-bg-blue-50 tw-text-blue-800 tw-ring-blue-100",
    green: "tw-bg-emerald-50 tw-text-emerald-800 tw-ring-emerald-100",
    amber: "tw-bg-amber-50 tw-text-amber-800 tw-ring-amber-100",
    red: "tw-bg-red-50 tw-text-red-800 tw-ring-red-100",
  } as const;
  return (
    <div className={`tw-rounded-2xl tw-p-4 tw-ring-1 ${tones[tone]}`}>
      <div className="tw-text-[10px] tw-font-black tw-uppercase tw-tracking-wider">{label}</div>
      <div className="ai-mono tw-mt-1.5 tw-text-2xl tw-font-black">{value.toLocaleString("en-US")}</div>
    </div>
  );
}

export default function GroundTruthPanel({ lang }: { lang: Lang }) {
  const c = COPY[lang];
  const [summary, setSummary] = useState<TrainingDatasetSummary | null>(null);
  const [batch, setBatch] = useState<GroundTruthBatch | null>(null);
  const [selectedImportId, setSelectedImportId] = useState("");
  const [selectedSha, setSelectedSha] = useState("");
  const [reviewer, setReviewer] = useState("");
  // Nothing is pre-selected: every saved label must be a decision the reviewer made.
  const [classification, setClassification] = useState<GroundTruthClassification | null>(null);
  const [faultFamily, setFaultFamily] = useState<GroundTruthFaultFamily | null>(null);
  const [notes, setNotes] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FileFilter>("all");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const readyImports = useMemo(
    () => (summary?.imports ?? []).filter((item) => item.status === "ready"),
    [summary],
  );

  const loadBatch = useCallback(async (importId: string, signal?: AbortSignal) => {
    if (!importId) {
      setBatch(null);
      setLoading(false);
      return null;
    }
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await getGroundTruthBatch(importId, { signal });
      setBatch(result);
      setSelectedSha((current) => result.files.some((file) => file.sha256 === current) ? current : result.files[0]?.sha256 ?? "");
      return result;
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return null;
      setError(caught instanceof Error ? caught.message : c.failed);
      return null;
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [c.failed]);

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTrainingDatasetSummary({ signal });
      setSummary(result);
      const ready = result.imports.filter((item) => item.status === "ready");
      setSelectedImportId((current) => ready.some((item) => item.importId === current)
        ? current
        : ready[0]?.importId ?? "");
      return result;
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : c.failed);
      return null;
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [c.failed]);

  const refreshAll = useCallback(async () => {
    const result = await loadSummary();
    if (!result) return;
    const ready = result.imports.filter((item) => item.status === "ready");
    const importId = ready.some((item) => item.importId === selectedImportId)
      ? selectedImportId
      : ready[0]?.importId ?? "";
    if (importId) await loadBatch(importId);
  }, [loadBatch, loadSummary, selectedImportId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadSummary(controller.signal);
    return () => controller.abort();
  }, [loadSummary]);

  useEffect(() => {
    if (!selectedImportId || batch?.importId === selectedImportId) return;
    const controller = new AbortController();
    void loadBatch(selectedImportId, controller.signal);
    return () => controller.abort();
  }, [batch?.importId, loadBatch, selectedImportId]);

  const selectedFile = useMemo(
    () => batch?.files.find((file) => file.sha256 === selectedSha) ?? null,
    [batch, selectedSha],
  );

  useEffect(() => {
    if (!selectedFile) return;
    setClassification(selectedFile.label?.classification ?? null);
    setFaultFamily(selectedFile.label?.faultFamily ?? null);
    setNotes(selectedFile.label?.notes ?? "");
  }, [selectedFile]);

  // Arrow keys move between Normal / Fault / Exclude like a native radio group.
  const moveClassification = (event: React.KeyboardEvent<HTMLButtonElement>, current: GroundTruthClassification) => {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const index = (CLASSIFICATION_ORDER.indexOf(current) + step + CLASSIFICATION_ORDER.length) % CLASSIFICATION_ORDER.length;
    setClassification(CLASSIFICATION_ORDER[index]);
    const radios = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
    radios?.[index]?.focus();
  };

  const decisionMissing = classification === null || (classification === "fault" && faultFamily === null);

  const filteredFiles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (batch?.files ?? []).filter((file) => {
      const matchesText = !needle || file.originalName.toLowerCase().includes(needle) || file.relativePath.toLowerCase().includes(needle);
      const matchesStatus = filter === "all" || (filter === "pending" ? !file.label : Boolean(file.label));
      return matchesText && matchesStatus;
    });
  }, [batch, filter, query]);
  const pageCount = Math.max(1, Math.ceil(filteredFiles.length / PAGE_SIZE));
  const visibleFiles = filteredFiles.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  useEffect(() => setPage(0), [filter, query, selectedImportId]);
  useEffect(() => {
    if (page >= pageCount) setPage(pageCount - 1);
  }, [page, pageCount]);

  const saveCurrent = useCallback(async () => {
    if (!selectedFile || !batch) return;
    if (!reviewer.trim()) {
      setError(c.reviewerRequired);
      return;
    }
    if (classification === null) {
      setError(c.chooseClassification);
      return;
    }
    if (classification === "fault" && faultFamily === null) {
      setError(c.familyRequired);
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await saveGroundTruthLabel(batch.importId, {
        sha256: selectedFile.sha256,
        classification,
        faultFamily: classification === "fault" ? faultFamily : null,
        reviewer: reviewer.trim(),
        notes,
        expectedRevision: selectedFile.label?.revision ?? 0,
      });
      const refreshed = await loadBatch(batch.importId);
      if (refreshed) {
        const currentIndex = refreshed.files.findIndex((file) => file.sha256 === selectedFile.sha256);
        const next = refreshed.files.slice(currentIndex + 1).find((file) => !file.label)
          ?? refreshed.files.find((file) => !file.label)
          ?? refreshed.files[Math.min(currentIndex + 1, refreshed.files.length - 1)];
        if (next) setSelectedSha(next.sha256);
      }
      setSuccess(c.saved);
      const refreshedSummary = await getTrainingDatasetSummary();
      setSummary(refreshedSummary);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : c.failed;
      if (batch.importId) await loadBatch(batch.importId);
      setError(message);
    } finally {
      setSaving(false);
    }
  }, [batch, c, classification, faultFamily, loadBatch, notes, reviewer, selectedFile]);

  return (
    <section className="fd-panel tw-overflow-hidden tw-border-t-[3px] tw-border-t-violet-600" data-testid="fd-ground-truth-panel">
      <div className="tw-border-b tw-border-slate-100 tw-p-4 sm:tw-p-6">
        <div className="tw-flex tw-flex-col tw-gap-4 sm:tw-flex-row sm:tw-items-start sm:tw-justify-between">
          <div className="tw-flex tw-items-start tw-gap-3">
            <span className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-violet-50 tw-text-violet-700 tw-ring-1 tw-ring-violet-100"><Tags className="tw-h-5 tw-w-5" /></span>
            <div>
              <h2 className="tw-text-lg tw-font-black tw-text-slate-950 sm:tw-text-xl">{c.title}</h2>
              <p className="tw-mt-1.5 tw-max-w-3xl tw-text-[13px] tw-font-medium tw-leading-6 tw-text-slate-500 sm:tw-text-sm">{c.subtitle}</p>
            </div>
          </div>
          <button type="button" onClick={() => void refreshAll()} disabled={loading || saving} className="tw-inline-flex tw-min-h-11 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3.5 tw-text-[12px] tw-font-bold tw-text-slate-700 hover:tw-bg-slate-50 disabled:tw-opacity-50">
            <RefreshCw className={`tw-h-4 tw-w-4 ${loading ? "tw-animate-spin" : ""}`} /> {c.refresh}
          </button>
        </div>
        <div className="tw-mt-4 tw-flex tw-items-start tw-gap-2 tw-rounded-xl tw-bg-violet-50 tw-p-3 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-violet-900 tw-ring-1 tw-ring-violet-100">
          <ShieldCheck className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0" /> {c.guard}
        </div>
      </div>

      <div className="tw-bg-slate-50/60 tw-p-4 sm:tw-p-6">
        {!summary && error && !loading ? (
          <div role="alert" className="tw-rounded-2xl tw-border tw-border-red-200 tw-bg-red-50 tw-p-6 tw-text-center tw-text-[13px] tw-font-semibold tw-leading-6 tw-text-red-800">
            {error}
            <div className="tw-mt-3">
              <button type="button" onClick={() => void refreshAll()} className="tw-inline-flex tw-min-h-10 tw-items-center tw-gap-2 tw-rounded-xl tw-border tw-border-red-200 tw-bg-white tw-px-3.5 tw-text-[12px] tw-font-bold tw-text-red-800 hover:tw-bg-red-50">
                <RefreshCw className="tw-h-4 tw-w-4" /> {c.retry}
              </button>
            </div>
          </div>
        ) : !readyImports.length && !loading ? (
          <div className="tw-rounded-2xl tw-border tw-border-dashed tw-border-slate-300 tw-bg-white tw-p-10 tw-text-center tw-text-[13px] tw-font-semibold tw-leading-6 tw-text-slate-500">{c.noDatasets}</div>
        ) : (
          <>
            <div className="tw-grid tw-gap-4 lg:tw-grid-cols-2">
              <label className="tw-block">
                <span className="tw-mb-1.5 tw-block tw-text-[11px] tw-font-black tw-text-slate-700">{c.batch}</span>
                <select value={selectedImportId} onChange={(event) => setSelectedImportId(event.target.value)} disabled={loading || saving} className="tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-text-[12px] tw-font-bold tw-text-slate-800 tw-outline-none focus:tw-border-violet-400">
                  {readyImports.map((item) => <option key={item.importId} value={item.importId}>{item.name} · {item.labeledFileCount}/{item.fileCount}</option>)}
                </select>
              </label>
              <label className="tw-block">
                <span className="tw-mb-1.5 tw-block tw-text-[11px] tw-font-black tw-text-slate-700">{c.reviewer}</span>
                <span className="tw-relative tw-block">
                  <UserRound className="tw-pointer-events-none tw-absolute tw-left-3 tw-top-3.5 tw-h-4 tw-w-4 tw-text-slate-400" />
                  <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={80} placeholder={c.reviewerPlaceholder} className="tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-pl-10 tw-pr-3 tw-text-[12px] tw-font-semibold tw-text-slate-800 tw-outline-none focus:tw-border-violet-400" />
                </span>
              </label>
            </div>

            <div className="tw-mt-4 tw-grid tw-grid-cols-2 tw-gap-3 lg:tw-grid-cols-4">
              <Metric label={c.total} value={batch?.fileCount ?? 0} />
              <Metric label={c.labeled} value={batch?.labeledFileCount ?? 0} tone="green" />
              <Metric label={c.remaining} value={batch?.remainingFileCount ?? 0} tone="amber" />
              <Metric label={c.faults} value={batch?.faultFileCount ?? 0} tone="red" />
            </div>
            <div className="tw-mt-3 tw-rounded-xl tw-bg-white tw-p-3 tw-ring-1 tw-ring-slate-200">
              <div className="tw-flex tw-items-center tw-justify-between tw-text-[10px] tw-font-black tw-text-slate-600"><span>{c.progress}</span><span>{batch?.labeledFileCount ?? 0}/{batch?.fileCount ?? 0}</span></div>
              <div className="tw-mt-2 tw-h-2 tw-overflow-hidden tw-rounded-full tw-bg-slate-100"><div className="tw-h-full tw-rounded-full tw-bg-violet-600 tw-transition-all" style={{ width: `${batch?.fileCount ? (batch.labeledFileCount / batch.fileCount) * 100 : 0}%` }} /></div>
            </div>

            {error && <div role="alert" className="tw-mt-4 tw-rounded-xl tw-bg-red-50 tw-p-3 tw-text-[12px] tw-font-semibold tw-text-red-800 tw-ring-1 tw-ring-red-100">{error}</div>}
            {success && <div role="status" className="tw-mt-4 tw-rounded-xl tw-bg-emerald-50 tw-p-3 tw-text-[12px] tw-font-semibold tw-text-emerald-800 tw-ring-1 tw-ring-emerald-100">{success}</div>}

            <div className="tw-mt-5 tw-grid tw-gap-4 lg:tw-grid-cols-[minmax(280px,0.85fr)_minmax(0,1.15fr)]">
              <div className="tw-overflow-hidden tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white">
                <div className="tw-border-b tw-border-slate-100 tw-p-3">
                  <label className="tw-relative tw-block"><Search className="tw-pointer-events-none tw-absolute tw-left-3 tw-top-3 tw-h-4 tw-w-4 tw-text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={c.search} className="tw-h-10 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-slate-50 tw-pl-9 tw-pr-3 tw-text-[11px] tw-font-semibold tw-outline-none focus:tw-border-violet-400" /></label>
                  <div role="group" aria-label={c.fileFilter} className="tw-mt-2 tw-grid tw-grid-cols-3 tw-gap-1 tw-rounded-xl tw-bg-slate-100 tw-p-1">
                    {(["all", "pending", "reviewed"] as FileFilter[]).map((item) => <button key={item} type="button" aria-pressed={filter === item} onClick={() => setFilter(item)} className={`tw-rounded-lg tw-px-2 tw-py-2 tw-text-[10px] tw-font-black ${filter === item ? "tw-bg-white tw-text-violet-700 tw-shadow-sm" : "tw-text-slate-500"}`}>{c[item]}</button>)}
                  </div>
                </div>
                <div className="tw-max-h-[570px] tw-overflow-y-auto tw-p-2">
                  {loading ? <div className="tw-flex tw-items-center tw-justify-center tw-gap-2 tw-py-12 tw-text-[12px] tw-font-semibold tw-text-slate-500"><LoaderCircle className="tw-h-4 tw-w-4 tw-animate-spin" /> {c.loading}</div> : !visibleFiles.length ? <div className="tw-py-12 tw-text-center tw-text-[12px] tw-font-semibold tw-text-slate-400">{c.noFiles}</div> : visibleFiles.map((file) => (
                    <button key={file.sha256} type="button" aria-current={selectedSha === file.sha256 ? "true" : undefined} onClick={() => { setError(null); setSuccess(null); setSelectedSha(file.sha256); }} className={`tw-mb-1.5 tw-flex tw-w-full tw-items-start tw-gap-3 tw-rounded-xl tw-border tw-p-3 tw-text-left tw-transition ${selectedSha === file.sha256 ? "tw-border-violet-300 tw-bg-violet-50" : "tw-border-transparent hover:tw-bg-slate-50"}`}>
                      <span className={`tw-mt-0.5 tw-flex tw-h-7 tw-w-7 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-lg ${labelTone(file)}`}>{file.label ? <FileCheck2 className="tw-h-4 tw-w-4" /> : <Tags className="tw-h-4 tw-w-4" />}</span>
                      <span className="tw-min-w-0 tw-flex-1"><span className="tw-block tw-truncate tw-text-[11px] tw-font-black tw-text-slate-900">{file.originalName}</span><span className="tw-mt-0.5 tw-block tw-truncate tw-text-[9px] tw-font-medium tw-text-slate-400">{file.relativePath}</span><span className="tw-mt-1 tw-block tw-text-[9px] tw-font-bold tw-text-slate-500">{formatBytes(file.sizeBytes)} · {file.captureFormat.toUpperCase()}</span></span>
                      {file.label && <span className={`tw-flex-shrink-0 tw-rounded-full tw-px-2 tw-py-1 tw-text-[8px] tw-font-black tw-uppercase ${labelTone(file)}`}>{file.label.classification}</span>}
                      {file.labelInvalid && <span className={`tw-flex-shrink-0 tw-rounded-full tw-px-2 tw-py-1 tw-text-[8px] tw-font-black ${labelTone(file)}`}>{c.unreadable}</span>}
                    </button>
                  ))}
                </div>
                <div className="tw-flex tw-items-center tw-justify-between tw-border-t tw-border-slate-100 tw-p-3 tw-text-[10px] tw-font-bold tw-text-slate-500">
                  <button type="button" aria-label={c.previousPage} disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))} className="tw-rounded-lg tw-p-2 disabled:tw-opacity-30"><ChevronLeft className="tw-h-4 tw-w-4" aria-hidden="true" /></button><span aria-live="polite">{page + 1}/{pageCount} · {filteredFiles.length}</span><button type="button" aria-label={c.nextPage} disabled={page >= pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} className="tw-rounded-lg tw-p-2 disabled:tw-opacity-30"><ChevronRight className="tw-h-4 tw-w-4" aria-hidden="true" /></button>
                </div>
              </div>

              <div className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 sm:tw-p-5">
                {!selectedFile ? <div className="tw-flex tw-min-h-[430px] tw-items-center tw-justify-center tw-text-center tw-text-[13px] tw-font-semibold tw-text-slate-400">{c.selectFile}</div> : (
                  <div>
                    <div className="tw-flex tw-items-start tw-justify-between tw-gap-3"><div className="tw-min-w-0"><div className="tw-truncate tw-text-base tw-font-black tw-text-slate-950">{selectedFile.originalName}</div><div className="tw-mt-1 tw-break-all tw-text-[10px] tw-font-medium tw-text-slate-400">{selectedFile.relativePath}</div></div>{selectedFile.label && <span className="tw-flex-shrink-0 tw-rounded-full tw-bg-slate-100 tw-px-2.5 tw-py-1 tw-text-[9px] tw-font-black tw-text-slate-600">{c.revision} {selectedFile.label.revision}</span>}</div>
                    {selectedFile.labelInvalid && <div role="alert" className="tw-mt-3 tw-flex tw-items-start tw-gap-2 tw-rounded-xl tw-bg-orange-50 tw-p-3 tw-text-[11px] tw-font-semibold tw-leading-5 tw-text-orange-900 tw-ring-1 tw-ring-orange-100"><AlertTriangle className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0" aria-hidden="true" /> {c.invalidLabel}</div>}
                    <div role="radiogroup" aria-label={c.classification} className="tw-mt-4 tw-grid tw-gap-2 sm:tw-grid-cols-3">
                      {([
                        ["normal", c.normal, c.normalBody, CheckCircle2, "emerald"],
                        ["fault", c.fault, c.faultBody, AlertTriangle, "red"],
                        ["exclude", c.exclude, c.excludeBody, Ban, "amber"],
                      ] as const).map(([value, title, body, Icon, tone]) => <button key={value} type="button" role="radio" aria-checked={classification === value} tabIndex={classification === value || (classification === null && value === "normal") ? 0 : -1} onKeyDown={(event) => moveClassification(event, value)} onClick={() => setClassification(value)} className={`tw-rounded-xl tw-border tw-p-3 tw-text-left ${classification === value ? tone === "emerald" ? "tw-border-emerald-400 tw-bg-emerald-50" : tone === "red" ? "tw-border-red-400 tw-bg-red-50" : "tw-border-amber-400 tw-bg-amber-50" : "tw-border-slate-200 tw-bg-white"}`}><Icon className={`tw-h-4 tw-w-4 ${tone === "emerald" ? "tw-text-emerald-700" : tone === "red" ? "tw-text-red-700" : "tw-text-amber-700"}`} /><span className="tw-mt-2 tw-block tw-text-[11px] tw-font-black tw-text-slate-900">{title}</span><span className="tw-mt-1 tw-block tw-text-[9px] tw-font-medium tw-leading-4 tw-text-slate-500">{body}</span></button>)}
                    </div>
                    {classification === "fault" && <label className="tw-mt-4 tw-block"><span className="tw-mb-1.5 tw-block tw-text-[11px] tw-font-black tw-text-slate-700">{c.faultFamily}</span><select value={faultFamily ?? ""} required onChange={(event) => setFaultFamily(event.target.value ? event.target.value as GroundTruthFaultFamily : null)} className="tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-text-[12px] tw-font-bold tw-text-slate-800 tw-outline-none focus:tw-border-red-400"><option value="" disabled>{c.chooseFamily}</option>{supportedFaultFamilies.map((family) => <option key={family} value={family}>{family.replaceAll("_", " ")} · {getFaultExplanation(family, lang).title}</option>)}</select></label>}
                    <label className="tw-mt-4 tw-block"><span className="tw-mb-1.5 tw-block tw-text-[11px] tw-font-black tw-text-slate-700">{c.notes}</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={2000} rows={6} placeholder={c.notesPlaceholder} className="tw-w-full tw-resize-y tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-p-3 tw-text-[12px] tw-font-medium tw-leading-5 tw-text-slate-800 tw-outline-none focus:tw-border-violet-400" /><span className="tw-mt-1 tw-block tw-text-right tw-text-[9px] tw-font-bold tw-text-slate-400">{notes.length}/2000</span></label>
                    {selectedFile.label && <div className="tw-mt-3 tw-rounded-xl tw-bg-slate-50 tw-p-3 tw-text-[10px] tw-font-semibold tw-leading-5 tw-text-slate-500"><span className="tw-font-black tw-text-slate-700">{c.lastReviewer}:</span> {selectedFile.label.reviewer} · <span className="tw-font-black tw-text-slate-700">{c.updated}:</span> {new Date(selectedFile.label.updatedAt).toLocaleString(snapshotDateLocale(lang))}</div>}
                    <div className="tw-mt-3 tw-flex tw-items-start tw-gap-2 tw-rounded-xl tw-bg-blue-50 tw-p-3 tw-text-[10px] tw-font-semibold tw-leading-4 tw-text-blue-800"><ShieldCheck className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0" /> {c.reused}</div>
                    {decisionMissing && <p className="tw-mt-3 tw-text-[11px] tw-font-semibold tw-text-slate-500">{classification === "fault" ? c.familyRequired : c.chooseClassification}</p>}
                    <button type="button" onClick={() => void saveCurrent()} disabled={saving || loading || decisionMissing} className="tw-mt-4 tw-inline-flex tw-min-h-11 tw-w-full tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-violet-700 tw-px-4 tw-text-[12px] tw-font-black tw-text-white hover:tw-bg-violet-800 disabled:tw-opacity-50">{saving ? <LoaderCircle className="tw-h-4 tw-w-4 tw-animate-spin" /> : <Save className="tw-h-4 tw-w-4" />} {c.saveNext}</button>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
