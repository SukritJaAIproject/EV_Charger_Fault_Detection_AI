"use client";

import { BookOpenCheck, CarFront, HelpCircle, ServerCog, TriangleAlert } from "lucide-react";

import {
  getFaultExplanation,
  type FaultLanguage,
  type StopParty,
} from "./fault-catalog";

type Props = {
  family?: string | null;
  reason?: string | null;
  lang: FaultLanguage;
  compact?: boolean;
};

export type ObservedStopAnalysis = {
  triggeredBy: "vehicle" | "charger" | "communication" | "unknown" | "not_applicable";
  requestSender: "vehicle" | null;
  confidence: "high" | "medium" | "low";
  evidence: string;
};

const PARTY_STYLE: Record<StopParty, string> = {
  ev: "tw-bg-blue-50 tw-text-blue-800 tw-ring-blue-200",
  evse: "tw-bg-red-50 tw-text-red-800 tw-ring-red-200",
  shared: "tw-bg-purple-50 tw-text-purple-800 tw-ring-purple-200",
  unknown: "tw-bg-amber-50 tw-text-amber-900 tw-ring-amber-200",
};

const partyIcon = (party: StopParty) => {
  if (party === "ev") return <CarFront className="tw-h-4 tw-w-4" />;
  if (party === "evse") return <ServerCog className="tw-h-4 tw-w-4" />;
  if (party === "shared") return <TriangleAlert className="tw-h-4 tw-w-4" />;
  return <HelpCircle className="tw-h-4 tw-w-4" />;
};

export default function FaultExplanationPanel({ family, reason, lang, compact = false }: Props) {
  const detail = getFaultExplanation(family, lang, reason);
  const labels = lang === "th"
    ? {
        heading: "คำอธิบาย Fault",
        cause: "สาเหตุที่เป็นไปได้",
        standard: "มาตรฐาน/ขั้นตอนที่เกี่ยวข้อง",
        party: "ฝ่ายที่หยุดหรือรายงาน",
        caution: "เป็นการระบุจากหลักฐานใน PCAP ไม่ใช่ผลทดสอบรับรองมาตรฐาน",
      }
    : {
        heading: "Fault interpretation",
        cause: "Probable cause",
        standard: "Related standard / phase",
        party: "Stopping or reporting party",
        caution: "This is packet-evidence attribution, not a standards conformance certification.",
      };

  return (
    <div className={`tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white ${compact ? "tw-p-3.5" : "tw-p-4"}`}>
      <div className="tw-flex tw-flex-wrap tw-items-center tw-justify-between tw-gap-2">
        <div>
          <div className="tw-text-[11px] tw-font-black tw-uppercase tw-tracking-[0.12em] tw-text-slate-400">
            {labels.heading}
          </div>
          <div className="tw-mt-1 tw-text-sm tw-font-black tw-text-slate-950">{detail.title}</div>
        </div>
        <span className={`tw-inline-flex tw-items-center tw-gap-1.5 tw-rounded-full tw-px-3 tw-py-1.5 tw-text-[11px] tw-font-black tw-ring-1 ${PARTY_STYLE[detail.stopParty]}`}>
          {partyIcon(detail.stopParty)}
          {detail.stopPartyLabel}
        </span>
      </div>

      <div className={`tw-mt-3 tw-grid tw-gap-2 ${compact ? "sm:tw-grid-cols-2" : "md:tw-grid-cols-2"}`}>
        <div className="tw-rounded-lg tw-bg-slate-50 tw-p-3">
          <div className="tw-text-[11px] tw-font-black tw-uppercase tw-tracking-wide tw-text-slate-400">{labels.cause}</div>
          <p className="tw-mt-1.5 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-slate-700">{detail.cause}</p>
        </div>
        <div className="tw-rounded-lg tw-bg-blue-50/70 tw-p-3">
          <div className="tw-flex tw-items-center tw-gap-1.5 tw-text-[11px] tw-font-black tw-uppercase tw-tracking-wide tw-text-blue-600">
            <BookOpenCheck className="tw-h-3.5 tw-w-3.5" />
            {labels.standard}
          </div>
          <p className="tw-mt-1.5 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-blue-950/80">{detail.standard}</p>
        </div>
      </div>

      <div className="tw-mt-2.5 tw-rounded-xl tw-bg-amber-50 tw-px-3.5 tw-py-2.5 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-amber-950/85">
        <span className="tw-font-black">{labels.party}: </span>{detail.attribution}
      </div>
      {!compact && (
        <p className="tw-mt-2.5 tw-text-[11px] tw-font-semibold tw-leading-5 tw-text-slate-500">{labels.caution}</p>
      )}
    </div>
  );
}

