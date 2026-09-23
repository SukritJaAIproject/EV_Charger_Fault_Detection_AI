import { describe, expect, it } from "vitest";
import {
  FULL_FLEET_LABELS,
  LABEL_LINEAGE,
  MODEL_ORDER,
  RESEARCH_GRIDS,
  RESEARCH_MODEL_ARTIFACT,
  RESEARCH_PROFILES,
  RESEARCH_PROFILES_V4,
  RESEARCH_V4_ARTIFACT,
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

  it("gives the v4 models baseline and both SLAC arms under every label profile, and no ISO-2 arm", () => {
    for (const profile of Object.values(RESEARCH_PROFILES_V4)) {
      expect(Object.keys(profile.arms).sort()).toEqual(["baseline", "empirical", "normative"]);
      for (const arm of Object.values(profile.arms)) {
        expect(Object.keys(arm ?? {}).sort()).toEqual([...MODEL_ORDER].sort());
      }
      expect(profile.faulty + profile.clean).toBe(profile.sessions);
    }
  });

  it("pins v4 strict.baseline to the shipped v4 benchmark leaderboard", () => {
    // G:/ev_charger_ai_data_v4/results/leaderboard_test.json, rounded to 1 dp
    const baseline = RESEARCH_PROFILES_V4.strict.arms.baseline!;
    expect(baseline.TraditionalAI.score).toBe(69.6);
    expect(baseline.AgenticAI.score).toBe(66.9);
    expect(baseline.MultiAgent.score).toBe(60.2);
    expect(baseline.AIAgent.score).toBe(46.4);
    expect(baseline.RL.score).toBe(39.2);
  });

  it("holds the invariants that make the v4 grid comparable with the 41ded2cd one", () => {
    const measured: ResearchArmId[] = ["baseline", "empirical", "normative"];
    for (const [profileId, profile] of Object.entries(RESEARCH_PROFILES_V4)) {
      const old = RESEARCH_PROFILES[profileId as keyof typeof RESEARCH_PROFILES];
      expect([profile.sessions, profile.faulty, profile.clean]).toEqual([old.sessions, old.faulty, old.clean]);
      for (const arm of measured) {
        // MultiAgent has no trained weights: its alerts are identical for both model sets
        expect(profile.arms[arm]!.MultiAgent).toEqual(old.arms[arm].MultiAgent);
        // RL has no SLAC path, so the SLAC arms cannot move it
        expect(profile.arms[arm]!.RL).toEqual(profile.arms.baseline!.RL);
      }
    }
  });

  it("lists one grid per model set, the 2026-09-12 set first", () => {
    expect(RESEARCH_GRIDS.map((grid) => grid.artifact)).toEqual([RESEARCH_MODEL_ARTIFACT, RESEARCH_V4_ARTIFACT]);
    expect(RESEARCH_GRIDS[0].profiles).toBe(RESEARCH_PROFILES);
    expect(RESEARCH_GRIDS[1].profiles).toBe(RESEARCH_PROFILES_V4);
    expect(RESEARCH_GRIDS[1].aiAgentLowerBoundArms).toEqual(["empirical", "normative"]);
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

