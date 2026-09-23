export type FaultLanguage = "th" | "en";
export type StopParty = "ev" | "evse" | "shared" | "unknown";

type LocalizedText = Record<FaultLanguage, string>;

type FaultDefinition = {
  title: LocalizedText;
  cause: LocalizedText;
  standard: LocalizedText;
  stopParty: StopParty;
  stopPartyLabel: LocalizedText;
  attribution: LocalizedText;
};

export type FaultExplanation = {
  family: string | null;
  title: string;
  cause: string;
  standard: string;
  stopParty: StopParty;
  stopPartyLabel: string;
  attribution: string;
  knownFamily: boolean;
};

/**
 * Human-readable semantics for the fault families produced by the verified
 * DIN 70121 / ISO 15118 PCAP detector.  A related standard is not, by itself,
 * a conformance verdict; the packet-level reason is still the primary evidence.
 */
const FAULT_DEFINITIONS: Record<string, FaultDefinition> = {
  PROTOCOL_FAILED: {
    title: { th: "ลำดับหรือคำตอบของโปรโตคอลล้มเหลว", en: "Protocol response or sequence failed" },
    cause: {
      th: "ตู้ฝั่ง SECC ส่ง ResponseCode แบบ FAILED_* เช่น ลำดับข้อความผิด คำขอไม่ถูกต้อง หรือเจรจาโปรโตคอลไม่สำเร็จ โดย subtype ในหลักฐานจะบอกสาเหตุที่ละเอียดกว่า",
      en: "The charger's SECC returned a FAILED_* ResponseCode, such as an invalid message sequence, rejected request, or unsuccessful protocol negotiation. The evidence subtype provides the finer cause.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — ลำดับ request-response และความหมายของ ResponseCode",
      en: "DIN SPEC 70121 / ISO 15118-2 — request-response sequencing and ResponseCode semantics",
    },
    stopParty: "unknown",
    stopPartyLabel: { th: "ตู้ส่ง FAILED; ผู้เริ่มหยุดดู detail", en: "EVSE sent FAILED; initiator depends on detail" },
    attribution: {
      th: "ยืนยันได้ว่าคำตอบ FAILED มาจากฝั่งตู้ แต่ยังไม่เท่ากับยืนยันว่าตู้เป็นผู้ตัด TCP หรือถอดสาย",
      en: "The FAILED response is attributable to the charger, but it does not prove who later closed TCP or disconnected the cable.",
    },
  },
  EVSE_FAULT: {
    title: { th: "ตู้ชาร์จรายงานความขัดข้อง", en: "Charger-reported fault" },
    cause: {
      th: "EVSEStatusCode ระบุ EVSE_Malfunction หรือ EVSE_EmergencyShutdown จึงอาจเป็นความผิดปกติภายในตู้ วงจรกำลัง ระบบควบคุม หรือการหยุดฉุกเฉิน",
      en: "EVSEStatusCode reports EVSE_Malfunction or EVSE_EmergencyShutdown, which may indicate an internal charger, power-stage, control-system, or emergency-stop condition.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — EVSEStatusCode; เกี่ยวข้องกับข้อกำหนดความปลอดภัยของ DC EVSE ใน IEC 61851-23",
      en: "DIN SPEC 70121 / ISO 15118-2 — EVSEStatusCode; related DC-EVSE safety requirements are covered by IEC 61851-23",
    },
    stopParty: "evse",
    stopPartyLabel: { th: "ตู้ชาร์จ (EVSE)", en: "Charger (EVSE)" },
    attribution: {
      th: "ตู้เป็นฝ่ายรายงาน fault และโดยปกติจะหยุดหรือไม่อนุญาตการจ่ายกำลังเพื่อความปลอดภัย",
      en: "The charger reports the fault and normally stops or inhibits power delivery for safety.",
    },
  },
  ISOLATION_FAULT: {
    title: { th: "ค่าฉนวนแรงดันสูงไม่ปลอดภัย", en: "Unsafe high-voltage isolation" },
    cause: {
      th: "ระหว่าง CableCheck ตู้รายงาน EVSEIsolationStatus = Fault อาจเกิดจากฉนวนรั่วหรือค่าความต้านทานฉนวนต่ำในรถ สาย หัวต่อ หรือวงจรแรงดันสูงของตู้ จึงยังชี้อุปกรณ์ต้นเหตุจากสถานะนี้อย่างเดียวไม่ได้",
      en: "During CableCheck the charger reports EVSEIsolationStatus = Fault. Low insulation resistance or leakage may be in the EV, cable, connector, or charger high-voltage path, so this status alone does not locate the failed component.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — CableCheck และ EVSEIsolationStatus; เกี่ยวข้องกับ IEC 61851-23",
      en: "DIN SPEC 70121 / ISO 15118-2 — CableCheck and EVSEIsolationStatus; related to IEC 61851-23",
    },
    stopParty: "evse",
    stopPartyLabel: { th: "ตู้หยุดเพื่อความปลอดภัย", en: "Charger safety stop" },
    attribution: {
      th: "ตู้เป็นผู้ตรวจและกั้นการจ่ายไฟ แต่ต้นเหตุทางกายภาพอาจอยู่ที่รถ สาย หรือฝั่งตู้",
      en: "The charger detects the condition and inhibits power, while the physical root cause may be on the EV, cable, or charger side.",
    },
  },
  EV_ERROR: {
    title: { th: "รถรายงานสถานะผิดปกติ", en: "Vehicle-reported error" },
    cause: {
      th: "EV/EVCC ส่ง EVErrorCode ที่ไม่ใช่ NO_ERROR เช่น ปัญหาล็อกหัวชาร์จ กระแสต่างกัน หรือแรงดันอยู่นอกช่วง รายละเอียดจริงอยู่ใน code ที่ปรากฏในหลักฐาน",
      en: "The EV/EVCC sends an EVErrorCode other than NO_ERROR, such as connector-lock, current-differential, or voltage-range problems. The exact code in the evidence identifies the condition.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — EV status และ EVErrorCode ในลำดับการชาร์จ DC",
      en: "DIN SPEC 70121 / ISO 15118-2 — EV status and EVErrorCode in the DC charging sequence",
    },
    stopParty: "ev",
    stopPartyLabel: { th: "รถ (EV/EVCC) รายงาน error", en: "Vehicle (EV/EVCC) reported error" },
    attribution: {
      th: "รถเป็นฝ่ายรายงาน error หรือขอไม่เดินหน้าต่อ ส่วนตู้ยังเป็นผู้ตัดกำลังไฟตามลำดับความปลอดภัย",
      en: "The vehicle reports the error or declines to continue; the charger still removes power as part of the safety sequence.",
    },
  },
  SESSION_ABORT: {
    title: { th: "Session จบแบบไม่สมบูรณ์", en: "Charging session ended uncleanly" },
    cause: {
      th: "ไม่พบการปิด SessionStop ที่สมบูรณ์ โดยอาจมี TCP RST, request ไม่มี response, ลิงก์เริ่ม SLAC ใหม่กลาง session หรือสตรีมหยุดลง ทั้งนี้ไฟล์ PCAP ที่ถูกตัดอาจให้ภาพเดียวกัน",
      en: "A complete SessionStop close is absent, potentially with TCP RST, an unanswered request, re-SLAC during the session, or a dead stream. A truncated PCAP can produce the same observation.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — SessionStop, ลำดับข้อความ และ message timeout; TCP RST เป็นหลักฐานระดับ transport",
      en: "DIN SPEC 70121 / ISO 15118-2 — SessionStop, message sequencing, and message timeouts; TCP RST is transport-layer evidence",
    },
    stopParty: "unknown",
    stopPartyLabel: { th: "ยังระบุรถหรือตู้ไม่ได้", en: "EV or charger not yet attributable" },
    attribution: {
      th: "ต้องดูทิศทางของ TCP RST หรือดูว่าข้อความสุดท้ายเป็น Req/Res ของฝ่ายใด การไม่มี SessionStop เพียงอย่างเดียวใช้ชี้ผู้หยุดไม่ได้",
      en: "Inspect the TCP RST direction or which party owed the next Req/Res. Missing SessionStop alone cannot identify who stopped charging.",
    },
  },
  SLAC_FAILURE: {
    title: { th: "จับคู่สื่อสาร PLC ไม่สำเร็จ", en: "PLC/SLAC link matching failed" },
    cause: {
      th: "รถและตู้ไม่สามารถสร้างลิงก์ HomePlug Green PHY ผ่าน SLAC จนเริ่ม V2G dialog ได้ อาจมาจาก EVCC, SECC, สาย/หัวต่อ, สัญญาณรบกวน หรือจับคู่คนละ connector",
      en: "The EV and charger do not establish a HomePlug Green PHY link through SLAC before a V2G dialog begins. Possible causes include EVCC, SECC, cable/connector, noise, or cross-connector matching.",
    },
    standard: {
      th: "ISO 15118-3 — physical/data-link layer และ SLAC บน HomePlug Green PHY",
      en: "ISO 15118-3 — physical/data-link layer and SLAC over HomePlug Green PHY",
    },
    stopParty: "shared",
    stopPartyLabel: { th: "รถ–ตู้/ลิงก์ (ยังไม่เริ่มชาร์จ)", en: "EV–charger/link (charging not started)" },
    attribution: {
      th: "ยังไม่มี V2G session ให้เรียกว่าใครหยุด ต้องดูว่าฝ่ายใดส่ง SLAC request แล้วอีกฝ่ายไม่ตอบจึงจะแยกต้นเหตุได้",
      en: "No V2G charging session was established. Determine which side sent a SLAC request without a matching response before assigning cause.",
    },
  },
  COMM_FREEZE: {
    title: { th: "การสื่อสารค้างหรือเกินเวลา", en: "Communication stalled or timed out" },
    cause: {
      th: "ข้อความระหว่างจ่ายไฟหยุดนานผิดปกติ หรือขั้น CableCheck ค้าง อาจเกิดจาก EVCC, SECC, PLC/TCP, อุปกรณ์ประมวลผลช้า หรือ packet loss",
      en: "Messages stall during power delivery or CableCheck remains stuck. Causes may include EVCC, SECC, PLC/TCP, slow processing, or packet loss.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — message sequence/timeout; เกณฑ์ stall >5 วินาทีเป็น heuristic ของโมเดล ไม่ใช่ข้อสรุปว่าผิดมาตรฐานโดยตัวมันเอง",
      en: "DIN SPEC 70121 / ISO 15118-2 — message sequencing/timeouts; the model's >5 s stall threshold is a heuristic, not a conformance failure by itself",
    },
    stopParty: "unknown",
    stopPartyLabel: { th: "ต้องดูฝ่ายที่ค้างตอบ", en: "Depends on which side failed to respond" },
    attribution: {
      th: "ดูข้อความสุดท้ายว่าเป็น Req จากรถหรือ Res จากตู้ และดู packet ถัดไป/timeout เพื่อระบุฝ่ายที่ไม่ตอบ",
      en: "Use the last Req/Res, subsequent packets, and timeout evidence to identify which party stopped responding.",
    },
  },
  NO_POWER_DELIVERED: {
    title: { th: "เริ่มชาร์จแล้วแต่ไม่มีการจ่ายไฟ", en: "Charge attempted, no power delivered" },
    cause: {
      th: "รถขอพารามิเตอร์การชาร์จ (ChargeParameterDiscovery) และ session ปิดอย่างเรียบร้อย แต่ไม่เคยเข้าสู่ CurrentDemand จึงไม่มีพลังงานถูกจ่าย ส่วนใหญ่ PreCharge ดันแรงดันไม่เข้าใกล้ค่าที่รถขอก่อน session ถูกปิด ส่วนน้อย PreCharge ถึงแรงดันแล้วแต่รถยังสั่งหยุด หรือ session ปิดก่อนเริ่ม PreCharge (หลักฐานเป็น stopped after ChargeParameterDiscovery หรือ CableCheck) หลักฐานระบุขั้นสุดท้ายที่ไปถึง",
      en: "The EV requested charge parameters (ChargeParameterDiscovery) and the session closed gracefully, but CurrentDemand was never reached, so no energy was delivered. Most often PreCharge never brought the voltage near the EV's target before the close; less often PreCharge converged and the EV stopped anyway, or the session closed before PreCharge started (evidence: stopped after ChargeParameterDiscovery or CableCheck). The evidence names the last phase reached.",
    },
    standard: {
      th: "DIN SPEC 70121 / ISO 15118-2 — ลำดับ CableCheck → PreCharge → PowerDelivery → CurrentDemand; เป็นผลที่อนุมานจากลำดับข้อความ ไม่ใช่ error code ของโปรโตคอล (ResponseCode อาจเป็น OK ทั้งหมด)",
      en: "DIN SPEC 70121 / ISO 15118-2 — the CableCheck → PreCharge → PowerDelivery → CurrentDemand sequence; an outcome derived from the message sequence, not a protocol error code (every ResponseCode can be OK)",
    },
    stopParty: "unknown",
    stopPartyLabel: { th: "ปิดเรียบร้อย; ดูขั้นสุดท้ายและแรงดัน PreCharge", en: "Closed cleanly; check the last phase and PreCharge voltage" },
    attribution: {
      th: "ถ้าแรงดัน PreCharge ไม่เข้าใกล้ค่าที่รถขอ หลักฐานชี้ไปที่ภาคกำลังของตู้ ถ้าแรงดันถึงแล้วแต่รถยังสั่งหยุด หรือปิดก่อนถึง PreCharge จึงไม่มีแรงดันให้ตัดสิน packet อย่างเดียวยังแยกไม่ได้ว่าเป็นรถหรือตู้",
      en: "If the PreCharge voltage never approached the EV's target, the evidence points to the charger's power stage; if it converged and the EV still stopped, or the session closed before PreCharge so there is no voltage to judge, the packets alone cannot tell EV from charger.",
    },
  },
};