export function FaultExplanationInline({ family, reason, lang }: Omit<Props, "compact">) {
  const detail = getFaultExplanation(family, lang, reason);
  const standardLabel = lang === "th" ? "มาตรฐานที่เกี่ยวข้อง" : "Related standard";
  const partyLabel = lang === "th" ? "ฝ่ายที่หยุด/รายงาน" : "Stop/report attribution";

  return (
    <div className="tw-mt-2.5 tw-space-y-2 tw-rounded-xl tw-bg-slate-50 tw-p-3 tw-ring-1 tw-ring-slate-200">
      <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-1.5">
        {detail.family && (
          <code className="tw-rounded-md tw-bg-slate-900 tw-px-2 tw-py-1 tw-text-[10px] tw-font-black tw-text-white">
            {detail.family}
          </code>
        )}
        <span className={`tw-inline-flex tw-items-center tw-gap-1 tw-rounded-full tw-px-2.5 tw-py-1 tw-text-[10px] tw-font-black tw-ring-1 ${PARTY_STYLE[detail.stopParty]}`}>
          {partyIcon(detail.stopParty)}
          {detail.stopPartyLabel}
        </span>
      </div>
      <p className="tw-text-[11px] tw-font-semibold tw-leading-5 tw-text-slate-700">{detail.cause}</p>
      <p className="tw-text-[10px] tw-font-semibold tw-leading-5 tw-text-blue-800">
        <span className="tw-font-black">{standardLabel}: </span>{detail.standard}
      </p>
      <p className="tw-text-[10px] tw-font-semibold tw-leading-5 tw-text-amber-900">
        <span className="tw-font-black">{partyLabel}: </span>{detail.attribution}
      </p>
    </div>
  );
}

export function ObservedStopAttribution({
  analysis,
  lang,
  compact = false,
}: {
  analysis: ObservedStopAnalysis;
  lang: FaultLanguage;
  compact?: boolean;
}) {
  const copy = lang === "th"
    ? {
        heading: "ผู้เริ่มหยุดจาก packet จริง",
        parties: {
          vehicle: "รถ (EV/EVCC)",
          charger: "ตู้ชาร์จ (EVSE/SECC)",
          communication: "ลิงก์สื่อสารขาด — ยังชี้รถ/ตู้ไม่ได้",
          unknown: "ยังระบุไม่ได้จาก PCAP",
          not_applicable: "ยังไม่เริ่ม charging session",
        },
        request: "พบ SessionStopReq จากรถ",
        confidence: { high: "หลักฐานชัด", medium: "ความมั่นใจปานกลาง", low: "หลักฐานจำกัด" },
      }
    : {
        heading: "Observed stop initiator",
        parties: {
          vehicle: "Vehicle (EV/EVCC)",
          charger: "Charger (EVSE/SECC)",
          communication: "Communication link — endpoint unknown",
          unknown: "Not attributable from this PCAP",
          not_applicable: "Charging session was not established",
        },
        request: "SessionStopReq from the vehicle observed",
        confidence: { high: "Strong evidence", medium: "Medium confidence", low: "Limited evidence" },
      };
  const tones = {
    vehicle: "tw-border-blue-200 tw-bg-blue-50 tw-text-blue-950",
    charger: "tw-border-red-200 tw-bg-red-50 tw-text-red-950",
    communication: "tw-border-purple-200 tw-bg-purple-50 tw-text-purple-950",
    unknown: "tw-border-amber-200 tw-bg-amber-50 tw-text-amber-950",
    not_applicable: "tw-border-slate-200 tw-bg-slate-50 tw-text-slate-800",
  } as const;

  return (
    <div className={`tw-rounded-xl tw-border ${tones[analysis.triggeredBy]} ${compact ? "tw-p-3" : "tw-p-3.5"}`}>
      <div className="tw-flex tw-flex-wrap tw-items-center tw-justify-between tw-gap-2">
        <div className="tw-text-[10px] tw-font-black tw-uppercase tw-tracking-wide tw-opacity-60">{copy.heading}</div>
        <span className="tw-rounded-full tw-bg-white/70 tw-px-2.5 tw-py-1 tw-text-[10px] tw-font-black tw-ring-1 tw-ring-black/5">
          {copy.confidence[analysis.confidence]}
        </span>
      </div>
      <div className="tw-mt-1.5 tw-text-[12px] tw-font-black">{copy.parties[analysis.triggeredBy]}</div>
      <p className="tw-mt-1 tw-text-[11px] tw-font-semibold tw-leading-5 tw-opacity-80">{analysis.evidence}</p>
      {analysis.requestSender === "vehicle" && (
        <p className="tw-mt-1 tw-text-[10px] tw-font-black tw-opacity-65">{copy.request}</p>
      )}
    </div>
  );
}
