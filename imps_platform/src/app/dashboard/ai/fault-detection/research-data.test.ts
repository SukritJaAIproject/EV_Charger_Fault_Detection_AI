import { describe, expect, it } from "vitest";
import {
  FULL_FLEET_LABELS,
  LABEL_LINEAGE,
  MODEL_ORDER,
  RESEARCH_PROFILES,
  SLAC_RESEARCH,
  type ResearchArmId,
} from "./research-data";

const arms: ResearchArmId[] = ["baseline", "iso2", "empirical", "normative"];

describe("fault-detection research snapshot", () => {
  it("keeps every model and metric complete for each profile and arm", () => {
    Object.values(RESEARCH_PROFILES).forEach((profile) => {
      arms.forEach((arm) => {
        expect(Object.keys(profile.arms[arm]).sort()).toEqual([...MODEL_ORDER].sort());
        Object.values(profile.arms[arm]).forEach((metric) => {
          expect(metric.score).toBeGreaterThanOrEqual(0);
          expect(metric.score).toBeLessThanOrEqual(100);
          expect(metric.recall).toBeGreaterThanOrEqual(0);
          expect(metric.recall).toBeLessThanOrEqual(100);
          expect(metric.far).toBeGreaterThanOrEqual(0);
          expect(metric.far).toBeLessThanOrEqual(100);
          expect(metric.lead).toBeGreaterThanOrEqual(0);
        });
      });
      expect(profile.faulty + profile.clean).toBe(profile.sessions);
    });
  });

  it("preserves the audited published normative leaderboard", () => {
    const normative = RESEARCH_PROFILES.published.arms.normative;
    expect(normative.TraditionalAI.score).toBe(77.7);
    expect(normative.RL.score).toBe(49.5);
    expect(normative.AIAgent.score).toBe(63.0);
    expect(normative.AgenticAI.score).toBe(71.5);
    expect(normative.MultiAgent.score).toBe(66.4);
  });

  it("keeps full-fleet label totals internally consistent", () => {
    const faultTotal = FULL_FLEET_LABELS.distribution.reduce(
      (sum, row) => sum + row.sessions,
      0,
    );
    const censorTotal = FULL_FLEET_LABELS.censorReasons.reduce(
      (sum, row) => sum + row.sessions,
      0,
    );
    expect(faultTotal).toBe(FULL_FLEET_LABELS.faulty);
    expect(censorTotal).toBe(FULL_FLEET_LABELS.censored);
    expect(
      FULL_FLEET_LABELS.clean
        + FULL_FLEET_LABELS.faulty
        + FULL_FLEET_LABELS.censored,
    ).toBe(FULL_FLEET_LABELS.sessions);
    expect(FULL_FLEET_LABELS.clean + FULL_FLEET_LABELS.faulty).toBe(
      FULL_FLEET_LABELS.scoring,
    );
  });

  it("keeps lineage and SLAC fire totals consistent", () => {
    expect(LABEL_LINEAGE.map((row) => row.id)).toEqual([
      "published",
      "strict",
      "reviewed",
    ]);
    expect(
      SLAC_RESEARCH.responseTimeoutFires + SLAC_RESEARCH.missingRequestFires,
    ).toBe(SLAC_RESEARCH.normativeFires);
  });
});