const UNKNOWN_DEFINITION: FaultDefinition = {
  title: { th: "AI พบรูปแบบผิดปกติที่ยังไม่จัดกลุ่ม", en: "Unclassified AI anomaly" },
  cause: {
    th: "โมเดลพบหลักฐานผิดปกติ แต่ข้อมูลปัจจุบันยังไม่พอผูกกับ Fault family ที่ยืนยันได้ ให้ใช้ข้อความ Evidence เป็นหลักในการตรวจต่อ",
    en: "The model found anomalous evidence but cannot yet bind it to a confirmed fault family. Use the Evidence text as the primary investigation lead.",
  },
  standard: {
    th: "ต้องเทียบ packet และลำดับข้อความจริงกับ DIN SPEC 70121 / ISO 15118 ก่อนสรุปว่าผิดข้อกำหนด",
    en: "Compare the actual packets and message sequence with DIN SPEC 70121 / ISO 15118 before concluding non-conformance",
  },
  stopParty: "unknown",
  stopPartyLabel: { th: "ยังระบุไม่ได้", en: "Not attributable yet" },
  attribution: {
    th: "Fault family หรือทิศทาง packet เพิ่มเติมจำเป็นต่อการแยกว่าเป็นรถหรือตู้",
    en: "A fault family or additional packet-direction evidence is required to distinguish EV from charger.",
  },
};

