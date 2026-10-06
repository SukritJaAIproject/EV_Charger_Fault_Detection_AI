"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Cpu,
  Database,
  FileCog,
  FlaskConical,
  Gauge,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import {
  createModelTrainingJob,
  getModelTrainingJob,
  getModelTrainingSummary,
  previewModelTraining,
  type ModelTrainingJob,
  type ModelTrainingPreview,
  type ModelTrainingSummary,
} from "./api";

const MAX_BATCHES_PER_RUN = 24;

const COPY = {
  th: {
    title: "Train Model",
    subtitle: "สร้าง candidate รุ่นใหม่จาก Dataset ที่ผ่าน Ground Truth ครบแล้ว โดยฝึก LSTM-AE และ GRU Forecaster ต่อจาก baseline ปัจจุบัน",
    guard: "ระบบจะไม่แทนที่โมเดลที่ใช้งานอยู่โดยอัตโนมัติ Candidate ทุกชุดต้องผ่านการทดสอบกับข้อมูลที่กันไว้และอนุมัติด้วยคนก่อนนำไปใช้งานจริง",
    engineReady: "Training engine พร้อมใช้งาน",
    engineReadyBody: (epochs: number) => `PyTorch · CUDA หรือ CPU · 1–${epochs} epoch`,
    engineMissing: "Training engine ยังไม่พร้อมบนเครื่องนี้",
    engineMissingBody: "การตรวจจับ Fault เดิมยังใช้งานได้ตามปกติ แต่ต้องมีส่วนประกอบด้านล่างครบก่อนเริ่มฝึก",
    configHint: "กำหนดตำแหน่งได้ในไฟล์นี้ (JSON: python, aiProject, baselineArtifacts) แล้วกดรีเฟรช",
    configError: "อ่านไฟล์ตั้งค่าไม่ได้",
    requirementLabels: {
      python: "Python ที่ติดตั้ง PyTorch",
      aiProject: "โปรเจกต์วิจัย (models/nn_tools.py, core/feature_tracker.py, core/schema.py)",
      baselineArtifacts: "Baseline checkpoint (lstm_ae.pt, gru_fore.pt)",
      worker: "Training worker (มากับแอป)",
      decoder: "ตัวถอดรหัส capture (มากับแอป)",
      tshark: "TShark (มากับแอป)",
      baseModel: "Manifest ของโมเดลที่ติดตั้ง (มากับแอป)",
      baselineMatch: "Baseline checkpoint ตรงกับโมเดลที่ติดตั้ง",
    } as Record<string, string>,
    requirementDetails: {
      "The external baseline checkpoints do not match the installed model.": "Baseline checkpoint ภายนอกไม่ตรงกับโมเดลที่ติดตั้ง",
      "The baseline model manifest or checkpoints are invalid.": "Manifest หรือ checkpoint ของ baseline ไม่ถูกต้อง",
      "Checked once every file above is present.": "จะตรวจเมื่อมีไฟล์ด้านบนครบ",
    } as Record<string, string>,
    sourceLabels: { command_line: "command line", environment: "environment", config_file: "engine.json", default: "ค่าเริ่มต้น" },
    batches: "เลือก Dataset batch",
    batchesHint: "แสดงเฉพาะ batch ที่ตรวจ Ground Truth ครบทุกไฟล์",
    noBatches: "ยังไม่มี batch ที่พร้อมฝึก กรุณานำเข้า Dataset และตรวจ Ground Truth ให้ครบก่อน",
    normal: "Normal สำหรับฝึก",
    fault: "Fault กันไว้ตรวจสอบ",
    exclude: "Exclude ไม่นำมาใช้",
    countedOnce: "นับไฟล์ที่ซ้ำกันระหว่าง batch เพียงครั้งเดียว",
    captureSize: "ขนาด capture รวม",
    overLimit: "Capture ที่เลือกเกินขีดจำกัด 4 GiB ต่อรอบ กรุณาเลือก batch น้อยลง",
    tooManyBatches: `เลือกได้สูงสุด ${MAX_BATCHES_PER_RUN} batch ต่อรอบ`,
    counting: "กำลังนับข้อมูลที่เลือก",
    runName: "ชื่อรอบฝึก",
    epochs: "จำนวน Epoch",
    start: "เริ่มฝึก Candidate",
    starting: "กำลังเริ่มงานฝึก",
    refresh: "รีเฟรช",
    runs: "ประวัติการฝึก",
    noRuns: "ยังไม่มีประวัติการฝึกโมเดล",
    current: "รายละเอียดงานฝึก",
    queued: "รอคิว",
    processing: "กำลังฝึก",
    complete: "ฝึกเสร็จแล้ว",
    failed: "ไม่สำเร็จ",
    base: "Baseline",
    candidate: "Candidate",
    device: "อุปกรณ์ประมวลผล",
    captures: "Capture ที่ให้ข้อมูลฝึก",
    capturesHint: (decoded: number) => `จาก Normal ที่ถอดรหัส ${decoded.toLocaleString("en-US")} ไฟล์`,
    sessions: "Session ที่ถูกสุ่มเลือก",
    sessionsHint: (normal: number, fault: number) => `Normal ${normal.toLocaleString("en-US")} · Fault กันไว้ ${fault.toLocaleString("en-US")}`,
    windows: "Training windows",
    windowsHint: "LSTM-AE / GRU",
    sampledOf: (ae: number, fore: number) => `สุ่มจาก ${ae.toLocaleString("en-US")} / ${fore.toLocaleString("en-US")} windows`,
    aeLoss: "LSTM-AE loss",
    foreLoss: "GRU loss",
    duration: "เวลาฝึก",
    epochUnit: "epoch",
    manualGate: "รอตรวจสอบและอนุมัติด้วยคน",
    selectNormal: "ต้องเลือก batch ที่มี Normal อย่างน้อย 1 ไฟล์",
    activeRun: "มีงานฝึกกำลังทำงานอยู่ กรุณารอให้เสร็จก่อนเริ่มรอบใหม่",
    failedLoad: "ไม่สามารถโหลดหรือเริ่มงานฝึกโมเดลได้",
    selected: "เลือกแล้ว",
    normalShort: "Normal",
    faultShort: "Fault",
  },
  en: {
    title: "Train Model",
    subtitle: "Create a new candidate from fully reviewed datasets by fine-tuning the LSTM-AE and GRU Forecaster from the current baseline.",
    guard: "Training never replaces the active model automatically. Every candidate requires reserved-data evaluation and manual approval before production use.",
    engineReady: "Training engine is ready",
    engineReadyBody: (epochs: number) => `PyTorch · CUDA or CPU · 1–${epochs} epochs`,
    engineMissing: "Training engine is unavailable on this PC",
    engineMissingBody: "Existing fault detection keeps working, but every item below must be present before a run can start.",
    configHint: "Set the locations in this file (JSON: python, aiProject, baselineArtifacts), then refresh.",
    configError: "The settings file cannot be read",
    requirementLabels: {} as Record<string, string>,
    requirementDetails: {} as Record<string, string>,
    sourceLabels: { command_line: "command line", environment: "environment", config_file: "engine.json", default: "default" },
    batches: "Select dataset batches",
    batchesHint: "Only batches with every Ground Truth label reviewed are shown.",
    noBatches: "No batch is ready. Import a dataset and complete its Ground Truth review first.",
    normal: "Normal for training",
    fault: "Fault reserved for evaluation",
    exclude: "Excluded from the run",
    countedOnce: "Captures shared between batches are counted once.",
    captureSize: "Total capture size",
    overLimit: "The selected captures exceed the 4 GiB per-run limit. Select fewer batches.",
    tooManyBatches: `Select at most ${MAX_BATCHES_PER_RUN} batches per run.`,
    counting: "Counting the selection",
    runName: "Training run name",
    epochs: "Epochs",
    start: "Train candidate",
    starting: "Starting training",
    refresh: "Refresh",
    runs: "Training history",
    noRuns: "No model-training runs yet.",
    current: "Training run details",
    queued: "Queued",
    processing: "Training",
    complete: "Complete",
    failed: "Failed",
    base: "Baseline",
    candidate: "Candidate",
    device: "Compute device",
    captures: "Captures contributing windows",
    capturesHint: (decoded: number) => `of ${decoded.toLocaleString("en-US")} Normal captures decoded`,
    sessions: "Sessions sampled",
    sessionsHint: (normal: number, fault: number) => `Normal ${normal.toLocaleString("en-US")} · Fault reserve ${fault.toLocaleString("en-US")}`,
    windows: "Training windows",
    windowsHint: "LSTM-AE / GRU",
    sampledOf: (ae: number, fore: number) => `sampled from ${ae.toLocaleString("en-US")} / ${fore.toLocaleString("en-US")} windows`,
    aeLoss: "LSTM-AE loss",
    foreLoss: "GRU loss",
    duration: "Training time",
    epochUnit: "epochs",
    manualGate: "Manual validation and approval required",
    selectNormal: "Select at least one batch containing a Normal capture.",
    activeRun: "A training run is active. Wait for it to finish before starting another.",
    failedLoad: "Unable to load or start model training.",
    selected: "selected",
    normalShort: "Normal",
    faultShort: "Fault",
  },
} as const;

