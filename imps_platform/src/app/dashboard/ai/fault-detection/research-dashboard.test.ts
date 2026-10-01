import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { BundledBenchmark, StationAnalysis } from "./data";
import {
  CURRENT_EDITION,
  ISO2_ONLY_BENCHMARK,
  ISO_EDITION,
  SNAPSHOT_EDITION,
  SNAPSHOT_FAMILIES,
  fixtureBundle,
  fixtureStation,
} from "./edition-fixtures";
import ResearchDashboard from "./research-dashboard";

// Renders the Overview the way each edition ships it and reads the text a user
// sees. createElement rather than JSX keeps this a plain .ts test.
const render = (
  bundled: BundledBenchmark | null,
  {
    lang = "en",
    modelArtifact = null,
    desktop = true,
    stations = [],
  }: { lang?: "th" | "en"; modelArtifact?: string | null; desktop?: boolean; stations?: StationAnalysis[] } = {},
) =>
  renderToStaticMarkup(
    createElement(ResearchDashboard, {
      lang,
      bundled,
      desktop,
      modelArtifact,
      stations,
      stationLoading: false,
      stationError: null,
      onRetryStations: () => {},
      onSelectStation: () => {},
      onOpenStations: () => {},
    }),
  );

/** The opening tag of one detection-policy tab, whatever order React wrote its attributes in. */
const armTab = (html: string, arm: string) => {
  const tag = html.match(new RegExp(`<button[^>]*data-testid="fd-arm-${arm}"[^>]*>`));
  if (!tag) throw new Error(`no tab for arm ${arm}`);
  return tag[0];
};

const ENTITIES: Record<string, string> = { "&#x27;": "'", "&quot;": '"', "&lt;": "<", "&gt;": ">", "&amp;": "&" };
const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;|&quot;|&lt;|&gt;|&amp;/g, (entity) => ENTITIES[entity])
    .replace(/\s+/g, " ");