const REASON_FAMILY_HINTS: Array<[RegExp, string]> = [
  [/goal 'evse healthy' failed|evse_malfunction|evse_emergencyshutdown/i, "EVSE_FAULT"],
  [/goal 'insulation ok' failed|isolation.?fault/i, "ISOLATION_FAULT"],
  [/goal 'ev healthy' failed|everrorcode/i, "EV_ERROR"],
  [/goal 'dialog ok' failed|failed response/i, "PROTOCOL_FAILED"],
  [/no sessionsetupres|v2g2-448|tcp rst|re-slac mid-session/i, "SESSION_ABORT"],
  [/link_establishment_failing|slac attempts|slac_failure/i, "SLAC_FAILURE"],
  [/v2g2-443|v2g2-711|dialog_freezing|communication freeze|cablecheck.*stuck/i, "COMM_FREEZE"],
  // the labeller's detail ("never reached CurrentDemand") and the online rule's reason ("no CurrentDemand")
  [/(?:never reached|no) currentdemand/i, "NO_POWER_DELIVERED"],
];

export function resolveFaultFamily(
  family?: string | null,
  reason?: string | null,
): string | null {
  const normalized = family?.trim().toUpperCase() || null;
  if (normalized && FAULT_DEFINITIONS[normalized]) return normalized;
  const matched = REASON_FAMILY_HINTS.find(([pattern]) => pattern.test(reason ?? ""));
  return matched?.[1] ?? normalized;
}