type Lang = keyof typeof COPY;

const statusTone = (status: ModelTrainingJob["status"]) => ({
  queued: "tw-bg-amber-100 tw-text-amber-800",
  processing: "tw-bg-blue-100 tw-text-blue-800",
  complete: "tw-bg-emerald-100 tw-text-emerald-800",
  failed: "tw-bg-red-100 tw-text-red-800",
})[status];

const fmt = (value: number) => value.toLocaleString("en-US");
const fmtLoss = (value: number) => value.toLocaleString("en-US", { maximumSignificantDigits: 5 });
const fmtDuration = (seconds: number) => seconds < 60 ? `${seconds.toFixed(1)}s` : `${(seconds / 60).toFixed(1)} min`;
const fmtBytes = (bytes: number) => bytes < 1024 ** 3 ? `${(bytes / 1024 ** 2).toFixed(1)} MiB` : `${(bytes / 1024 ** 3).toFixed(2)} GiB`;

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-p-3">
      <div className="tw-text-[9px] tw-font-black tw-uppercase tw-tracking-wider tw-text-slate-400">{label}</div>
      <div className="ai-mono tw-mt-1 tw-text-base tw-font-black tw-text-slate-950">{value}</div>
      {hint && <div className="tw-mt-0.5 tw-text-[10px] tw-font-semibold tw-text-slate-500">{hint}</div>}
    </div>
  );
}