describe("Overview differs by edition because it reads the bundled benchmark", () => {
  it("draws the current edition's own held-out fault mix, including NO_POWER_DELIVERED", () => {
    const html = render(CURRENT_EDITION);
    expect(html).toContain('data-mix="edition"');
    const t = text(html);
    expect(t).toContain("Fault distribution · held-out test set");
    expect(t).toContain(
      "1,326 fault sessions among 8,820 held-out sessions at 45 stations the models never saw · read from this edition's data/summary.json",
    );
    expect(t).toContain("7 types");
    expect(t).toContain("NO POWER DELIVERED");
  });

  it("draws the snapshot edition's six-family mix, with no NO_POWER_DELIVERED", () => {
    const t = text(render(SNAPSHOT_EDITION));
    expect(t).toContain("957 fault sessions among 8,820 held-out sessions");
    expect(t).toContain("6 types");
    // the donut and its legend are this edition's; NPD must not appear in them
    const mix = t.slice(t.indexOf("Fault distribution · held-out test set"), t.indexOf("Station fault distribution"));
    expect(mix).not.toContain("NO POWER DELIVERED");
  });

  it("falls back to the labelled research full-fleet mix when nothing is bundled", () => {
    const html = render(null);
    expect(html).toContain('data-mix="research"');
    expect(text(html)).toContain("Fault distribution · full fleet (research)");
    expect(text(html)).toContain("9 types");
  });

  it("says whether the research panel describes the models behind the benchmark", () => {
    expect(render(SNAPSHOT_EDITION)).toContain('data-relation="same"');
    expect(text(render(SNAPSHOT_EDITION))).toContain(
      "Computed on the same models as the benchmark above (41ded2cdd5c2ba3f)",
    );
    // v4 now has its own grid
    expect(render(CURRENT_EDITION)).toContain('data-relation="same"');
    expect(text(render(CURRENT_EDITION))).toContain(
      "Computed on the same models as the benchmark above (53b6f14244c2e633)",
    );
    // the sidecar's artifact id agrees with the v4 leaderboard
    expect(render(CURRENT_EDITION, { modelArtifact: "53b6f14244c2e633" })).toContain('data-relation="same"');
    // models with no grid of their own get the 2026-09-12 grid, and say so; the
    // research id sits with "earlier model set", not after "not ... this"
    expect(text(render(null, { modelArtifact: "0123456789abcdef" }))).toContain(
      "Computed on an earlier model set (41ded2cdd5c2ba3f), not the one behind the benchmark above",
    );
    // and a contradiction is reported as unknown rather than guessed
    expect(render(SNAPSHOT_EDITION, { modelArtifact: "53b6f14244c2e633" })).toContain('data-relation="unknown"');
    expect(render(null)).toContain('data-relation="unknown"');
  });

  it("shows the v4 models' own research numbers in the v4 edition", () => {
    const t = text(render(CURRENT_EDITION));
    // strict labels (the edition's own) x "+ SLAC 600 ms": v4 TraditionalAI 76.6 / 94.3% / 24.8% / 23.9 s
    expect(t).toContain("76.6 Traditional AI · Highest score in this view");
    expect(t).toContain("Recall 94.3% False alarm 24.8% Median lead 23.9s");
    expect(t).not.toContain("69.2 Traditional AI · Highest score in this view");
    expect(t).toContain("Verified: 23 Sept 2026");
    // the snapshot edition keeps the 2026-09-12 numbers
    expect(text(render(SNAPSHOT_EDITION))).toContain("77.7 Traditional AI · Highest score in this view");
  });

  it("marks what was projected for the v4 models, which now have every arm measured", () => {
    const v4 = render(CURRENT_EDITION);
    // ISO-2 alone was replayed 2026-09-30/10-01: the tab is live, nothing is marked not measured
    for (const arm of ["baseline", "iso2", "empirical", "normative", "iso2normative"]) {
      expect(armTab(v4, arm)).not.toContain('disabled=""');
      expect(armTab(v4, arm)).not.toContain('aria-describedby="fd-arms-not-measured"');
    }
    expect(text(v4)).not.toContain("Not measured for this model set");
    expect(text(v4)).not.toContain("not yet measured for this model set");
    expect(text(v4)).toContain("including ISO 15118-2 rules and ISO 15118-3 SLAC timing.");
    // the default +SLAC 600 ms arm is still a projection, with AIAgent a lower bound
    expect(text(v4)).toContain(
      "This policy is projected from recorded alerts, not replayed · AI Agent's recall and false-alarm rate are lower bounds",
    );
    // ...without claiming the set was never replayed: its ISO-2 + SLAC arm is a replay
    expect(text(v4)).toContain("— SLAC projection not checked against a replay for this model set");
    expect(text(v4)).not.toContain("Not replayed for this model set");
    expect(text(v4)).not.toContain("Projection–replay agreement");

    // the 2026-09-12 set was replayed under ISO-2; only its normative arm is a projection
    const old = render(SNAPSHOT_EDITION);
    expect(armTab(old, "iso2")).not.toContain('disabled=""');
    // ...but it never ran ISO-2 and SLAC together
    expect(armTab(old, "iso2normative")).toContain('disabled=""');
    expect(armTab(old, "iso2normative")).toContain('title="Not measured for this model set (needs a replay)"');
    // the reason is visible text tied to the tab, not only a tooltip on a tab that cannot take focus
    expect(armTab(old, "iso2normative")).toContain('aria-describedby="fd-arms-not-measured"');
    expect(old).toContain('id="fd-arms-not-measured"');
    expect(text(old)).toContain("+ ISO-2 + SLAC 600 ms: Not measured for this model set (needs a replay)");
    expect(text(old)).not.toContain("+ ISO 15118-2: Not measured");
    expect(text(old)).toContain("including ISO 15118-2 rules and ISO 15118-3 SLAC timing.");
    expect(text(old)).toContain("100% Projection–replay agreement");
    expect(text(old)).toContain("This policy is projected from recorded alerts, not replayed");
    expect(text(old)).not.toContain("lower bounds");
  });

  it("opens the ISO 15118 edition on its own policy, so the panel's first view is its bundled leaderboard", () => {
    const iso = render(ISO_EDITION, { modelArtifact: "53b6f14244c2e633" });
    expect(iso).toMatch(/aria-selected="true"[^>]*data-testid="fd-arm-iso2normative"/);
    const t = text(iso);
    // strict x ISO-2 + SLAC 600 ms = the ISO edition's leaderboard: TraditionalAI 77.3 / 95.9% / 25.0% / 22.6 s
    expect(t).toContain("77.3 Traditional AI · Highest score in this view");
    expect(t).toContain("Recall 95.9% False alarm 25.0% Median lead 22.6s");
    // a replay, not a projection: no provenance footnote, no lower-bound note
    expect(iso).not.toContain('data-testid="fd-arm-provenance"');
    // dated when that arm was scored, not when the rest of the v4 grid was
    expect(t).toContain("Verified: 30 Sept 2026");
    // the baseline editions still open on + SLAC 600 ms
    expect(render(CURRENT_EDITION)).toMatch(/aria-selected="true"[^>]*data-testid="fd-arm-normative"/);
    expect(text(render(CURRENT_EDITION))).toContain("Verified: 23 Sept 2026");
  });

  it("opens an ISO-2-only benchmark on the replayed ISO-2 arm, not on a projection", () => {
    const iso2 = render(ISO2_ONLY_BENCHMARK);
    expect(iso2).toContain('data-relation="same"');
    expect(iso2).toMatch(/aria-selected="true"[^>]*data-testid="fd-arm-iso2"/);
    // strict x ISO-2 alone = that replay's leaderboard: TraditionalAI 70.3 / 84.1% / 24.8% / 8.4 s
    expect(text(iso2)).toContain("70.3 Traditional AI · Highest score in this view");
    expect(text(iso2)).toContain("Recall 84.1% False alarm 24.8% Median lead 8.4s");
    expect(iso2).not.toContain('data-testid="fd-arm-provenance"');
  });

  it("finds the ISO edition's own arm from its leaderboard when the sidecar gives no artifact id", () => {
    // web build, older sidecar, or the moment before /health answers
    const iso = render(ISO_EDITION);
    expect(iso).toContain('data-relation="same"');
    expect(iso).toMatch(/aria-selected="true"[^>]*data-testid="fd-arm-iso2normative"/);
    expect(text(iso)).toContain("77.3 Traditional AI · Highest score in this view");
    expect(text(iso)).not.toContain("+ ISO-2 + SLAC 600 ms: Not measured");
  });

  it("warns that the old labels count the v4 models' NO_POWER_DELIVERED alerts as false alarms", () => {
    // v4 weights benchmarked on the 2026-09-12 labels: opens on the published profile of the v4 grid
    const v4OnOldLabels = fixtureBundle(957, SNAPSHOT_FAMILIES, [
      ["traditional", 67.3, 76.9, 28.0],
      ["agentic-ai", 70.2, 90.7, 33.0],
      ["multi-agent", 56.3, 62.6, 28.3],
      ["ai-agent", 51.3, 58.0, 35.9],
      ["rl", 41.3, 21.6, 5.8],
    ]);
    const t = text(render(v4OnOldLabels));
    expect(t).toContain("These labels count 369 sessions this model set was trained to flag");
    expect(text(render(v4OnOldLabels, { lang: "th" }))).toContain(
      "369 sessions ที่โมเดลชุดนี้ถูกสอนให้แจ้งว่าเป็น fault (NO_POWER_DELIVERED 360, SLAC 9) เป็น session ปกติ",
    );
    expect(text(render(SNAPSHOT_EDITION))).not.toContain("369 sessions");
  });

  it("opens the research panel on the label profile this benchmark was scored with", () => {
    const current = text(render(CURRENT_EDITION));
    expect(current).toContain("Recomputed strict labels · no censorship same labels as the benchmark above");
    const snapshot = text(render(SNAPSHOT_EDITION));
    expect(snapshot).toContain("Original published benchmark · 8,820 sessions same labels as the benchmark above");
  });

  it("keeps the footnote honest about which models the research rescored", () => {
    expect(text(render(SNAPSHOT_EDITION))).toContain("rescores these same models");
    expect(text(render(CURRENT_EDITION))).toContain("rescores these same models");
    expect(text(render(null, { modelArtifact: "0123456789abcdef" }))).toContain("rescores earlier models");
  });

  it("renders the Thai copy with the same data", () => {
    const t = text(render(CURRENT_EDITION, { lang: "th" }));
    expect(t).toContain("สัดส่วน Fault · ชุดทดสอบ held-out");
    expect(t).toContain("1,326 fault sessions จาก 8,820 sessions ทดสอบใน 45 สถานีที่โมเดลไม่เคยเห็น");
    expect(t).toContain("7 ประเภท");
    expect(t).toContain("คำนวณบนโมเดลชุดเดียวกับ benchmark ด้านบน (53b6f14244c2e633)");
    expect(armTab(render(CURRENT_EDITION, { lang: "th" }), "iso2")).not.toContain('disabled=""');
    expect(armTab(render(SNAPSHOT_EDITION, { lang: "th" }), "iso2normative")).toContain('title="ยังไม่ได้วัดกับโมเดลชุดนี้ (ต้อง replay)"');
    expect(text(render(null, { lang: "th", modelArtifact: "0123456789abcdef" }))).toContain(
      "คำนวณบนโมเดลชุดก่อน (41ded2cdd5c2ba3f) ไม่ใช่ชุดที่ใช้ใน benchmark ด้านบน",
    );
  });

  it("derives the research stat-row shares instead of hard-coding them", () => {
    const t = text(render(null));
    // 100% is the full fleet as its own denominator; the other three are computed
    for (const share of ["100%", "96.5%", "15.1%", "3.5%"]) expect(t).toContain(share);
  });
});

