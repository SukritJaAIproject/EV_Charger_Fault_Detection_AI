import {
  stationSplitOf,
  type BundledBenchmark,
  type DetectionPolicy,
  type FaultDetectionModelId,
  type StationAnalysis,
} from "./data";
import {
  LABEL_LINEAGE,
  MODEL_ORDER,
  RESEARCH_GRIDS,
  type ResearchGrid,
  type ResearchModelId,
  type ResearchProfileId,
} from "./research-data";

/**
 * Numbers derived from the benchmark bundled with the running edition
 * (data/summary.json). Two editions ship the same UI code and differ only in
 * this file and their model weights, so anything the page presents as "this
 * edition's result" is computed here rather than written as a literal.
 *
 * Headline totals come from `dataset` and the leaderboard only. They are never
 * summed over `analysis.byStation`: a later summary also lists the training
 * stations there, with in-sample predictions, and those must not leak into
 * held-out figures.
 */

// Leaderboard ids used by data/summary.json -> ids of the research constants.
export const RESEARCH_ID_BY_MODEL_ID: Record<FaultDetectionModelId, ResearchModelId> = {
  traditional: "TraditionalAI",
  rl: "RL",
  "ai-agent": "AIAgent",
  "agentic-ai": "AgenticAI",
  "multi-agent": "MultiAgent",
};

export type FaultCount = { family: string; sessions: number };

/**
 * Held-out fault mix of this edition: sessions per first-fault family. Every
 * model's `byFamily` carries the same `nFaulty` counts (they describe the
 * labels, not the model), so the first non-empty one is used. Largest first.
 */
export function heldOutFaultDistribution(bundled: BundledBenchmark | null): FaultCount[] {
  const source = bundled?.leaderboard.find((row) => row.byFamily.length > 0);
  if (!source) return [];
  return source.byFamily
    .filter((row) => row.nFaulty > 0)
    .map((row) => ({ family: row.family, sessions: row.nFaulty }))
    .sort((left, right) => right.sessions - left.sessions || left.family.localeCompare(right.family));
}

/**
 * The research label profile whose held-out counts are exactly this edition's
 * labels (957 faulty = published, 1,326 = strict), or null when none match.
 * Faulty, clean and scored-session counts must all agree: a summary that kept
 * the 295 inconclusive sessions as clean is not the ISO-reviewed label set.
 */
export function researchProfileForBundled(bundled: BundledBenchmark | null): ResearchProfileId | null {
  const dataset = bundled?.dataset;
  if (!dataset || dataset.sessions === null || dataset.faultySessions === null || dataset.normalSessions === null) {
    return null;
  }
  const match = LABEL_LINEAGE.find(
    (row) =>
      row.faulty === dataset.faultySessions &&
      row.clean === dataset.normalSessions &&
      row.total - row.censored === dataset.sessions,
  );
  return match?.id ?? null;
}

export type DetectionPolicyKind = "baseline" | "rules";

/**
 * Whether a benchmark ran the plain detectors or added standard rule layers.
 * Absent (every summary before 1.3.0) means baseline.
 */
export function detectionPolicyKind(policy: DetectionPolicy | null | undefined): DetectionPolicyKind {
  if (!policy) return "baseline";
  const slac = policy.slacRuleMode?.trim().toLowerCase() ?? "";
  return policy.iso2Rules || (slac !== "" && slac !== "off") ? "rules" : "baseline";
}

export type ResearchModelRelation = "same" | "different" | "unknown";

const oneDecimal = (value: number) => Number(value.toFixed(1));

/**
 * The bundled leaderboard's own verdict on which research grid it belongs to:
 * under the same labels and the baseline policy, a grid's baseline arm must
 * reproduce all five models' score, recall and false-alarm rate to the
 * research data's one decimal. `checkable` is false when the leaderboard
 * cannot speak - nothing bundled, labels that match no profile, a partial
 * leaderboard, or a rule-armed benchmark (ISO 15118 edition), which matches
 * no single research arm.
 */
function gridFromLeaderboard(bundled: BundledBenchmark | null): { checkable: boolean; grid: ResearchGrid | null } {
  if (!bundled || detectionPolicyKind(bundled.detectionPolicy) !== "baseline") return { checkable: false, grid: null };
  const profileId = researchProfileForBundled(bundled);
  if (!profileId) return { checkable: false, grid: null };
  const scored = bundled.leaderboard.filter(
    (row) => row.score !== null && row.recall !== null && row.falseAlarmRate !== null,
  );
  if (scored.length !== MODEL_ORDER.length) return { checkable: false, grid: null };
  const grid = RESEARCH_GRIDS.find((candidate) => {
    const baseline = candidate.profiles[profileId].arms.baseline;
    return (
      baseline !== undefined &&
      scored.every((row) => {
        const research = baseline[RESEARCH_ID_BY_MODEL_ID[row.id]];
        return (
          oneDecimal(row.score as number) === research.score &&
          oneDecimal(row.recall as number) === research.recall &&
          oneDecimal(row.falseAlarmRate as number) === research.far
        );
      })
    );
  });
  return { checkable: true, grid: grid ?? null };
}

export type ResearchGridChoice = { grid: ResearchGrid; relation: ResearchModelRelation };

/**
 * The research grid to show and how it relates to the models behind the
 * bundled benchmark. The sidecar's artifact id decides when it is known, the
 * leaderboard when it is not (web build, older sidecar). When both can speak
 * and disagree, the models and the summary were packaged from different runs:
 * the page falls back to the first grid and says it does not know. Models with
 * no grid of their own get the first grid, marked "different".
 */
export function selectResearchGrid(
  bundled: BundledBenchmark | null,
  modelArtifact?: string | null,
): ResearchGridChoice {
  const fallback = RESEARCH_GRIDS[0];
  const fromLeaderboard = gridFromLeaderboard(bundled);
  const artifact = modelArtifact?.trim().toLowerCase();
  if (artifact) {
    const byArtifact = RESEARCH_GRIDS.find((grid) => grid.artifact === artifact) ?? null;
    if (fromLeaderboard.checkable && fromLeaderboard.grid !== byArtifact) {
      return { grid: fallback, relation: "unknown" };
    }
    return byArtifact ? { grid: byArtifact, relation: "same" } : { grid: fallback, relation: "different" };
  }
  if (fromLeaderboard.grid) return { grid: fromLeaderboard.grid, relation: "same" };
  return { grid: fallback, relation: fromLeaderboard.checkable ? "different" : "unknown" };
}

/** How the shown research grid relates to the models behind the benchmark. */
export function researchModelRelation(
  bundled: BundledBenchmark | null,
  modelArtifact?: string | null,
): ResearchModelRelation {
  return selectResearchGrid(bundled, modelArtifact).relation;
}

/**
 * Held-out stations only. From 1.3.0 a summary may also carry in-sample
 * training stations; anything captioned "held-out" must not count them.
 */
export function heldOutStations(stations: StationAnalysis[]): StationAnalysis[] {
  return stations.filter((station) => stationSplitOf(station) === "test");
}

/** Share of `whole` as a one-decimal percentage string, or null when undefined. */
export function percentOf(part: number, whole: number): string | null {
  return whole > 0 ? `${((part / whole) * 100).toFixed(1)}%` : null;
}
