import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { BundledBenchmark, StationAnalysis } from "./data";
import {
  CURRENT_EDITION,
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

  it("marks what was not measured and what was projected for the v4 models", () => {
    const v4 = render(CURRENT_EDITION);
    expect(armTab(v4, "iso2")).toContain('disabled=""');
    expect(armTab(v4, "iso2")).toContain('title="Not measured for this model set (needs a replay)"');
    expect(armTab(v4, "normative")).not.toContain('disabled=""');
    expect(text(v4)).toContain(
      "This policy is projected from recorded alerts, not replayed · AI Agent's recall and false-alarm rate are lower bounds",
    );
    // the reason is visible text, not only a tooltip on a tab that cannot take focus
    expect(text(v4)).toContain("+ ISO 15118-2: Not measured for this model set (needs a replay)");
    expect(armTab(v4, "iso2")).toContain('aria-describedby="fd-arms-not-measured"');
    // nothing on the page claims ISO-2 results or a replay check for the v4 set
    expect(text(v4)).toContain("(ISO 15118-2 rules not yet measured for this model set)");
    expect(text(v4)).toContain("— Not replayed for this model set");
    expect(text(v4)).not.toContain("Projection–replay agreement");

    // the 2026-09-12 set was replayed under ISO-2; only its normative arm is a projection
    const old = render(SNAPSHOT_EDITION);
    expect(armTab(old, "iso2")).not.toContain('disabled=""');
    expect(text(old)).not.toContain("Not measured for this model set");
    expect(text(old)).toContain("including ISO 15118-2 rules and ISO 15118-3 SLAC timing.");
    expect(text(old)).toContain("100% Projection–replay agreement");
    expect(text(old)).toContain("This policy is projected from recorded alerts, not replayed");
    expect(text(old)).not.toContain("lower bounds");
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
    expect(armTab(render(CURRENT_EDITION, { lang: "th" }), "iso2")).toContain('title="ยังไม่ได้วัดกับโมเดลชุดนี้ (ต้อง replay)"');
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
  });
});