describe("Overview wording follows where the numbers came from", () => {
  it("names the fault-detection service, not a bundled file, on the web", () => {
    const t = text(render(CURRENT_EDITION, { desktop: false }));
    expect(t).toContain("1,326 fault sessions among 8,820 held-out sessions at 45 stations the models never saw · read from the fault-detection service");
    expect(t).not.toContain("this edition's data/summary.json");
    expect(t).toContain("Benchmark from the fault-detection service");
  });

  it("drops the unseen-stations claim when the summary has no station count", () => {
    const noStations = { ...CURRENT_EDITION, dataset: { ...CURRENT_EDITION.dataset, stations: null } };
    const t = text(render(noStations));
    expect(t).toContain("1,326 fault sessions among 8,820 held-out sessions · read from");
    expect(t).not.toContain("stations the models never saw");
    expect(t).not.toContain("at — stations");
  });

  it("states the baseline policy only for a baseline benchmark", () => {
    expect(text(render(CURRENT_EDITION))).toContain("with the baseline detection policy, no ISO 15118 rule arms");
    const iso = text(render(ISO_EDITION, { modelArtifact: "53b6f14244c2e633" }));
    expect(iso).not.toContain("no ISO 15118 rule arms");
    expect(iso).toContain(
      "under a detection policy with standard rule layers: ISO 15118-2 rules + ISO 15118-3 SLAC timers (normative)",
    );
    // the ISO edition ships the v4 weights, so its research grid is v4's own
    expect(iso).toContain("rescores these same models");
    expect(text(render(ISO_EDITION, { lang: "th" }))).toContain("กฎ ISO 15118-2 + ตัวจับเวลา SLAC ของ ISO 15118-3 (normative)");
  });

  it("keeps in-sample training stations off the held-out station cards", () => {
    const stations = [
      fixtureStation("001_Alpha", 200, 30),
      fixtureStation("002_Beta", 100, 10, "test"),
      fixtureStation("900_TrainOnly", 5_000, 900, "train"),
    ];
    const t = text(render(CURRENT_EDITION, { stations }));
    expect(t).toContain("Alpha");
    expect(t).toContain("Beta");
    expect(t).not.toContain("Train Only");
    // the Faults-by-station tiles: 2 stations, 40 fault sessions
    expect(t).toMatch(/\b2 Stations 40 Fault sessions\b/);
    // ...and the card says where the training station went, with a way to all of them
    expect(t).toContain(
      "This card shows the 2 held-out stations only · results for the other 1 training station (in-sample) are in the Stations tab",
    );
    expect(t).toContain("View all 3 stations");
    expect(text(render(CURRENT_EDITION, { stations, lang: "th" }))).toContain(
      "การ์ดนี้แสดงเฉพาะ 2 สถานี held-out · ผลของอีก 1 สถานีชุดฝึก (in-sample) อยู่ในแท็บผลรายสถานี",
    );
    // the station fault-mix picker next to it is held-out only too, and says so
    expect(render(CURRENT_EDITION, { stations })).toContain('data-testid="fd-pie-held-out-only-note"');
    // the benchmark tile's 45 is labelled held-out, so it is not read as every station
    expect(t).toContain("Held-out stations");
    expect(text(render(CURRENT_EDITION, { stations, lang: "th" }))).toContain("สถานี held-out");
  });

  it("says nothing about training stations when the build has none", () => {
    const html = render(CURRENT_EDITION, { stations: [fixtureStation("001_Alpha", 200, 30)] });
    expect(html).not.toContain('data-testid="fd-held-out-only-note"');
    expect(html).not.toContain('data-testid="fd-pie-held-out-only-note"');
    expect(text(html)).toContain("View all stations");
    expect(text(html)).not.toContain("Held-out stations");
  });
});
