<!--
  Harness for the M2 Message CT spec.

  `Message.svelte` reaches into `useActiveChat()` (Regenerate /
  Retry button -> editAndResend) and `useToast()` (copy-failure
  surface + retry-failure surface). The harness provides both via
  `setContext` BEFORE rendering, mirroring what
  `(app)/+layout.svelte` does in production.

  The component also recurses into `<Markdown />`, which is pure
  content rendering and reads no context — so the two store
  contexts are sufficient.

  Playwright CT's `mount(...)` cannot serialise rune-store
  instances across the worker boundary, so the harness constructs
  fresh `ActiveChatStore` and `ToastStore` instances inside the
  browser at mount time. The active chat is left at `null` (the
  Message component doesn't read it — `editAndResend` would, but
  the spec asserts on the rendered DOM, not the click outcome of
  Regenerate). Specs that need a populated `chat` can extend the
  harness or set it via the exposed `__activeChatStore` window
  handle.
-->
<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import { ActiveChatStore, ACTIVE_CHAT_CONTEXT_KEY } from '$lib/stores/active-chat.svelte';
  import { ToastStore, TOAST_CONTEXT_KEY } from '$lib/stores/toast.svelte';
  import Message from '$lib/components/chat/Message.svelte';
  import type { HistoryMessage } from '$lib/types/history';

  interface Props {
    message: HistoryMessage;
    parent: HistoryMessage | null;
  }

  let { message, parent }: Props = $props();

  // Capture-on-mount snapshot of the props so the harness drives the
  // Message component as a fresh render, not a reactive re-render of
  // the harness's `$props`. Mirrors the established `untrack` pattern
  // in the M1 ThemePickerHarness.
  const messageSnapshot = untrack(() => message);
  const parentSnapshot = untrack(() => parent);

  const activeChatStore = new ActiveChatStore();
  const toastStore = new ToastStore();
  setContext(ACTIVE_CHAT_CONTEXT_KEY, activeChatStore);
  setContext(TOAST_CONTEXT_KEY, toastStore);

  // Expose the stores on `window` so specs can introspect / drive
  // them via `page.evaluate(...)`. Mirrors the M1 ThemePicker
  // harness convention.
  if (typeof window !== 'undefined') {
    (
      window as unknown as {
        __activeChatStore: ActiveChatStore;
        __toastStore: ToastStore;
      }
    ).__activeChatStore = activeChatStore;
    (window as unknown as { __toastStore: ToastStore }).__toastStore = toastStore;
  }
</script>

<Message message={messageSnapshot} parent={parentSnapshot} />