export default function TrainModelPanel({ lang }: { lang: Lang }) {
  const c = COPY[lang];
  const [summary, setSummary] = useState<ModelTrainingSummary | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<ModelTrainingPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [name, setName] = useState("Monthly candidate");
  const [epochs, setEpochs] = useState(3);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getModelTrainingSummary({ signal });
      setSummary(result);
      // keep the same array when nothing was dropped, or every refresh re-runs the preview
      setSelectedIds((current) => {
        const kept = current.filter((id) => result.eligibleImports.some((item) => item.importId === id));
        return kept.length === current.length ? current : kept;
      });
      setSelectedJobId((current) => result.jobs.some((job) => job.jobId === current) ? current : result.jobs[0]?.jobId ?? "");
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(caught instanceof Error ? caught.message : c.failedLoad);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [c.failedLoad]);

  useEffect(() => {
    const controller = new AbortController();
    void loadSummary(controller.signal);
    return () => controller.abort();
  }, [loadSummary]);

  // The server counts the selection with each capture once; summing the
  // per-batch counts would overstate batches that share captures.
  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(false);
    if (!selectedIds.length || selectedIds.length > MAX_BATCHES_PER_RUN) return undefined;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setPreviewLoading(true);
      previewModelTraining(selectedIds, { signal: controller.signal })
        .then((result) => setPreview(result))
        .catch((caught) => {
          if (caught instanceof DOMException && caught.name === "AbortError") return;
          setPreviewError(caught instanceof Error ? caught.message : c.failedLoad);
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [c.failedLoad, selectedIds]);

  const selectedJob = useMemo(
    () => summary?.jobs.find((job) => job.jobId === selectedJobId) ?? summary?.jobs[0] ?? null,
    [selectedJobId, summary],
  );
  const activeJobId = useMemo(
    () => summary?.jobs.find((job) => job.status === "queued" || job.status === "processing")?.jobId ?? null,
    [summary],
  );

  useEffect(() => {
    if (!activeJobId) return undefined;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getModelTrainingJob(activeJobId).then((job) => {
        if (cancelled) return;
        setSummary((current) => current ? {
          ...current,
          jobs: current.jobs.some((item) => item.jobId === job.jobId)
            ? current.jobs.map((item) => item.jobId === job.jobId ? job : item)
            : [job, ...current.jobs],
        } : current);
      }).catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : c.failedLoad);
      });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeJobId, c.failedLoad]);

  const toggleImport = (importId: string) => {
    setSelectedIds((current) => current.includes(importId)
      ? current.filter((id) => id !== importId)
      : [...current, importId]);
  };

  const tooManyBatches = selectedIds.length > MAX_BATCHES_PER_RUN;
  const previewCurrent = preview !== null && preview.importIds.length === selectedIds.length
    && preview.importIds.every((id) => selectedIds.includes(id));
  const canStart = Boolean(
    summary?.engine.available
    && selectedIds.length
    && !tooManyBatches
    && previewCurrent
    && preview?.hasNormal
    && preview?.withinLimit
    && !activeJobId
    && name.trim()
    && !starting,
  );

  const startTraining = async () => {
    if (!canStart) return;
    setStarting(true);
    setError(null);
    try {
      const job = await createModelTrainingJob({ name: name.trim(), importIds: selectedIds, epochs });
      setSummary((current) => current ? { ...current, jobs: [job, ...current.jobs] } : current);
      setSelectedJobId(job.jobId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : c.failedLoad);
    } finally {
      setStarting(false);
    }
  };

  const statusLabel = (status: ModelTrainingJob["status"]) => c[status];
  const engine = summary?.engine;
  const training = selectedJob?.candidate?.training;

  return (
    <div className="fd-panel tw-overflow-hidden tw-border-t-[3px] tw-border-t-violet-600" data-testid="fd-train-model-panel">
      <div className="tw-border-b tw-border-slate-100 tw-bg-gradient-to-r tw-from-violet-50/80 tw-via-white tw-to-blue-50/60 tw-p-4 sm:tw-p-6">
        <div className="tw-flex tw-flex-col tw-gap-4 lg:tw-flex-row lg:tw-items-start lg:tw-justify-between">
          <div className="tw-max-w-3xl">
            <div className="tw-flex tw-items-center tw-gap-3">
              <span className="tw-flex tw-h-11 tw-w-11 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-violet-600 tw-text-white tw-shadow-lg tw-shadow-violet-600/20"><BrainCircuit className="tw-h-5 tw-w-5" /></span>
              <div>
                <h2 className="tw-text-lg tw-font-black tw-text-slate-950 sm:tw-text-xl">{c.title}</h2>
                <p className="tw-mt-0.5 tw-text-[12px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.subtitle}</p>
              </div>
            </div>
            <div className="tw-mt-4 tw-flex tw-items-start tw-gap-2 tw-rounded-xl tw-bg-white/80 tw-p-3 tw-text-[11px] tw-font-semibold tw-leading-5 tw-text-slate-600 tw-ring-1 tw-ring-violet-100">
              <ShieldCheck className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0 tw-text-violet-700" /> {c.guard}
            </div>
          </div>
          <button type="button" onClick={() => void loadSummary()} disabled={loading} className="tw-inline-flex tw-min-h-10 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-text-[11px] tw-font-black tw-text-slate-700 hover:tw-bg-slate-50 disabled:tw-opacity-60">
            <RefreshCw className={`tw-h-3.5 tw-w-3.5 ${loading ? "tw-animate-spin" : ""}`} /> {c.refresh}
          </button>
        </div>
      </div>

      <div className="tw-bg-slate-50/70 tw-p-4 sm:tw-p-6">
        {engine && (
          <div className={`tw-rounded-2xl tw-border tw-p-4 ${engine.available ? "tw-border-emerald-200 tw-bg-emerald-50" : "tw-border-amber-200 tw-bg-amber-50"}`}>
            <div className="tw-flex tw-items-start tw-gap-3">
              {engine.available ? <CheckCircle2 className="tw-h-5 tw-w-5 tw-flex-shrink-0 tw-text-emerald-700" /> : <AlertTriangle className="tw-h-5 tw-w-5 tw-flex-shrink-0 tw-text-amber-700" />}
              <div className="tw-min-w-0 tw-flex-1">
                <div className={`tw-text-[12px] tw-font-black ${engine.available ? "tw-text-emerald-950" : "tw-text-amber-950"}`}>{engine.available ? c.engineReady : c.engineMissing}</div>
                <div className={`tw-mt-1 tw-text-[10px] tw-font-semibold tw-leading-4 ${engine.available ? "tw-text-emerald-700" : "tw-text-amber-700"}`}>
                  {engine.available ? c.engineReadyBody(engine.maxEpochs) : c.engineMissingBody}
                </div>
              </div>
            </div>
            {!engine.available && (
              <div className="tw-mt-3 tw-space-y-1.5 tw-pl-8">
                {engine.configError && <p className="tw-text-[10px] tw-font-bold tw-text-red-700">{c.configError}: {engine.configError}</p>}
                {engine.requirements.length > 0 ? (
                  <ul className="tw-space-y-1.5">
                    {engine.requirements.map((item) => (
                      <li key={item.id} className="tw-flex tw-items-start tw-gap-2 tw-text-[10px] tw-leading-4">
                        {item.ok
                          ? <CheckCircle2 className="tw-mt-0.5 tw-h-3.5 tw-w-3.5 tw-flex-shrink-0 tw-text-emerald-600" aria-hidden="true" />
                          : <XCircle className="tw-mt-0.5 tw-h-3.5 tw-w-3.5 tw-flex-shrink-0 tw-text-red-600" aria-hidden="true" />}
                        <span className="tw-min-w-0">
                          <span className={`tw-font-black ${item.ok ? "tw-text-slate-700" : "tw-text-red-800"}`}>{c.requirementLabels[item.id] ?? item.label}</span>
                          {engine.configSource && item.id in engine.configSource && (
                            <span className="tw-ml-1 tw-font-semibold tw-text-slate-400">({c.sourceLabels[engine.configSource[item.id as keyof typeof engine.configSource]]})</span>
                          )}
                          {item.path && <span className="ai-mono tw-block tw-break-all tw-font-medium tw-text-slate-500">{item.path}</span>}
                          {!item.ok && item.detail && <span className="tw-block tw-font-semibold tw-text-amber-800">{c.requirementDetails[item.detail] ?? item.detail}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <ul className="tw-list-disc tw-pl-4 tw-text-[10px] tw-font-medium tw-text-amber-800">
                    {engine.missing.map((item) => <li key={item} className="tw-break-all">{item}</li>)}
                  </ul>
                )}
                {engine.configFile && (
                  <div className="tw-mt-2 tw-flex tw-items-start tw-gap-2 tw-rounded-lg tw-bg-white/70 tw-p-2.5 tw-text-[10px] tw-font-semibold tw-leading-4 tw-text-slate-600 tw-ring-1 tw-ring-amber-100">
                    <FileCog className="tw-mt-0.5 tw-h-3.5 tw-w-3.5 tw-flex-shrink-0 tw-text-amber-700" aria-hidden="true" />
                    <span className="tw-min-w-0">{c.configHint}<span className="ai-mono tw-block tw-break-all tw-text-slate-800">{engine.configFile}</span></span>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {error && <div role="alert" className="tw-mt-4 tw-rounded-xl tw-bg-red-50 tw-p-3 tw-text-[11px] tw-font-semibold tw-text-red-800 tw-ring-1 tw-ring-red-100">{error}</div>}

        <div className="tw-mt-4 tw-grid tw-gap-4 xl:tw-grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
          <section className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 sm:tw-p-5">
            <div className="tw-flex tw-items-start tw-justify-between tw-gap-3">
              <div>
                <h3 className="tw-flex tw-items-center tw-gap-2 tw-text-sm tw-font-black tw-text-slate-950"><Database className="tw-h-4 tw-w-4 tw-text-violet-700" /> {c.batches}</h3>
                <p className="tw-mt-1 tw-text-[10px] tw-font-semibold tw-text-slate-500">{c.batchesHint}</p>
              </div>
              <span className="tw-rounded-full tw-bg-violet-100 tw-px-2.5 tw-py-1 tw-text-[9px] tw-font-black tw-text-violet-800">{selectedIds.length} {c.selected}</span>
            </div>

            {!summary?.eligibleImports.length ? (
              <div className="tw-mt-4 tw-rounded-xl tw-border tw-border-dashed tw-border-slate-200 tw-p-8 tw-text-center tw-text-[11px] tw-font-semibold tw-leading-5 tw-text-slate-400">{loading ? <LoaderCircle className="tw-mx-auto tw-h-5 tw-w-5 tw-animate-spin" /> : c.noBatches}</div>
            ) : (
              <div className="tw-mt-4 tw-max-h-[420px] tw-space-y-2 tw-overflow-y-auto tw-pr-1">
                {summary.eligibleImports.map((item) => {
                  const checked = selectedIds.includes(item.importId);
                  return (
                    <label key={item.importId} className={`tw-flex tw-cursor-pointer tw-items-start tw-gap-3 tw-rounded-xl tw-border tw-p-3 tw-transition ${checked ? "tw-border-violet-300 tw-bg-violet-50/70" : "tw-border-slate-100 tw-bg-slate-50 hover:tw-border-slate-200"}`}>
                      <input type="checkbox" checked={checked} onChange={() => toggleImport(item.importId)} className="tw-mt-0.5 tw-h-4 tw-w-4 tw-rounded tw-border-slate-300 tw-text-violet-600 focus:tw-ring-violet-500" />
                      <span className="tw-min-w-0 tw-flex-1">
                        <span className="tw-block tw-truncate tw-text-[12px] tw-font-black tw-text-slate-900" title={item.name}>{item.name}</span>
                        <span className="tw-mt-1 tw-flex tw-flex-wrap tw-gap-x-3 tw-gap-y-1 tw-text-[10px] tw-font-bold">
                          <span className="tw-text-emerald-700">{item.normalFileCount} Normal</span>
                          <span className="tw-text-red-700">{item.faultFileCount} Fault</span>
                          <span className="tw-text-amber-700">{item.excludedFileCount} Exclude</span>
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}

            <div className="tw-mt-4 tw-grid tw-grid-cols-3 tw-gap-2">
              <Metric label={c.normal} value={previewCurrent ? fmt(preview.normalFileCount) : "—"} />
              <Metric label={c.fault} value={previewCurrent ? fmt(preview.faultFileCount) : "—"} />
              <Metric label={c.exclude} value={previewCurrent ? fmt(preview.excludedFileCount) : "—"} />
            </div>
            <p className="tw-mt-2 tw-flex tw-items-center tw-gap-1.5 tw-text-[10px] tw-font-semibold tw-text-slate-500">
              {previewLoading && <LoaderCircle className="tw-h-3 tw-w-3 tw-animate-spin" aria-hidden="true" />}
              {previewLoading ? c.counting : c.countedOnce}
              {previewCurrent && <span className="ai-mono tw-ml-auto">{c.captureSize}: {fmtBytes(preview.captureBytes)}</span>}
            </p>

            <div className="tw-mt-4 tw-grid tw-gap-3 sm:tw-grid-cols-[minmax(0,1fr)_120px]">
              <label className="tw-text-[10px] tw-font-black tw-uppercase tw-tracking-wider tw-text-slate-500">
                {c.runName}
                <input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} className="tw-mt-1.5 tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-text-[12px] tw-font-semibold tw-normal-case tw-tracking-normal tw-text-slate-900 focus:tw-border-violet-400 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-violet-100" />
              </label>
              <label className="tw-text-[10px] tw-font-black tw-uppercase tw-tracking-wider tw-text-slate-500">
                {c.epochs}
                <input type="number" min={1} max={engine?.maxEpochs ?? 8} value={epochs} onChange={(event) => setEpochs(Math.max(1, Math.min(engine?.maxEpochs ?? 8, Number(event.target.value) || 1)))} className="tw-mt-1.5 tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-text-[12px] tw-font-black tw-text-slate-900 focus:tw-border-violet-400 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-violet-100" />
              </label>
            </div>
            {tooManyBatches && <p className="tw-mt-2 tw-text-[10px] tw-font-bold tw-text-amber-700">{c.tooManyBatches}</p>}
            {previewError && <p role="alert" className="tw-mt-2 tw-text-[10px] tw-font-bold tw-text-red-700">{previewError}</p>}
            {!activeJobId && previewCurrent && !preview.hasNormal && <p className="tw-mt-2 tw-text-[10px] tw-font-bold tw-text-amber-700">{c.selectNormal}</p>}
            {previewCurrent && !preview.withinLimit && <p className="tw-mt-2 tw-text-[10px] tw-font-bold tw-text-amber-700">{c.overLimit}</p>}
            {activeJobId && <p className="tw-mt-2 tw-text-[10px] tw-font-bold tw-text-blue-700">{c.activeRun}</p>}
            <button type="button" disabled={!canStart} onClick={() => void startTraining()} className="tw-mt-4 tw-inline-flex tw-min-h-12 tw-w-full tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-violet-700 tw-px-4 tw-text-[12px] tw-font-black tw-text-white tw-shadow-lg tw-shadow-violet-700/15 hover:tw-bg-violet-800 disabled:tw-cursor-not-allowed disabled:tw-bg-slate-300 disabled:tw-shadow-none">
              {starting ? <LoaderCircle className="tw-h-4 tw-w-4 tw-animate-spin" /> : <Play className="tw-h-4 tw-w-4" />} {starting ? c.starting : c.start}
            </button>
          </section>

          <section className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 sm:tw-p-5">
            <h3 className="tw-flex tw-items-center tw-gap-2 tw-text-sm tw-font-black tw-text-slate-950"><Gauge className="tw-h-4 tw-w-4 tw-text-blue-700" /> {c.current}</h3>
            {!selectedJob ? (
              <div className="tw-py-12 tw-text-center tw-text-[11px] tw-font-semibold tw-text-slate-400">{c.noRuns}</div>
            ) : (
              <div className="tw-mt-4">
                <div className="tw-flex tw-items-start tw-justify-between tw-gap-3">
                  <div className="tw-min-w-0">
                    <div className="tw-truncate tw-text-[13px] tw-font-black tw-text-slate-950">{selectedJob.name}</div>
                    <div className="ai-mono tw-mt-1 tw-text-[9px] tw-font-semibold tw-text-slate-400">{selectedJob.jobId.slice(0, 12)}</div>
                  </div>
                  <span className={`tw-flex-shrink-0 tw-rounded-full tw-px-2.5 tw-py-1 tw-text-[9px] tw-font-black ${statusTone(selectedJob.status)}`}>{statusLabel(selectedJob.status)}</span>
                </div>
                <div className="tw-mt-4 tw-h-2.5 tw-overflow-hidden tw-rounded-full tw-bg-slate-100">
                  <div className={`tw-h-full tw-rounded-full tw-transition-all ${selectedJob.status === "failed" ? "tw-bg-red-500" : "tw-bg-violet-600"}`} style={{ width: `${selectedJob.progress}%` }} />
                </div>
                <div className="tw-mt-2 tw-flex tw-items-start tw-justify-between tw-gap-3 tw-text-[10px] tw-font-semibold tw-text-slate-500"><span>{selectedJob.detail}</span><span className="ai-mono tw-flex-shrink-0">{Math.round(selectedJob.progress)}%</span></div>
                {selectedJob.error && <div className="tw-mt-3 tw-max-h-40 tw-overflow-y-auto tw-whitespace-pre-wrap tw-rounded-xl tw-bg-red-50 tw-p-3 tw-text-[10px] tw-font-semibold tw-leading-4 tw-text-red-800">{selectedJob.error}</div>}
                <div className="tw-mt-4 tw-grid tw-grid-cols-2 tw-gap-2">
                  <Metric label={c.base} value={selectedJob.baseArtifactVersion.slice(0, 12)} />
                  <Metric label={c.candidate} value={selectedJob.candidate?.artifactVersion.slice(0, 12) ?? "—"} />
                  <Metric label={c.normal} value={fmt(selectedJob.dataset.normalFileCount)} />
                  <Metric label={c.fault} value={fmt(selectedJob.dataset.faultFileCount)} />
                </div>
                {training && (
                  <>
                    <div className="tw-mt-3 tw-grid tw-grid-cols-2 tw-gap-2">
                      <Metric label={c.device} value={training.device.toUpperCase()} hint={training.deviceName} />
                      <Metric label={c.duration} value={fmtDuration(training.durationSeconds)} hint={`${training.epochs} ${c.epochUnit}`} />
                      <Metric
                        label={c.captures}
                        value={training.contributingCaptures !== undefined ? fmt(training.contributingCaptures) : fmt(training.normalCaptures)}
                        hint={c.capturesHint(training.normalCaptures)}
                      />
                      <Metric
                        label={c.sessions}
                        value={training.contributingSessions !== undefined ? fmt(training.contributingSessions) : "—"}
                        hint={c.sessionsHint(training.normalSessions, training.faultReserveSessions)}
                      />
                      <Metric
                        label={c.windows}
                        value={`${fmt(training.aeWindows)} / ${fmt(training.forecasterWindows)}`}
                        hint={training.aeWindowsAvailable !== undefined && training.forecasterWindowsAvailable !== undefined
                          ? `${c.windowsHint} · ${c.sampledOf(training.aeWindowsAvailable, training.forecasterWindowsAvailable)}`
                          : c.windowsHint}
                      />
                      <Metric label={c.aeLoss} value={`${fmtLoss(training.aeLossInitial)} → ${fmtLoss(training.aeLossFinal)}`} />
                      <Metric label={c.foreLoss} value={`${fmtLoss(training.forecasterLossInitial)} → ${fmtLoss(training.forecasterLossFinal)}`} />
                    </div>
                    <div className="tw-mt-3 tw-flex tw-items-center tw-gap-2 tw-rounded-xl tw-bg-amber-50 tw-p-3 tw-text-[10px] tw-font-black tw-text-amber-800 tw-ring-1 tw-ring-amber-100"><FlaskConical className="tw-h-4 tw-w-4" /> {c.manualGate}</div>
                  </>
                )}
              </div>
            )}
          </section>
        </div>

        <section className="tw-mt-4 tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 sm:tw-p-5">
          <h3 className="tw-flex tw-items-center tw-gap-2 tw-text-sm tw-font-black tw-text-slate-950"><Cpu className="tw-h-4 tw-w-4 tw-text-slate-600" /> {c.runs}</h3>
          {!summary?.jobs.length ? <div className="tw-py-6 tw-text-center tw-text-[11px] tw-font-semibold tw-text-slate-400">{c.noRuns}</div> : (
            <div className="tw-mt-3 tw-grid tw-gap-2 md:tw-grid-cols-2 xl:tw-grid-cols-3">
              {summary.jobs.map((job) => (
                <button key={job.jobId} type="button" aria-pressed={selectedJob?.jobId === job.jobId} onClick={() => setSelectedJobId(job.jobId)} className={`tw-rounded-xl tw-border tw-p-3 tw-text-left tw-transition ${selectedJob?.jobId === job.jobId ? "tw-border-violet-300 tw-bg-violet-50" : "tw-border-slate-100 tw-bg-slate-50 hover:tw-border-slate-200"}`}>
                  <div className="tw-flex tw-items-start tw-justify-between tw-gap-2"><span className="tw-truncate tw-text-[11px] tw-font-black tw-text-slate-900">{job.name}</span><span className={`tw-flex-shrink-0 tw-rounded-full tw-px-2 tw-py-0.5 tw-text-[8px] tw-font-black ${statusTone(job.status)}`}>{statusLabel(job.status)}</span></div>
                  <div className="tw-mt-1.5 tw-text-[9px] tw-font-semibold tw-text-slate-500">{job.dataset.normalFileCount} {c.normalShort} · {job.dataset.faultFileCount} {c.faultShort} · {job.config.epochs} {c.epochUnit}</div>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
