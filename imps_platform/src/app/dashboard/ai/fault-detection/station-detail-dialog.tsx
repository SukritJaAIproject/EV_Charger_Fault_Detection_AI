"use client";

import {
  Dialog,
  DialogBody,
  DialogHeader,
} from "@material-tailwind/react";
import {
  AlertTriangle,
  BarChart3,
  Clock3,
  MapPin,
  Network,
  ShieldCheck,
  Target,
  X,
} from "lucide-react";

import useLanguage from "@/utils/useLanguage";

import type { StationAnalysis } from "./data";
import FaultExplanationPanel from "./fault-explanation";

type Props = {
  station: StationAnalysis | null;
  onClose: () => void;
};

const COPY = {
  th: {
    title: "รายละเอียดผลวิเคราะห์รายสถานี",
    close: "ปิดรายละเอียดสถานี",
    benchmarkScore: "คะแนน Benchmark",
    topFault: "Fault หลัก",
    overview: "ภาพรวมข้อมูลทดสอบ",
    outcomes: "ผลลัพธ์การตรวจจับ",
    modelMetrics: "ตัวชี้วัดโมเดล",
    connectors: "ผลแยกตาม Connector",
    faultFamilies: "ผลแยกตามประเภท Fault",
    sessions: "Sessions",
    faultSessions: "Fault sessions",
    normalSessions: "Normal sessions",
    alertedSessions: "AI alerts",
    alertsShort: "Alerts",
    faultRate: "Fault rate",
    truePositive: "ตรวจพบตรงเวลา (TP)",
    late: "ตรวจพบช้า",
    missed: "ตรวจไม่พบ",
    falsePositive: "แจ้งเตือนผิด (FP)",
    trueNegative: "ไม่แจ้งเตือนถูกต้อง (TN)",
    recall: "Recall",
    precision: "Precision",
    f1: "F1 score",
    falseAlarmRate: "False alarm rate",
    falseAlarmShort: "FAR",
    medianLead: "Median lead time",
    seconds: "วินาที",
    connector: "Connector",
    faults: "Faults",
    detected: "TP / ช้า / พลาด",
    falseAlarms: "FP",
    score: "Score",
    family: "Fault family",
    commonEvidence: "หลักฐานที่พบบ่อยในสถานีนี้",
    noConnectorData: "ไม่มีข้อมูลแยก Connector สำหรับสถานีนี้",
    noFamilyData: "ไม่พบ Fault family ในชุดทดสอบของสถานีนี้",
    heldOutNote:
      "ผลชุดนี้คำนวณจาก held-out PCAP benchmark เพื่อประเมินคุณภาพโมเดล ไม่ใช่สถานะสุขภาพแบบเรียลไทม์ของสถานี",
    connectorCount: "Connector ในชุดทดสอบ",
    group: "กลุ่ม",
  },
  en: {
    title: "Station analysis details",
    close: "Close station details",
    benchmarkScore: "Benchmark score",
    topFault: "Top fault",
    overview: "Test-data overview",
    outcomes: "Detection outcomes",
    modelMetrics: "Model metrics",
    connectors: "Results by connector",
    faultFamilies: "Results by fault family",
    sessions: "Sessions",
    faultSessions: "Fault sessions",
    normalSessions: "Normal sessions",
    alertedSessions: "AI alerts",
    alertsShort: "Alerts",
    faultRate: "Fault rate",
    truePositive: "On-time detection (TP)",
    late: "Late detection",
    missed: "Missed",
    falsePositive: "False positive (FP)",
    trueNegative: "Correctly silent (TN)",
    recall: "Recall",
    precision: "Precision",
    f1: "F1 score",
    falseAlarmRate: "False alarm rate",
    falseAlarmShort: "FAR",
    medianLead: "Median lead time",
    seconds: "seconds",
    connector: "Connector",
    faults: "Faults",
    detected: "TP / late / miss",
    falseAlarms: "FP",
    score: "Score",
    family: "Fault family",
    commonEvidence: "Common evidence at this station",
    noConnectorData: "No connector-level data is available for this station.",
    noFamilyData: "No fault family was present for this station in the test set.",
    heldOutNote:
      "These results are calculated from the held-out PCAP benchmark to evaluate model quality. They are not the station's real-time health status.",
    connectorCount: "Connectors in test set",
    group: "Group",
  },
} as const;

