/**
 * Pure helper that turns an epoch-millisecond timestamp into a short,
 * sentence-fragment relative phrase ("just now", "5 minutes ago",
 * "yesterday", "12 days ago"). The `at` argument lets callers (and
 * tests) inject a deterministic "now" so the output is reproducible.
 *
 * Used by:
 *   - `lib/components/chat/ShareModal.svelte` — "Captured {x}".
 *   - `routes/(public)/s/[token]/+page.svelte` — sublineunder the
 *     snapshot title.
 *
 * Voice rules (project anti-patterns from `.cursor/skills/impeccable/PROJECT.md`):
 *   - No em dashes in the output.
 *   - Lowercase, sentence-fragment shape so it composes inline
 *     ("Captured 5 minutes ago", "Shared 2 hours ago by …").
 *   - The phrase always ends in "ago" except for the special-case
 *     "just now"; "yesterday" returns the literal word so the consumer
 *     can sentence-case it without re-parsing.
 *
 * Bias toward readable units up to a week; beyond that we fall back
 * to a fixed-format date so a months-old snapshot doesn't read as
 * "62 days ago" (loses information at scale, and nobody thinks in
 * months as a count of days).
 */

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

export function formatRelativeTime(epochMs: number, at: number = Date.now()): string {
  const delta = Math.max(0, at - epochMs);

  if (delta < 45_000) return 'just now';
  if (delta < HOUR_MS) {
    const minutes = Math.max(1, Math.round(delta / MINUTE_MS));
    return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  }
  if (delta < DAY_MS) {
    const hours = Math.max(1, Math.round(delta / HOUR_MS));
    return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  }
  if (delta < 2 * DAY_MS) return 'yesterday';
  if (delta < WEEK_MS) {
    const days = Math.max(1, Math.round(delta / DAY_MS));
    return `${days} days ago`;
  }

  // Beyond a week: ISO-style short date, locale-default month name. We
  // intentionally avoid `toLocaleString` with options here to keep the
  // output deterministic across runtimes (Playwright CI vs developer
  // laptops). Format: "12 Apr 2026".
  const d = new Date(epochMs);
  const day = d.getUTCDate();
  const month = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ][d.getUTCMonth()];
  const year = d.getUTCFullYear();
  return `${day} ${month} ${year}`;
}
