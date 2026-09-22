"use client";

import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  ChartPie,
  CheckCircle2,
  Clock3,
  Database,
  FileCheck2,
  Gauge,
  Layers3,
  MapPin,
  RadioTower,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TimerReset,
  Upload,
} from "lucide-react";
import {
  FULL_FLEET_LABELS,
  LABEL_LINEAGE,
  MODEL_META,
  MODEL_ORDER,
  RESEARCH_PROFILES,
  RESEARCH_SNAPSHOT,
  SLAC_RESEARCH,
  type ResearchArmId,
  type ResearchModelId,
  type ResearchProfileId,
} from "./research-data";
import type { StationAnalysis } from "./data";

type Lang = "th" | "en";

const COPY = {
  th: {
    verified: "VERIFIED RESEARCH SNAPSHOT",
    title: "ภาพรวมประสิทธิภาพการตรวจจับ Fault",
    subtitle:
      "เปรียบเทียบโมเดล 5 สถาปัตยกรรมบน label policy เดียวกัน พร้อมผลของกฎ ISO 15118-2 และ SLAC จาก ISO 15118-3",
    fullFleet: "Fleet ทั้งหมด",
    scoringSessions: "ใช้ประเมินผล",
    faultLabels: "Fault labels",
    censored: "ตัดออกอย่างมีเหตุผล",
    replay: "Replay ตรงกับ projection",
    profile: "Label snapshot",
    arm: "Detection policy",
    published: "Published",
    strict: "Strict ก่อน review",
    reviewed: "ISO-reviewed",
    publishedNote: "ผล benchmark เดิมที่เผยแพร่ · 8,820 sessions",
    strictNote: "คำนวณ label strict ใหม่ · ยังไม่ตัด censored",
    reviewedNote: "label ที่ review แล้ว · ตัด 295 sessions ที่ตัดสินไม่ได้",
    baseline: "Baseline",
    iso2: "+ ISO 15118-2",
    empirical: "+ SLAC 10 s",
    normative: "+ SLAC 600 ms",
    score: "Score",
    recall: "Recall",
    far: "False alarm",
    lead: "Median lead",
    seconds: "วินาที",
    versusBaseline: "เทียบ baseline",
    unchanged: "ไม่เปลี่ยน",
    bestModel: "คะแนนสูงสุดในมุมมองนี้",
    rescored: "Rescored โมเดลเดิม — ยังไม่ได้ retrain",
    slacTitle: "กฎ SLAC ที่แก้แล้ว",
    slacSub: "แยก response timer ออกจาก match-session timer",
    request: "MATCH.REQ",
    window: "response window",
    retry: "retry",
    hardBudget: "งบเวลาตรวจจับ",
    missingRequest: "ไม่พบ MATCH/VALIDATE หลัง sounding",
    normativeFires: "Normative rule fires",
    responseTimeout: "response timeout",
    sessionTimeout: "missing request",
    publicSource: "Public-source profile",
    publicSourceNote:
      "600 ms เป็นค่าระมัดระวังจาก 3 response windows ไม่ใช่ใบรับรอง conformance",
    lineageTitle: "Label lineage",
    lineageSub: "อย่าเทียบ Published กับ ISO-reviewed โดยข้าม strict snapshot",
    sessions: "sessions",
    faulty: "faulty",
    clean: "clean",
    excluded: "excluded",
    fullFleetTitle: "สัดส่วน Fault ใน Fleet",
    fullFleetSub: "39,142 sessions ใน scoring index · 1,400 censored เก็บไว้แยกต่างหาก",
    faultLabelsTotal: "Fault labels",
    stationFaultTitle: "Fault แยกตามสถานี",
    stationFaultSub: "ผล Agentic AI จาก held-out test 8,820 sessions · คลิกสถานีเพื่อดู Connector และประเภท Fault",
    stationBenchmark: "HELD-OUT BENCHMARK",
    stations: "สถานี",
    stationFaultSessions: "Fault sessions",
    stationFaultRate: "Fault rate",
    stationTopFault: "Fault หลัก",
    stationPieTitle: "สัดส่วน Fault ของสถานี",
    stationPieSub: "เลือกสถานีจากรายการเพื่อดูสัดส่วน Fault แต่ละประเภท",
    stationPieEyebrow: "STATION FAULT MIX",
    faultTypes: "ประเภท Fault",
    noFaultBreakdown: "สถานีนี้ไม่มี Fault ในชุดทดสอบ",
    openStationDetails: "เปิดรายละเอียดเชิงลึก",
    loadingStations: "กำลังโหลดผลรายสถานี",
    stationLoadFailed: "โหลดข้อมูล Fault รายสถานีไม่สำเร็จ",
    noStationData: "ยังไม่มีข้อมูล Fault รายสถานี",
    retryLoad: "ลองอีกครั้ง",
    viewAllStations: "ดูครบทุกสถานี",
    viewStation: "ดูรายละเอียดสถานี",
    evidenceTitle: "ความน่าเชื่อถือของหลักฐาน",
    corroborated: "ข้อค้นพบที่ยืนยันข้ามแหล่ง",
    pending: "รอยืนยันเพิ่มเติม",
    completedAgents: "research jobs สำเร็จ",
    quotaStopped: "หยุดเพราะ quota",
    evidenceNote:
      "ใช้เฉพาะข้อมูลจากแหล่งสาธารณะและโค้ด open source; รายการ pending ไม่ถูกใช้ตั้ง hard threshold",
    stationCta: "ผลรายสถานี",
    pcapCta: "วิเคราะห์ PCAP",
    updated: "ตรวจสอบล่าสุด",
  },
  en: {
    verified: "VERIFIED RESEARCH SNAPSHOT",
    title: "Fault-detection performance overview",
    subtitle:
      "Compare five model architectures under the same label policy, including ISO 15118-2 rules and ISO 15118-3 SLAC timing.",
    fullFleet: "Full fleet",
    scoringSessions: "Scoring cohort",
    faultLabels: "Fault labels",
    censored: "Evidence-based exclusions",
    replay: "Projection–replay agreement",
    profile: "Label snapshot",
    arm: "Detection policy",
    published: "Published",
    strict: "Pre-review strict",
    reviewed: "ISO-reviewed",
    publishedNote: "Original published benchmark · 8,820 sessions",
    strictNote: "Recomputed strict labels · no censorship",
    reviewedNote: "Reviewed labels · 295 inconclusive sessions excluded",
    baseline: "Baseline",
    iso2: "+ ISO 15118-2",
    empirical: "+ SLAC 10 s",
    normative: "+ SLAC 600 ms",
    score: "Score",
    recall: "Recall",
    far: "False alarm",
    lead: "Median lead",
    seconds: "seconds",
    versusBaseline: "vs baseline",
    unchanged: "unchanged",
    bestModel: "Highest score in this view",
    rescored: "Existing models rescored — not retrained",
    slacTitle: "Corrected SLAC rule",
    slacSub: "Response and match-session timers are evaluated separately",
    request: "MATCH.REQ",
    window: "response window",
    retry: "retry",
    hardBudget: "Detection budget",
    missingRequest: "No MATCH/VALIDATE after sounding",
    normativeFires: "Normative rule fires",
    responseTimeout: "response timeout",
    sessionTimeout: "missing request",
    publicSource: "Public-source profile",
    publicSourceNote:
      "600 ms is a conservative three-window budget, not a conformance certification.",
    lineageTitle: "Label lineage",
    lineageSub: "Published and ISO-reviewed results must be compared through the strict snapshot",
    sessions: "sessions",
    faulty: "faulty",
    clean: "clean",
    excluded: "excluded",
    fullFleetTitle: "Fault distribution · full fleet",
    fullFleetSub: "39,142 sessions in the scoring index · 1,400 censored records retained separately",
    faultLabelsTotal: "Fault labels",
    stationFaultTitle: "Faults by station",
    stationFaultSub: "Agentic AI results from 8,820 held-out sessions · select a station for connector and fault details",
    stationBenchmark: "HELD-OUT BENCHMARK",
    stations: "Stations",
    stationFaultSessions: "Fault sessions",
    stationFaultRate: "Fault rate",
    stationTopFault: "Top fault",
    stationPieTitle: "Station fault distribution",
    stationPieSub: "Select a station to inspect its fault-family mix.",
    stationPieEyebrow: "STATION FAULT MIX",
    faultTypes: "Fault types",
    noFaultBreakdown: "This station has no faults in the held-out set.",
    openStationDetails: "Open detailed analysis",
    loadingStations: "Loading station results",
    stationLoadFailed: "Unable to load station fault data",
    noStationData: "No station fault data is available yet.",
    retryLoad: "Try again",
    viewAllStations: "View all stations",
    viewStation: "View station details",
    evidenceTitle: "Evidence confidence",
    corroborated: "Cross-source corroborated",
    pending: "Pending verification",
    completedAgents: "research jobs complete",
    quotaStopped: "stopped at quota",
    evidenceNote:
      "Only public sources and open-source code were used; pending findings do not set hard thresholds.",
    stationCta: "Station results",
    pcapCta: "Analyze PCAP",
    updated: "Verified",
  },
} as const;

