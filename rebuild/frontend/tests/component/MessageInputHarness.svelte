<!--
  Harness for the M2 MessageInput CT spec.

  `MessageInput.svelte` reads three contexts:
    - `useActiveChat()` for `send()` / `cancel()` / `streaming`.
    - `useToast()` for failure surfacing.
    - The transitive `<AgentSelector>` reaches `useAgents()`.

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
  import { AgentsStore, AGENTS_CONTEXT_KEY } from '$lib/stores/agents.svelte';
  import { ToastStore, TOAST_CONTEXT_KEY } from '$lib/stores/toast.svelte';
  import MessageInput from '$lib/components/chat/MessageInput.svelte';
  import type { ChatRead } from '$lib/types/chat';
  import type { AgentInfo } from '$lib/types/agent';

  interface Props {
    /** Optional initial agent id forwarded into the component. */
    initialAgentId?: string;
    /** Optional agents catalogue (defaults to a single GPT-4o). */
    agents?: AgentInfo[];
    /** Optional pre-loaded chat — without one, `send()` throws. */
    chat?: ChatRead | null;
  }

  const DEFAULT_AGENTS: AgentInfo[] = [{ id: 'gpt-4o', label: 'GPT-4o', owned_by: 'openai' }];

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

  let {
    initialAgentId = 'gpt-4o',
    agents = DEFAULT_AGENTS,
    chat = STUB_CHAT,
  }: Props = $props();

  const initialAgentIdSnapshot = untrack(() => initialAgentId);
  const agentsSnapshot = untrack(() => agents);
  const chatSnapshot = untrack(() => chat);

  const activeChatStore = new ActiveChatStore();
  if (chatSnapshot) activeChatStore.chat = chatSnapshot;
  const agentsStore = new AgentsStore(agentsSnapshot);
  const toastStore = new ToastStore();
  setContext(ACTIVE_CHAT_CONTEXT_KEY, activeChatStore);
  setContext(AGENTS_CONTEXT_KEY, agentsStore);
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
      __agentsStore: AgentsStore;
      __toastStore: ToastStore;
      __sendCalls: SendInput[];
      __cancelCalls: number[];
    };
    w.__activeChatStore = activeChatStore;
    w.__agentsStore = agentsStore;
    w.__toastStore = toastStore;
    w.__sendCalls = sendCalls;
    w.__cancelCalls = cancelCalls;
  }
</script>

<MessageInput initialAgentId={initialAgentIdSnapshot} />
