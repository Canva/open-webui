<!--
  Harness for the M2 MessageInput CT spec.

  `MessageInput.svelte` reads three contexts:
    - `useActiveChat()` for `send()` / `cancel()` / `streaming`.
    - `useToast()` for failure surfacing.
    - The transitive `<ModelSelector>` reaches `useModels()`.

  Per the M2 plan § Stores and state, all three are constructed in
  `(app)/+layout.svelte` via `provide*()`; this harness mirrors
  that.

  Test seam: the harness REPLACES `activeChatStore.send` and
  `activeChatStore.cancel` with recording stubs that resolve
  immediately and append the call args onto
  `window.__sendCalls` / `window.__cancelCalls`. This lets specs
  assert on the input's "press Enter -> call send" contract
  WITHOUT spinning up MSW inside the CT bundle (which the existing
  `frontend/playwright/index.ts` deliberately does not do — see
  the comment in that file). A future CT spec that wants to drive
  the real `chats.send` HTTP call can override
  `window.__activeChatStore.send` from the spec's `page.evaluate`.
-->
<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import {
    ActiveChatStore,
    ACTIVE_CHAT_CONTEXT_KEY,
    type SendInput,
  } from '$lib/stores/active-chat.svelte';
  import { ModelsStore, MODELS_CONTEXT_KEY } from '$lib/stores/models.svelte';
  import { ToastStore, TOAST_CONTEXT_KEY } from '$lib/stores/toast.svelte';
  import MessageInput from '$lib/components/chat/MessageInput.svelte';
  import type { ChatRead } from '$lib/types/chat';
  import type { ModelInfo } from '$lib/types/model';

  interface Props {
    /** Optional initial model id forwarded into the component. */
    initialModel?: string;
    /** Optional models catalogue (defaults to a single GPT-4o). */
    models?: ModelInfo[];
    /** Optional pre-loaded chat — without one, `send()` throws. */
    chat?: ChatRead | null;
  }

  const DEFAULT_MODELS: ModelInfo[] = [{ id: 'gpt-4o', label: 'GPT-4o', owned_by: 'openai' }];

  const STUB_CHAT: ChatRead = {
    id: 'chat-1',
    title: 'Test chat',
    pinned: false,
    archived: false,
    folder_id: null,
    created_at: 0,
    updated_at: 0,
    history: { messages: {}, currentId: null },
    share_id: null,
  };

  let { initialModel = 'gpt-4o', models = DEFAULT_MODELS, chat = STUB_CHAT }: Props = $props();

  const initialModelSnapshot = untrack(() => initialModel);
  const modelsSnapshot = untrack(() => models);
  const chatSnapshot = untrack(() => chat);

  const activeChatStore = new ActiveChatStore();
  if (chatSnapshot) activeChatStore.chat = chatSnapshot;
  const modelsStore = new ModelsStore(modelsSnapshot);
  const toastStore = new ToastStore();
  setContext(ACTIVE_CHAT_CONTEXT_KEY, activeChatStore);
  setContext(MODELS_CONTEXT_KEY, modelsStore);
  setContext(TOAST_CONTEXT_KEY, toastStore);

  // Recording stubs (keep the original signatures so the
  // component's `await activeChat.send(...)` resolves cleanly).
  const sendCalls: SendInput[] = [];
  const cancelCalls: number[] = [];
  activeChatStore.send = async (input: SendInput): Promise<void> => {
    sendCalls.push(input);
  };
  activeChatStore.cancel = async (): Promise<void> => {
    cancelCalls.push(Date.now());
  };

  if (typeof window !== 'undefined') {
    const w = window as unknown as {
      __activeChatStore: ActiveChatStore;
      __modelsStore: ModelsStore;
      __toastStore: ToastStore;
      __sendCalls: SendInput[];
      __cancelCalls: number[];
    };
    w.__activeChatStore = activeChatStore;
    w.__modelsStore = modelsStore;
    w.__toastStore = toastStore;
    w.__sendCalls = sendCalls;
    w.__cancelCalls = cancelCalls;
  }
</script>

<MessageInput initialModel={initialModelSnapshot} />