const MODEL_TONES: Record<ResearchModelId, { bar: string; badge: string }> = {
  TraditionalAI: { bar: "tw-bg-sky-500", badge: "tw-bg-sky-50 tw-text-sky-700 tw-ring-sky-100" },
  RL: { bar: "tw-bg-violet-500", badge: "tw-bg-violet-50 tw-text-violet-700 tw-ring-violet-100" },
  AIAgent: { bar: "tw-bg-emerald-500", badge: "tw-bg-emerald-50 tw-text-emerald-700 tw-ring-emerald-100" },
  AgenticAI: { bar: "tw-bg-amber-500", badge: "tw-bg-amber-50 tw-text-amber-800 tw-ring-amber-100" },
  MultiAgent: { bar: "tw-bg-rose-500", badge: "tw-bg-rose-50 tw-text-rose-700 tw-ring-rose-100" },
};

const FAULT_DISTRIBUTION_COLORS: Record<string, string> = {
  NO_POWER_DELIVERED: "#dc2626",
  PROTOCOL_FAILED: "#2563eb",
  SLAC_FAILURE: "#ea580c",
  SESSION_ABORT: "#7c3aed",
  COMM_FREEZE: "#0891b2",
  EV_ERROR: "#16a34a",
  EVSE_FAULT: "#db2777",
  ISOLATION_FAULT: "#ca8a04",
  EVSE_PROCESSING_STALL: "#475569",
};

const FALLBACK_FAULT_COLORS = ["#dc2626", "#2563eb", "#ea580c", "#7c3aed", "#0891b2", "#16a34a", "#db2777", "#ca8a04", "#475569"] as const;

const formatInt = (value: number) => new Intl.NumberFormat("en-US").format(value);

const formatFaultFamily = (family: string) => family.replaceAll("_", " ");

type FaultCountItem = {
  family: string;
  sessions: number;
};

type FaultSlice = FaultCountItem & {
  color: string;
  percentage: number;
};

const buildFaultSlices = (items: FaultCountItem[], total: number): FaultSlice[] =>
  items.map((item, index) => ({
    ...item,
    color: FAULT_DISTRIBUTION_COLORS[item.family] ?? FALLBACK_FAULT_COLORS[index % FALLBACK_FAULT_COLORS.length],
    percentage: total > 0 ? item.sessions / total * 100 : 0,
  }));

function FaultDonut({
  slices,
  total,
  totalLabel,
  size = "fleet",
}: {
  slices: FaultSlice[];
  total: number;
  totalLabel: string;
  size?: "fleet" | "station";
}) {
  const radius = 63;
  const circumference = 2 * Math.PI * radius;
  let runningTotal = 0;
  const segments = slices.map((item) => {
    const start = runningTotal;
    runningTotal += item.sessions;
    const segmentLength = total > 0 ? item.sessions / total * circumference : 0;
    return {
      ...item,
      dashLength: Math.max(segmentLength - Math.min(1.5, segmentLength * 0.2), 0.3),
      dashOffset: total > 0 ? -(start / total) * circumference : 0,
    };
  });
  const accessibleSummary = slices
    .map((item) => `${formatFaultFamily(item.family)} ${item.percentage.toFixed(1)}%`)
    .join(", ");
  const sizing = size === "fleet"
    ? "tw-h-[250px] tw-w-[250px] sm:tw-h-[300px] sm:tw-w-[300px]"
    : "tw-h-[220px] tw-w-[220px] sm:tw-h-[250px] sm:tw-w-[250px]";
  const totalSize = size === "fleet" ? "tw-text-[34px] sm:tw-text-[38px]" : "tw-text-[29px] sm:tw-text-[32px]";

  return (
    <div className={`fd-donut-shell tw-relative tw-mx-auto ${sizing}`} role="img" aria-label={`${totalLabel}: ${accessibleSummary || "0"}`}>
      <div className="fd-donut-backplate tw-absolute tw-inset-[7%] tw-rounded-full" />
      <svg viewBox="0 0 180 180" className="fd-donut-svg tw-relative tw-h-full tw-w-full" aria-hidden="true">
        <circle cx="90" cy="90" r={radius} fill="none" stroke="#f1f5f9" strokeWidth="27" />
        {segments.map((item) => (
          <circle
            key={item.family}
            className="fd-pie-segment"
            cx="90"
            cy="90"
            r={radius}
            fill="none"
            stroke={item.color}
            strokeWidth="26"
            strokeDasharray={`${item.dashLength} ${circumference - item.dashLength}`}
            strokeDashoffset={item.dashOffset}
            transform="rotate(-90 90 90)"
          >
            <title>{`${formatFaultFamily(item.family)} · ${formatInt(item.sessions)} · ${item.percentage.toFixed(1)}%`}</title>
          </circle>
        ))}
        <circle cx="90" cy="90" r="45" fill="#ffffff" stroke="#e2e8f0" strokeWidth="1" />
      </svg>
      <div className="tw-pointer-events-none tw-absolute tw-inset-0 tw-flex tw-flex-col tw-items-center tw-justify-center tw-text-center">
        <span className={`ai-mono tw-font-extrabold tw-leading-none tw-text-slate-950 ${totalSize}`}>{formatInt(total)}</span>
        <span className="tw-mt-2 tw-max-w-[116px] tw-text-[11px] tw-font-semibold tw-leading-4 tw-text-slate-500">{totalLabel}</span>
      </div>
    </div>
  );
}