export function getFaultExplanation(
  family: string | null | undefined,
  language: FaultLanguage,
  reason?: string | null,
): FaultExplanation {
  const resolvedFamily = resolveFaultFamily(family, reason);
  const definition = (resolvedFamily && FAULT_DEFINITIONS[resolvedFamily]) || UNKNOWN_DEFINITION;
  const explanation: FaultExplanation = {
    family: resolvedFamily,
    title: definition.title[language],
    cause: definition.cause[language],
    standard: definition.standard[language],
    stopParty: definition.stopParty,
    stopPartyLabel: definition.stopPartyLabel[language],
    attribution: definition.attribution[language],
    knownFamily: Boolean(resolvedFamily && FAULT_DEFINITIONS[resolvedFamily]),
  };

  const evidence = reason ?? "";
  if (resolvedFamily === "PROTOCOL_FAILED" && /SessionStopRes.*FAILED_SequenceError/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "shared",
      stopPartyLabel: language === "th"
        ? "รถเริ่มปิด session; ตู้ตอบ SequenceError"
        : "EV started close; EVSE returned SequenceError",
      attribution: language === "th"
        ? "รถส่ง SessionStopReq ก่อน จึงเป็นฝ่ายเริ่มจบการชาร์จ ส่วนตู้ตอบ SessionStopRes ด้วย FAILED_SequenceError ซึ่งเป็นความผิดปกติของขั้นปิด session"
        : "The EV sent SessionStopReq first and therefore initiated the close; the EVSE then returned FAILED_SequenceError in SessionStopRes.",
    };
  }
  if (resolvedFamily === "PROTOCOL_FAILED" && /Failed_NoNegotiation/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "shared",
      stopPartyLabel: language === "th" ? "รถ–ตู้เจรจา protocol ไม่สำเร็จ" : "EV–EVSE negotiation failed",
      attribution: language === "th"
        ? "ทั้งสองฝั่งไม่มี application protocol ที่ตกลงร่วมกัน จึงยังไม่เข้าสู่ charging session และยังไม่ใช่การหยุดระหว่างจ่ายไฟ"
        : "The two sides found no mutually supported application protocol, so a charging session never started.",
    };
  }
  if (resolvedFamily === "EV_ERROR" && /ChargingCurrentdifferential/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "ev",
      stopPartyLabel: language === "th" ? "รถหยุด; สาเหตุชี้ไปที่การควบคุมตู้" : "EV stopped; cause points to EVSE regulation",
      attribution: language === "th"
        ? "รถเป็นฝ่ายส่ง error และหยุดลำดับการชาร์จ หลังตรวจว่ากระแสที่ตู้จ่ายต่างจากค่าที่ร้องขอเกินเกณฑ์"
        : "The EV reported the error and stopped the sequence after detecting excessive difference between requested and delivered current.",
    };
  }
  if (resolvedFamily === "EV_ERROR" && /ChargerConnectorLockFault/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "ev",
      stopPartyLabel: language === "th" ? "รถรายงานและไม่เดินหน้าต่อ" : "EV reported and declined to continue",
      attribution: language === "th"
        ? "รถตรวจไม่พบสถานะล็อกที่ต้องการจึงรายงาน fault แต่กลไกล็อกอยู่ตรง interface รถ–หัวชาร์จ จึงยังฟันธงอุปกรณ์ต้นเหตุไม่ได้"
        : "The EV did not observe the required lock state and reported the fault; the lock is at the EV–connector interface, so the failed component is not proven.",
    };
  }
  if (resolvedFamily === "SESSION_ABORT" && /no SessionSetupRes/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "evse",
      stopPartyLabel: language === "th" ? "ตู้/SECC ไม่ตอบ SessionSetup" : "EVSE/SECC did not answer SessionSetup",
      attribution: language === "th"
        ? "รถส่งคำขอตั้ง session แต่ไม่พบคำตอบจากตู้ภายในเวลา อย่างไรก็ตาม packet loss หรือ PCAP ไม่ครบยังทำให้เห็นอาการเดียวกันได้"
        : "The EV requested session setup but no EVSE response was observed in time; packet loss or an incomplete capture can still mimic this.",
    };
  }
  if (resolvedFamily === "SESSION_ABORT" && /re-SLAC/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "shared",
      stopPartyLabel: language === "th" ? "ลิงก์รถ–ตู้หลุด" : "EV–EVSE link dropped",
      attribution: language === "th"
        ? "เกิดการเริ่มจับคู่ SLAC ใหม่กลาง session แสดงว่าลิงก์เดิมขาด แต่ข้อมูลนี้ยังไม่บอกว่า modem ฝั่งรถ ตู้ สาย หรือสัญญาณรบกวนเป็นต้นเหตุ"
        : "SLAC matching restarted mid-session, proving loss of the previous link but not whether the EV modem, EVSE modem, cable, or noise caused it.",
    };
  }
  if (["COMM_FREEZE", "SESSION_ABORT"].includes(resolvedFamily ?? "") && /no further request/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "ev",
      stopPartyLabel: language === "th" ? "รถหยุดส่ง request" : "EV stopped sending requests",
      attribution: language === "th"
        ? "ข้อความ response ล่าสุดมาจากตู้ แต่รถไม่ส่ง request ถัดไปจน timeout; ตู้จึงยุติการเชื่อมต่อตามเวลา"
        : "The charger sent the latest response, but the EV sent no next request before timeout; the charger then terminates the connection.",
    };
  }
  if (["COMM_FREEZE", "SESSION_ABORT"].includes(resolvedFamily ?? "") && /EVSEProcessing.*Ongoing/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "shared",
      stopPartyLabel: language === "th" ? "ตู้ค้าง; รถหยุดเมื่อ timeout" : "EVSE stalled; EV stops at timeout",
      attribution: language === "th"
        ? "ตู้รายงาน Processing=Ongoing นานเกินช่วงที่กำหนด และรถเป็นฝ่ายต้องยุติ session เมื่อครบ timeout"
        : "The EVSE remained Processing=Ongoing beyond the allowed interval, and the EV is required to stop the session at timeout.",
    };
  }
  if (["COMM_FREEZE", "SESSION_ABORT"].includes(resolvedFamily ?? "") && /CableCheck stuck/i.test(evidence)) {
    return {
      ...explanation,
      stopParty: "shared",
      stopPartyLabel: language === "th" ? "ตู้ทดสอบไม่เสร็จ; รถหยุด timeout" : "EVSE test stalled; EV stops at timeout",
      attribution: language === "th"
        ? "ตู้ไม่จบขั้นตรวจฉนวน CableCheck ภายในเวลา และรถต้องยุติเมื่อถึง timeout; ต้องตรวจ IMD และลิงก์สื่อสารของตู้เพิ่มเติม"
        : "The EVSE did not complete CableCheck in time and the EV must stop at timeout; inspect the EVSE insulation monitor and communication path.",
    };
  }
  return explanation;
}

export const supportedFaultFamilies = Object.freeze(Object.keys(FAULT_DEFINITIONS));
