"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  Activity,
  AlertTriangle,
  BookOpenCheck,
  BrainCircuit,
  ChevronRight,
  CircleDashed,
  Database,
  LoaderCircle,
  LayoutDashboard,
  MapPin,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
  Zap,
} from "lucide-react";
import useLanguage from "@/utils/useLanguage";
import {
  MAX_PCAP_UPLOAD_BYTES,
  createPcapAnalysisJob,
  getDesktopRuntimeStatus,
  getFaultDetectionSummary,
  getPcapAnalysisJob,
  isDesktopFaultDetectionApi,
  type DesktopRuntimeStatus,
  type PcapAnalysisJob,
} from "./api";
import {
  snapshotDateLocale,
  type BundledBenchmark,
  type StationAnalysis,
  allStationRows,
  heldOutStationTotals,
  sortStationRows,
  stationRowTotals,
  stationSplitOf,
  type StationSortKey,
  type StationSplit,
} from "./data";
import { supportedFaultFamilies } from "./fault-catalog";
import FaultExplanationPanel, {
  FaultExplanationInline,
  ObservedStopAttribution,
} from "./fault-explanation";
import { useEditionTabTitle } from "./edition-identity";
import FaultGlossaryDialog from "./fault-glossary-dialog";
import ResearchDashboard from "./research-dashboard";
import StationDetailDialog from "./station-detail-dialog";
import "../ai-theme.css";
import "./fault-detection.css";

const COPY = {
  th: {
    eyebrow: "AI · CHARGER FAULT INTELLIGENCE",
    title: "แดชบอร์ดตรวจจับความผิดปกติตู้ชาร์จ",
    subtitle: "สำรวจผล benchmark ที่ตรวจสอบแล้วทั้ง fleet เปรียบเทียบกฎ ISO 15118 และวิเคราะห์ PCAP ใหม่ด้วย Agentic AI ในพื้นที่เดียวกัน",
    desktopSubtitle: "สำรวจผล benchmark ที่ตรวจสอบแล้วทั้ง fleet เปรียบเทียบกฎ ISO 15118 และเจาะลึกสัดส่วน Fault ของทุกสถานีในโปรแกรมเดียว",
    modelBadge: "VERIFIED RESEARCH",
    formatBadge: "ISO 15118-2 / -3",
    // Hero counts come from the bundled benchmark (see heroStats); the labels
    // stay English in both languages, as the original design had them.
    workflowSessions: "Held-out sessions",
    workflowModels: "AI architectures",
    workflowFamilies: "Held-out fault families",
    overviewTab: "ภาพรวม",
    stationsTab: "ผลรายสถานี",
    pcapTab: "วิเคราะห์ PCAP",
    workspaceTitle: "อัปโหลดและวิเคราะห์ไฟล์",
    workspaceSub: "ระบบประมวลผลจากข้อมูลในไฟล์โดยตรง โดยไม่ใช้ ground truth และไม่แก้ไขผล benchmark เดิม",
    dropTitle: "ลากไฟล์มาวาง หรือคลิกเพื่อเลือก",
    dropHint: "รองรับ .pcap และ .pcapng · สูงสุด 256 MiB",
    selectedFile: "ไฟล์ที่เลือก",
    analyze: "เริ่มวิเคราะห์ด้วย AI",
    remove: "นำไฟล์ออก",
    emptyTitle: "เลือก PCAP เพื่อเริ่มวิเคราะห์",
    emptyBody: "ผลวิเคราะห์จะแสดง fault, confidence, หลักฐาน และรายละเอียดแต่ละ charging session ที่นี่",
    queued: "อยู่ในคิวประมวลผล",
    processing: "AI กำลังประมวลผล",
    failed: "ประมวลผลไม่สำเร็จ",
    resultTitle: "ผลการวิเคราะห์",
    faultDetected: "ตรวจพบความผิดปกติ",
    noFaultDetected: "ไม่พบสัญญาณ fault ในข้อมูลที่เห็น",
    inconclusive: "หลักฐานไม่เพียงพอ",
    confidence: "ความมั่นใจ",
    faultType: "ประเภท fault",
    modelUsed: "โมเดลที่ใช้",
    evidence: "หลักฐาน / เหตุผล",
    relevantEvents: "Relevant events",
    sessions: "Charging sessions",
    completeSessions: "Complete sessions",
    alertedSessions: "Alerted sessions",
    sessionDetails: "รายละเอียดแต่ละ session",
    session: "Session",
    events: "Events",
    duration: "Duration",
    dialog: "Dialog",
    alert: "AI alert",
    stopAttribution: "ผู้เริ่มหยุด",
    graceful: "Complete",
    partial: "Partial",
    noAlert: "No alert",
    warnings: "ข้อควรทราบ",
    runAnother: "วิเคราะห์ไฟล์อื่น",
    invalidExtension: "กรุณาเลือกไฟล์ .pcap หรือ .pcapng",
    emptyFile: "ไฟล์นี้ว่างเปล่า",
    fileTooLarge: "ไฟล์มีขนาดเกิน 256 MiB",
    uploadFailed: "ไม่สามารถส่งไฟล์ไปวิเคราะห์ได้",
    stationTitle: "ผลวิเคราะห์ PCAP แยกตามสถานี",
    stationSub: (sessions: string | null) =>
      sessions
        ? `ผล Agentic AI จาก held-out test ${sessions} sessions แสดงแยกทุกสถานี โดยใช้เกณฑ์เดียวกับ benchmark`
        : "ผล Agentic AI จาก held-out test แสดงแยกทุกสถานี โดยใช้เกณฑ์เดียวกับ benchmark",
    stationNote: "กดที่สถานีเพื่อดูผลแยก Connector และ Fault · เป็นข้อมูล PCAP ทดสอบ ไม่ใช่สถานะสุขภาพแบบเรียลไทม์",
    stationsAnalyzed: "สถานีที่วิเคราะห์",
    testSessions: "Test sessions",
    knownFaults: "Known fault sessions",
    aiAlerts: "AI alerts",
    searchStation: "ค้นหารหัสหรือชื่อสถานี",
    sortStation: "เรียงตามชื่อสถานี",
    sortFaultRate: "Fault rate สูงสุด",
    sortRecall: "Recall ต่ำสุด",
    sortFar: "False alarm สูงสุด",
    station: "สถานี",
    stationSessions: "Sessions",
    faultSessions: "Fault sessions",
    detected: "ตรวจพบตรงเวลา",
    lateMissed: "ช้า / พลาด",
    falseAlarms: "False alarms",
    topFault: "Fault หลัก",
    score: "Score",
    viewStationDetails: "ดูรายละเอียดสถานี",
    noStations: "ไม่พบสถานีที่ตรงกับคำค้น",
    stationNoteSplit: "กดที่สถานีเพื่อดูผลแยก Connector และ Fault · แต่ละสถานีมีป้ายบอกว่าเป็น held-out หรือชุดฝึก (in-sample) · ไม่ใช่สถานะสุขภาพแบบเรียลไทม์",
    otherSplitMatches: (count: number) => `พบ ${count} สถานีที่ตรงกับคำค้นในชุดข้อมูลอื่น · แสดงทั้งหมด`,
    loadingStations: "กำลังโหลดผลรายสถานี",
    stationLoadFailed: "โหลดผลวิเคราะห์รายสถานีไม่สำเร็จ",
    retry: "ลองใหม่",
    updatedAt: "ข้อมูลล่าสุด",
    faultGuide: "คู่มือ Fault",
    openFaultGuide: (count: number) => `เปิดคู่มือ Fault ทั้ง ${count} ประเภท`,
    visibleStations: "สถานีที่แสดง",
    splitLabel: "ชุดข้อมูล",
    splitHeldOut: "Held-out (ประเมินจริง)",
    splitTrain: "ชุดฝึก (in-sample)",
    splitAll: "ทั้งหมด",
    badgeHeldOut: "HELD-OUT",
    badgeTrain: "ชุดฝึก · IN-SAMPLE",
    trainBanner:
      "สถานีชุดฝึก: โมเดลเรียนรู้จาก session เหล่านี้มาแล้ว คะแนนและ Recall จึงสูงเกินจริงและไม่ใช่ผลประเมิน ใช้ดูสัดส่วน Fault ของสถานีเท่านั้น",
    excludesTrain: (stations: number, sessions: string) =>
      `ตัวเลขด้านบนนับเฉพาะสถานี held-out · ไม่รวม ${stations} สถานีชุดฝึก (${sessions} sessions, in-sample)`,
    stationSubAll: (total: number, heldOut: number, heldOutSessions: string, train: number) =>
      `ผล Agentic AI รายสถานีครบ ${total} สถานี: ${heldOut} สถานี held-out (${heldOutSessions} sessions, เกณฑ์เดียวกับ benchmark) และ ${train} สถานีชุดฝึก (in-sample)`,
    stationSubTrain: (train: number, sessions: string) =>
      `ผล Agentic AI ของ ${train} สถานีชุดฝึก (${sessions} sessions, in-sample) · ไม่ใช่ผลประเมินโมเดล`,
    allSessions: "Sessions ทั้งหมด",
    trainSessions: "Sessions ชุดฝึก",
    includesTrain: (heldOut: number, heldOutSessions: string, train: number, trainSessions: string) =>
      `ตัวเลขด้านบนรวม ${heldOut} สถานี held-out (${heldOutSessions} sessions) และ ${train} สถานีชุดฝึก (${trainSessions} sessions, in-sample) · ผลประเมินโมเดลและ leaderboard นับเฉพาะ held-out`,
    trainOnly: (stations: number, sessions: string) =>
      `ตัวเลขด้านบนนับเฉพาะ ${stations} สถานีชุดฝึก (${sessions} sessions, in-sample) · ไม่ใช่ผลประเมินโมเดล`,
    editionLabel: "รุ่นโปรแกรม",
    modelLabel: "โมเดล",
    dataAsOfLabel: "ข้อมูล benchmark ณ",
    policyLabel: "กฎมาตรฐาน",
    policyIso: "ISO 15118-2 + SLAC (ISO 15118-3)",
    policyOther: "นโยบายตรวจจับ",
  },
  en: {
    eyebrow: "AI · CHARGER FAULT INTELLIGENCE",
    title: "EV charger fault-detection dashboard",
    subtitle: "Explore the verified fleet benchmark, compare ISO 15118 rule profiles, and analyze a new PCAP with Agentic AI from one workspace.",
    desktopSubtitle: "Explore the verified fleet benchmark, compare ISO 15118 rule profiles, and inspect fault distributions for every station in one desktop app.",
    modelBadge: "VERIFIED RESEARCH",
    formatBadge: "ISO 15118-2 / -3",
    workflowSessions: "Held-out sessions",
    workflowModels: "AI architectures",
    workflowFamilies: "Held-out fault families",
    overviewTab: "Overview",
    stationsTab: "Stations",
    pcapTab: "Analyze PCAP",
    workspaceTitle: "Upload and analyze a capture",
    workspaceSub: "The file is analyzed directly without ground truth and does not alter the existing benchmark results.",
    dropTitle: "Drop a file here, or click to browse",
    dropHint: "Supports .pcap and .pcapng · up to 256 MiB",
    selectedFile: "Selected file",
    analyze: "Run AI analysis",
    remove: "Remove file",
    emptyTitle: "Choose a PCAP to start an analysis",
    emptyBody: "The detected fault, confidence, evidence, and charging-session details will appear here.",
    queued: "Queued for processing",
    processing: "AI analysis in progress",
    failed: "Analysis failed",
    resultTitle: "Analysis result",
    faultDetected: "Fault signal detected",
    noFaultDetected: "No fault alert in the observed evidence",
    inconclusive: "Evidence is inconclusive",
    confidence: "Confidence",
    faultType: "Fault family",
    modelUsed: "Model used",
    evidence: "Evidence / reason",
    relevantEvents: "Relevant events",
    sessions: "Charging sessions",
    completeSessions: "Complete sessions",
    alertedSessions: "Alerted sessions",
    sessionDetails: "Session details",
    session: "Session",
    events: "Events",
    duration: "Duration",
    dialog: "Dialog",
    alert: "AI alert",
    stopAttribution: "Stop initiator",
    graceful: "Complete",
    partial: "Partial",
    noAlert: "No alert",
    warnings: "Important notes",
    runAnother: "Analyze another file",
    invalidExtension: "Please choose a .pcap or .pcapng file.",
    emptyFile: "The selected file is empty.",
    fileTooLarge: "The selected file exceeds 256 MiB.",
    uploadFailed: "The capture could not be submitted for analysis.",
    stationTitle: "PCAP analysis by station",
    stationSub: (sessions: string | null) =>
      sessions
        ? `Agentic AI results from ${sessions} held-out sessions, broken down by station using the benchmark's exact scoring rules.`
        : "Agentic AI results on the held-out sessions, broken down by station using the benchmark's exact scoring rules.",
    stationNote: "Select a station for connector and fault details · These are held-out PCAP results, not real-time station health.",
    stationsAnalyzed: "Stations analyzed",
    testSessions: "Test sessions",
    knownFaults: "Known fault sessions",
    aiAlerts: "AI alerts",
    searchStation: "Search station code or name",
    sortStation: "Sort by station",
    sortFaultRate: "Highest fault rate",
    sortRecall: "Lowest recall",
    sortFar: "Highest false alarms",
    station: "Station",
    stationSessions: "Sessions",
    faultSessions: "Fault sessions",
    detected: "On-time detections",
    lateMissed: "Late / missed",
    falseAlarms: "False alarms",
    topFault: "Top fault",
    score: "Score",
    viewStationDetails: "View station details",
    noStations: "No stations match the search.",
    stationNoteSplit: "Select a station for connector and fault details · Each station is labelled held-out or training (in-sample) · Not real-time station health.",
    otherSplitMatches: (count: number) => `${count} matching station${count === 1 ? "" : "s"} in the other data split · show all`,
    loadingStations: "Loading station results",
    stationLoadFailed: "Unable to load station analysis",
    retry: "Retry",
    updatedAt: "Updated",
    faultGuide: "Fault guide",
    openFaultGuide: (count: number) => `Open the guide to all ${count} fault families`,
    visibleStations: "Stations shown",
    splitLabel: "Data split",
    splitHeldOut: "Held-out (evaluation)",
    splitTrain: "Training (in-sample)",
    splitAll: "All",
    badgeHeldOut: "HELD-OUT",
    badgeTrain: "TRAIN · IN-SAMPLE",
    trainBanner:
      "Training stations: the models learned from these sessions, so score and recall are optimistic and are not an evaluation. Use them for the station's fault mix only.",
    excludesTrain: (stations: number, sessions: string) =>
      `The figures above count held-out stations only · ${stations} training station${stations === 1 ? "" : "s"} (${sessions} sessions, in-sample) ${stations === 1 ? "is" : "are"} excluded`,
    stationSubAll: (total: number, heldOut: number, heldOutSessions: string, train: number) =>
      `Agentic AI results for all ${total} stations: ${heldOut} held-out station${heldOut === 1 ? "" : "s"} (${heldOutSessions} sessions, the benchmark's scoring rules) and ${train} training station${train === 1 ? "" : "s"} (in-sample).`,
    stationSubTrain: (train: number, sessions: string) =>
      `Agentic AI results for the ${train} training station${train === 1 ? "" : "s"} (${sessions} sessions, in-sample) · not a model evaluation.`,
    allSessions: "All sessions",
    trainSessions: "Training sessions",
    includesTrain: (heldOut: number, heldOutSessions: string, train: number, trainSessions: string) =>
      `The figures above include ${heldOut} held-out station${heldOut === 1 ? "" : "s"} (${heldOutSessions} sessions) and ${train} training station${train === 1 ? "" : "s"} (${trainSessions} sessions, in-sample) · model evaluation and the leaderboard count held-out stations only`,
    trainOnly: (stations: number, sessions: string) =>
      `The figures above count the ${stations} training station${stations === 1 ? "" : "s"} only (${sessions} sessions, in-sample) · not a model evaluation`,
    editionLabel: "Edition",
    modelLabel: "Model",
    dataAsOfLabel: "Benchmark data as of",
    policyLabel: "Standard rules",
    policyIso: "ISO 15118-2 + SLAC (ISO 15118-3)",
    policyOther: "Detection policy",
  },
} as const;