const formatInt = (value: number) => new Intl.NumberFormat("en-US").format(value);
const formatPercent = (value: number) => `${value.toFixed(1)}%`;

const displayIdentifier = (value: string) =>
  value.replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");

const displayFamily = (family: string) =>
  family
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

function SectionTitle({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="tw-mb-3 tw-flex tw-items-center tw-gap-2">
      <span className="tw-flex tw-h-7 tw-w-7 tw-items-center tw-justify-center tw-rounded-lg tw-bg-gray-900 tw-text-blue-300">
        {icon}
      </span>
      <h3 className="tw-text-[13px] tw-font-black tw-uppercase tw-tracking-[0.12em] tw-text-gray-800">
        {children}
      </h3>
    </div>
  );
}

function MetricCard({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: string;
  tone?: "slate" | "blue" | "emerald" | "amber" | "red" | "purple";
}) {
  const tones = {
    slate: "tw-bg-slate-50 tw-text-slate-900 tw-ring-slate-200",
    blue: "tw-bg-blue-50 tw-text-blue-800 tw-ring-blue-100",
    emerald: "tw-bg-emerald-50 tw-text-emerald-800 tw-ring-emerald-100",
    amber: "tw-bg-amber-50 tw-text-amber-800 tw-ring-amber-100",
    red: "tw-bg-red-50 tw-text-red-800 tw-ring-red-100",
    purple: "tw-bg-purple-50 tw-text-purple-800 tw-ring-purple-100",
  } as const;

  return (
    <div className={`tw-rounded-2xl tw-p-3.5 tw-ring-1 ${tones[tone]}`}>
      <div className="tw-text-[11px] tw-font-bold tw-leading-4 tw-tracking-wide tw-opacity-65">
        {label}
      </div>
      <div className="ai-mono tw-mt-2 tw-text-xl tw-font-black tw-leading-none">{value}</div>
    </div>
  );
}

