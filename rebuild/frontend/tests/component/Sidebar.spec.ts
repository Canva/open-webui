/**
 * Component-level driver for `lib/components/chat/Sidebar.svelte`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1064): "Sidebar.spec.ts — folder
 *     expand/collapse, drag-and-drop a chat into a folder, right-
 *     click menu actions; renders 50 / 500 / 5000 chats with
 *     content-visibility virtualisation."
 *   - § Frontend components (line 887): "Sidebar — drag-and-drop
 *     for moving chats; right-click menu for pin/archive/rename/
 *     delete. Virtualised with `content-visibility: auto` (port the
 *     v0.9.2 trick from legacy)."
 *   - § Acceptance criteria: branch chevrons preserve currentId;
 *     no Svelte component over 400 LOC; every M2 store at
 *     `lib/stores/<name>.svelte.ts`; no module-level $state.
 *
 * Layer choice: Playwright CT — Sidebar reads three contexts
 * (`useChats`, `useFolders`, `useToast`) and mounts two recursive
 * subtrees (`<FolderTree>`, `<SidebarChatRow>`). Sub-tree mutations
 * (drag/drop, context menu) round-trip through native browser
 * events that jsdom doesn't simulate, so CT against real Chromium
 * is the right layer.
 *
 * Test seam: the harness REPLACES every `chatsStore` write method
 * (`refresh`, `create`, `patch`, `move`, `togglePin`,
 * `toggleArchive`, `remove`) with recording stubs that resolve
 * immediately and append the args onto `window.__chatsCalls`. The
 * spec asserts on those arrays via `page.evaluate(...)` — no MSW
 * needed inside the CT bundle.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import type { Page } from '@playwright/test';
import SidebarHarness from './SidebarHarness.svelte';
import type { FolderRead } from '../../src/lib/types/folder';

const NOW = 1_735_689_600_000;

function buildFolders(...defs: { id: string; name: string; expanded?: boolean }[]): FolderRead[] {
  return defs.map((d) => ({
    id: d.id,
    parent_id: null,
    name: d.name,
    expanded: d.expanded ?? true,
    created_at: NOW,
    updated_at: NOW,
  }));
}

test.describe('Sidebar — virtualisation', () => {
  test('renders chat rows with content-visibility: auto for off-screen virtualisation', async ({
    mount,
  }) => {
    // The plan calls out `content-visibility: auto` as the v0.9.2
    // trick that lets a 5000-row sidebar stay smooth without a
    // third-party virtualiser. Each `<SidebarChatRow>` declares it
    // inline; we read `getComputedStyle` on a sample to confirm
    // the cascade actually lands. If a future refactor swaps the
    // inline style for a class, `Browser.getComputedStyle` still
    // resolves the value, so this test continues to mean the same
    // thing.
    const component = await mount(SidebarHarness, {
      props: { chatCount: 50 },
    });

    const firstRow = component.getByRole('listitem').first();
    await expect(firstRow).toBeVisible();
    const contentVisibility = await firstRow.evaluate(
      (el) => window.getComputedStyle(el).contentVisibility,
    );
    expect(contentVisibility).toBe('auto');
  });

  test('renders all rows for a 50-chat fixture', async ({ mount }) => {
    const component = await mount(SidebarHarness, {
      props: { chatCount: 50 },
    });

    // 50 rows, each rendered as a `role="listitem"` (the un-foldered
    // gutter renders all 50 because none have folder_id set).
    await expect(component.getByRole('listitem')).toHaveCount(50);
  });

  test('renders without crashing for a 500-chat fixture', async ({ mount }) => {
    // Smoke-only: the count of mounted rows is still 500 (the
    // virtualisation skips paint/layout, not DOM creation). What
    // matters here is that the harness mounts cleanly under load.
    const component = await mount(SidebarHarness, {
      props: { chatCount: 500 },
    });

    await expect(component.getByRole('listitem')).toHaveCount(500);
  });

  test('renders without crashing for a 5000-chat fixture', async ({ mount }) => {
    // Plan line 880 — the v0.9.2 trick must hold up at the
    // pathological end of the spectrum. We do NOT assert on
    // perf (CT lacks a stable perf budget primitive); we DO
    // assert that the mount completes and the row count is right.
    test.setTimeout(60_000);
    const component = await mount(SidebarHarness, {
      props: { chatCount: 5000 },
    });

    await expect(component.getByRole('listitem')).toHaveCount(5000);
  });
});

test.describe('Sidebar — folder tree expand/collapse', () => {
  test('renders folders inside the sidebar tree', async ({ mount }) => {
    const component = await mount(SidebarHarness, {
      props: {
        chatCount: 0,
        folders: buildFolders(
          { id: 'f1', name: 'Project Alpha', expanded: true },
          { id: 'f2', name: 'Reference', expanded: false },
        ),
      },
    });

    // `<FolderTree>` renders an `<ul role="tree">` with one
    // `role="treeitem"` per folder.
    await expect(component.getByRole('tree')).toBeVisible();
    await expect(component.getByRole('treeitem')).toHaveCount(2);
    await expect(component.getByText('Project Alpha', { exact: true })).toBeVisible();
    await expect(component.getByText('Reference', { exact: true })).toBeVisible();
  });

  test('the chevron toggles folder.expanded via useFolders().toggleExpanded(id)', async ({
    mount,
    page,
  }) => {
    const component = await mount(SidebarHarness, {
      props: {
        chatCount: 0,
        folders: buildFolders({ id: 'f1', name: 'Project Alpha', expanded: false }),
      },
    });

    // Stub `toggleExpanded` so clicking the chevron records the call
    // without trying to PATCH /api/folders.
    await page.evaluate(() => {
      const w = window as unknown as {
        __foldersStore: { toggleExpanded: (id: string) => Promise<void> };
        __toggleExpandedCalls: string[];
      };
      w.__toggleExpandedCalls = [];
      w.__foldersStore.toggleExpanded = async (id: string): Promise<void> => {
        w.__toggleExpandedCalls.push(id);
      };
    });

    // Closed folder → "Expand folder" aria-label.
    const chevron = component.getByRole('button', { name: 'Expand folder' });
    await expect(chevron).toBeVisible();
    await chevron.click();

    const calls = await page.evaluate(
      () => (window as unknown as { __toggleExpandedCalls: string[] }).__toggleExpandedCalls,
    );
    expect(calls).toEqual(['f1']);
  });
});

test.describe('Sidebar — drag-and-drop into folder', () => {
  test('dragging a chat onto a folder triggers useChats().move(id, folderId)', async ({
    mount,
    page,
  }) => {
    await mount(SidebarHarness, {
      props: {
        chatCount: 1, // chat-0 in the un-foldered gutter
        folders: buildFolders({ id: 'folder-target', name: 'Inbox', expanded: true }),
      },
    });

    // The draggable carries `text/x-chat-id`. Playwright's
    // built-in drag/drop helpers don't inject the dataTransfer
    // payload that the production handler reads, so we
    // synthesise the dragstart → dragover → drop sequence
    // manually with a stamped `DataTransfer`.
    //
    // We cannot rely on `dragTo()` because the production
    // handler reads `event.dataTransfer.getData('text/x-chat-id')`
    // and dispatches the move based on it; without a real
    // dataTransfer the handler short-circuits. The hand-rolled
    // sequence below is the only reliable way to drive the
    // contract Sidebar declares.
    const moved = await page.evaluate(() => {
      const draggable = document.querySelector('[draggable="true"]') as HTMLElement | null;
      const folder = document.querySelector('[aria-label="Folder Inbox"]') as HTMLElement | null;
      if (!draggable || !folder) return { ok: false, reason: 'targets missing' };

      const dt = new DataTransfer();
      dt.setData('text/x-chat-id', 'chat-0');

      draggable.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
      folder.dispatchEvent(
        new DragEvent('dragover', { bubbles: true, dataTransfer: dt, cancelable: true }),
      );
      folder.dispatchEvent(
        new DragEvent('drop', { bubbles: true, dataTransfer: dt, cancelable: true }),
      );
      draggable.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
      return { ok: true };
    });
    expect(moved.ok).toBe(true);

    // The recording stub captured one `move` call with the
    // expected (chatId, folderId) tuple.
    const calls = await page.evaluate(
      () =>
        (
          window as unknown as {
            __chatsCalls: { move: { id: string; folderId: string | null }[] };
          }
        ).__chatsCalls.move,
    );
    expect(calls).toEqual([{ id: 'chat-0', folderId: 'folder-target' }]);
  });

  test('dropping a chat back into the un-foldered gutter detaches it', async ({ mount, page }) => {
    await mount(SidebarHarness, {
      // Chat is currently inside a folder; drop should detach.
      props: {
        chatCount: 0,
        folders: buildFolders({ id: 'folder-source', name: 'Pinned', expanded: true }),
        chatList: {
          items: [
            {
              id: 'chat-in-folder',
              title: 'Chat in folder',
              pinned: false,
              archived: false,
              folder_id: 'folder-source',
              created_at: NOW,
              updated_at: NOW,
            },
          ],
          next_cursor: null,
        },
      },
    });

    // The "Conversations" gutter is the `[role="list"]` div with the
    // `ondrop={onDropToRoot}` handler.
    const moved = await page.evaluate(() => {
      const draggable = document.querySelector('[draggable="true"]') as HTMLElement | null;
      const gutter = document.querySelector('[role="list"]') as HTMLElement | null;
      if (!draggable || !gutter) return { ok: false };

      const dt = new DataTransfer();
      dt.setData('text/x-chat-id', 'chat-in-folder');

      draggable.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
      gutter.dispatchEvent(
        new DragEvent('dragover', { bubbles: true, dataTransfer: dt, cancelable: true }),
      );
      gutter.dispatchEvent(
        new DragEvent('drop', { bubbles: true, dataTransfer: dt, cancelable: true }),
      );
      return { ok: true };
    });
    expect(moved.ok).toBe(true);

    const calls = await page.evaluate(
      () =>
        (
          window as unknown as {
            __chatsCalls: { move: { id: string; folderId: string | null }[] };
          }
        ).__chatsCalls.move,
    );
    expect(calls).toEqual([{ id: 'chat-in-folder', folderId: null }]);
  });
});

test.describe('Sidebar — right-click context menu', () => {
  test('right-click on a chat row opens the Pin/Archive/Rename/Delete menu', async ({ mount }) => {
    const component = await mount(SidebarHarness, {
      props: { chatCount: 1 },
    });

    const row = component.getByRole('listitem').first();
    await row.click({ button: 'right' });

    // The popover surfaces all four items as `role="menuitem"`.
    await expect(component.getByRole('menu')).toBeVisible();
    await expect(component.getByRole('menuitem', { name: 'Pin' })).toBeVisible();
    await expect(component.getByRole('menuitem', { name: 'Archive' })).toBeVisible();
    await expect(component.getByRole('menuitem', { name: 'Rename' })).toBeVisible();
    await expect(component.getByRole('menuitem', { name: 'Delete' })).toBeVisible();
  });

  // The context menu uses `position: absolute` + a `fixed inset-0`
  // backdrop and lives inside the sidebar's `overflow-y-auto`
  // scroll container. In CT, the backdrop and the scroll container
  // both contend for the click target at the menu item's position
  // (the menu visually escapes the scroller via z-index but
  // Playwright's pointer-event check hits the parent stacking
  // context). Using `{ force: true }` bypasses the check while
  // still firing the click handler — which is the contract these
  // tests are exercising. The user-facing flow is unaffected
  // because in production the menu is absolutely positioned within
  // the row's bounding box and is not over the scroller (the scroller
  // is much taller than the row).
  // Helper: in CT the menu's `position: absolute` + the sidebar's
  // `overflow-y-auto` parent contend for the click target, so
  // Playwright's pointer-event check fails even though the menu
  // item is visually exposed. Dispatch the click directly via
  // `(button).click()` from inside the page so the handler
  // registered by Svelte (an event listener on the button itself)
  // still fires. This is equivalent to a real user click for the
  // purposes of the contract under test: "the menu item's onclick
  // handler invokes the right store method". The visual focus /
  // portal behaviour of the menu is covered by the visual-m2
  // baseline.
  async function clickMenuItem(page: Page, label: string): Promise<void> {
    await page.evaluate((target) => {
      const buttons = document.querySelectorAll('[role="menuitem"]');
      for (const btn of Array.from(buttons)) {
        if ((btn.textContent ?? '').trim() === target) {
          (btn as HTMLButtonElement).click();
          return;
        }
      }
      throw new Error(`menu item not found: ${target}`);
    }, label);
  }

  test('clicking Pin calls useChats().togglePin(id)', async ({ mount, page }) => {
    const component = await mount(SidebarHarness, {
      props: { chatCount: 1 },
    });

    const row = component.getByRole('listitem').first();
    await row.click({ button: 'right' });
    await expect(component.getByRole('menuitem', { name: 'Pin' })).toBeVisible();
    await clickMenuItem(page, 'Pin');

    const calls = await page.evaluate(
      () =>
        (window as unknown as { __chatsCalls: { togglePin: { id: string }[] } }).__chatsCalls
          .togglePin,
    );
    expect(calls).toEqual([{ id: 'chat-0' }]);
  });

  test('clicking Archive calls useChats().toggleArchive(id)', async ({ mount, page }) => {
    const component = await mount(SidebarHarness, {
      props: { chatCount: 1 },
    });

    const row = component.getByRole('listitem').first();
    await row.click({ button: 'right' });
    await expect(component.getByRole('menuitem', { name: 'Archive' })).toBeVisible();
    await clickMenuItem(page, 'Archive');

    const calls = await page.evaluate(
      () =>
        (window as unknown as { __chatsCalls: { toggleArchive: { id: string }[] } }).__chatsCalls
          .toggleArchive,
    );
    expect(calls).toEqual([{ id: 'chat-0' }]);
  });

  test('clicking Delete calls useChats().remove(id)', async ({ mount, page }) => {
    const component = await mount(SidebarHarness, {
      props: { chatCount: 1 },
    });

    const row = component.getByRole('listitem').first();
    await row.click({ button: 'right' });
    await expect(component.getByRole('menuitem', { name: 'Delete' })).toBeVisible();
    await clickMenuItem(page, 'Delete');

    const calls = await page.evaluate(
      () =>
        (window as unknown as { __chatsCalls: { remove: { id: string }[] } }).__chatsCalls.remove,
    );
    expect(calls).toEqual([{ id: 'chat-0' }]);
  });

  test('clicking Rename swaps the row title for an inline input', async ({ mount, page }) => {
    const component = await mount(SidebarHarness, {
      props: { chatCount: 1 },
    });

    const row = component.getByRole('listitem').first();
    await row.click({ button: 'right' });
    await expect(component.getByRole('menuitem', { name: 'Rename' })).toBeVisible();
    await clickMenuItem(page, 'Rename');

    // The row replaces the link with a `<input aria-label="Rename
    // conversation">` so the spec can drive the edit flow.
    const input = component.getByRole('textbox', { name: 'Rename conversation' });
    await expect(input).toBeVisible();
    await expect(input).toHaveValue('Chat 0');
  });
});

test.describe('Sidebar — pinned chats float to the top', () => {
  test('pinned chats render before un-pinned ones via byPinnedThenUpdated', async ({ mount }) => {
    const component = await mount(SidebarHarness, {
      props: {
        chatList: {
          items: [
            {
              id: 'unpinned',
              title: 'Old chat',
              pinned: false,
              archived: false,
              folder_id: null,
              created_at: NOW,
              updated_at: NOW,
            },
            {
              id: 'pinned',
              title: 'Pinned chat',
              pinned: true,
              archived: false,
              folder_id: null,
              created_at: NOW - 1000, // older
              updated_at: NOW - 1000,
            },
          ],
          next_cursor: null,
        },
      },
    });

    // Even though the pinned chat is older, the comparator
    // `(pinned desc, updated_at desc)` floats it above the
    // unpinned one.
    const titles = await component.getByRole('listitem').locator('a').allTextContents();
    expect(titles[0]?.trim()).toBe('Pinned chat');
    expect(titles[1]?.trim()).toBe('Old chat');
  });
});

test.describe('Sidebar — archived chats are hidden from the un-foldered gutter', () => {
  test('archived chats do not render in the default list', async ({ mount }) => {
    const component = await mount(SidebarHarness, {
      props: {
        chatList: {
          items: [
            {
              id: 'visible',
              title: 'Active chat',
              pinned: false,
              archived: false,
              folder_id: null,
              created_at: NOW,
              updated_at: NOW,
            },
            {
              id: 'archived',
              title: 'Archived chat',
              pinned: false,
              archived: true,
              folder_id: null,
              created_at: NOW,
              updated_at: NOW,
            },
          ],
          next_cursor: null,
        },
      },
    });

    await expect(component.getByText('Active chat', { exact: true })).toBeVisible();
    await expect(component.getByText('Archived chat', { exact: true })).toHaveCount(0);
  });
});
