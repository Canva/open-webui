/**
 * Component-level smoke driver for the M2 `(app)/+layout.svelte` chat
 * shell.
 *
 * Phase 3d replaced the M0 identity-demo card (`Hello {data.user.email}`,
 * debug `<pre>` JSON dump, "Signed in as" copy, "Identity" `<section>`)
 * with the real chrome: a persistent sidebar, the active conversation
 * slot, the global toaster, and a mobile drawer toggle. The two M0
 * tests this file used to ship — "renders the email when data.user is
 * hydrated" and "renders fallback copy and not raw 'null'..." — both
 * asserted against vanished M0 markup (email/name/timezone leaf text;
 * a `<section>` first-of-type locator). The hydrated case has been
 * deleted: there is no equivalent layout-level assertion now that the
 * email/name/timezone are no longer surfaced anywhere on the shell —
 * the M2 surface is "the sidebar appears and the conversation slot
 * mounts", which `tests/component/Sidebar.spec.ts` and the Phase 4b
 * E2E `tests/e2e/send-and-stream.spec.ts` cover end-to-end. The null
 * case has been kept and rewritten to drop the M0 `<section>` selector.
 *
 * Two smoke tests remain so the layout-level branches do not regress:
 *
 *   - **hydrated user**: the workspace navigation landmark mounts when
 *     `data.user` is populated. This is the only layout-level signal
 *     for "the chat shell rendered" — the rest of the chrome is owned
 *     by `Sidebar.svelte` and tested by its own CT spec.
 *   - **null user**: the trusted-header gate copy appears (proxy-header
 *     guidance + `X-Forwarded-Email` example) when `data.user` is null,
 *     so engineers hitting the dev server without the proxy see what
 *     is wrong instead of a blank shell.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import LayoutHarness from './LayoutHarness.svelte';
import type { User } from '../../src/lib/types/user';
import type { ChatList } from '../../src/lib/types/chat';

const fixtureUser: User = {
  id: '01900000-0000-7000-8000-000000000000',
  email: 'alice@canva.com',
  name: 'Alice Example',
  timezone: 'UTC',
  created_at: 1_704_067_200_000,
};

const baselineThemeData = { theme: 'tokyo-night' as const, themeSource: 'fallback' as const };

const emptyChatList: ChatList = { items: [], next_cursor: null };

test.describe('(app)/+layout.svelte', () => {
  test('mounts the workspace navigation landmark when data.user is hydrated', async ({ mount }) => {
    const component = await mount(LayoutHarness, {
      props: {
        data: {
          user: fixtureUser,
          ...baselineThemeData,
          chats: emptyChatList,
          folders: [],
          agents: [],
        },
      },
    });

    // The hydrated branch renders the chat shell: a persistent
    // <aside aria-label="Workspace navigation"> in the inline-start
    // grid column. Sidebar.spec.ts owns the deeper assertions on the
    // sidebar's contents; here we only confirm the layout's hydrated
    // branch fires and the landmark exists.
    await expect(component.locator('aside[aria-label="Workspace navigation"]')).toBeAttached();

    // The mobile drawer toggle is rendered inside <main> and is the
    // only authenticated-shell affordance the layout itself owns
    // (everything else is delegated to <Sidebar />). Asserting on its
    // aria-label keeps the test resilient to icon swaps.
    await expect(component.locator('button[aria-label="Open navigation"]')).toBeAttached();
  });

  test('renders the trusted-header gate copy when data.user is null', async ({ mount }) => {
    const component = await mount(LayoutHarness, {
      props: { data: { user: null, ...baselineThemeData } },
    });

    // The null branch is the load-bearing developer signal when the
    // dev server is hit without the X-Forwarded-Email proxy header.
    // We assert on the visible copy rather than DOM structure because
    // the layout uses semantic tags (<h1>, <p>, <code>) and not a
    // wrapping <section> — the M0 `<section>` locator is gone.
    await expect(component).toContainText(/proxy header/i);
    await expect(component).toContainText('X-Forwarded-Email');

    // The hydrated branch must not fire: no Workspace navigation
    // landmark when the trusted-header gate failed.
    await expect(component.locator('aside[aria-label="Workspace navigation"]')).toHaveCount(0);
  });
});
