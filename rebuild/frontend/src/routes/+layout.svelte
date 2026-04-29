<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';
  import type { LayoutData } from './$types';

  let { data, children }: { data: LayoutData; children: Snippet } = $props();

  const userJson = $derived(JSON.stringify(data.user, null, 2));
</script>

<div class="mx-auto flex min-h-svh w-full max-w-2xl flex-col gap-10 px-6 py-16">
  <header class="space-y-3">
    <p class="text-mention-sky tracking-label text-xs font-medium uppercase">M0 / Foundations</p>
    <h1 class="font-display text-strong-ink tracking-headline text-xl/[1.25] font-semibold">
      The workshop is wired.
    </h1>
    <p class="text-secondary-ink max-w-prose text-sm/[1.5]">
      Trusted-header authentication round-trips against the FastAPI backend. The chat shell,
      channels, and automations arrive with M1 through M4.
    </p>
  </header>

  <section class="border-divider bg-paper-white rounded-2xl border p-6">
    <p class="text-muted-ink tracking-label text-xs font-medium uppercase">Identity</p>
    {#if data.user}
      <p class="text-strong-ink mt-3 text-sm/[1.5]">
        Signed in as <span class="font-medium">{data.user.email}</span>
      </p>
      <p class="text-muted-ink mt-1 text-xs">
        {data.user.name} · {data.user.timezone}
      </p>
    {:else}
      <p class="text-strong-ink mt-3 text-sm/[1.5] font-medium">No proxy header on this request.</p>
      <p class="text-muted-ink mt-2 text-sm/[1.5]">
        Set <code class="font-mono text-xs">X-Forwarded-Email</code> at the edge, or pass
        <code class="font-mono text-xs">-H 'X-Forwarded-Email: you@canva.com'</code> to curl, to
        populate <code class="font-mono text-xs">event.locals.user</code>.
      </p>
    {/if}
  </section>

  <section class="space-y-2">
    <p class="text-muted-ink tracking-label text-xs font-medium uppercase">data.user</p>
    <pre
      class="border-divider bg-page-fill text-strong-ink overflow-x-auto rounded-xl border p-4 font-mono text-xs leading-relaxed">{userJson}</pre>
  </section>

  {@render children()}
</div>