export default function StationDetailDialog({ station, onClose }: Props) {
  const { lang } = useLanguage();
  const c = COPY[lang];

  if (!station) return null;

  const trueNegative = Math.max(0, station.normalSessions - station.fp);
  const scoreTone =
    station.score >= 70
      ? "tw-bg-emerald-400/15 tw-text-emerald-300 tw-ring-emerald-400/25"
      : station.score >= 50
        ? "tw-bg-amber-400/15 tw-text-amber-300 tw-ring-amber-400/25"
        : "tw-bg-red-400/15 tw-text-red-300 tw-ring-red-400/25";

  return (
    <Dialog
      id="station-analysis-dialog"
      open
      handler={onClose}
      size="lg"
      dismiss={{ outsidePress: true, escapeKey: true }}
      aria-label={c.title}
      aria-labelledby="station-analysis-dialog-title"
      className="tw-flex tw-max-h-[96vh] tw-flex-col tw-overflow-hidden !tw-m-2 !tw-rounded-[22px] sm:tw-max-h-[92vh] sm:!tw-m-4"
    >
      <DialogHeader
        className="tw-flex-shrink-0 !tw-p-0 tw-text-white tw-shadow-xl"
        style={{ background: "linear-gradient(135deg, #111827 0%, #0f172a 62%, #1e293b 100%)" }}
      >
        <div className="tw-flex tw-w-full tw-items-start tw-justify-between tw-gap-4 tw-px-4 tw-py-5 sm:tw-px-7 sm:tw-py-6">
          <div className="tw-flex tw-min-w-0 tw-items-start tw-gap-3">
            <span className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-500/15 tw-text-blue-300 tw-ring-1 tw-ring-blue-400/25">
              <MapPin className="tw-h-[22px] tw-w-[22px]" />
            </span>
            <div className="tw-min-w-0">
              <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-[0.16em] tw-text-blue-300/90">
                {c.title}
              </div>
              <h2
                id="station-analysis-dialog-title"
                className="tw-mt-1 tw-truncate tw-text-xl tw-font-black tw-tracking-tight tw-text-white sm:tw-text-2xl"
                title={station.station}
              >
                {displayIdentifier(station.station)}
              </h2>
              <div className="tw-mt-1.5 tw-flex tw-flex-wrap tw-gap-x-3 tw-gap-y-1 tw-text-[12px] tw-font-semibold tw-text-white/60">
                <span>{c.group}: {displayIdentifier(station.group)}</span>
                <span>{c.connectorCount}: {formatInt(station.connectors)}</span>
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={c.close}
            title={c.close}
            className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-white/10 tw-text-white/70 tw-transition hover:tw-bg-white/20 hover:tw-text-white focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-blue-300"
          >
            <X className="tw-h-5 tw-w-5" />
          </button>
        </div>
      </DialogHeader>

      <DialogBody className="tw-min-h-0 tw-flex-1 tw-overflow-y-auto !tw-p-0 tw-text-gray-700">
        <div className="tw-space-y-6 tw-bg-slate-50/70 tw-p-4 sm:tw-p-7">
          <section className="tw-grid tw-gap-3 sm:tw-grid-cols-2">
            <div className="tw-rounded-2xl tw-bg-gray-900 tw-p-4 tw-text-white tw-shadow-sm">
              <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-[0.13em] tw-text-white/50">
                {c.benchmarkScore}
              </div>
              <div className="tw-mt-2 tw-flex tw-items-end tw-gap-3">
                <span className={`ai-mono tw-inline-flex tw-rounded-xl tw-px-3 tw-py-2 tw-text-3xl tw-font-black tw-ring-1 ${scoreTone}`}>
                  {station.score.toFixed(1)}
                </span>
                <span className="tw-pb-2 tw-text-[12px] tw-font-bold tw-text-white/45">/ 100</span>
              </div>
            </div>
            <div className="tw-rounded-2xl tw-border tw-border-gray-200 tw-bg-white tw-p-4 tw-shadow-sm">
              <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-[0.13em] tw-text-gray-500">
                {c.topFault}
              </div>
              <div className="tw-mt-2 tw-flex tw-items-center tw-gap-2">
                <AlertTriangle className="tw-h-5 tw-w-5 tw-flex-shrink-0 tw-text-red-500" />
                <span className="tw-truncate tw-text-sm tw-font-black tw-text-gray-900" title={station.topFaultFamily ?? undefined}>
                  {station.topFaultFamily ? displayFamily(station.topFaultFamily) : "—"}
                </span>
              </div>
            </div>
          </section>

          <section>
            <SectionTitle icon={<BarChart3 className="tw-h-4 tw-w-4" />}>{c.overview}</SectionTitle>
            <div className="tw-grid tw-grid-cols-2 tw-gap-2.5 sm:tw-grid-cols-5">
              <MetricCard label={c.sessions} value={formatInt(station.sessions)} />
              <MetricCard label={c.faultSessions} value={formatInt(station.faultySessions)} tone="red" />
              <MetricCard label={c.normalSessions} value={formatInt(station.normalSessions)} tone="emerald" />
              <MetricCard label={c.alertedSessions} value={formatInt(station.alertedSessions)} tone="purple" />
              <MetricCard label={c.faultRate} value={formatPercent(station.faultRate)} tone="amber" />
            </div>
          </section>

          <section>
            <SectionTitle icon={<Target className="tw-h-4 tw-w-4" />}>{c.outcomes}</SectionTitle>
            <div className="tw-grid tw-grid-cols-2 tw-gap-2.5 sm:tw-grid-cols-5">
              <MetricCard label={c.truePositive} value={formatInt(station.tp)} tone="emerald" />
              <MetricCard label={c.late} value={formatInt(station.late)} tone="amber" />
              <MetricCard label={c.missed} value={formatInt(station.miss)} tone="red" />
              <MetricCard label={c.falsePositive} value={formatInt(station.fp)} tone="purple" />
              <MetricCard label={c.trueNegative} value={formatInt(trueNegative)} tone="blue" />
            </div>
          </section>

          <section>
            <SectionTitle icon={<ShieldCheck className="tw-h-4 tw-w-4" />}>{c.modelMetrics}</SectionTitle>
            <div className="tw-grid tw-grid-cols-2 tw-gap-2.5 sm:tw-grid-cols-5">
              <MetricCard label={c.recall} value={formatPercent(station.recall)} tone="emerald" />
              <MetricCard label={c.precision} value={formatPercent(station.precision)} tone="blue" />
              <MetricCard label={c.f1} value={formatPercent(station.f1)} tone="purple" />
              <MetricCard label={c.falseAlarmRate} value={formatPercent(station.falseAlarmRate)} tone="amber" />
              <MetricCard label={c.medianLead} value={`${station.medianLeadSeconds.toFixed(1)} ${c.seconds}`} />
            </div>
          </section>

          <section>
            <SectionTitle icon={<Network className="tw-h-4 tw-w-4" />}>{c.connectors}</SectionTitle>
            {station.byConnector.length === 0 ? (
              <div className="tw-rounded-xl tw-border tw-border-dashed tw-border-gray-300 tw-bg-white tw-p-5 tw-text-center tw-text-[13px] tw-font-semibold tw-text-gray-500">
                {c.noConnectorData}
              </div>
            ) : (
              <>
              <div className="tw-space-y-3 sm:tw-hidden">
                {station.byConnector.map((connector) => (
                  <article key={connector.connector} className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 tw-shadow-sm">
                    <div className="tw-flex tw-items-start tw-justify-between tw-gap-3">
                      <div>
                        <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wide tw-text-slate-400">{c.connector}</div>
                        <div className="tw-mt-0.5 tw-text-[15px] tw-font-black tw-text-slate-950">{displayIdentifier(connector.connector)}</div>
                      </div>
                      <span className="ai-mono tw-rounded-xl tw-bg-blue-50 tw-px-3 tw-py-2 tw-text-[13px] tw-font-black tw-text-blue-700 tw-ring-1 tw-ring-blue-100">
                        {connector.score.toFixed(1)}
                      </span>
                    </div>
                    <div className="tw-mt-3 tw-grid tw-grid-cols-2 tw-gap-2">
                      <MetricCard label={c.sessions} value={formatInt(connector.sessions)} />
                      <MetricCard label={c.faults} value={`${formatInt(connector.faultySessions)} · ${formatPercent(connector.faultRate)}`} tone="red" />
                      <MetricCard label={c.recall} value={formatPercent(connector.recall)} tone="emerald" />
                      <MetricCard label={c.falseAlarmRate} value={formatPercent(connector.falseAlarmRate)} tone="amber" />
                    </div>
                    <div className="tw-mt-3 tw-rounded-xl tw-bg-slate-50 tw-p-3">
                      <div className="tw-text-[11px] tw-font-bold tw-text-slate-500">{c.detected}</div>
                      <div className="ai-mono tw-mt-1 tw-text-[13px] tw-font-black tw-text-slate-800">{connector.tp} / {connector.late} / {connector.miss}</div>
                      <div className="tw-mt-2 tw-text-[11px] tw-font-bold tw-text-slate-500">{c.topFault}</div>
                      <div className="tw-mt-1 tw-text-[12px] tw-font-extrabold tw-text-slate-800">
                        {connector.topFaultFamily ? displayFamily(connector.topFaultFamily) : "—"}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              <div className="tw-hidden tw-overflow-x-auto tw-rounded-xl tw-border tw-border-gray-200 tw-bg-white tw-shadow-sm sm:tw-block">
                <table className="tw-w-full tw-min-w-[780px] tw-border-collapse tw-text-left">
                  <caption className="tw-sr-only">{c.connectors}</caption>
                  <thead className="tw-bg-gray-900 tw-text-white">
                    <tr>
                      {[c.connector, c.sessions, c.faults, c.alertsShort, c.detected, c.falseAlarms, c.recall, c.falseAlarmShort, c.score, c.topFault].map((label) => (
                        <th key={label} scope="col" className="tw-whitespace-nowrap tw-px-3.5 tw-py-3 tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wide tw-text-white/65">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {station.byConnector.map((connector) => (
                      <tr key={connector.connector} className="tw-border-b tw-border-gray-100 last:tw-border-0">
                        <th scope="row" className="tw-whitespace-nowrap tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-extrabold tw-text-gray-900">
                          {displayIdentifier(connector.connector)}
                        </th>
                        <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold">{formatInt(connector.sessions)}</td>
                        <td className="tw-px-3 tw-py-3">
                          <div className="ai-mono tw-text-[13px] tw-font-bold tw-text-red-700">{formatInt(connector.faultySessions)}</div>
                          <div className="ai-mono tw-text-[10px] tw-text-gray-400">{formatPercent(connector.faultRate)}</div>
                        </td>
                        <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold tw-text-purple-700">{formatInt(connector.alertedSessions)}</td>
                        <td className="ai-mono tw-whitespace-nowrap tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold">{connector.tp} / {connector.late} / {connector.miss}</td>
                        <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold tw-text-purple-700">{formatInt(connector.fp)}</td>
                        <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold tw-text-emerald-700">{formatPercent(connector.recall)}</td>
                        <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-bold tw-text-amber-700">{formatPercent(connector.falseAlarmRate)}</td>
                        <td className="ai-mono tw-px-3.5 tw-py-3.5 tw-text-[13px] tw-font-black tw-text-blue-700">{connector.score.toFixed(1)}</td>
                        <td className="tw-max-w-[150px] tw-truncate tw-whitespace-nowrap tw-px-3.5 tw-py-3.5 tw-text-[12px] tw-font-bold" title={connector.topFaultFamily ?? undefined}>
                          {connector.topFaultFamily ? displayFamily(connector.topFaultFamily) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
          </section>

          <section>
            <SectionTitle icon={<Clock3 className="tw-h-4 tw-w-4" />}>{c.faultFamilies}</SectionTitle>
            {station.byFaultFamily.length === 0 ? (
              <div className="tw-rounded-xl tw-border tw-border-dashed tw-border-gray-300 tw-bg-white tw-p-5 tw-text-center tw-text-[13px] tw-font-semibold tw-text-gray-500">
                {c.noFamilyData}
              </div>
            ) : (
              <div className="tw-space-y-2.5">
                {station.byFaultFamily.map((family) => (
                  <div key={family.family} className="tw-rounded-xl tw-border tw-border-gray-200 tw-bg-white tw-p-3.5 tw-shadow-sm">
                    <div className="tw-flex tw-flex-col tw-gap-2 sm:tw-flex-row sm:tw-items-center sm:tw-justify-between">
                      <div className="tw-min-w-0">
                        <div className="tw-truncate tw-text-[13px] tw-font-black tw-text-gray-900" title={family.family}>{displayFamily(family.family)}</div>
                        <div className="tw-mt-1 tw-text-[11px] tw-font-semibold tw-text-gray-500">
                          {c.faultSessions}: {formatInt(family.faultySessions)} · TP {family.tp} · {c.late} {family.late} · {c.missed} {family.miss}
                        </div>
                      </div>
                      <div className="tw-flex tw-flex-shrink-0 tw-items-center tw-gap-3">
                        <span className="ai-mono tw-text-[11px] tw-font-bold tw-text-gray-500">{family.medianLeadSeconds.toFixed(1)} {c.seconds}</span>
                        <span className="ai-mono tw-min-w-[58px] tw-text-right tw-text-[13px] tw-font-black tw-text-emerald-700">{formatPercent(family.recall)}</span>
                      </div>
                    </div>
                    <div
                      role="progressbar"
                      aria-label={`${displayFamily(family.family)} ${c.recall}`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Number(family.recall.toFixed(1))}
                      className="tw-mt-2.5 tw-h-2 tw-overflow-hidden tw-rounded-full tw-bg-gray-100"
                    >
                      <div className="tw-h-full tw-rounded-full tw-bg-gradient-to-r tw-from-blue-500 tw-to-emerald-500" style={{ width: `${Math.min(100, Math.max(0, family.recall))}%` }} />
                    </div>
                    {family.topEvidence.length > 0 && (
                      <div className="tw-mt-3 tw-rounded-lg tw-bg-slate-50 tw-p-3">
                        <div className="tw-text-[11px] tw-font-black tw-uppercase tw-tracking-wide tw-text-slate-400">
                          {c.commonEvidence}
                        </div>
                        <ul className="tw-mt-1.5 tw-space-y-1">
                          {family.topEvidence.map((evidence) => (
                            <li key={evidence.detail} className="tw-flex tw-items-start tw-justify-between tw-gap-3 tw-text-[11px] tw-leading-5 tw-text-slate-600">
                              <code className="tw-break-all tw-font-semibold">{evidence.detail}</code>
                              <span className="ai-mono tw-flex-shrink-0 tw-rounded-md tw-bg-white tw-px-1.5 tw-py-0.5 tw-font-black tw-text-slate-500 tw-ring-1 tw-ring-slate-200">
                                {formatInt(evidence.count)}×
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <div className="tw-mt-3">
                      <FaultExplanationPanel
                        family={family.family}
                        reason={family.topEvidence[0]?.detail}
                        lang={lang}
                        compact
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="tw-flex tw-items-start tw-gap-2.5 tw-rounded-xl tw-border tw-border-amber-200 tw-bg-amber-50 tw-p-3.5 tw-text-amber-900">
            <AlertTriangle className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0" />
            <p className="tw-text-[12px] tw-font-semibold tw-leading-5">{c.heldOutNote}</p>
          </div>
        </div>
      </DialogBody>
    </Dialog>
  );
}
