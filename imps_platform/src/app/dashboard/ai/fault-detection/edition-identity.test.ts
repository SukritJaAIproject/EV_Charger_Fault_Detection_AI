import { describe, expect, it } from "vitest";

import { editionTabTitle } from "./edition-identity";

describe("editionTabTitle", () => {
  it("puts the distinguishing part of the product name first", () => {
    expect(editionTabTitle({ productName: "iMPS Fault Detection", appVersion: "1.2.2" })).toBe(
      "iMPS v1.2.2 - Fault Detection",
    );
    expect(
      editionTabTitle({ productName: "iMPS Fault Detection Snapshot 2026-09-12", appVersion: "1.1.2" }),
    ).toBe("iMPS Snapshot 2026-09-12 v1.1.2 - Fault Detection");
    expect(editionTabTitle({ productName: "iMPS Fault Detection ISO 15118", appVersion: "1.3.0" })).toBe(
      "iMPS ISO 15118 v1.3.0 - Fault Detection",
    );
  });

  it("keeps a product name that does not follow the naming pattern", () => {
    expect(editionTabTitle({ productName: "Charger Lab", appVersion: null })).toBe(
      "iMPS Charger Lab - Fault Detection",
    );
  });

  it("returns null when the sidecar did not report a product name", () => {
    expect(editionTabTitle(null)).toBeNull();
    expect(editionTabTitle({ productName: null, appVersion: "1.2.2" })).toBeNull();
    expect(editionTabTitle({ productName: "   ", appVersion: "1.2.2" })).toBeNull();
  });
});
