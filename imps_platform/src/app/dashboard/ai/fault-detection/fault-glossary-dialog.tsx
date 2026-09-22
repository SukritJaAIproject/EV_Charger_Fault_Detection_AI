"use client";

import {
  Dialog,
  DialogBody,
  DialogHeader,
} from "@material-tailwind/react";
import { BookOpenCheck, Info, ShieldAlert, X } from "lucide-react";

import useLanguage from "@/utils/useLanguage";

import { supportedFaultFamilies } from "./fault-catalog";
import FaultExplanationPanel from "./fault-explanation";

type Props = {
  open: boolean;
  onClose: () => void;
};

const COPY = {
  th: {
    eyebrow: "PCAP FAULT REFERENCE",
    title: "คู่มือ Fault จาก PCAP",
    subtitle: "ความหมาย สาเหตุ มาตรฐานที่เกี่ยวข้อง และฝ่ายรถ/ตู้ตามหลักฐานใน packet",
    count: "7 ประเภทที่ระบบจำแนก",
    close: "ปิดคู่มือ Fault",
    attributionTitle: "อ่านคำว่า ‘ฝ่ายที่หยุด/รายงาน’ อย่างไร",
    attributionBody:
      "ผู้ส่ง error หรือผู้เริ่มหยุด อาจไม่ใช่อุปกรณ์ต้นเหตุเสมอไป เช่น รถสามารถหยุดตาม timeout หลังตู้ค้างได้ ระบบจึงแยกผู้รายงาน ผู้เริ่มหยุด และสาเหตุที่เป็นไปได้จากกัน",
    caution:
      "การอ้างมาตรฐานด้านล่างระบุ protocol หรือขั้นตอนที่ควรตรวจเทียบ ไม่ใช่ผลรับรองว่าอุปกรณ์ผิดมาตรฐาน ต้องยืนยันด้วย packet เต็ม ทิศทางการสื่อสาร และผลทดสอบอุปกรณ์ก่อนสรุปสาเหตุราก",
  },
  en: {
    eyebrow: "PCAP FAULT REFERENCE",
    title: "PCAP fault guide",
    subtitle: "Meanings, probable causes, related standards, and EV/charger attribution from packet evidence",
    count: "7 classified fault families",
    close: "Close fault guide",
    attributionTitle: "How to read ‘stopping or reporting party’",
    attributionBody:
      "The device reporting an error or initiating a stop is not necessarily the root cause. For example, an EV may stop on timeout after the charger stalls. Reporting party, stop initiator, and probable cause are therefore shown separately.",
    caution:
      "The standards below identify protocols or phases to investigate; they are not a conformance verdict. Confirm with the complete packet sequence, traffic direction, and equipment tests before assigning root cause.",
  },
} as const;

export default function FaultGlossaryDialog({ open, onClose }: Props) {
  const { lang } = useLanguage();
  const c = COPY[lang];

  return (
    <Dialog
      id="fault-glossary-dialog"
      open={open}
      handler={onClose}
      size="lg"
      dismiss={{ outsidePress: true, escapeKey: true }}
      aria-label={c.title}
      aria-labelledby="fault-glossary-dialog-title"
      className="tw-flex tw-max-h-[96vh] tw-flex-col tw-overflow-hidden !tw-m-2 !tw-rounded-[22px] sm:tw-max-h-[92vh] sm:!tw-m-4"
    >
      <DialogHeader
        className="tw-flex-shrink-0 !tw-p-0 tw-text-white tw-shadow-xl"
        style={{ background: "linear-gradient(135deg, #111827 0%, #0f172a 62%, #172554 100%)" }}
      >
        <div className="tw-flex tw-w-full tw-items-start tw-justify-between tw-gap-4 tw-px-4 tw-py-5 sm:tw-px-7 sm:tw-py-6">
          <div className="tw-flex tw-min-w-0 tw-items-start tw-gap-3">
            <span className="tw-flex tw-h-11 tw-w-11 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-xl tw-bg-blue-500/15 tw-text-blue-300 tw-ring-1 tw-ring-blue-400/25">
              <BookOpenCheck className="tw-h-[22px] tw-w-[22px]" />
            </span>
            <div className="tw-min-w-0">
              <div className="tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-[0.16em] tw-text-blue-300/90">
                {c.eyebrow}
              </div>
              <h2
                id="fault-glossary-dialog-title"
                className="tw-mt-1 tw-text-xl tw-font-black tw-tracking-tight tw-text-white sm:tw-text-2xl"
              >
                {c.title}
              </h2>
              <p className="tw-mt-1.5 tw-max-w-2xl tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-white/65 sm:tw-text-[13px]">
                {c.subtitle}
              </p>
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
        <div className="tw-space-y-5 tw-bg-slate-50/70 tw-p-4 sm:tw-p-7">
          <div className="tw-grid tw-gap-3 md:tw-grid-cols-[minmax(0,1fr)_auto]">
            <div className="tw-flex tw-items-start tw-gap-2.5 tw-rounded-xl tw-border tw-border-blue-200 tw-bg-blue-50 tw-p-3.5 tw-text-blue-950">
              <Info className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0 tw-text-blue-600" />
              <div>
                <div className="tw-text-[13px] tw-font-black">{c.attributionTitle}</div>
                <p className="tw-mt-1.5 tw-text-[12px] tw-font-semibold tw-leading-5 tw-text-blue-900/80">
                  {c.attributionBody}
                </p>
              </div>
            </div>
            <div className="tw-flex tw-items-center tw-justify-center tw-rounded-xl tw-bg-gray-900 tw-px-5 tw-py-3 tw-text-center tw-text-white">
              <div>
                <div className="ai-mono tw-text-2xl tw-font-black tw-text-blue-300">
                  {supportedFaultFamilies.length}
                </div>
                <div className="tw-mt-1 tw-text-[11px] tw-font-bold tw-uppercase tw-tracking-wider tw-text-white/55">
                  {c.count}
                </div>
              </div>
            </div>
          </div>

          <div className="tw-space-y-3">
            {supportedFaultFamilies.map((family, index) => (
              <section
                key={family}
                aria-labelledby={`fault-guide-${family}`}
                className="tw-rounded-2xl tw-border tw-border-slate-200 tw-bg-white tw-p-4 tw-shadow-sm sm:tw-p-5"
              >
                <div className="tw-mb-2.5 tw-flex tw-items-center tw-gap-2">
                  <span className="ai-mono tw-flex tw-h-7 tw-w-7 tw-flex-shrink-0 tw-items-center tw-justify-center tw-rounded-lg tw-bg-gray-900 tw-text-[11px] tw-font-black tw-text-blue-300">
                    {index + 1}
                  </span>
                  <code
                    id={`fault-guide-${family}`}
                    className="tw-break-all tw-text-[12px] tw-font-black tw-tracking-wide tw-text-slate-700"
                  >
                    {family}
                  </code>
                </div>
                <FaultExplanationPanel family={family} lang={lang} compact />
              </section>
            ))}
          </div>

          <div className="tw-flex tw-items-start tw-gap-2.5 tw-rounded-xl tw-border tw-border-amber-200 tw-bg-amber-50 tw-p-3.5 tw-text-amber-950">
            <ShieldAlert className="tw-mt-0.5 tw-h-4 tw-w-4 tw-flex-shrink-0 tw-text-amber-600" />
            <p className="tw-text-[12px] tw-font-semibold tw-leading-5">{c.caution}</p>
          </div>
        </div>
      </DialogBody>
    </Dialog>
  );
}
