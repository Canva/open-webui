<!--
  Harness for the M3 ShareModal CT spec.

  `ShareModal.svelte` reads one context (`useToast()`) and reaches
  three module-level functions on the `shares` namespace from
  `$lib/api/client`. The harness:

    - constructs a fresh `ToastStore` and `setContext`s it under
      the canonical `TOAST_CONTEXT_KEY` (mirrors what
      `(app)/+layout.svelte` does in production), so `useToast()`
      resolves cleanly without provisioning the rest of the M2
      store tree;
    - monkey-patches `shares.create` / `shares.revoke` /
      `shares.get` with controllable stubs (the same pattern
      `MessageInputHarness` uses for `activeChatStore.send`).
      Specs drive the stubs through `window.__shareModal.controls`
      via `page.evaluate(...)`;
    - records `onClose` and `onShareChange` invocations onto
      `window.__shareModal.{closeCalls, shareChangeCalls}` so the
      spec can assert without passing function props through CT's
      worker boundary (only serialisable props cross that boundary
      per Playwright CT, mirroring the existing harness shape);
    - replaces `navigator.clipboard.writeText` with a recording
      stub on `window.__shareModal.clipboardCalls` so the Copy-link
      test can assert the absolute URL hit the clipboard without
      depending on a real Permissions prompt or a CT-level
      Permissions API mock.

  Why mutate the module-level `shares` object directly
  -----------------------------------------------------
  ShareModal imports `shares` as a const object from
  `$lib/api/client`. JS module exports are bindings, but the
  exported object's properties are mutable from the outside. Each
  harness mount re-runs this `<script>` and re-installs the stubs,
  so cross-test bleed is bounded to the single CT page reload
  Playwright already does between specs. The shape mirrors
  `MessageInputHarness.svelte`'s `activeChatStore.send = async
  (...)` line: monkey-patch on every mount, expose the recording
  arrays via `window`.

  Fixture data lives in `share-fixtures.ts` (sibling of this file)
  so the spec can re-use the same constants and factories. Existing
  CT harnesses in this repo expose only their default component
  export — keeping that invariant means the Playwright CT loader
  never has to disambiguate a non-component named export from a
  Svelte module.
-->
<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import { shares as sharesApi } from '$lib/api/client';
  import { ToastStore, TOAST_CONTEXT_KEY } from '$lib/stores/toast.svelte';
  import ShareModal from '$lib/components/chat/ShareModal.svelte';
  import type { ChatRead } from '$lib/types/chat';
  import type { ShareCreateResponse, SharedChatSnapshot } from '$lib/types/share';
  import { TEST_TOKEN, FIXTURE_NOW, defaultChatFixture } from './share-fixtures';

  interface Props {
    /** Optional override for the seed chat. Defaults to a not-shared fixture. */
    chat?: ChatRead;
  }

  let { chat = defaultChatFixture() }: Props = $props();
  const chatSnapshot = untrack(() => chat);

  const toastStore = new ToastStore();
  setContext(TOAST_CONTEXT_KEY, toastStore);

  // ------------------------------------------------------------------
  // Recording sinks. Specs read these through `page.evaluate(...)`.
  // ------------------------------------------------------------------
  const closeCalls: number[] = [];
  const shareChangeCalls: (string | null)[] = [];
  const clipboardCalls: string[] = [];
  const apiCalls = {
    create: [] as string[],
    revoke: [] as string[],
    get: [] as string[],
  };

  type Pending<T> = { resolve: (value: T) => void; reject: (err: unknown) => void };

  /**
   * Controllable mock surface. Specs flip `holdCreate` / `holdRevoke`
   * / `holdGet` to pause the corresponding stub and inspect the
   * mid-flight UI (the Esc / backdrop in-flight lock cases). They
   * then resolve the captured pending promise to release.
   */
  const controls = {
    createResponse: {
      token: TEST_TOKEN,
      url: `/s/${TEST_TOKEN}`,
      created_at: FIXTURE_NOW,
    } satisfies ShareCreateResponse,
    revokeShouldFail: false,
    getResponse: {
      token: chatSnapshot.share_id ?? TEST_TOKEN,
      title: chatSnapshot.title,
      history: chatSnapshot.history,
      shared_by: { name: 'Alice Example', email: 'alice@canva.com' },
      created_at: FIXTURE_NOW,
    } satisfies SharedChatSnapshot,
    holdCreate: false,
    holdRevoke: false,
    holdGet: false,
    pending: {
      create: null as Pending<ShareCreateResponse> | null,
      revoke: null as Pending<void> | null,
      get: null as Pending<SharedChatSnapshot> | null,
    },
  };

  sharesApi.create = async (chatId: string): Promise<ShareCreateResponse> => {
    apiCalls.create.push(chatId);
    if (controls.holdCreate) {
      return new Promise<ShareCreateResponse>((resolve, reject) => {
        controls.pending.create = { resolve, reject };
      });
    }
    return controls.createResponse;
  };
  sharesApi.revoke = async (chatId: string): Promise<void> => {
    apiCalls.revoke.push(chatId);
    if (controls.holdRevoke) {
      return new Promise<void>((resolve, reject) => {
        controls.pending.revoke = { resolve, reject };
      });
    }
    if (controls.revokeShouldFail) throw new Error('revoke failed');
  };
  sharesApi.get = async (token: string): Promise<SharedChatSnapshot> => {
    apiCalls.get.push(token);
    if (controls.holdGet) {
      return new Promise<SharedChatSnapshot>((resolve, reject) => {
        controls.pending.get = { resolve, reject };
      });
    }
    return controls.getResponse;
  };

  // ------------------------------------------------------------------
  // Clipboard stub. Replaces `navigator.clipboard` wholesale on every
  // mount so the spec can assert what URL was written without granting
  // the Clipboard API permission inside the CT browser context.
  // ------------------------------------------------------------------
  if (typeof navigator !== 'undefined') {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text: string): Promise<void> => {
          clipboardCalls.push(text);
        },
      },
    });
  }

  function handleClose(): void {
    closeCalls.push(Date.now());
  }
  function handleShareChange(next: string | null): void {
    shareChangeCalls.push(next);
  }

  if (typeof window !== 'undefined') {
    const w = window as unknown as {
      __toastStore: ToastStore;
      __shareModal: {
        controls: typeof controls;
        apiCalls: typeof apiCalls;
        closeCalls: number[];
        shareChangeCalls: (string | null)[];
        clipboardCalls: string[];
        TEST_TOKEN: string;
        FIXTURE_CHAT_ID: string;
      };
    };
    w.__toastStore = toastStore;
    w.__shareModal = {
      controls,
      apiCalls,
      closeCalls,
      shareChangeCalls,
      clipboardCalls,
      TEST_TOKEN,
      FIXTURE_CHAT_ID: chatSnapshot.id,
    };
  }
</script>

<ShareModal chat={chatSnapshot} onClose={handleClose} onShareChange={handleShareChange} />