type StationSort = StationSortKey;
type StationSplitFilter = StationSplit | "all";

/** Held-out / in-sample marker next to a station name. */
function SplitBadge({ split, heldOut, train }: { split: StationSplit; heldOut: string; train: string }) {
  return (
    <span
      className={`tw-inline-flex tw-flex-shrink-0 tw-items-center tw-rounded-md tw-px-1.5 tw-py-0.5 tw-text-[9px] tw-font-extrabold tw-tracking-wider tw-ring-1 ${
        split === "train" ? "tw-bg-amber-50 tw-text-amber-800 tw-ring-amber-200" : "tw-bg-emerald-50 tw-text-emerald-700 tw-ring-emerald-100"
      }`}
      data-testid={`fd-split-badge-${split}`}
    >
      {split === "train" ? train : heldOut}
    </span>
  );
}
type DashboardView = "overview" | "stations" | "pcap";
const PCAP_ANALYSIS_ENABLED = process.env.NEXT_PUBLIC_FAULT_PCAP_ENABLED !== "false";

const formatInt = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat("en-US").format(value);

const displayFamily = (family: string) =>
  family
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const displayStation = (station: string) =>
  station
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2");

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
};

const waitForPoll = (milliseconds: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });

function PanelHeading({
  icon,
  title,
  description,
  note,
  tone = "amber",
  actions,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  note?: string;
  tone?: "amber" | "blue";
  actions?: React.ReactNode;
}) {
  const iconTone = tone === "amber"
    ? "tw-bg-amber-50 tw-text-amber-700 tw-ring-amber-100"
    : "tw-bg-blue-50 tw-text-blue-700 tw-ring-blue-100";

  return (
    <div className="tw-flex tw-flex-col tw-justify-between tw-gap-4 sm:tw-flex-row sm:tw-items-start">
      <div className="tw-flex tw-min-w-0 tw-items-start tw-gap-3 sm:tw-gap-4">
        <span className={`tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-2xl tw-ring-1 sm:tw-h-12 sm:tw-w-12 ${iconTone}`}>
          {icon}
        </span>
        <div className="tw-min-w-0">
          <h2 className="tw-text-lg tw-font-black tw-leading-tight tw-tracking-tight tw-text-slate-950 sm:tw-text-xl">
            {title}
          </h2>
          <p className="tw-mt-1.5 tw-max-w-3xl tw-text-[13px] tw-font-medium tw-leading-6 tw-text-slate-500 sm:tw-text-sm">
            {description}
          </p>
          {note && (
            <p className="tw-mt-1.5 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-amber-700">
              {note}
            </p>
          )}
        </div>
      </div>
      {actions && <div className="tw-flex tw-flex-shrink-0 tw-items-center tw-gap-2">{actions}</div>}
    </div>
  );
}

/** One identity chip in the hero: which edition, model and data snapshot is running. */
function EditionChip({ id, label, value, mono = false }: { id: string; label: string; value: string; mono?: boolean }) {
  return (
    <span
      className="fd-edition-chip tw-inline-flex tw-max-w-full tw-items-center tw-gap-2 tw-rounded-lg tw-bg-white/[0.06] tw-px-2.5 tw-py-1.5 tw-text-[11px] tw-font-semibold tw-text-slate-100 tw-ring-1 tw-ring-white/10"
      data-testid={`fd-edition-chip-${id}`}
      title={value}
    >
      <span className="tw-flex-shrink-0 tw-text-[9px] tw-font-extrabold tw-uppercase tw-tracking-[0.14em] tw-text-yellow-300/80">{label}</span>
      <span className={`tw-min-w-0 tw-break-words ${mono ? "ai-mono" : ""}`}>{value}</span>
    </span>
  );
}

function SummaryMetric({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: "slate" | "blue" | "emerald" | "amber" | "red" | "purple";
}) {
  const tones = {
    slate: "tw-bg-slate-50 tw-text-slate-800 tw-ring-slate-200",
    blue: "tw-bg-blue-50 tw-text-blue-800 tw-ring-blue-100",
    emerald: "tw-bg-emerald-50 tw-text-emerald-800 tw-ring-emerald-100",
    amber: "tw-bg-amber-50 tw-text-amber-900 tw-ring-amber-100",
    red: "tw-bg-red-50 tw-text-red-800 tw-ring-red-100",
    purple: "tw-bg-purple-50 tw-text-purple-800 tw-ring-purple-100",
  } as const;

  return (
    <div className={`tw-rounded-2xl tw-p-3.5 tw-ring-1 sm:tw-p-4 ${tones[tone]}`}>
      <div className="tw-flex tw-items-center tw-gap-2 tw-text-[11px] tw-font-bold tw-leading-4 tw-opacity-70">
        <span className="tw-flex tw-h-7 tw-w-7 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-lg tw-bg-white/80 tw-shadow-sm">
          {icon}
        </span>
        <span>{label}</span>
      </div>
      <div className="ai-mono tw-mt-2 tw-text-xl tw-font-black tw-leading-none sm:tw-text-2xl">{value}</div>
    </div>
  );
}

