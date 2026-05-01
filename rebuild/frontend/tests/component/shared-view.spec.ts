/**
 * Behavioural CT spec for the M3 public share view at `/s/{token}`.
 *
 * Locked by `rebuild/docs/plans/m3-sharing.md`:
 *   - § Tests § Component (line 241): "shared-view.spec.ts —
 *     renders +page.svelte against a fixture snapshot covering
 *     markdown, code blocks, and math, asserting it uses the same
 *     Message component as the conversation view (no input box,
 *     no regen controls, no model selector). Includes a long-history
 *     fixture (200+ messages) to exercise virtualization."
 *   - § Frontend route (lines 205-216): the read-only contract —
 *     no composer, no model selector, no regen, no scroll-to-
 *     bottom-on-stream; the M2 `MessageList` + `Message` components
 *     in `readonly` mode; max-width matches the conversation view.
 *   - § User journeys row 4: the recipient opens `/s/{token}` and
 *     reads the snapshot through the M2 renderer.
 *
 * Layer choice: Playwright Component Testing.
 *   - The harness mirrors the route's markup (option b — see the
 *     harness file's docstring for why we don't import the route
 *     `+page.svelte` directly into CT). The behavioural assertions
 *     here pin the read-only contract; the geometric invariants
 *     (negative containment for composer / model-selector / regen)
 *     live in the sibling `SharedView-geometry.spec.ts`.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';

import SharedViewHarness from './SharedViewHarness.svelte';
import { defaultSnapshotFixture, longHistoryFixture, FIXTURE_NOW, msg } from './share-fixtures';

test.describe('SharedView — happy-path snapshot rendering', () => {
  test('renders the snapshot title and the shared-by subline', async ({ mount }) => {
    const snapshot = defaultSnapshotFixture({
      title: 'Refactor draft',
      shared_by: { name: 'Alice Example', email: 'alice@canva.com' },
      created_at: FIXTURE_NOW,
    });
    const component = await mount(SharedViewHarness, {
      // Now exactly 1 minute after creation -> "1 minute ago" subline.
      props: { snapshot, now: FIXTURE_NOW + 60_000 },
    });

    await expect(
      component.getByRole('heading', { name: 'Refactor draft', level: 1 }),
    ).toBeVisible();
    // Subline includes both the sharer name and a relative-time clause.
    await expect(component.getByText(/Shared by Alice Example/)).toBeVisible();
    await expect(component.getByText(/1 minute ago/)).toBeVisible();
  });

  test('renders both messages via the M2 Message component in readonly mode', async ({ mount }) => {
    const snapshot = defaultSnapshotFixture();
    const component = await mount(SharedViewHarness, { props: { snapshot } });

    // The user turn surfaces the literal content; the assistant turn
    // hits the Markdown subtree (the fixture includes a code fence)
    // so the body text from the fenced block is reachable.
    await expect(component.getByText('Refactor this function for clarity.')).toBeVisible();
    await expect(component).toContainText('const sum =');

    // Negative containment: readonly mode strips the per-message
    // action cluster (Copy / Regenerate). Pinned by `m3-sharing.md`
    // § Frontend route — no regen, no edit affordances on the share
    // view.
    await expect(component.getByRole('button', { name: 'Regenerate message' })).toHaveCount(0);
    await expect(component.getByRole('button', { name: 'Copy message' })).toHaveCount(0);

    // No composer (compose textbox is the user-facing affordance).
    await expect(component.getByRole('textbox', { name: 'Compose a message' })).toHaveCount(0);
    // No model selector — the share view never instantiates one.
    await expect(component.getByRole('button', { name: /Model/ })).toHaveCount(0);
  });

  test('renders the dead-link panel when snapshot is null', async ({ mount }) => {
    const component = await mount(SharedViewHarness, { props: { snapshot: null } });

    await expect(
      component.getByRole('heading', { name: 'Shared chat unavailable', level: 1 }),
    ).toBeVisible();
    await expect(component.getByText('This share link is no longer active.')).toBeVisible();

    // Negative containment: no MessageList renders on the dead-link
    // path — the recipient should never see snapshot bytes for a
    // revoked share.
    await expect(component.getByText('Refactor this function for clarity.')).toHaveCount(0);
  });
});

test.describe('SharedView — long histories exercise the M2 virtualisation', () => {
  test('renders a 200-pair (400-message) history without layout explosion', async ({ mount }) => {
    test.setTimeout(60_000);
    const snapshot = longHistoryFixture(200);
    const component = await mount(SharedViewHarness, { props: { snapshot } });

    // First and last turn are both reachable. The MessageList walks
    // `currentId` to root, so all 400 messages mount at once; the
    // M2 virtualisation lives in `content-visibility: auto` on the
    // row container, which keeps painting cheap without skipping
    // the DOM nodes themselves.
    await expect(component.getByText('User turn 0', { exact: true })).toBeVisible();
    // The last turn requires a scroll to land in the viewport.
    const lastAssistant = component.getByText('Assistant turn 199', { exact: true });
    await lastAssistant.scrollIntoViewIfNeeded();
    await expect(lastAssistant).toBeVisible();
  });
});

test.describe('SharedView — system messages render as the quiet rule (M2 contract)', () => {
  // Pinned because the M2 Message component renders system messages
  // as a quiet horizontal rule, not a bubble. The share view inherits
  // that surface — assert here so a future Message refactor doesn't
  // silently regress the share-rendering of historical system turns.
  test('a system message in the snapshot renders the System rule', async ({ mount }) => {
    const snapshot = defaultSnapshotFixture({
      history: {
        messages: {
          's-1': msg({
            id: 's-1',
            role: 'system',
            content: 'You are a senior engineer.',
            childrenIds: ['u-1'],
          }),
          'u-1': msg({
            id: 'u-1',
            role: 'user',
            parentId: 's-1',
            childrenIds: ['a-1'],
            content: 'Hello.',
          }),
          'a-1': msg({
            id: 'a-1',
            role: 'assistant',
            parentId: 'u-1',
            content: 'Hi back.',
          }),
        },
        currentId: 'a-1',
      },
    });
    const component = await mount(SharedViewHarness, { props: { snapshot } });

    await expect(component.getByText('System', { exact: true })).toBeVisible();
  });
});
