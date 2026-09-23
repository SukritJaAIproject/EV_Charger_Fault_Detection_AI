import { useEffect } from "react";

import type { DesktopRuntimeStatus } from "./api";

const BASE_PRODUCT = "iMPS Fault Detection";

/**
 * Browser-tab title for a desktop edition, e.g. "iMPS Snapshot 2026-09-12 v1.1.2 - Fault Detection".
 *
 * Every edition ships the same Next.js build, so the root layout's <title>
 * ("iMPS") cannot differ between them; the edition is only known at runtime
 * from the sidecar's /health. The part that tells editions apart comes first
 * because browsers truncate tab titles from the right.
 */
export function editionTabTitle(
  status: Pick<DesktopRuntimeStatus, "productName" | "appVersion"> | null | undefined,
): string | null {
  const product = status?.productName?.trim();
  if (!product) return null;
  const version = status?.appVersion?.trim();
  const edition = product.startsWith(BASE_PRODUCT) ? product.slice(BASE_PRODUCT.length).trim() : product;
  const parts = ["iMPS", edition, version ? `v${version}` : ""].filter(Boolean);
  return `${parts.join(" ")} - Fault Detection`;
}

/**
 * Sets the document title from the running edition once /health has answered
 * (desktop only; the web build has no sidecar and keeps the layout's title).
 * Runs after hydration, so React does not revert it, and restores the previous
 * title when the page unmounts. Inside Electron the window title is pinned to
 * the product name by main.cjs, so this only affects browser tabs.
 */
export function useEditionTabTitle(
  status: Pick<DesktopRuntimeStatus, "productName" | "appVersion"> | null | undefined,
): void {
  const title = editionTabTitle(status);
  useEffect(() => {
    if (!title || typeof document === "undefined") return;
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
