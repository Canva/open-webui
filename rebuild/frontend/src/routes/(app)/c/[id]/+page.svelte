<script lang="ts">
  /**
   * Thin route wrapper for `/c/[id]`. The conversation view does the
   * heavy lifting: loading into the store, rendering the message
   * list, owning the streaming lifecycle.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Stores and
   * state (line 1022): the store is loaded by the view's `$effect`,
   * not here. Keeping this file tiny means the route is just "mount
   * the view with the SSR'd chat".
   */
  import ConversationView from '$lib/components/chat/ConversationView.svelte';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
</script>

<ConversationView chat={data.chat} />