function FaultDistributionChart({ totalLabel }: { totalLabel: string }) {
  const total = FULL_FLEET_LABELS.faulty;
  const slices = buildFaultSlices(FULL_FLEET_LABELS.distribution, total);

  return (
    <div className="fd-fault-distribution tw-grid tw-items-center tw-gap-6 lg:tw-grid-cols-[340px_minmax(0,1fr)] lg:tw-gap-8">
      <div className="fd-donut-stage tw-relative tw-overflow-hidden tw-rounded-[24px] tw-border tw-border-slate-200 tw-bg-white tw-p-5 sm:tw-p-6">
        <div className="tw-relative tw-mb-1 tw-flex tw-items-center tw-justify-between tw-gap-3">
          <span className="tw-text-[10px] tw-font-bold tw-text-slate-500">Fault distribution</span>
          <span className="ai-mono tw-rounded-full tw-bg-slate-100 tw-px-2.5 tw-py-1 tw-text-[9px] tw-font-bold tw-text-slate-600 tw-ring-1 tw-ring-slate-200">{slices.length} types</span>
        </div>
        <FaultDonut slices={slices} total={total} totalLabel={totalLabel} />
        <div className="tw-relative tw-mt-2 tw-flex tw-items-center tw-justify-between tw-gap-3 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-slate-50 tw-px-3.5 tw-py-3">
          <span className="tw-flex tw-min-w-0 tw-items-center tw-gap-2 tw-text-[10px] tw-font-bold tw-text-slate-700">
            <span className="tw-h-2.5 tw-w-2.5 tw-flex-shrink-0 tw-rounded-full" style={{ backgroundColor: slices[0].color }} />
            <span className="tw-truncate">Top fault · {formatFaultFamily(slices[0].family)}</span>
          </span>
          <span className="ai-mono tw-flex-shrink-0 tw-text-[11px] tw-font-extrabold" style={{ color: slices[0].color }}>{slices[0].percentage.toFixed(1)}%</span>
        </div>
      </div>

      <div className="tw-grid tw-gap-x-5 tw-gap-y-1 sm:tw-grid-cols-2">
        {slices.map((item) => (
          <div key={item.family} className="fd-fault-legend-row tw-group tw-min-h-[58px] tw-border-b tw-border-slate-100 tw-px-1 tw-py-3">
            <div className="tw-flex tw-items-center tw-gap-2.5">
              <span className="tw-h-3 tw-w-3 tw-flex-shrink-0 tw-rounded-full tw-ring-4 tw-ring-white" style={{ backgroundColor: item.color }} />
              <div className="tw-min-w-0 tw-flex-1">
                <div className="tw-pr-1 tw-text-[10px] tw-font-bold tw-leading-[14px] tw-text-slate-700" title={item.family}>{formatFaultFamily(item.family)}</div>
                <div className="tw-mt-1.5 tw-h-1 tw-overflow-hidden tw-rounded-full tw-bg-slate-100">
                  <div className="tw-h-full tw-rounded-full" style={{ width: `${item.percentage}%`, backgroundColor: item.color }} />
                </div>
              </div>
              <div className="tw-flex-shrink-0 tw-text-right">
                <div className="ai-mono tw-text-base tw-font-extrabold tw-text-slate-950">{formatInt(item.sessions)}</div>
                <div className="ai-mono tw-text-[9px] tw-font-bold" style={{ color: item.color }}>{item.percentage.toFixed(1)}%</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const displayStationName = (station: string) =>
  station
    .replace(/^\d+_/, "")
    .replaceAll("_", " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2");

function StationFaultDistributionChart({
  lang,
  stations,
  station,
  loading,
  error,
  onChangeStation,
  onOpenDetails,
}: {
  lang: Lang;
  stations: StationAnalysis[];
  station: StationAnalysis | null;
  loading: boolean;
  error: string | null;
  onChangeStation: (stationId: string) => void;
  onOpenDetails: (stationId: string) => void;
}) {
  const c = COPY[lang];
  const stationOptions = useMemo(
    () => [...stations].sort((left, right) => left.station.localeCompare(right.station, undefined, { numeric: true })),
    [stations],
  );
  const slices = useMemo(() => {
    if (!station) return [];
    return buildFaultSlices(
      station.byFaultFamily
        .filter((item) => item.faultySessions > 0)
        .map((item) => ({ family: item.family, sessions: item.faultySessions }))
        .sort((left, right) => right.sessions - left.sessions),
      station.faultySessions,
    );
  }, [station]);

  return (
    <div className="fd-station-pie-card fd-panel">
      <div className="tw-border-b tw-border-slate-100 tw-p-5 sm:tw-p-6">
        <div className="tw-flex tw-items-start tw-gap-3">
          <span className="tw-flex tw-h-10 tw-w-10 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-50 tw-text-blue-700 tw-ring-1 tw-ring-blue-100"><ChartPie className="tw-h-4 tw-w-4" /></span>
          <div className="tw-min-w-0">
            <div className="tw-text-[9px] tw-font-extrabold tw-uppercase tw-tracking-[0.14em] tw-text-blue-600">{c.stationPieEyebrow}</div>
            <h3 className="tw-mt-1 tw-text-base tw-font-black tw-text-slate-950">{c.stationPieTitle}</h3>
            <p className="tw-mt-1 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.stationPieSub}</p>
          </div>
        </div>
        {stations.length > 0 && (
          <label className="tw-mt-4 tw-block">
            <span className="tw-sr-only">{c.stations}</span>
            <select
              value={station?.station ?? ""}
              onChange={(event) => onChangeStation(event.target.value)}
              className="tw-h-11 tw-w-full tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-text-[11px] tw-font-bold tw-text-slate-800 tw-outline-none tw-transition focus:tw-border-blue-400 focus:tw-ring-4 focus:tw-ring-blue-100"
            >
              {stationOptions.map((option) => (
                <option key={option.station} value={option.station}>
                  {displayStationName(option.station)} · {formatInt(option.faultySessions)} faults
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="tw-p-5 sm:tw-p-6">
        {loading && !station ? (
          <div className="tw-flex tw-min-h-[420px] tw-items-center tw-justify-center" role="status" aria-label={c.loadingStations}>
            <div className="tw-h-10 tw-w-10 tw-animate-spin tw-rounded-full tw-border-4 tw-border-blue-100 tw-border-t-blue-600" />
          </div>
        ) : error && !station ? (
          <div className="tw-flex tw-min-h-[420px] tw-flex-col tw-items-center tw-justify-center tw-rounded-2xl tw-bg-red-50 tw-p-6 tw-text-center">
            <AlertTriangle className="tw-h-6 tw-w-6 tw-text-red-600" />
            <div className="tw-mt-3 tw-text-sm tw-font-black tw-text-red-950">{c.stationLoadFailed}</div>
          </div>
        ) : station ? (
          <>
            <div className="tw-flex tw-items-start tw-justify-between tw-gap-3">
              <div className="tw-min-w-0">
                <div className="tw-truncate tw-text-sm tw-font-black tw-text-slate-950" title={station.station}>{displayStationName(station.station)}</div>
                <div className="tw-mt-1 tw-text-[10px] tw-font-semibold tw-text-slate-400">{station.group} · {formatInt(station.sessions)} sessions · {station.connectors} connector{station.connectors === 1 ? "" : "s"}</div>
              </div>
              <span className="ai-mono tw-flex-shrink-0 tw-rounded-lg tw-bg-red-50 tw-px-2.5 tw-py-1.5 tw-text-[11px] tw-font-black tw-text-red-700 tw-ring-1 tw-ring-red-100">{station.faultRate.toFixed(1)}%</span>
            </div>

            <div className="fd-station-donut-stage tw-relative tw-mt-5 tw-overflow-hidden tw-rounded-[24px] tw-border tw-border-slate-200 tw-bg-white tw-p-5">
              <FaultDonut slices={slices} total={station.faultySessions} totalLabel={c.stationFaultSessions} size="station" />
              <div className="tw-relative tw-mt-2 tw-grid tw-grid-cols-2 tw-divide-x tw-divide-slate-200 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-slate-50 tw-py-3 tw-text-center">
                <span className="tw-px-2">
                  <span className="ai-mono tw-block tw-text-sm tw-font-extrabold tw-text-slate-950">{slices.length}</span>
                  <span className="tw-mt-0.5 tw-block tw-text-[9px] tw-font-semibold tw-text-slate-500">{c.faultTypes}</span>
                </span>
                <span className="tw-min-w-0 tw-px-2">
                  <span className="tw-block tw-truncate tw-text-[10px] tw-font-bold tw-text-slate-800">{station.topFaultFamily ? formatFaultFamily(station.topFaultFamily) : "—"}</span>
                  <span className="tw-mt-0.5 tw-block tw-text-[9px] tw-font-semibold tw-text-slate-500">Top fault</span>
                </span>
              </div>
            </div>

            {slices.length > 0 ? (
              <div className="tw-mt-4 tw-divide-y tw-divide-slate-100 tw-overflow-hidden tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white">
                {slices.map((item) => (
                  <div key={item.family} className="fd-fault-legend-row tw-grid tw-grid-cols-[10px_minmax(0,1fr)_auto] tw-items-center tw-gap-2.5 tw-px-3 tw-py-3">
                    <span className="tw-h-2.5 tw-w-2.5 tw-rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="tw-min-w-0 tw-truncate tw-text-[10px] tw-font-bold tw-text-slate-700" title={item.family}>{formatFaultFamily(item.family)}</span>
                    <span className="tw-text-right">
                      <span className="ai-mono tw-block tw-text-[12px] tw-font-extrabold tw-text-slate-900">{formatInt(item.sessions)}</span>
                      <span className="ai-mono tw-block tw-text-[9px] tw-font-bold" style={{ color: item.color }}>{item.percentage.toFixed(1)}%</span>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="tw-mt-4 tw-rounded-xl tw-bg-slate-50 tw-p-4 tw-text-center tw-text-[11px] tw-font-semibold tw-text-slate-500">{c.noFaultBreakdown}</div>
            )}

            <button
              type="button"
              onClick={() => onOpenDetails(station.station)}
              className="tw-mt-4 tw-flex tw-min-h-11 tw-w-full tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-slate-950 tw-px-4 tw-text-[11px] tw-font-bold tw-text-white tw-shadow-lg tw-shadow-slate-950/10 tw-transition hover:tw-bg-slate-800 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-slate-200"
            >
              {c.openStationDetails} <ArrowRight className="tw-h-3.5 tw-w-3.5" />
            </button>
          </>
        ) : (
          <div className="tw-flex tw-min-h-[420px] tw-items-center tw-justify-center tw-rounded-2xl tw-bg-slate-50 tw-p-6 tw-text-center tw-text-[11px] tw-font-semibold tw-text-slate-500">{c.noStationData}</div>
        )}
      </div>
    </div>
  );
}

function StationFaultSummary({
  lang,
  stations,
  loading,
  error,
  onRetry,
  onOpenStations,
  selectedStationId,
  onPreviewStation,
}: {
  lang: Lang;
  stations: StationAnalysis[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpenStations: () => void;
  selectedStationId: string | null;
  onPreviewStation: (stationId: string) => void;
}) {
  const c = COPY[lang];
  const rankedStations = useMemo(
    () => [...stations].sort((left, right) =>
      right.faultySessions - left.faultySessions ||
      right.faultRate - left.faultRate ||
      left.station.localeCompare(right.station, undefined, { numeric: true })),
    [stations],
  );
  const totalFaults = stations.reduce((total, station) => total + station.faultySessions, 0);
  const maxFaults = rankedStations[0]?.faultySessions || 1;

  return (
    <div className="fd-station-summary-card fd-panel">
      <div className="tw-flex tw-flex-col tw-gap-4 tw-border-b tw-border-slate-100 tw-p-5 sm:tw-flex-row sm:tw-items-start sm:tw-justify-between sm:tw-p-6">
        <div className="tw-flex tw-items-start tw-gap-3">
          <span className="tw-flex tw-h-10 tw-w-10 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-50 tw-text-blue-700 tw-ring-1 tw-ring-blue-100">
            <MapPin className="tw-h-4 tw-w-4" />
          </span>
          <div>
            <div className="tw-text-[9px] tw-font-extrabold tw-uppercase tw-tracking-[0.14em] tw-text-blue-600">{c.stationBenchmark}</div>
            <h3 className="tw-mt-1 tw-text-base tw-font-black tw-text-slate-950">{c.stationFaultTitle}</h3>
            <p className="tw-mt-1 tw-max-w-2xl tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.stationFaultSub}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onOpenStations}
          className="tw-inline-flex tw-min-h-10 tw-flex-shrink-0 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3.5 tw-text-[11px] tw-font-bold tw-text-slate-700 tw-shadow-sm tw-transition hover:tw-border-blue-300 hover:tw-text-blue-700 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-blue-100"
        >
          {c.viewAllStations} <ArrowRight className="tw-h-3.5 tw-w-3.5" />
        </button>
      </div>

      <div className="tw-p-4 sm:tw-p-5">
        {loading && stations.length === 0 ? (
          <div className="tw-space-y-2" role="status" aria-label={c.loadingStations}>
            {[0, 1, 2, 3, 4].map((item) => (
              <div key={item} className="tw-h-[74px] tw-animate-pulse tw-rounded-xl tw-bg-slate-100" />
            ))}
          </div>
        ) : error && stations.length === 0 ? (
          <div className="tw-flex tw-min-h-[260px] tw-flex-col tw-items-center tw-justify-center tw-rounded-2xl tw-border tw-border-red-100 tw-bg-red-50/70 tw-p-6 tw-text-center">
            <AlertTriangle className="tw-h-6 tw-w-6 tw-text-red-600" />
            <div className="tw-mt-3 tw-text-sm tw-font-black tw-text-red-950">{c.stationLoadFailed}</div>
            <p className="tw-mt-1 tw-max-w-md tw-break-words tw-text-[11px] tw-leading-5 tw-text-red-700">{error}</p>
            <button type="button" onClick={onRetry} className="tw-mt-4 tw-inline-flex tw-min-h-10 tw-items-center tw-gap-2 tw-rounded-xl tw-bg-red-700 tw-px-4 tw-text-[11px] tw-font-bold tw-text-white hover:tw-bg-red-800 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-red-100">
              <RefreshCw className="tw-h-3.5 tw-w-3.5" /> {c.retryLoad}
            </button>
          </div>
        ) : stations.length === 0 ? (
          <div className="tw-flex tw-min-h-[260px] tw-items-center tw-justify-center tw-rounded-2xl tw-bg-slate-50 tw-p-6 tw-text-center tw-text-[12px] tw-font-semibold tw-text-slate-500">
            {c.noStationData}
          </div>
        ) : (
          <>
            <div className="tw-mb-3 tw-grid tw-grid-cols-2 tw-gap-2">
              <div className="tw-rounded-xl tw-bg-blue-50 tw-px-3.5 tw-py-3 tw-ring-1 tw-ring-blue-100">
                <div className="ai-mono tw-text-xl tw-font-black tw-text-blue-900">{formatInt(stations.length)}</div>
                <div className="tw-mt-0.5 tw-text-[10px] tw-font-bold tw-text-blue-700">{c.stations}</div>
              </div>
              <div className="tw-rounded-xl tw-bg-red-50 tw-px-3.5 tw-py-3 tw-ring-1 tw-ring-red-100">
                <div className="ai-mono tw-text-xl tw-font-black tw-text-red-900">{formatInt(totalFaults)}</div>
                <div className="tw-mt-0.5 tw-text-[10px] tw-font-bold tw-text-red-700">{c.stationFaultSessions}</div>
              </div>
            </div>

            <div className="tw-mb-1.5 tw-hidden tw-grid-cols-[30px_minmax(180px,1fr)_92px_minmax(130px,0.8fr)_18px] tw-gap-x-3 tw-px-3 tw-text-[9px] tw-font-extrabold tw-uppercase tw-tracking-wider tw-text-slate-400 sm:tw-grid">
              <span aria-hidden="true" />
              <span>{c.stations}</span>
              <span className="tw-text-right">{c.stationFaultSessions}<br />{c.stationFaultRate}</span>
              <span>{c.stationTopFault}</span>
              <span aria-hidden="true" />
            </div>

            <div className="fd-station-summary-scroll tw-max-h-[500px] tw-space-y-1.5 tw-overflow-y-auto tw-pr-1 lg:tw-max-h-[640px]" aria-label={c.stationFaultTitle}>
              {rankedStations.map((station, index) => (
                <button
                  key={station.station}
                  type="button"
                  onClick={() => onPreviewStation(station.station)}
                  aria-pressed={selectedStationId === station.station}
                  aria-label={`${c.stationPieTitle}: ${displayStationName(station.station)}, ${c.stationFaultSessions} ${formatInt(station.faultySessions)}, ${c.stationFaultRate} ${station.faultRate.toFixed(1)}%`}
                  className={`fd-station-summary-row tw-grid tw-w-full tw-grid-cols-[30px_minmax(0,1fr)_auto] tw-items-center tw-gap-x-3 tw-gap-y-2 tw-rounded-xl tw-border tw-p-3 tw-text-left tw-outline-none tw-transition focus-visible:tw-ring-4 focus-visible:tw-ring-blue-100 sm:tw-grid-cols-[30px_minmax(180px,1fr)_92px_minmax(130px,0.8fr)_18px] ${selectedStationId === station.station ? "tw-border-blue-400 tw-bg-blue-50/70 tw-ring-2 tw-ring-blue-100" : "tw-border-slate-200 tw-bg-white hover:tw-border-blue-200 hover:tw-bg-blue-50/40"}`}>
                  <span className="ai-mono tw-flex tw-h-7 tw-w-7 tw-items-center tw-justify-center tw-rounded-lg tw-bg-slate-100 tw-text-[10px] tw-font-bold tw-text-slate-500">{index + 1}</span>
                  <span className="tw-min-w-0">
                    <span className="tw-block tw-truncate tw-text-[12px] tw-font-black tw-text-slate-900" title={station.station}>{displayStationName(station.station)}</span>
                    <span className="ai-mono tw-mt-0.5 tw-block tw-text-[9px] tw-font-semibold tw-text-slate-400">{formatInt(station.sessions)} sessions · {station.connectors} connector{station.connectors === 1 ? "" : "s"}</span>
                  </span>
                  <span className="tw-text-right">
                    <span className="ai-mono tw-block tw-text-[13px] tw-font-black tw-text-red-700">{formatInt(station.faultySessions)}</span>
                    <span className="ai-mono tw-block tw-text-[9px] tw-font-semibold tw-text-slate-400">{station.faultRate.toFixed(1)}%</span>
                  </span>
                  <span className="tw-col-span-2 tw-col-start-2 tw-min-w-0 sm:tw-col-auto sm:tw-col-span-1">
                    <span className="tw-inline-block tw-max-w-full tw-truncate tw-rounded-md tw-bg-slate-100 tw-px-2 tw-py-1 tw-text-[9px] tw-font-extrabold tw-uppercase tw-text-slate-600" title={station.topFaultFamily ?? undefined}>
                      {station.topFaultFamily ? formatFaultFamily(station.topFaultFamily) : "—"}
                    </span>
                  </span>
                  <ChartPie className={`tw-hidden tw-h-3.5 tw-w-3.5 sm:tw-block ${selectedStationId === station.station ? "tw-text-blue-600" : "tw-text-slate-300"}`} />
                  <span className="tw-col-span-2 tw-col-start-2 tw-h-1.5 tw-overflow-hidden tw-rounded-full tw-bg-slate-100 sm:tw-col-span-3" aria-hidden="true">
                    <span className="tw-block tw-h-full tw-rounded-full tw-bg-red-500" style={{ width: `${station.faultySessions / maxFaults * 100}%` }} />
                  </span>
                </button>
              ))}
            </div>

            {error && (
              <button type="button" onClick={onRetry} className="tw-mt-3 tw-flex tw-w-full tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-amber-50 tw-p-2.5 tw-text-[10px] tw-font-bold tw-text-amber-800 tw-ring-1 tw-ring-amber-100">
                <RefreshCw className="tw-h-3.5 tw-w-3.5" /> {c.stationLoadFailed} · {c.retryLoad}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function DashboardStat({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: "blue" | "red" | "amber" | "emerald";
}) {
  const tones = {
    blue: "tw-bg-blue-50 tw-text-blue-700 tw-ring-blue-100",
    red: "tw-bg-red-50 tw-text-red-700 tw-ring-red-100",
    amber: "tw-bg-amber-50 tw-text-amber-800 tw-ring-amber-100",
    emerald: "tw-bg-emerald-50 tw-text-emerald-700 tw-ring-emerald-100",
  } as const;
  return (
    <div className="fd-stat-card tw-rounded-2xl tw-border tw-border-slate-200/90 tw-bg-white tw-p-4 tw-shadow-sm sm:tw-p-5">
      <div className="tw-flex tw-items-center tw-justify-between tw-gap-3">
        <span className={`tw-flex tw-h-9 tw-w-9 tw-items-center tw-justify-center tw-rounded-xl tw-ring-1 ${tones[tone]}`}>
          {icon}
        </span>
        <span className="ai-mono tw-text-[11px] tw-font-semibold tw-uppercase tw-tracking-wider tw-text-slate-400">{detail}</span>
      </div>
      <div className="ai-mono tw-mt-3.5 tw-text-2xl tw-font-black tw-tracking-tight tw-text-slate-950 sm:tw-text-3xl">{value}</div>
      <div className="tw-mt-1.5 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-slate-500">{label}</div>
    </div>
  );
}

export default function ResearchDashboard({
  lang,
  stations,
  stationLoading,
  stationError,
  onRetryStations,
  onSelectStation,
  onOpenStations,
  onOpenPcap,
}: {
  lang: Lang;
  stations: StationAnalysis[];
  stationLoading: boolean;
  stationError: string | null;
  onRetryStations: () => void;
  onSelectStation: (stationId: string) => void;
  onOpenStations: () => void;
  onOpenPcap?: () => void;
}) {
  const c = COPY[lang];
  const [profileId, setProfileId] = useState<ResearchProfileId>("published");
  const [armId, setArmId] = useState<ResearchArmId>("normative");
  const [selectedSummaryStationId, setSelectedSummaryStationId] = useState<string | null>(null);
  const profile = RESEARCH_PROFILES[profileId];
  const rows = useMemo(
    () => MODEL_ORDER.map((id) => ({
      id,
      current: profile.arms[armId][id],
      baseline: profile.arms.baseline[id],
    })).sort((left, right) => right.current.score - left.current.score),
    [armId, profile],
  );
  const topModel = rows[0];
  const selectedSummaryStation = useMemo(
    () => stations.find((station) => station.station === selectedSummaryStationId)
      ?? [...stations].sort((left, right) =>
        right.faultySessions - left.faultySessions || left.station.localeCompare(right.station, undefined, { numeric: true }))[0]
      ?? null,
    [selectedSummaryStationId, stations],
  );
  const profileLabels: Record<ResearchProfileId, { label: string; note: string }> = {
    published: { label: c.published, note: c.publishedNote },
    strict: { label: c.strict, note: c.strictNote },
    reviewed: { label: c.reviewed, note: c.reviewedNote },
  };
  const armLabels: Record<ResearchArmId, string> = {
    baseline: c.baseline,
    iso2: c.iso2,
    empirical: c.empirical,
    normative: c.normative,
  };
  const verifiedDate = new Intl.DateTimeFormat(lang === "th" ? "th-TH" : "en-GB", {
    dateStyle: "medium",
  }).format(new Date(RESEARCH_SNAPSHOT));

  return (
    <div className="tw-space-y-4 sm:tw-space-y-6">
      <section className="fd-panel tw-overflow-hidden">
        <div className="tw-flex tw-flex-col tw-gap-5 tw-border-b tw-border-slate-100 tw-p-5 sm:tw-p-6 lg:tw-flex-row lg:tw-items-end lg:tw-justify-between">
          <div>
            <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-2">
              <span className="tw-inline-flex tw-items-center tw-gap-1.5 tw-rounded-full tw-bg-emerald-50 tw-px-2.5 tw-py-1 tw-text-[10px] tw-font-bold tw-uppercase tw-tracking-[0.14em] tw-text-emerald-700 tw-ring-1 tw-ring-emerald-100 sm:tw-text-[11px]">
                <CheckCircle2 className="tw-h-3.5 tw-w-3.5" /> {c.verified}
              </span>
              <span className="ai-mono tw-text-[10px] tw-font-semibold tw-text-slate-400 sm:tw-text-[11px]">{c.updated}: {verifiedDate}</span>
            </div>
            <h2 className="fd-display tw-mt-3 tw-text-xl tw-font-black tw-tracking-tight tw-text-slate-950 sm:tw-text-2xl">{c.title}</h2>
            <p className="tw-mt-2 tw-max-w-3xl tw-text-[13px] tw-font-normal tw-leading-6 tw-text-slate-500 sm:tw-text-sm">{c.subtitle}</p>
          </div>
          <div className={`tw-grid tw-w-full tw-gap-2 lg:tw-flex lg:tw-w-auto lg:tw-flex-wrap ${onOpenPcap ? "tw-grid-cols-2" : "tw-grid-cols-1"}`}>
            <button type="button" onClick={onOpenStations} className="tw-inline-flex tw-min-h-11 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-border tw-border-slate-200 tw-bg-white tw-px-3 tw-py-2.5 tw-text-[11px] tw-font-bold tw-text-slate-700 tw-shadow-sm tw-transition hover:tw-border-blue-300 hover:tw-text-blue-700 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-blue-100 sm:tw-px-4 sm:tw-text-[12px]">
              <BarChart3 className="tw-h-4 tw-w-4" /> {c.stationCta}
            </button>
            {onOpenPcap && (
              <button type="button" onClick={onOpenPcap} className="tw-inline-flex tw-min-h-11 tw-items-center tw-justify-center tw-gap-2 tw-rounded-xl tw-bg-slate-950 tw-px-3 tw-py-2.5 tw-text-[11px] tw-font-bold tw-text-white tw-shadow-lg tw-shadow-slate-950/10 tw-transition hover:tw-bg-slate-800 focus:tw-outline-none focus:tw-ring-4 focus:tw-ring-slate-200 sm:tw-px-4 sm:tw-text-[12px]">
                <Upload className="tw-h-4 tw-w-4 tw-text-amber-300" /> {c.pcapCta}
              </button>
            )}
          </div>
        </div>

        <div className="tw-grid tw-grid-cols-2 tw-gap-2.5 tw-bg-slate-50/70 tw-p-4 sm:tw-grid-cols-4 sm:tw-gap-3 sm:tw-p-6">
          <DashboardStat icon={<Database className="tw-h-4 tw-w-4" />} label={c.fullFleet} value={formatInt(FULL_FLEET_LABELS.sessions)} detail="100%" tone="blue" />
          <DashboardStat icon={<FileCheck2 className="tw-h-4 tw-w-4" />} label={c.scoringSessions} value={formatInt(FULL_FLEET_LABELS.scoring)} detail="96.5%" tone="emerald" />
          <DashboardStat icon={<AlertTriangle className="tw-h-4 tw-w-4" />} label={c.faultLabels} value={formatInt(FULL_FLEET_LABELS.faulty)} detail="15.1%" tone="red" />
          <DashboardStat icon={<ShieldCheck className="tw-h-4 tw-w-4" />} label={c.censored} value={formatInt(FULL_FLEET_LABELS.censored)} detail="3.5%" tone="amber" />
        </div>
      </section>

      <section className="fd-overview-summary-grid tw-grid tw-grid-cols-1 tw-gap-5">
        <div className="fd-fault-mix-card fd-panel">
          <div className="tw-border-b tw-border-slate-100 tw-p-5 sm:tw-p-6">
            <div className="tw-flex tw-items-start tw-gap-3">
              <span className="tw-flex tw-h-10 tw-w-10 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-red-50 tw-text-red-700 tw-ring-1 tw-ring-red-100"><ChartPie className="tw-h-4 tw-w-4" /></span>
              <div>
                <h3 className="tw-text-base tw-font-black tw-text-slate-950">{c.fullFleetTitle}</h3>
                <p className="tw-mt-1 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.fullFleetSub}</p>
              </div>
            </div>
          </div>
          <div className="tw-p-5 sm:tw-p-6">
            <FaultDistributionChart totalLabel={c.faultLabelsTotal} />
          </div>
        </div>

        <div className="fd-station-analysis-grid tw-grid tw-grid-cols-1 tw-gap-5">
          <StationFaultDistributionChart
            lang={lang}
            stations={stations}
            station={selectedSummaryStation}
            loading={stationLoading}
            error={stationError}
            onChangeStation={setSelectedSummaryStationId}
            onOpenDetails={onSelectStation}
          />
          <StationFaultSummary
            lang={lang}
            stations={stations}
            loading={stationLoading}
            error={stationError}
            onRetry={onRetryStations}
            onOpenStations={onOpenStations}
            selectedStationId={selectedSummaryStation?.station ?? null}
            onPreviewStation={setSelectedSummaryStationId}
          />
        </div>
      </section>

      <section className="tw-grid tw-grid-cols-1 tw-gap-5 xl:tw-grid-cols-12">
        <div className="fd-panel xl:tw-col-span-8">
          <div className="tw-border-b tw-border-slate-100 tw-p-4 sm:tw-p-6">
            <div className="tw-flex tw-flex-col tw-gap-4 lg:tw-flex-row lg:tw-items-end lg:tw-justify-between">
              <div>
                <div className="tw-flex tw-items-center tw-gap-2 tw-text-[11px] tw-font-extrabold tw-uppercase tw-tracking-wider tw-text-slate-400">
                  <Gauge className="tw-h-4 tw-w-4 tw-text-blue-600" /> {c.score}
                </div>
                <div className="tw-mt-2 tw-flex tw-items-baseline tw-gap-2">
                  <span className="ai-mono tw-text-3xl tw-font-black tw-text-slate-950">{topModel.current.score.toFixed(1)}</span>
                  <span className="tw-text-[12px] tw-font-bold tw-text-slate-500">{MODEL_META[topModel.id].name} · {c.bestModel}</span>
                </div>
              </div>
              <span className="tw-inline-flex tw-items-center tw-gap-1.5 tw-self-start tw-rounded-lg tw-bg-amber-50 tw-px-2.5 tw-py-1.5 tw-text-[11px] tw-font-bold tw-text-amber-800 tw-ring-1 tw-ring-amber-100 lg:tw-self-auto">
                <Sparkles className="tw-h-3.5 tw-w-3.5" /> {c.rescored}
              </span>
            </div>

            <div className="tw-mt-5 tw-grid tw-gap-4 lg:tw-grid-cols-2">
              <fieldset>
                <legend className="tw-mb-2 tw-text-[10px] tw-font-extrabold tw-uppercase tw-tracking-wider tw-text-slate-400">{c.profile}</legend>
                <div className="tw-grid tw-grid-cols-3 tw-gap-1 tw-rounded-xl tw-bg-slate-100 tw-p-1" role="tablist" aria-label={c.profile}>
                  {(Object.keys(profileLabels) as ResearchProfileId[]).map((id) => (
                    <button key={id} type="button" role="tab" aria-selected={profileId === id} onClick={() => setProfileId(id)} className={`tw-min-h-10 tw-rounded-lg tw-px-2 tw-py-2 tw-text-[11px] tw-font-extrabold tw-transition focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-blue-400 ${profileId === id ? "tw-bg-white tw-text-slate-950 tw-shadow-sm" : "tw-text-slate-500 hover:tw-text-slate-800"}`}>
                      {profileLabels[id].label}
                    </button>
                  ))}
                </div>
                <p className="tw-mt-2 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{profileLabels[profileId].note}</p>
              </fieldset>
              <fieldset>
                <legend className="tw-mb-2 tw-text-[10px] tw-font-extrabold tw-uppercase tw-tracking-wider tw-text-slate-400">{c.arm}</legend>
                <div className="tw-grid tw-grid-cols-2 tw-gap-1 tw-rounded-xl tw-bg-slate-100 tw-p-1 sm:tw-grid-cols-4" role="tablist" aria-label={c.arm}>
                  {(Object.keys(armLabels) as ResearchArmId[]).map((id) => (
                    <button key={id} type="button" role="tab" aria-selected={armId === id} onClick={() => setArmId(id)} className={`tw-min-h-10 tw-rounded-lg tw-px-2 tw-py-2 tw-text-[10px] tw-font-extrabold tw-leading-4 tw-transition focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-blue-400 ${armId === id ? "tw-bg-slate-950 tw-text-white tw-shadow-sm" : "tw-text-slate-500 hover:tw-text-slate-800"}`}>
                      {armLabels[id]}
                    </button>
                  ))}
                </div>
              </fieldset>
            </div>
          </div>

          <div className="tw-space-y-1 tw-p-3 sm:tw-p-5">
            {rows.map((row, index) => {
              const meta = MODEL_META[row.id];
              const tone = MODEL_TONES[row.id];
              const delta = row.current.score - row.baseline.score;
              return (
                <div key={row.id} className="fd-model-row tw-grid tw-grid-cols-[42px_minmax(0,1fr)] tw-gap-3 tw-rounded-2xl tw-p-3 tw-transition sm:tw-grid-cols-[48px_170px_minmax(0,1fr)_82px] sm:tw-items-center sm:tw-gap-4 sm:tw-p-4">
                  <div className={`ai-mono tw-flex tw-h-10 tw-w-10 tw-items-center tw-justify-center tw-rounded-xl tw-text-[11px] tw-font-black tw-ring-1 sm:tw-h-11 sm:tw-w-11 ${tone.badge}`}>{meta.short}</div>
                  <div className="tw-min-w-0">
                    <div className="tw-flex tw-items-center tw-gap-2">
                      <span className="ai-mono tw-text-[10px] tw-font-bold tw-text-slate-400">#{index + 1}</span>
                      <span className="tw-truncate tw-text-[13px] tw-font-black tw-text-slate-900 sm:tw-text-sm">{meta.name}</span>
                    </div>
                    <div className="tw-mt-0.5 tw-truncate tw-text-[11px] tw-font-medium tw-text-slate-400">{meta.family}</div>
                  </div>
                  <div className="tw-col-span-2 sm:tw-col-span-1">
                    <div className="tw-h-2.5 tw-overflow-hidden tw-rounded-full tw-bg-slate-100" role="img" aria-label={`${meta.name}: ${row.current.score.toFixed(1)}`}>
                      <div className={`tw-h-full tw-rounded-full tw-transition-all tw-duration-500 ${tone.bar}`} style={{ width: `${row.current.score}%` }} />
                    </div>
                    <div className="tw-mt-2 tw-flex tw-flex-wrap tw-gap-x-4 tw-gap-y-1 tw-text-[11px] tw-font-medium tw-text-slate-500">
                      <span>{c.recall} <strong className="ai-mono tw-text-slate-800">{row.current.recall.toFixed(1)}%</strong></span>
                      <span>{c.far} <strong className="ai-mono tw-text-slate-800">{row.current.far.toFixed(1)}%</strong></span>
                      <span>{c.lead} <strong className="ai-mono tw-text-slate-800">{row.current.lead.toFixed(1)}s</strong></span>
                    </div>
                  </div>
                  <div className="tw-col-start-2 tw-flex tw-items-baseline tw-justify-between tw-gap-3 sm:tw-col-start-auto sm:tw-block sm:tw-text-right">
                    <span className="ai-mono tw-text-xl tw-font-black tw-text-slate-950">{row.current.score.toFixed(1)}</span>
                    <span className={`ai-mono tw-text-[11px] tw-font-semibold ${delta > 0 ? "tw-text-emerald-600" : delta < 0 ? "tw-text-red-600" : "tw-text-slate-400"}`}>
                      {delta === 0 ? c.unchanged : `${delta > 0 ? "+" : ""}${delta.toFixed(1)} ${c.versusBaseline}`}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="fd-panel xl:tw-col-span-4">
          <div className="tw-border-b tw-border-slate-100 tw-p-5 sm:tw-p-6">
            <div className="tw-flex tw-items-start tw-gap-3">
              <span className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-amber-50 tw-text-amber-700 tw-ring-1 tw-ring-amber-100">
                <RadioTower className="tw-h-5 tw-w-5" />
              </span>
              <div>
                <h3 className="tw-text-base tw-font-black tw-text-slate-950">{c.slacTitle}</h3>
                <p className="tw-mt-1 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.slacSub}</p>
              </div>
            </div>
          </div>
          <div className="tw-p-5 sm:tw-p-6">
            <div className="tw-rounded-2xl tw-bg-slate-950 tw-p-4 tw-text-white">
              <div className="tw-flex tw-items-center tw-justify-between tw-gap-3">
                <span className="tw-text-[10px] tw-font-extrabold tw-uppercase tw-tracking-wider tw-text-white/50">{c.hardBudget}</span>
                <span className="ai-mono tw-text-2xl tw-font-black tw-text-amber-300">{SLAC_RESEARCH.responseBudgetMs} ms</span>
              </div>
              <div className="tw-mt-4 tw-flex tw-items-center tw-gap-1.5" aria-label="Three 200 millisecond response windows">
                {[0, 1, 2].map((item) => (
                  <React.Fragment key={item}>
                    <div className="tw-min-w-0 tw-flex-1 tw-rounded-lg tw-bg-white/10 tw-px-2 tw-py-2.5 tw-text-center tw-ring-1 tw-ring-white/10">
                      <div className="ai-mono tw-text-[12px] tw-font-black tw-text-white">{SLAC_RESEARCH.responseWindowMs} ms</div>
                      <div className="tw-mt-0.5 tw-text-[9px] tw-font-bold tw-uppercase tw-text-white/40">{item === 0 ? c.request : `${c.retry} ${item}`}</div>
                    </div>
                    {item < 2 && <ArrowRight className="tw-h-3.5 tw-w-3.5 tw-flex-shrink-0 tw-text-amber-300" />}
                  </React.Fragment>
                ))}
              </div>
            </div>

            <div className="tw-mt-3 tw-flex tw-items-center tw-justify-between tw-gap-3 tw-rounded-xl tw-bg-blue-50 tw-p-3.5 tw-ring-1 tw-ring-blue-100">
              <div className="tw-flex tw-items-center tw-gap-2.5">
                <TimerReset className="tw-h-4 tw-w-4 tw-flex-shrink-0 tw-text-blue-700" />
                <span className="tw-text-[11px] tw-font-bold tw-leading-4 tw-text-blue-950">{c.missingRequest}</span>
              </div>
              <span className="ai-mono tw-text-lg tw-font-black tw-text-blue-700">{SLAC_RESEARCH.matchSessionSeconds}s</span>
            </div>

            <div className="tw-mt-5">
              <div className="tw-flex tw-items-end tw-justify-between tw-gap-3">
                <span className="tw-text-[11px] tw-font-bold tw-text-slate-500">{c.normativeFires}</span>
                <span className="ai-mono tw-text-xl tw-font-black tw-text-slate-950">{SLAC_RESEARCH.normativeFires}</span>
              </div>
              <div className="tw-mt-2 tw-flex tw-h-2.5 tw-overflow-hidden tw-rounded-full tw-bg-slate-100">
                <div className="tw-bg-amber-500" style={{ width: `${SLAC_RESEARCH.responseTimeoutFires / SLAC_RESEARCH.normativeFires * 100}%` }} />
                <div className="tw-bg-blue-500" style={{ width: `${SLAC_RESEARCH.missingRequestFires / SLAC_RESEARCH.normativeFires * 100}%` }} />
              </div>
              <div className="tw-mt-2 tw-grid tw-grid-cols-2 tw-gap-2 tw-text-[10px] tw-font-semibold tw-text-slate-500">
                <span><i className="tw-mr-1.5 tw-inline-block tw-h-2 tw-w-2 tw-rounded-full tw-bg-amber-500" />{SLAC_RESEARCH.responseTimeoutFires} {c.responseTimeout}</span>
                <span className="tw-text-right"><i className="tw-mr-1.5 tw-inline-block tw-h-2 tw-w-2 tw-rounded-full tw-bg-blue-500" />{SLAC_RESEARCH.missingRequestFires} {c.sessionTimeout}</span>
              </div>
            </div>

            <div className="tw-mt-5 tw-rounded-xl tw-border tw-border-amber-200 tw-bg-amber-50 tw-p-3.5">
              <div className="tw-flex tw-items-center tw-gap-2 tw-text-[11px] tw-font-extrabold tw-text-amber-900">
                <AlertTriangle className="tw-h-4 tw-w-4" /> {c.publicSource}
              </div>
              <p className="tw-mt-1.5 tw-text-[10px] tw-font-medium tw-leading-5 tw-text-amber-800">{c.publicSourceNote}</p>
            </div>
          </div>
        </div>
      </section>

      <section className="fd-panel">
          <div className="tw-border-b tw-border-slate-100 tw-p-5 sm:tw-p-6">
            <div className="tw-flex tw-items-start tw-gap-3">
              <span className="tw-flex tw-h-10 tw-w-10 tw-items-center tw-justify-center tw-rounded-xl tw-bg-violet-50 tw-text-violet-700 tw-ring-1 tw-ring-violet-100"><Layers3 className="tw-h-4 tw-w-4" /></span>
              <div>
                <h3 className="tw-text-base tw-font-black tw-text-slate-950">{c.lineageTitle}</h3>
                <p className="tw-mt-1 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.lineageSub}</p>
              </div>
            </div>
          </div>
          <div className="tw-grid tw-gap-3 tw-p-4 sm:tw-grid-cols-3 sm:tw-p-6">
            {LABEL_LINEAGE.map((item, index) => (
              <div key={item.id} className={`tw-relative tw-rounded-2xl tw-border tw-p-4 ${item.id === "reviewed" ? "tw-border-emerald-200 tw-bg-emerald-50/60" : "tw-border-slate-200 tw-bg-white"}`}>
                {index < LABEL_LINEAGE.length - 1 && <ArrowRight className="tw-absolute tw--right-5 tw-top-1/2 tw-z-10 tw-hidden tw-h-4 tw-w-4 tw--translate-y-1/2 tw-text-slate-300 sm:tw-block" />}
                <div className="tw-flex tw-items-center tw-justify-between tw-gap-2">
                  <span className="tw-text-[11px] tw-font-black tw-text-slate-900">{profileLabels[item.id].label}</span>
                  {item.id === "reviewed" && <CheckCircle2 className="tw-h-4 tw-w-4 tw-text-emerald-600" />}
                </div>
                <div className="ai-mono tw-mt-3 tw-text-2xl tw-font-black tw-text-slate-950">{formatInt(item.total - item.censored)}</div>
                <div className="tw-text-[10px] tw-font-semibold tw-text-slate-400">{c.sessions}</div>
                <div className="tw-mt-3 tw-flex tw-h-2 tw-overflow-hidden tw-rounded-full tw-bg-slate-100">
                  <div className="tw-bg-red-500" style={{ width: `${item.faulty / item.total * 100}%` }} />
                  <div className="tw-bg-emerald-500" style={{ width: `${item.clean / item.total * 100}%` }} />
                  {item.censored > 0 && <div className="tw-bg-amber-400" style={{ width: `${item.censored / item.total * 100}%` }} />}
                </div>
                <div className="tw-mt-3 tw-grid tw-grid-cols-2 tw-gap-2 tw-text-[10px] tw-font-semibold tw-text-slate-500">
                  <span>{c.faulty} <strong className="ai-mono tw-text-red-700">{formatInt(item.faulty)}</strong></span>
                  <span className="tw-text-right">{c.clean} <strong className="ai-mono tw-text-emerald-700">{formatInt(item.clean)}</strong></span>
                  {item.censored > 0 && <span className="tw-col-span-2">{c.excluded} <strong className="ai-mono tw-text-amber-700">{formatInt(item.censored)}</strong></span>}
                </div>
              </div>
            ))}
          </div>
      </section>

      <section className="fd-panel tw-p-5 sm:tw-p-6">
        <div className="tw-grid tw-gap-5 lg:tw-grid-cols-[minmax(0,1fr)_2fr] lg:tw-items-center">
          <div className="tw-flex tw-items-start tw-gap-3">
            <span className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-2xl tw-bg-emerald-50 tw-text-emerald-700 tw-ring-1 tw-ring-emerald-100"><ShieldCheck className="tw-h-5 tw-w-5" /></span>
            <div>
              <h3 className="tw-text-base tw-font-black tw-text-slate-950">{c.evidenceTitle}</h3>
              <p className="tw-mt-1 tw-text-[11px] tw-font-medium tw-leading-5 tw-text-slate-500">{c.evidenceNote}</p>
            </div>
          </div>
          <div className="tw-grid tw-grid-cols-2 tw-gap-2 sm:tw-grid-cols-4">
            {[
              { value: SLAC_RESEARCH.corroborated, label: c.corroborated, icon: <CheckCircle2 className="tw-h-3.5 tw-w-3.5" />, tone: "tw-text-emerald-700" },
              { value: SLAC_RESEARCH.pending, label: c.pending, icon: <Clock3 className="tw-h-3.5 tw-w-3.5" />, tone: "tw-text-amber-700" },
              { value: SLAC_RESEARCH.completedAgents, label: c.completedAgents, icon: <Sparkles className="tw-h-3.5 tw-w-3.5" />, tone: "tw-text-blue-700" },
              { value: SLAC_RESEARCH.replayAgreement, label: c.replay, icon: <Gauge className="tw-h-3.5 tw-w-3.5" />, tone: "tw-text-violet-700", suffix: "%" },
            ].map((item) => (
              <div key={item.label} className="tw-rounded-xl tw-bg-slate-50 tw-p-3 tw-ring-1 tw-ring-slate-100">
                <div className={`tw-flex tw-items-center tw-gap-1.5 ${item.tone}`}>{item.icon}<span className="ai-mono tw-text-lg tw-font-black">{item.value}{item.suffix ?? ""}</span></div>
                <div className="tw-mt-1 tw-text-[10px] tw-font-bold tw-leading-4 tw-text-slate-500">{item.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