export default function FaultDetectionPage() {
  const { lang } = useLanguage();
  const c = COPY[lang];
  const [activeView, setActiveView] = useState<DashboardView>("overview");
  const [pcapFile, setPcapFile] = useState<File | null>(null);
  const [analysisJob, setAnalysisJob] = useState<PcapAnalysisJob | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisSubmitting, setAnalysisSubmitting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [stations, setStations] = useState<StationAnalysis[]>([]);
  const [stationLoading, setStationLoading] = useState(true);
  const [stationHasLoaded, setStationHasLoaded] = useState(false);
  const [stationError, setStationError] = useState<string | null>(null);
  const [stationSnapshot, setStationSnapshot] = useState<string | null>(null);
  const [bundled, setBundled] = useState<BundledBenchmark | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<DesktopRuntimeStatus | null>(null);
  useEditionTabTitle(runtimeStatus);
  // Known from the launch query string / remembered loopback port, so it is
  // stable for the life of the tab; the server snapshot is false (no window).
  const desktopMode = useSyncExternalStore(
    () => () => {},
    () => isDesktopFaultDetectionApi(),
    () => false,
  );
  const [stationQuery, setStationQuery] = useState("");
  const [stationSort, setStationSort] = useState<StationSort>("station");
  // open on every station the build carries (212 in the 1.3.x current line): the tab is
  // where users look for per-station results; held-out-only views are one click away and
  // every training row keeps its in-sample badge and banner
  const [stationSplitFilter, setStationSplitFilter] = useState<StationSplitFilter>("all");
  const [selectedStationId, setSelectedStationId] = useState<string | null>(null);
  const [faultGlossaryOpen, setFaultGlossaryOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const analysisAbortRef = useRef<AbortController | null>(null);

  const loadStations = useCallback(async (signal?: AbortSignal) => {
    setStationLoading(true);
    setStationError(null);
    try {
      const summary = await getFaultDetectionSummary({ signal });
      setStations(allStationRows(summary.analysis));
      setStationSnapshot(summary.snapshotAt);
      setBundled({
        source: summary.source,
        snapshotAt: summary.snapshotAt,
        dataset: summary.dataset,
        leaderboard: summary.leaderboard,
        faultFamilies: summary.analysis.faultFamilies,
        detectionPolicy: summary.detectionPolicy ?? null,
      });
      setStationHasLoaded(true);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setStationError(caught instanceof Error ? caught.message : "Unable to load station analysis.");
    } finally {
      if (!signal?.aborted) setStationLoading(false);
    }
  }, []);

  useEffect(() => {
    if ((activeView !== "overview" && activeView !== "stations") || stationHasLoaded) return;
    const controller = new AbortController();
    void loadStations(controller.signal);
    return () => controller.abort();
  }, [activeView, loadStations, stationHasLoaded]);

  // Edition identity (product name, version, model artifact) comes from the
  // desktop sidecar's /health; the web deployment has no sidecar and shows none.
  useEffect(() => {
    if (!isDesktopFaultDetectionApi()) return;
    const controller = new AbortController();
    getDesktopRuntimeStatus({ signal: controller.signal })
      .then(setRuntimeStatus)
      .catch(() => setRuntimeStatus(null));
    return () => controller.abort();
  }, []);

  useEffect(
    () => () => {
      analysisAbortRef.current?.abort();
    },
    [],
  );

  const choosePcap = useCallback(
    (file: File | null) => {
      setAnalysisError(null);
      setAnalysisJob(null);
      if (!file) {
        setPcapFile(null);
        return;
      }
      const lowerName = file.name.toLowerCase();
      if (!lowerName.endsWith(".pcap") && !lowerName.endsWith(".pcapng")) {
        setPcapFile(null);
        setAnalysisError(c.invalidExtension);
        return;
      }
      if (file.size === 0) {
        setPcapFile(null);
        setAnalysisError(c.emptyFile);
        return;
      }
      if (file.size > MAX_PCAP_UPLOAD_BYTES) {
        setPcapFile(null);
        setAnalysisError(c.fileTooLarge);
        return;
      }
      setPcapFile(file);
    },
    [c.emptyFile, c.fileTooLarge, c.invalidExtension],
  );

  const runPcapAnalysis = useCallback(async () => {
    if (!pcapFile || analysisSubmitting) return;
    analysisAbortRef.current?.abort();
    const controller = new AbortController();
    analysisAbortRef.current = controller;
    setAnalysisSubmitting(true);
    setAnalysisError(null);
    setAnalysisJob(null);

    try {
      let job = await createPcapAnalysisJob(pcapFile, { signal: controller.signal });
      setAnalysisJob(job);
      while (job.status === "queued" || job.status === "processing") {
        await waitForPoll(1200, controller.signal);
        job = await getPcapAnalysisJob(job.jobId, { signal: controller.signal });
        setAnalysisJob(job);
      }
      if (job.status === "failed") {
        setAnalysisError(job.error || c.uploadFailed);
      } else if (job.status === "complete" && !job.result) {
        setAnalysisError(c.uploadFailed);
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setAnalysisError(caught instanceof Error ? caught.message : c.uploadFailed);
    } finally {
      if (analysisAbortRef.current === controller) {
        analysisAbortRef.current = null;
        setAnalysisSubmitting(false);
      }
    }
  }, [analysisSubmitting, c.uploadFailed, pcapFile]);

  const analysisIsBusy =
    analysisSubmitting ||
    (!analysisError && (analysisJob?.status === "queued" || analysisJob?.status === "processing"));
  const analysisResult = analysisJob?.status === "complete" ? analysisJob.result ?? null : null;
  const verdictTone =
    analysisResult?.verdict.status === "fault_detected"
      ? "red"
      : analysisResult?.verdict.status === "no_fault_detected"
        ? "emerald"
        : "amber";
  const verdictTitle =
    analysisResult?.verdict.status === "fault_detected"
      ? c.faultDetected
      : analysisResult?.verdict.status === "no_fault_detected"
        ? c.noFaultDetected
        : c.inconclusive;
  const hasTrainStations = useMemo(() => stations.some((row) => stationSplitOf(row) === "train"), [stations]);
  const splitStations = useMemo(
    () => (!hasTrainStations || stationSplitFilter === "all"
      ? stations
      : stations.filter((row) => stationSplitOf(row) === stationSplitFilter)),
    [hasTrainStations, stationSplitFilter, stations],
  );
  const visibleStations = useMemo(() => {
    const query = stationQuery.trim().toLowerCase();
    const rows = query
      ? splitStations.filter((row) => row.station.toLowerCase().includes(query))
      : splitStations;
    return sortStationRows(rows, stationSort);
  }, [stationQuery, stationSort, splitStations]);
  // the search is scoped to the selected split; say so when the other split has matches
  const otherSplitMatches = useMemo(() => {
    const query = stationQuery.trim().toLowerCase();
    if (!query || !hasTrainStations || stationSplitFilter === "all") return 0;
    return stations.filter((row) => stationSplitOf(row) !== stationSplitFilter && row.station.toLowerCase().includes(query)).length;
  }, [hasTrainStations, stationQuery, stationSplitFilter, stations]);
  // the tab's count tiles follow the selected split and say what they include; model
  // evaluation (leaderboard, Overview) stays held-out only
  const stationTotals = useMemo(() => stationRowTotals(splitStations), [splitStations]);
  const heldOutTotals = useMemo(() => heldOutStationTotals(stations), [stations]);
  const trainTotals = useMemo(
    () => stationRowTotals(stations.filter((row) => stationSplitOf(row) === "train")),
    [stations],
  );
  const showsTrainRows = hasTrainStations && stationSplitFilter !== "test";
  const stationSessionsLabel = !hasTrainStations || stationSplitFilter === "test"
    ? c.testSessions
    : stationSplitFilter === "train"
      ? c.trainSessions
      : c.allSessions;
  const stationSnapshotLabel = stationSnapshot
    ? new Intl.DateTimeFormat(snapshotDateLocale(lang), {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(stationSnapshot))
    : null;
  const selectedStation = useMemo(
    () => stations.find((station) => station.station === selectedStationId) ?? null,
    [selectedStationId, stations],
  );
  // Desktop only: the sidecar reports the snapshot date; an older sidecar
  // without that field falls back to the summary it serves. The web build
  // shows no edition strip at all.
  const editionSnapshotAt = desktopMode ? runtimeStatus?.summarySnapshotAt ?? bundled?.snapshotAt ?? null : null;
  const editionSnapshotLabel =
    editionSnapshotAt && Number.isFinite(Date.parse(editionSnapshotAt))
      ? new Intl.DateTimeFormat(snapshotDateLocale(lang), { dateStyle: "medium" }).format(new Date(editionSnapshotAt))
      : null;
  // "Bundled with this edition" wording only when the portable sidecar answered;
  // the legacy dev launcher serves live results and the web build uses the API.
  const bundledFromSidecar = runtimeStatus ? runtimeStatus.service === "fault-detection-portable" : desktopMode;
  const editionName = runtimeStatus?.productName
    ? `${runtimeStatus.productName}${runtimeStatus.appVersion ? ` v${runtimeStatus.appVersion}` : ""}`
    : null;
  // Hero counts from the benchmark bundled with this edition (held-out totals
  // from `dataset`, never a sum over stations); just the label until it loads.
  const heroStats: Array<[React.ReactNode, number | null, string]> = [
    [<Upload key="upload" className="tw-h-4 tw-w-4" />, bundled?.dataset.sessions ?? null, c.workflowSessions],
    [<BrainCircuit key="analyze" className="tw-h-4 tw-w-4" />, bundled?.leaderboard.length || null, c.workflowModels],
    [<BookOpenCheck key="review" className="tw-h-4 tw-w-4" />, bundled?.faultFamilies.length || null, c.workflowFamilies],
  ];
  const heldOutSessionsLabel =
    bundled?.dataset.sessions != null ? bundled.dataset.sessions.toLocaleString("en-US") : null;

  return (
    <main className={`ai-root fd-page fd-lang-${lang} tw-min-h-screen`}>
      <div className="tw-mx-auto tw-w-full tw-max-w-[1440px] tw-px-0 tw-py-3 sm:tw-px-5 sm:tw-py-6 lg:tw-px-6 lg:tw-py-7">
        <section
          className="fd-hero tw-relative tw-overflow-hidden tw-rounded-[22px] tw-p-5 tw-text-white tw-shadow-2xl tw-shadow-slate-950/15 tw-ring-1 tw-ring-white/10 sm:tw-rounded-[26px] sm:tw-p-7 lg:tw-p-8"
          style={{ background: "linear-gradient(135deg, #030712 0%, #111827 55%, #1e293b 100%)" }}
        >
          <div
            className="tw-pointer-events-none tw-absolute tw-inset-0 tw-opacity-[0.06]"
            style={{
              backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)",
              backgroundSize: "22px 22px",
            }}
          />
          <div className="tw-absolute tw--right-16 tw--top-24 tw-h-64 tw-w-64 tw-rounded-full tw-bg-yellow-400/10 tw-blur-3xl" />
          <div className="tw-relative tw-z-10">
            <div className="tw-grid tw-gap-6 lg:tw-grid-cols-[minmax(0,1fr)_auto] lg:tw-items-start lg:tw-gap-10">
              <div className="tw-min-w-0">
                <div className="tw-flex tw-items-center tw-gap-3">
                  <div className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-[14px] tw-bg-yellow-400 tw-text-gray-950 tw-shadow-lg tw-shadow-yellow-500/20 sm:tw-h-12 sm:tw-w-12">
                    <Zap className="tw-h-5 tw-w-5 sm:tw-h-6 sm:tw-w-6" strokeWidth={2.4} />
                  </div>
                  <div className="tw-text-[10px] tw-font-bold tw-uppercase tw-leading-4 tw-tracking-[0.18em] tw-text-yellow-300/90 sm:tw-text-[11px]">{c.eyebrow}</div>
                </div>
                <h1 className="fd-display tw-mt-5 tw-max-w-4xl tw-text-[28px] tw-font-black tw-leading-[1.12] tw-tracking-[-0.035em] tw-text-white sm:tw-text-4xl lg:tw-text-[42px] lg:tw-leading-[1.08]">{c.title}</h1>
                <p className="tw-mt-3 tw-max-w-2xl tw-text-[13px] tw-font-medium tw-leading-6 tw-text-slate-300 sm:tw-mt-4 sm:tw-text-[15px] sm:tw-leading-7">{PCAP_ANALYSIS_ENABLED ? c.subtitle : c.desktopSubtitle}</p>
                {(editionName || runtimeStatus?.artifactVersion || editionSnapshotLabel) && (
                  <div className="fd-edition-strip tw-mt-4 tw-flex tw-flex-wrap tw-gap-2" data-testid="fd-edition-strip">
                    {editionName && <EditionChip id="edition" label={c.editionLabel} value={editionName} />}
                    {runtimeStatus?.artifactVersion && <EditionChip id="model" label={c.modelLabel} value={runtimeStatus.artifactVersion} mono />}
                    {editionSnapshotLabel && <EditionChip id="snapshot" label={c.dataAsOfLabel} value={editionSnapshotLabel} />}
                    {runtimeStatus?.detectionPolicy && runtimeStatus.detectionPolicy.id !== "baseline" && (
                      <EditionChip
                        id="policy"
                        label={runtimeStatus.detectionPolicy.id === "iso15118-standard" ? c.policyLabel : c.policyOther}
                        value={runtimeStatus.detectionPolicy.id === "iso15118-standard" ? c.policyIso : runtimeStatus.detectionPolicy.label ?? runtimeStatus.detectionPolicy.id}
                      />
                    )}
                  </div>
                )}
              </div>
              <div className="tw-grid tw-grid-cols-2 tw-gap-2 sm:tw-flex sm:tw-flex-wrap lg:tw-max-w-[270px] lg:tw-justify-end">
                <span className="tw-inline-flex tw-min-h-10 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-emerald-400/10 tw-px-2.5 tw-text-center tw-text-[9px] tw-font-extrabold tw-uppercase tw-tracking-wider tw-text-emerald-300 tw-ring-1 tw-ring-emerald-300/20 sm:tw-px-3.5 sm:tw-text-[11px]">
                  <ShieldCheck className="tw-h-4 tw-w-4" /> {c.modelBadge}
                </span>
                <span className="tw-inline-flex tw-min-h-10 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-white/5 tw-px-2.5 tw-text-center tw-text-[9px] tw-font-bold tw-text-white/70 tw-ring-1 tw-ring-white/10 sm:tw-px-3.5 sm:tw-text-[11px]">
                  <Database className="tw-h-4 tw-w-4" />
                  <span className="sm:tw-hidden">ISO 15118</span>
                  <span className="tw-hidden sm:tw-inline">{c.formatBadge}</span>
                </span>
              </div>
            </div>
            <div className="fd-hero-stats tw-mt-7 tw-grid tw-gap-px tw-overflow-hidden tw-rounded-2xl tw-bg-white/10 tw-ring-1 tw-ring-white/10 sm:tw-grid-cols-3 lg:tw-max-w-4xl">
              {heroStats.map(([icon, value, label]) => (
                <div key={label} className="tw-flex tw-min-h-12 tw-items-center tw-gap-2.5 tw-bg-white/[0.045] tw-px-4 tw-py-3 tw-text-[12px] tw-font-semibold tw-text-slate-200" data-testid="fd-hero-stat">
                  <span className="tw-flex tw-h-7 tw-w-7 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-lg tw-bg-yellow-300/10 tw-text-yellow-300">{icon}</span>
                  <span>{value === null ? label : `${value.toLocaleString("en-US")} · ${label}`}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <nav className="tw-mt-3 sm:tw-mt-5" aria-label="Fault detection dashboard views">
          <div role="tablist" className={`fd-view-tabs tw-grid tw-w-full tw-gap-1 tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white/95 tw-p-1.5 tw-shadow-sm sm:tw-inline-grid sm:tw-w-auto ${PCAP_ANALYSIS_ENABLED ? "tw-grid-cols-3 sm:tw-min-w-[540px]" : "tw-grid-cols-2 sm:tw-min-w-[380px]"}`}>
            {[
              { id: "overview" as const, label: c.overviewTab, icon: <LayoutDashboard className="tw-h-4 tw-w-4" /> },
              { id: "stations" as const, label: c.stationsTab, icon: <MapPin className="tw-h-4 tw-w-4" /> },
              ...(PCAP_ANALYSIS_ENABLED
                ? [{ id: "pcap" as const, label: c.pcapTab, icon: <Upload key="pcap" className="tw-h-4 tw-w-4" /> }]
                : []),
            ].map((item) => (
              <button
                key={item.id}
                id={`fault-view-tab-${item.id}`}
                type="button"
                role="tab"
                aria-selected={activeView === item.id}
                aria-controls={`fault-view-panel-${item.id}`}
                onClick={() => setActiveView(item.id)}
                className={`fd-view-tab tw-flex tw-min-h-14 tw-flex-col tw-items-center tw-justify-center tw-gap-1 tw-rounded-xl tw-px-1 tw-py-2 tw-text-[10px] tw-font-bold tw-transition focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-blue-100 sm:tw-min-h-11 sm:tw-flex-row sm:tw-gap-2 sm:tw-px-4 sm:tw-py-2.5 sm:tw-text-[12px] ${
                  activeView === item.id
                    ? "fd-view-tab--active tw-bg-slate-900 tw-text-white tw-shadow-md tw-shadow-slate-900/10"
                    : "tw-text-slate-500 hover:tw-bg-slate-50 hover:tw-text-slate-900"
                }`}
              >
                {item.icon}
                <span className="tw-whitespace-nowrap tw-leading-4">{item.label}</span>
              </button>
            ))}
          </div>
        </nav>

        {activeView === "overview" && (
          <section
            id="fault-view-panel-overview"
            role="tabpanel"
            aria-labelledby="fault-view-tab-overview"
            className="tw-mt-5 sm:tw-mt-6"
          >
            <ResearchDashboard
              lang={lang}
              bundled={bundled}
              desktop={bundledFromSidecar}
              modelArtifact={runtimeStatus?.artifactVersion ?? null}
              stations={stations}
              stationLoading={stationLoading}
              stationError={stationError}
              onRetryStations={() => void loadStations()}
              onSelectStation={setSelectedStationId}
              onOpenStations={() => setActiveView("stations")}
              onOpenAllStations={() => {
                // "View all N stations" means all of them: no leftover search, whatever split was chosen last
                setStationQuery("");
                setStationSplitFilter("all");
                setActiveView("stations");
              }}
              onOpenPcap={PCAP_ANALYSIS_ENABLED ? () => setActiveView("pcap") : undefined}
            />
          </section>
        )}

        {PCAP_ANALYSIS_ENABLED && activeView === "pcap" && (
        <section
          id="fault-view-panel-pcap"
          role="tabpanel"
          aria-labelledby="fault-view-tab-pcap"
          className="tw-mt-5 sm:tw-mt-6"
        >
          <div className="fd-panel tw-border-t-[3px] tw-border-t-amber-500">
            <div className="tw-border-b tw-border-slate-100 tw-p-4 sm:tw-p-6">
              <PanelHeading
                icon={<BrainCircuit className="tw-h-5 tw-w-5 sm:tw-h-6 sm:tw-w-6" />}
                title={c.workspaceTitle}
                description={c.workspaceSub}
              />
            </div>

            <div className="tw-grid tw-grid-cols-1 lg:tw-grid-cols-12">
              <div className="tw-border-b tw-border-slate-100 tw-p-4 sm:tw-p-6 lg:tw-col-span-5 lg:tw-border-b-0 lg:tw-border-r">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pcap,.pcapng,application/vnd.tcpdump.pcap,application/octet-stream"
                  className="tw-hidden"
                  disabled={analysisIsBusy}
                  onChange={(event) => {
                    choosePcap(event.currentTarget.files?.[0] ?? null);
                    event.currentTarget.value = "";
                  }}
                />
                <div
                  role="button"
                  tabIndex={analysisIsBusy ? -1 : 0}
                  aria-disabled={analysisIsBusy}
                  onClick={() => !analysisIsBusy && fileInputRef.current?.click()}
                  onKeyDown={(event) => {
                    if (!analysisIsBusy && (event.key === "Enter" || event.key === " ")) {
                      event.preventDefault();
                      fileInputRef.current?.click();
                    }
                  }}
                  onDragEnter={(event) => {
                    event.preventDefault();
                    if (!analysisIsBusy) setIsDragging(true);
                  }}
                  onDragOver={(event) => event.preventDefault()}
                  onDragLeave={(event) => {
                    event.preventDefault();
                    if (event.currentTarget === event.target) setIsDragging(false);
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    setIsDragging(false);
                    if (!analysisIsBusy) choosePcap(event.dataTransfer.files?.[0] ?? null);
                  }}
                  className={`fd-dropzone tw-flex tw-min-h-[220px] tw-flex-col tw-items-center tw-justify-center tw-rounded-2xl tw-border-2 tw-border-dashed tw-p-6 tw-text-center tw-outline-none tw-transition focus-visible:tw-ring-4 focus-visible:tw-ring-amber-200 ${
                    analysisIsBusy
                      ? "tw-cursor-not-allowed tw-border-gray-200 tw-bg-gray-50 tw-opacity-70"
                      : isDragging
                        ? "tw-border-yellow-500 tw-bg-yellow-50"
                        : "tw-cursor-pointer tw-border-gray-300 tw-bg-slate-50 hover:tw-border-yellow-500 hover:tw-bg-yellow-50/50"
                  }`}
                >
                  <div className="tw-flex tw-h-14 tw-w-14 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-gray-900 tw-text-yellow-300 tw-shadow-lg tw-shadow-slate-900/15">
                    <Upload className="tw-h-6 tw-w-6" />
                  </div>
                  <div className="tw-mt-4 tw-text-[15px] tw-font-extrabold tw-text-gray-900">{c.dropTitle}</div>
                  <div className="tw-mt-1.5 tw-text-[12px] tw-font-medium tw-leading-5 tw-text-gray-500">{c.dropHint}</div>
                </div>

                {pcapFile && (
                  <div className="tw-mt-3 tw-flex tw-items-center tw-gap-3 tw-rounded-2xl tw-border tw-border-gray-200 tw-bg-white tw-p-3.5 tw-shadow-sm">
                    <div className="tw-flex tw-h-10 tw-w-10 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-50 tw-text-blue-700">
                      <Database className="tw-h-[18px] tw-w-[18px]" />
                    </div>
                    <div className="tw-min-w-0 tw-flex-1">
                      <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-gray-500">{c.selectedFile}</div>
                      <div className="tw-mt-0.5 tw-truncate tw-text-[13px] tw-font-extrabold tw-text-gray-900" title={pcapFile.name}>{pcapFile.name}</div>
                      <div className="ai-mono tw-mt-0.5 tw-text-[11px] tw-text-gray-500">{formatBytes(pcapFile.size)}</div>
                    </div>
                    {!analysisIsBusy && (
                      <button
                        type="button"
                        aria-label={c.remove}
                        title={c.remove}
                        onClick={() => choosePcap(null)}
                        className="tw-flex tw-h-11 tw-w-11 tw-items-center tw-justify-center tw-rounded-xl tw-text-gray-400 tw-transition hover:tw-bg-red-50 hover:tw-text-red-600 focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-red-300"
                      >
                        <X className="tw-h-4 tw-w-4" />
                      </button>
                    )}
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => void runPcapAnalysis()}
                  disabled={!pcapFile || analysisIsBusy}
                  className="tw-mt-3 tw-inline-flex tw-min-h-12 tw-w-full tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-gray-900 tw-px-4 tw-py-3 tw-text-[13px] tw-font-extrabold tw-text-white tw-shadow-lg tw-shadow-slate-900/10 tw-transition hover:tw-bg-gray-700 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-slate-200 disabled:tw-cursor-not-allowed disabled:tw-bg-gray-300 disabled:tw-shadow-none"
                >
                  {analysisIsBusy ? <LoaderCircle className="tw-h-4 tw-w-4 tw-animate-spin" /> : <Sparkles className="tw-h-4 tw-w-4 tw-text-yellow-300" />}
                  {analysisIsBusy ? c.processing : c.analyze}
                </button>
              </div>

              <div className="tw-p-4 sm:tw-p-6 lg:tw-col-span-7" aria-live="polite">
                {!analysisJob && !analysisError && (
                  <div className="tw-flex tw-min-h-[320px] tw-flex-col tw-items-center tw-justify-center tw-rounded-2xl tw-bg-slate-50 tw-p-5 tw-text-center tw-ring-1 tw-ring-slate-200/70 sm:tw-p-8">
                    <span className="tw-flex tw-h-14 tw-w-14 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-white tw-text-slate-400 tw-shadow-sm tw-ring-1 tw-ring-slate-200">
                      <CircleDashed className="tw-h-7 tw-w-7" />
                    </span>
                    <div className="tw-mt-4 tw-text-base tw-font-extrabold tw-text-gray-800">{c.emptyTitle}</div>
                    <p className="tw-mt-1.5 tw-max-w-lg tw-text-[13px] tw-font-medium tw-leading-6 tw-text-gray-500">{c.emptyBody}</p>
                    <div className="tw-mt-5 tw-grid tw-w-full tw-max-w-xl tw-grid-cols-1 tw-gap-2 sm:tw-grid-cols-3">
                      {[
                        [<AlertTriangle key="fault" className="tw-h-4 tw-w-4" />, c.faultType],
                        [<ShieldCheck key="confidence" className="tw-h-4 tw-w-4" />, c.confidence],
                        [<Activity key="stop" className="tw-h-4 tw-w-4" />, c.stopAttribution],
                      ].map(([icon, label]) => (
                        <div key={String(label)} className="tw-flex tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-white tw-px-3 tw-py-2.5 tw-text-[11px] tw-font-bold tw-text-slate-600 tw-ring-1 tw-ring-slate-200">
                          <span className="tw-text-blue-600">{icon}</span>
                          <span>{label}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {analysisError && (
                  <div className="tw-flex tw-min-h-[320px] tw-flex-col tw-justify-center tw-rounded-2xl tw-border tw-border-red-200 tw-bg-red-50 tw-p-6">
                    <AlertTriangle className="tw-h-7 tw-w-7 tw-text-red-600" />
                    <div className="tw-mt-3 tw-text-base tw-font-extrabold tw-text-red-950">{c.failed}</div>
                    <p className="tw-mt-1.5 tw-break-words tw-text-[13px] tw-font-medium tw-leading-6 tw-text-red-800/80">{analysisError}</p>
                  </div>
                )}

                {!analysisError && analysisJob && (analysisJob.status === "queued" || analysisJob.status === "processing") && (
                  <div className="tw-flex tw-min-h-[320px] tw-flex-col tw-justify-center tw-rounded-2xl tw-bg-gray-900 tw-p-5 tw-text-white sm:tw-p-6">
                    <div className="tw-flex tw-items-center tw-justify-between tw-gap-3">
                      <div className="tw-flex tw-items-center tw-gap-2 tw-text-[13px] tw-font-extrabold tw-text-yellow-300">
                        <LoaderCircle className="tw-h-4 tw-w-4 tw-animate-spin" />
                        {analysisJob.status === "queued" ? c.queued : c.processing}
                      </div>
                      <div className="ai-mono tw-text-2xl tw-font-black">{Math.round(analysisJob.progress)}%</div>
                    </div>
                    <div className="tw-mt-4 tw-h-2.5 tw-overflow-hidden tw-rounded-full tw-bg-white/10">
                      <div className="tw-h-full tw-rounded-full tw-bg-yellow-400 tw-transition-all" style={{ width: `${Math.max(0, Math.min(100, analysisJob.progress))}%` }} />
                    </div>
                    <div className="tw-mt-3 tw-flex tw-items-center tw-justify-between tw-gap-3 tw-text-[11px] tw-text-white/55">
                      <span className="tw-font-bold tw-uppercase tw-tracking-wider">{analysisJob.stage.replaceAll("_", " ")}</span>
                      <span className="ai-mono tw-truncate">{analysisJob.originalName}</span>
                    </div>
                    <div className="tw-mt-6 tw-grid tw-grid-cols-2 tw-gap-2">
                      <div className="tw-rounded-lg tw-bg-white/5 tw-p-3 tw-ring-1 tw-ring-white/10">
                        <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-white/45">{c.modelUsed}</div>
                        <div className="tw-mt-1 tw-text-[13px] tw-font-extrabold">Agentic AI</div>
                      </div>
                      <div className="tw-rounded-lg tw-bg-white/5 tw-p-3 tw-ring-1 tw-ring-white/10">
                        <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-white/45">SHA-256</div>
                        <div className="ai-mono tw-mt-1 tw-truncate tw-text-[12px] tw-font-bold">{analysisJob.sha256?.slice(0, 16) ?? "calculating"}</div>
                      </div>
                    </div>
                  </div>
                )}

                {analysisResult && (
                  <div className={`tw-min-h-[320px] tw-rounded-2xl tw-border tw-bg-white tw-p-5 tw-shadow-sm sm:tw-p-6 ${
                    verdictTone === "red"
                      ? "tw-border-red-200"
                      : verdictTone === "emerald"
                        ? "tw-border-emerald-200"
                        : "tw-border-amber-200"
                  }`}>
                    <div className="tw-flex tw-flex-col tw-justify-between tw-gap-3 sm:tw-flex-row sm:tw-items-start">
                      <div className="tw-flex tw-items-start tw-gap-3">
                        <div className={`tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl ${
                          verdictTone === "red"
                            ? "tw-bg-red-600 tw-text-white"
                            : verdictTone === "emerald"
                              ? "tw-bg-emerald-600 tw-text-white"
                              : "tw-bg-amber-500 tw-text-white"
                        }`}>
                          {verdictTone === "red" ? <AlertTriangle className="tw-h-5 tw-w-5" /> : verdictTone === "emerald" ? <ShieldCheck className="tw-h-5 tw-w-5" /> : <CircleDashed className="tw-h-5 tw-w-5" />}
                        </div>
                        <div>
                          <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-[0.14em] tw-text-gray-500">{c.resultTitle}</div>
                          <div className="tw-mt-1 tw-text-xl tw-font-black tw-leading-tight tw-text-gray-950">{verdictTitle}</div>
                          <div className="tw-mt-1.5 tw-text-[12px] tw-font-semibold tw-text-gray-500">{analysisResult.model.name}</div>
                        </div>
                      </div>
                      {analysisResult.verdict.confidence != null && (
                        <div className="tw-rounded-xl tw-bg-slate-50 tw-px-4 tw-py-2.5 tw-text-left tw-ring-1 tw-ring-slate-200 sm:tw-text-right">
                          <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-gray-500">{c.confidence}</div>
                          <div className="ai-mono tw-text-2xl tw-font-black tw-text-gray-950">{(analysisResult.verdict.confidence * 100).toFixed(0)}%</div>
                        </div>
                      )}
                    </div>
                    <div className="tw-mt-4 tw-grid tw-grid-cols-1 tw-gap-2 sm:tw-grid-cols-2">
                      <div className="tw-rounded-xl tw-bg-slate-50 tw-p-3.5 tw-ring-1 tw-ring-slate-200/80">
                        <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-gray-500">{c.faultType}</div>
                        <div className="ai-mono tw-mt-1 tw-text-[13px] tw-font-extrabold tw-text-gray-900">{analysisResult.verdict.faultFamily ? displayFamily(analysisResult.verdict.faultFamily) : "—"}</div>
                      </div>
                      <div className="tw-rounded-xl tw-bg-slate-50 tw-p-3.5 tw-ring-1 tw-ring-slate-200/80">
                        <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-gray-500">{c.modelUsed}</div>
                        <div className="tw-mt-1 tw-text-[13px] tw-font-extrabold tw-text-gray-900">{analysisResult.model.name}</div>
                        {analysisResult.model.detectionPolicy && analysisResult.model.detectionPolicy.id !== "baseline" && (
                          <div className="tw-mt-0.5 tw-text-[11px] tw-font-semibold tw-text-emerald-700" data-testid="fd-result-policy">
                            {analysisResult.model.detectionPolicy.id === "iso15118-standard" ? c.policyIso : analysisResult.model.detectionPolicy.label ?? analysisResult.model.detectionPolicy.id}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="tw-mt-2 tw-rounded-xl tw-bg-slate-50 tw-p-3.5 tw-ring-1 tw-ring-slate-200/80">
                      <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-gray-500">{c.evidence}</div>
                      <div className="tw-mt-1.5 tw-text-[13px] tw-font-semibold tw-leading-6 tw-text-gray-800">{analysisResult.verdict.reason ?? "—"}</div>
                    </div>
                    {analysisResult.verdict.faultDetected === true && (
                      <div className="tw-mt-3">
                        <FaultExplanationPanel
                          family={analysisResult.verdict.faultFamily}
                          reason={analysisResult.verdict.reason}
                          lang={lang}
                        />
                      </div>
                    )}
                    {analysisResult.verdict.stopAnalysis && (
                      <div className="tw-mt-3">
                        <ObservedStopAttribution analysis={analysisResult.verdict.stopAnalysis} lang={lang} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {analysisResult && (
              <div className="tw-border-t tw-border-gray-100 tw-p-4 sm:tw-p-6">
                <div className="tw-grid tw-grid-cols-2 tw-gap-2.5 sm:tw-grid-cols-4 sm:tw-gap-3">
                  {[
                    { label: c.relevantEvents, value: formatInt(analysisResult.capture.extractedEvents), icon: <Database className="tw-h-4 tw-w-4" />, tone: "slate" as const },
                    { label: c.sessions, value: formatInt(analysisResult.capture.sessionCount), icon: <Activity className="tw-h-4 tw-w-4" />, tone: "blue" as const },
                    { label: c.completeSessions, value: formatInt(analysisResult.capture.completeSessions), icon: <ShieldCheck className="tw-h-4 tw-w-4" />, tone: "emerald" as const },
                    { label: c.alertedSessions, value: formatInt(analysisResult.capture.alertedSessions), icon: <AlertTriangle className="tw-h-4 tw-w-4" />, tone: "red" as const },
                  ].map((metric) => <SummaryMetric key={metric.label} {...metric} />)}
                </div>

                {analysisResult.sessions.length > 0 && (
                  <div className="tw-mt-6">
                    <div className="tw-flex tw-items-center tw-gap-2.5">
                      <span className="tw-flex tw-h-8 tw-w-8 tw-items-center tw-justify-center tw-rounded-lg tw-bg-slate-900 tw-text-yellow-300">
                        <Activity className="tw-h-4 tw-w-4" />
                      </span>
                      <h3 className="tw-text-[15px] tw-font-black tw-text-slate-900">{c.sessionDetails}</h3>
                    </div>

                    <div className="tw-mt-3 tw-space-y-3 md:tw-hidden">
                      {analysisResult.sessions.slice(0, 50).map((session) => (
                        <article key={session.index} className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 tw-shadow-sm">
                          <div className="tw-flex tw-items-start tw-justify-between tw-gap-3">
                            <div>
                              <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-slate-400">{c.session}</div>
                              <div className="ai-mono tw-mt-0.5 tw-text-lg tw-font-black tw-text-slate-950">#{session.index}</div>
                            </div>
                            <div className="tw-flex tw-flex-wrap tw-justify-end tw-gap-1.5">
                              <span className={`tw-inline-flex tw-rounded-lg tw-px-2.5 tw-py-1 tw-text-[11px] tw-font-extrabold ${session.gracefulClose ? "tw-bg-emerald-50 tw-text-emerald-700" : "tw-bg-amber-50 tw-text-amber-700"}`}>
                                {session.gracefulClose ? c.graceful : c.partial}
                              </span>
                              <span className={`tw-inline-flex tw-rounded-lg tw-px-2.5 tw-py-1 tw-text-[11px] tw-font-extrabold ${session.alert ? "tw-bg-red-50 tw-text-red-700" : "tw-bg-gray-100 tw-text-gray-600"}`}>
                                {session.alert ? `${c.alert} ${(session.alert.confidence * 100).toFixed(0)}%` : c.noAlert}
                              </span>
                            </div>
                          </div>
                          <div className="tw-mt-3 tw-grid tw-grid-cols-2 tw-gap-2">
                            <div className="tw-rounded-xl tw-bg-slate-50 tw-p-3">
                              <div className="tw-text-[11px] tw-font-bold tw-text-slate-500">{c.events}</div>
                              <div className="ai-mono tw-mt-0.5 tw-text-[15px] tw-font-black tw-text-slate-900">{formatInt(session.eventCount)}</div>
                            </div>
                            <div className="tw-rounded-xl tw-bg-slate-50 tw-p-3">
                              <div className="tw-text-[11px] tw-font-bold tw-text-slate-500">{c.duration}</div>
                              <div className="ai-mono tw-mt-0.5 tw-text-[15px] tw-font-black tw-text-slate-900">{session.durationSeconds.toFixed(1)}s</div>
                            </div>
                          </div>
                          {session.stopAnalysis && (
                            <div className="tw-mt-3">
                              <ObservedStopAttribution analysis={session.stopAnalysis} lang={lang} compact />
                            </div>
                          )}
                          <div className="tw-mt-3 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-slate-600">
                            {session.alert?.reason ?? `${session.firstMessage ?? "—"} → ${session.lastMessage ?? "—"}`}
                          </div>
                          {session.alert && (
                            <FaultExplanationInline
                              family={session.alert.faultFamily ?? session.alert.faultGuess}
                              reason={session.alert.reason}
                              lang={lang}
                            />
                          )}
                        </article>
                      ))}
                    </div>

                    <div className="tw-mt-3 tw-hidden tw-overflow-x-auto tw-rounded-xl tw-border tw-border-gray-200 md:tw-block">
                      <table className="tw-w-full tw-min-w-[1080px] tw-border-collapse tw-text-left">
                        <caption className="tw-sr-only">{c.sessionDetails}</caption>
                        <thead className="tw-bg-gray-50">
                          <tr>
                            {[c.session, c.events, c.duration, c.dialog, c.alert, c.stopAttribution, c.evidence].map((heading) => (
                              <th key={heading} scope="col" className="tw-px-3.5 tw-py-3 tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wide tw-text-gray-500">{heading}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {analysisResult.sessions.slice(0, 50).map((session) => (
                            <tr key={session.index} className="tw-border-t tw-border-gray-100 hover:tw-bg-slate-50/70">
                              <td className="ai-mono tw-whitespace-nowrap tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-black tw-text-gray-900">#{session.index}</td>
                              <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold tw-text-gray-700">{formatInt(session.eventCount)}</td>
                              <td className="ai-mono tw-whitespace-nowrap tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-text-gray-600">{session.durationSeconds.toFixed(1)}s</td>
                              <td className="tw-px-3.5 tw-py-3.5">
                                <span className={`tw-inline-flex tw-rounded-md tw-px-2.5 tw-py-1 tw-text-[11px] tw-font-extrabold ${session.gracefulClose ? "tw-bg-emerald-50 tw-text-emerald-700" : "tw-bg-amber-50 tw-text-amber-700"}`}>
                                  {session.gracefulClose ? c.graceful : c.partial}
                                </span>
                              </td>
                              <td className="tw-px-3.5 tw-py-3.5">
                                <span className={`tw-inline-flex tw-rounded-md tw-px-2.5 tw-py-1 tw-text-[11px] tw-font-extrabold ${session.alert ? "tw-bg-red-50 tw-text-red-700" : "tw-bg-gray-100 tw-text-gray-500"}`}>
                                  {session.alert ? `${(session.alert.confidence * 100).toFixed(0)}%` : c.noAlert}
                                </span>
                              </td>
                              <td className="tw-w-[230px] tw-px-3.5 tw-py-3.5">
                                {session.stopAnalysis ? (
                                  <ObservedStopAttribution analysis={session.stopAnalysis} lang={lang} compact />
                                ) : (
                                  <span className="tw-text-[11px] tw-font-semibold tw-text-gray-400">—</span>
                                )}
                              </td>
                              <td className="tw-w-[420px] tw-px-3.5 tw-py-3.5 tw-text-[12px] tw-leading-5 tw-text-gray-600">
                                <div>{session.alert?.reason ?? `${session.firstMessage ?? "—"} → ${session.lastMessage ?? "—"}`}</div>
                                {session.alert && (
                                  <FaultExplanationInline
                                    family={session.alert.faultFamily ?? session.alert.faultGuess}
                                    reason={session.alert.reason}
                                    lang={lang}
                                  />
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {analysisResult.warnings.length > 0 && (
                  <div className="tw-mt-4 tw-rounded-xl tw-border tw-border-amber-200 tw-bg-amber-50 tw-p-4">
                    <div className="tw-flex tw-items-center tw-gap-2 tw-text-xs tw-font-extrabold tw-text-amber-950">
                      <AlertTriangle className="tw-h-4 tw-w-4 tw-text-amber-600" /> {c.warnings}
                    </div>
                    <ul className="tw-mt-2 tw-space-y-1.5 tw-pl-5 tw-text-[12px] tw-leading-5 tw-text-amber-900/80">
                      {analysisResult.warnings.map((warning, index) => (
                        <li key={`${warning.code}-${index}`} className="tw-list-disc">{warning.message}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="tw-mt-4 tw-flex tw-flex-wrap tw-items-center tw-justify-between tw-gap-3 tw-text-[11px] tw-text-gray-500">
                  <span className="ai-mono">SHA-256 {analysisResult.file.sha256.slice(0, 20)}… · {analysisResult.processing.durationSeconds.toFixed(1)}s</span>
                  <button
                    type="button"
                    onClick={() => choosePcap(null)}
                    className="tw-inline-flex tw-min-h-11 tw-items-center tw-gap-1.5 tw-rounded-xl tw-border tw-border-gray-300 tw-bg-white tw-px-3.5 tw-py-2 tw-text-[12px] tw-font-bold tw-text-gray-700 hover:tw-bg-gray-50 focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-slate-300"
                  >
                    <Upload className="tw-h-3.5 tw-w-3.5" /> {c.runAnother}
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>
        )}

        {activeView === "stations" && (
        <section
          id="fault-view-panel-stations"
          role="tabpanel"
          aria-labelledby="fault-view-tab-stations"
          className="tw-mt-5 tw-pb-4 sm:tw-mt-6 sm:tw-pb-6"
        >
          <div className="fd-panel tw-border-t-[3px] tw-border-t-blue-600">
            <div className="tw-border-b tw-border-gray-100 tw-p-4 sm:tw-p-6">
              <PanelHeading
                tone="blue"
                icon={<MapPin className="tw-h-5 tw-w-5 sm:tw-h-6 sm:tw-w-6" />}
                title={c.stationTitle}
                description={!showsTrainRows
                  ? c.stationSub(heldOutSessionsLabel)
                  : stationSplitFilter === "train"
                    ? c.stationSubTrain(trainTotals.stations, formatInt(trainTotals.sessions))
                    : c.stationSubAll(heldOutTotals.stations + trainTotals.stations, heldOutTotals.stations, formatInt(heldOutTotals.sessions), trainTotals.stations)}
                note={showsTrainRows ? c.stationNoteSplit : c.stationNote}
                actions={(
                  <>
                  {stationSnapshotLabel && (
                    <span className="tw-hidden tw-text-right tw-text-[11px] tw-font-semibold tw-uppercase tw-tracking-wider tw-text-gray-400 lg:tw-block">
                      {c.updatedAt}<br /><span className="ai-mono tw-normal-case tw-tracking-normal">{stationSnapshotLabel}</span>
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => setFaultGlossaryOpen(true)}
                    aria-haspopup="dialog"
                    aria-controls="fault-glossary-dialog"
                    aria-label={c.openFaultGuide(supportedFaultFamilies.length)}
                    title={c.openFaultGuide(supportedFaultFamilies.length)}
                    className="tw-inline-flex tw-h-11 tw-items-center tw-justify-center tw-gap-1.5 tw-rounded-xl tw-border tw-border-blue-200 tw-bg-blue-50 tw-px-3.5 tw-text-[12px] tw-font-black tw-text-blue-700 tw-shadow-sm tw-transition hover:tw-border-blue-300 hover:tw-bg-blue-100 focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-blue-400 focus:tw-ring-offset-2"
                  >
                    <BookOpenCheck className="tw-h-4 tw-w-4" />
                    <span className="tw-hidden sm:tw-inline">{c.faultGuide}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void loadStations()}
                    disabled={stationLoading}
                    aria-label={c.retry}
                    title={c.retry}
                    className="tw-inline-flex tw-h-11 tw-w-11 tw-items-center tw-justify-center tw-rounded-xl tw-border tw-border-gray-200 tw-bg-white tw-text-gray-500 tw-shadow-sm tw-transition hover:tw-bg-gray-50 focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-slate-300 disabled:tw-cursor-not-allowed disabled:tw-opacity-50"
                  >
                    <RefreshCw className={`tw-h-4 tw-w-4 ${stationLoading ? "tw-animate-spin" : ""}`} />
                  </button>
                  </>
                )}
              />
            </div>

            {stationLoading && stations.length === 0 ? (
              <div className="tw-flex tw-min-h-[260px] tw-items-center tw-justify-center tw-gap-2 tw-p-6 tw-text-[13px] tw-font-bold tw-text-gray-500">
                <LoaderCircle className="tw-h-5 tw-w-5 tw-animate-spin tw-text-blue-600" /> {c.loadingStations}
              </div>
            ) : stationError && stations.length === 0 ? (
              <div className="tw-flex tw-min-h-[260px] tw-flex-col tw-items-center tw-justify-center tw-p-6 tw-text-center">
                <AlertTriangle className="tw-h-7 tw-w-7 tw-text-red-600" />
                <div className="tw-mt-3 tw-text-base tw-font-extrabold tw-text-red-950">{c.stationLoadFailed}</div>
                <p className="tw-mt-1 tw-max-w-xl tw-break-words tw-text-[13px] tw-leading-6 tw-text-red-700">{stationError}</p>
                <button
                  type="button"
                  onClick={() => void loadStations()}
                  className="tw-mt-4 tw-inline-flex tw-min-h-11 tw-items-center tw-gap-2 tw-rounded-xl tw-bg-gray-900 tw-px-4 tw-py-2.5 tw-text-[13px] tw-font-bold tw-text-white"
                >
                  <RefreshCw className="tw-h-3.5 tw-w-3.5" /> {c.retry}
                </button>
              </div>
            ) : (
              <>
                <div className="tw-grid tw-grid-cols-2 tw-gap-2.5 tw-border-b tw-border-gray-100 tw-p-4 sm:tw-grid-cols-4 sm:tw-gap-3 sm:tw-p-6">
                  {[
                    { label: c.stationsAnalyzed, value: formatInt(stationTotals.stations), icon: <MapPin className="tw-h-4 tw-w-4" />, tone: "blue" as const },
                    { label: stationSessionsLabel, value: formatInt(stationTotals.sessions), icon: <Database className="tw-h-4 tw-w-4" />, tone: "slate" as const },
                    { label: c.knownFaults, value: formatInt(stationTotals.faultySessions), icon: <AlertTriangle className="tw-h-4 tw-w-4" />, tone: "red" as const },
                    { label: c.aiAlerts, value: formatInt(stationTotals.alertedSessions), icon: <Sparkles className="tw-h-4 tw-w-4" />, tone: "purple" as const },
                  ].map((metric) => <SummaryMetric key={metric.label} {...metric} />)}
                  {hasTrainStations && (
                    <p className="tw-col-span-2 tw-text-[11px] tw-font-semibold tw-text-slate-500 sm:tw-col-span-4" data-testid="fd-station-totals-scope" data-split={stationSplitFilter}>
                      {stationSplitFilter === "test"
                        ? c.excludesTrain(trainTotals.stations, formatInt(trainTotals.sessions))
                        : stationSplitFilter === "train"
                          ? c.trainOnly(trainTotals.stations, formatInt(trainTotals.sessions))
                          : c.includesTrain(heldOutTotals.stations, formatInt(heldOutTotals.sessions), trainTotals.stations, formatInt(trainTotals.sessions))}
                    </p>
                  )}
                </div>

                <div className="tw-flex tw-flex-col tw-gap-2.5 tw-border-b tw-border-gray-100 tw-bg-gray-50/70 tw-p-4 sm:tw-flex-row sm:tw-items-center sm:tw-justify-between sm:tw-px-6 sm:tw-py-4">
                  <label className="tw-relative tw-block tw-w-full sm:tw-max-w-sm">
                    <span className="tw-sr-only">{c.searchStation}</span>
                    <Search className="tw-pointer-events-none tw-absolute tw-left-3 tw-top-1/2 tw-h-4 tw-w-4 tw--translate-y-1/2 tw-text-gray-400" />
                    <input
                      type="search"
                      value={stationQuery}
                      onChange={(event) => setStationQuery(event.target.value)}
                      placeholder={c.searchStation}
                      className="tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-gray-200 tw-bg-white tw-pl-10 tw-pr-3 tw-text-[13px] tw-font-semibold tw-text-gray-800 tw-outline-none tw-transition placeholder:tw-text-gray-400 focus:tw-border-blue-500 focus:tw-ring-4 focus:tw-ring-blue-100"
                    />
                  </label>
                  <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-3">
                    {hasTrainStations && (
                      <div role="radiogroup" aria-label={c.splitLabel} className="tw-inline-flex tw-rounded-xl tw-bg-slate-100 tw-p-1" data-testid="fd-split-filter">
                        {([["test", c.splitHeldOut], ["train", c.splitTrain], ["all", c.splitAll]] as const).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            role="radio"
                            aria-checked={stationSplitFilter === value}
                            onClick={() => setStationSplitFilter(value)}
                            className={`tw-min-h-9 tw-rounded-lg tw-px-2.5 tw-text-[11px] tw-font-bold tw-transition focus:tw-outline-none focus-visible:tw-ring-2 focus-visible:tw-ring-blue-400 ${
                              stationSplitFilter === value ? "tw-bg-white tw-text-slate-900 tw-shadow-sm" : "tw-text-slate-500 hover:tw-text-slate-800"
                            }`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                    <span className="tw-hidden tw-whitespace-nowrap tw-text-[11px] tw-font-bold tw-text-slate-500 md:tw-inline">
                      {c.visibleStations}: <span className="ai-mono tw-text-slate-900">{visibleStations.length}/{splitStations.length}</span>
                    </span>
                    <select
                      value={stationSort}
                      onChange={(event) => setStationSort(event.target.value as StationSort)}
                      aria-label={c.sortStation}
                      className="tw-h-11 tw-min-w-0 tw-flex-1 tw-rounded-xl tw-border tw-border-gray-200 tw-bg-white tw-px-3 tw-text-[13px] tw-font-bold tw-text-gray-700 tw-outline-none focus:tw-border-blue-500 focus:tw-ring-4 focus:tw-ring-blue-100 sm:tw-min-w-[190px]"
                    >
                      <option value="station">{c.sortStation}</option>
                      <option value="fault_rate">{c.sortFaultRate}</option>
                      <option value="recall">{c.sortRecall}</option>
                      <option value="far">{c.sortFar}</option>
                    </select>
                  </div>
                </div>

                {stationError && (
                  <div className="tw-border-b tw-border-amber-200 tw-bg-amber-50 tw-px-5 tw-py-3 tw-text-[12px] tw-font-semibold tw-text-amber-800">
                    {c.stationLoadFailed}: {stationError}
                  </div>
                )}

                {showsTrainRows && (
                  <div role="note" className="tw-flex tw-items-start tw-gap-2.5 tw-border-b tw-border-amber-200 tw-bg-amber-50 tw-px-5 tw-py-3 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-amber-900" data-testid="fd-train-banner">
                    <AlertTriangle className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0" />
                    <span>{c.trainBanner}</span>
                  </div>
                )}

                <div className="tw-space-y-3 tw-p-4 sm:tw-p-6 lg:tw-hidden">
                  {visibleStations.map((station) => {
                    const scoreTone = station.score >= 70
                      ? "tw-bg-emerald-50 tw-text-emerald-700 tw-ring-emerald-100"
                      : station.score >= 50
                        ? "tw-bg-amber-50 tw-text-amber-700 tw-ring-amber-100"
                        : "tw-bg-red-50 tw-text-red-700 tw-ring-red-100";
                    return (
                      <button
                        key={station.station}
                        type="button"
                        onClick={() => setSelectedStationId(station.station)}
                        aria-haspopup="dialog"
                        aria-controls="station-analysis-dialog"
                        aria-label={`${c.viewStationDetails}: ${displayStation(station.station)}`}
                        className="fd-station-card tw-block tw-w-full tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 tw-text-left tw-shadow-sm tw-outline-none focus-visible:tw-ring-4 focus-visible:tw-ring-blue-100"
                      >
                        <span className="tw-flex tw-items-start tw-justify-between tw-gap-3">
                          <span className="tw-flex tw-min-w-0 tw-items-start tw-gap-3">
                            <span className="tw-flex tw-h-10 tw-w-10 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-50 tw-text-blue-700">
                              <MapPin className="tw-h-[18px] tw-w-[18px]" />
                            </span>
                            <span className="tw-min-w-0">
                              <span className="tw-block tw-truncate tw-text-[15px] tw-font-black tw-text-slate-950" title={station.station}>
                                {displayStation(station.station)}
                              </span>
                              <span className="tw-mt-0.5 tw-flex tw-min-w-0 tw-items-center tw-gap-1.5 tw-text-[11px] tw-font-semibold tw-uppercase tw-tracking-wide tw-text-slate-400">
                                {hasTrainStations && <SplitBadge split={stationSplitOf(station)} heldOut={c.badgeHeldOut} train={c.badgeTrain} />}
                                <span className="tw-truncate">{station.group} · {station.connectors} connector{station.connectors === 1 ? "" : "s"}</span>
                              </span>
                            </span>
                          </span>
                          <span className={`ai-mono tw-inline-flex tw-min-w-[64px] tw-justify-center tw-rounded-xl tw-px-2.5 tw-py-2 tw-text-[13px] tw-font-black tw-ring-1 ${scoreTone}`}>
                            {station.score.toFixed(1)}
                          </span>
                        </span>

                        <span className="tw-mt-4 tw-grid tw-grid-cols-3 tw-gap-2">
                          {[
                            [c.stationSessions, formatInt(station.sessions), "tw-text-slate-900"],
                            [c.faultSessions, `${station.faultRate.toFixed(1)}%`, "tw-text-red-700"],
                            ["Recall", `${station.recall.toFixed(1)}%`, "tw-text-emerald-700"],
                          ].map(([label, value, color]) => (
                            <span key={label} className="tw-rounded-xl tw-bg-slate-50 tw-p-2.5 tw-ring-1 tw-ring-slate-100">
                              <span className="tw-block tw-text-[10px] tw-font-bold tw-leading-4 tw-text-slate-500">{label}</span>
                              <span className={`ai-mono tw-mt-0.5 tw-block tw-text-[13px] tw-font-black ${color}`}>{value}</span>
                            </span>
                          ))}
                        </span>

                        <span className="tw-mt-3 tw-flex tw-items-center tw-justify-between tw-gap-3 tw-border-t tw-border-slate-100 tw-pt-3">
                          <span className="tw-min-w-0">
                            <span className="tw-block tw-text-[10px] tw-font-bold tw-uppercase tw-tracking-wide tw-text-slate-400">{c.topFault}</span>
                            <span className="tw-mt-0.5 tw-block tw-truncate tw-text-[12px] tw-font-extrabold tw-text-slate-700">
                              {station.topFaultFamily ? displayFamily(station.topFaultFamily) : "—"}
                            </span>
                          </span>
                          <span className="tw-flex tw-flex-shrink-0 tw-items-center tw-gap-1 tw-text-[12px] tw-font-extrabold tw-text-blue-700">
                            {c.viewStationDetails}
                            <ChevronRight className="tw-h-4 tw-w-4" />
                          </span>
                        </span>
                      </button>
                    );
                  })}
                  {visibleStations.length === 0 && (
                    <div className="tw-flex tw-min-h-[180px] tw-flex-col tw-items-center tw-justify-center tw-gap-3 tw-rounded-2xl tw-border tw-border-dashed tw-border-slate-300 tw-bg-slate-50 tw-p-6 tw-text-center tw-text-[13px] tw-font-semibold tw-text-gray-500">
                      {c.noStations}
                      {otherSplitMatches > 0 && (
                        <button type="button" onClick={() => setStationSplitFilter("all")} className="tw-rounded-lg tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-py-1.5 tw-text-[12px] tw-font-bold tw-text-blue-700 hover:tw-border-blue-300">
                          {c.otherSplitMatches(otherSplitMatches)}
                        </button>
                      )}
                    </div>
                  )}
                </div>

                <div className="tw-hidden tw-max-h-[620px] tw-overflow-auto lg:tw-block">
                  <table className="tw-w-full tw-min-w-[920px] tw-table-fixed tw-border-collapse tw-text-left">
                    <caption className="tw-sr-only">{c.stationTitle}</caption>
                    <thead className="tw-sticky tw-top-0 tw-z-10 tw-bg-gray-900 tw-text-white">
                      <tr>
                        {[
                          { label: c.station, width: "tw-w-[220px]" },
                          { label: c.stationSessions, width: "tw-w-[82px]" },
                          { label: c.faultSessions, width: "tw-w-[92px]" },
                          { label: c.detected, width: "tw-w-[116px]" },
                          { label: c.lateMissed, width: "tw-w-[90px]" },
                          { label: c.falseAlarms, width: "tw-w-[104px]" },
                          { label: c.topFault, width: "tw-w-[130px]" },
                          { label: c.score, width: "tw-w-[74px]" },
                        ].map((heading) => (
                          <th key={heading.label} scope="col" className={`${heading.width} tw-whitespace-normal tw-px-3.5 tw-py-3.5 tw-align-bottom tw-text-[11px] tw-font-bold tw-uppercase tw-leading-tight tw-tracking-wide tw-text-white/65`}>{heading.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {visibleStations.map((station) => {
                        const scoreTone = station.score >= 70
                          ? "tw-bg-emerald-50 tw-text-emerald-700"
                          : station.score >= 50
                            ? "tw-bg-amber-50 tw-text-amber-700"
                            : "tw-bg-red-50 tw-text-red-700";
                        return (
                          <tr
                            key={station.station}
                            onClick={() => setSelectedStationId(station.station)}
                            className="fd-table-row tw-cursor-pointer tw-border-b tw-border-gray-100 last:tw-border-0"
                            title={`${c.viewStationDetails}: ${displayStation(station.station)}`}
                          >
                            <td className="tw-px-3.5 tw-py-3.5">
                              <button
                                type="button"
                                aria-haspopup="dialog"
                                aria-controls="station-analysis-dialog"
                                aria-label={`${c.viewStationDetails}: ${displayStation(station.station)}`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setSelectedStationId(station.station);
                                }}
                                className="tw-group tw-flex tw-w-full tw-items-start tw-gap-2.5 tw-text-left tw-outline-none focus-visible:tw-rounded-lg focus-visible:tw-ring-2 focus-visible:tw-ring-blue-500 focus-visible:tw-ring-offset-2"
                              >
                                <div className="tw-mt-0.5 tw-flex tw-h-9 tw-w-9 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-50 tw-text-blue-700">
                                  <MapPin className="tw-h-4 tw-w-4" />
                                </div>
                                <div className="tw-min-w-0 tw-flex-1">
                                  <div className="tw-truncate tw-text-[13px] tw-font-extrabold tw-text-gray-900" title={station.station}>{displayStation(station.station)}</div>
                                  <div className="tw-mt-0.5 tw-flex tw-min-w-0 tw-items-center tw-gap-1.5 tw-text-[10px] tw-font-semibold tw-uppercase tw-tracking-wider tw-text-gray-400">
                                    {hasTrainStations && <SplitBadge split={stationSplitOf(station)} heldOut={c.badgeHeldOut} train={c.badgeTrain} />}
                                    <span className="tw-truncate">{station.group} · {station.connectors} connector{station.connectors === 1 ? "" : "s"}</span>
                                  </div>
                                </div>
                                <ChevronRight className="tw-mt-2 tw-h-3.5 tw-w-3.5 tw-flex-shrink-0 tw-text-gray-300 tw-transition-transform group-hover:tw-translate-x-0.5 group-hover:tw-text-blue-600" />
                              </button>
                            </td>
                            <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-black tw-text-gray-800">{formatInt(station.sessions)}</td>
                            <td className="tw-px-3.5 tw-py-3.5">
                              <div className="ai-mono tw-text-[13px] tw-font-black tw-text-red-700">{formatInt(station.faultySessions)}</div>
                              <div className="ai-mono tw-mt-0.5 tw-text-[10px] tw-text-gray-400">{station.faultRate.toFixed(1)}%</div>
                            </td>
                            <td className="tw-px-3.5 tw-py-3.5">
                              <div className="ai-mono tw-text-[13px] tw-font-black tw-text-emerald-700">{formatInt(station.tp)}</div>
                              <div className="ai-mono tw-mt-0.5 tw-text-[10px] tw-text-gray-400">Recall {station.recall.toFixed(1)}%</div>
                            </td>
                            <td className="ai-mono tw-whitespace-nowrap tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold tw-text-gray-700">{station.late} / {station.miss}</td>
                            <td className="tw-px-3.5 tw-py-3.5">
                              <div className="ai-mono tw-text-[13px] tw-font-black tw-text-purple-700">{formatInt(station.fp)}</div>
                              <div className="ai-mono tw-mt-0.5 tw-text-[10px] tw-text-gray-400">FAR {station.falseAlarmRate.toFixed(1)}%</div>
                            </td>
                            <td className="tw-px-3.5 tw-py-3.5">
                              <span className="tw-inline-block tw-max-w-full tw-truncate tw-whitespace-nowrap tw-rounded-md tw-bg-gray-100 tw-px-2.5 tw-py-1 tw-text-[10px] tw-font-extrabold tw-text-gray-600" title={station.topFaultFamily ?? undefined}>
                                {station.topFaultFamily ? displayFamily(station.topFaultFamily) : "—"}
                              </span>
                            </td>
                            <td className="tw-px-3.5 tw-py-3.5">
                              <span className={`ai-mono tw-inline-flex tw-min-w-[58px] tw-justify-center tw-rounded-lg tw-px-2.5 tw-py-1.5 tw-text-[13px] tw-font-black ${scoreTone}`}>
                                {station.score.toFixed(1)}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {visibleStations.length === 0 && (
                    <div className="tw-flex tw-min-h-[180px] tw-flex-col tw-items-center tw-justify-center tw-gap-3 tw-p-6 tw-text-[13px] tw-font-semibold tw-text-gray-500">
                      {c.noStations}
                      {otherSplitMatches > 0 && (
                        <button type="button" onClick={() => setStationSplitFilter("all")} className="tw-rounded-lg tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-py-1.5 tw-text-[12px] tw-font-bold tw-text-blue-700 hover:tw-border-blue-300">
                          {c.otherSplitMatches(otherSplitMatches)}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </section>
        )}
      </div>
      <FaultGlossaryDialog open={faultGlossaryOpen} onClose={() => setFaultGlossaryOpen(false)} />
      <StationDetailDialog station={selectedStation} onClose={() => setSelectedStationId(null)} />
    </main>
  );
}
