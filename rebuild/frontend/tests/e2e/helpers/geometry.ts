/**
 * Geometric invariants for `@journey-m{n}` specs.
 *
 * The `@visual-m{n}` layer diffs pixels against a locked baseline — useful
 * for catching drift, useless for catching a bug present when the baseline
 * was first captured. The `@journey-m{n}` layer asserts *intent*: sibling
 * controls never overlap, every control stays inside its container, every
 * input has enough content-box width to fit its placeholder at the current
 * font size. An invariant fails on the first run when the bug is present,
 * which is precisely what "feature complete" needs to mean.
 *
 * See `rebuild/docs/best-practises/visual-qa-best-practises.md` for the
 * three-layer discipline this module underpins.
 */

import { expect, type Locator } from '@playwright/test';

export type Rect = { x: number; y: number; width: number; height: number };

const EPS_PX = 1; // sub-pixel layout noise absorbed; any real overlap is ≥ 2 px.

/**
 * Resolve a locator's bounding box, asserting it's visible and has a
 * non-null rect. Fails fast with a named-selector hint so debugging
 * never has to guess which locator came back `null`.
 */
async function rectOf(locator: Locator, label: string): Promise<Rect> {
  await expect(locator, `${label}: expected visible for geometry check`).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, `${label}: boundingBox() returned null`).not.toBeNull();
  return box!;
}

/** True iff two axis-aligned rects intersect on both axes (EPS-tolerant). */
export function rectsOverlap(a: Rect, b: Rect): boolean {
  const horizontal = a.x + a.width - EPS_PX > b.x && b.x + b.width - EPS_PX > a.x;
  const vertical = a.y + a.height - EPS_PX > b.y && b.y + b.height - EPS_PX > a.y;
  return horizontal && vertical;
}

/** True iff `inner` is fully inside `outer` (EPS-tolerant). */
export function rectContains(outer: Rect, inner: Rect): boolean {
  return (
    inner.x + EPS_PX >= outer.x &&
    inner.y + EPS_PX >= outer.y &&
    inner.x + inner.width - EPS_PX <= outer.x + outer.width &&
    inner.y + inner.height - EPS_PX <= outer.y + outer.height
  );
}

/**
 * Assert two locators do not overlap. Fails with the two rects pretty-
 * printed so the diagnostic tells you *how much* they collide, not just
 * that they do.
 */
export async function expectNoOverlap(
  a: Locator,
  b: Locator,
  labels: [string, string],
): Promise<void> {
  const [ra, rb] = [await rectOf(a, labels[0]), await rectOf(b, labels[1])];
  const overlap = rectsOverlap(ra, rb);
  expect(
    overlap,
    `Expected no overlap between ${labels[0]} ${JSON.stringify(ra)} and ${labels[1]} ${JSON.stringify(rb)}`,
  ).toBe(false);
}

/**
 * Assert `inner` is fully contained in `outer` (no horizontal / vertical
 * overflow). Catches "advanced knobs spill out of the composer card".
 */
export async function expectContains(
  outer: Locator,
  inner: Locator,
  labels: [string, string],
): Promise<void> {
  const [ro, ri] = [await rectOf(outer, labels[0]), await rectOf(inner, labels[1])];
  const contains = rectContains(ro, ri);
  expect(
    contains,
    `Expected ${labels[1]} ${JSON.stringify(ri)} fully inside ${labels[0]} ${JSON.stringify(ro)}`,
  ).toBe(true);
}

/**
 * Assert an input's content-box has enough width to fit a given piece
 * of placeholder / value text at the control's current font. `minPx` is
 * the caller's asserted minimum — typically measured once off the design
 * tokens (e.g. `text-xs` = 12 px, 7 chars × ~6 px + padding = ~56 px for
 * `"default"`). Strict enough to catch `"default"` truncating to `"defa"`;
 * loose enough that legitimate font-stack drift doesn't flake.
 */
export async function expectMinContentWidth(
  input: Locator,
  minPx: number,
  label: string,
): Promise<void> {
  const rect = await rectOf(input, label);
  // Native number inputs reserve ~16 px for the spinner chrome on Chromium;
  // we subtract it from the raw width so the assertion reflects the space
  // actually available to placeholder / value text.
  const SPINNER_PX = 16;
  const typeAttr = await input.getAttribute('type');
  const available = typeAttr === 'number' ? rect.width - SPINNER_PX : rect.width;
  expect(
    available,
    `${label}: content-box width ${available}px < required ${minPx}px (raw ${rect.width}px, type=${typeAttr ?? 'text'})`,
  ).toBeGreaterThanOrEqual(minPx);
}

/**
 * Assert the element's scrollWidth does not exceed its clientWidth — i.e.
 * the text inside is not clipped. Catches `"default"` → `"defa"` at the
 * CSS level rather than via a width heuristic, for selects and labels
 * where `expectMinContentWidth` can't cheaply predict the needed pixels.
 */
export async function expectNoTextClipping(locator: Locator, label: string): Promise<void> {
  await expect(locator, `${label}: expected visible for clipping check`).toBeVisible();
  const metrics = await locator.evaluate((el) => {
    const node = el as HTMLElement;
    return { scrollWidth: node.scrollWidth, clientWidth: node.clientWidth };
  });
  expect(
    metrics.scrollWidth,
    `${label}: scrollWidth ${metrics.scrollWidth}px exceeds clientWidth ${metrics.clientWidth}px (text clipped)`,
  ).toBeLessThanOrEqual(metrics.clientWidth + EPS_PX);
}
