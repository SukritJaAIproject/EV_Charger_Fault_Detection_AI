import { describe, expect, it } from "vitest";

import {
  getFaultExplanation,
  resolveFaultFamily,
  supportedFaultFamilies,
} from "./fault-catalog";

describe("fault catalog", () => {
  it("documents every fault family produced by the detector", () => {
    expect(supportedFaultFamilies).toHaveLength(7);
    expect(supportedFaultFamilies).toEqual(expect.arrayContaining([
      "PROTOCOL_FAILED",
      "EVSE_FAULT",
      "ISOLATION_FAULT",
      "EV_ERROR",
      "SESSION_ABORT",
      "SLAC_FAILURE",
      "COMM_FREEZE",
    ]));
    for (const family of supportedFaultFamilies) {
      const detail = getFaultExplanation(family, "th");
      expect(detail.knownFamily).toBe(true);
      expect(detail.cause.length).toBeGreaterThan(20);
      expect(detail.standard.length).toBeGreaterThan(10);
      expect(detail.attribution.length).toBeGreaterThan(10);
    }
  });

  it("infers hard-fault semantics from an Agentic AI reason", () => {
    expect(resolveFaultFamily(null, "goal 'EV healthy' failed: FAILED_ChargingCurrentdifferential"))
      .toBe("EV_ERROR");
    expect(resolveFaultFamily(null, "goal 'session established' failed: no SessionSetupRes within 20s [V2G2-448]"))
      .toBe("SESSION_ABORT");
  });

  it("does not pretend an unknown model anomaly identifies the stopping party", () => {
    const detail = getFaultExplanation(null, "en", "pattern anomaly confirmed");
    expect(detail.knownFamily).toBe(false);
    expect(detail.stopParty).toBe("unknown");
  });

  it("uses packet detail to distinguish the stop initiator from the reporter", () => {
    const closeFailure = getFaultExplanation(
      "PROTOCOL_FAILED",
      "th",
      "SessionStopRes:FAILED_SequenceError",
    );
    expect(closeFailure.stopParty).toBe("shared");
    expect(closeFailure.attribution).toContain("รถส่ง SessionStopReq");

    const noNextRequest = getFaultExplanation(
      "COMM_FREEZE",
      "en",
      "no further request for 60s [V2G2-443]",
    );
    expect(noNextRequest.stopParty).toBe("ev");
  });
});
