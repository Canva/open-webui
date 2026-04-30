<script lang="ts">
  /**
   * Model picker. Native `<select>` when the catalog is short (≤10
   * items); a custom searchable popover otherwise. Both surfaces feed
   * the same `bind:value` so the parent can stay agnostic.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Frontend
   * components (line 887): "ModelSelector — `<select>` if ≤10 models,
   * searchable popover otherwise. Reads `useModels()`. Calls
   * `useModels().maybeRefresh()` on dropdown open."
   *
   * Brand: agents over models. The selector is small, lives in the
   * input chrome, and never above the conversation as a hero element
   * (per project/PRODUCT.md absolute ban: "no model-forward chrome").
   * Ids render in body weight; `label` (when different from `id`)
   * sits underneath in `text-ink-muted text-[11px]` so the user sees
   * the technical model id without it dominating the row.
   */
  import { useModels } from '$lib/stores/models.svelte';

  interface Props {
    value: string;
    oninput?: (next: string) => void;
  }

  let { value = $bindable(''), oninput }: Props = $props();

  const models = useModels();

  /** Switch from native select to popover at this many items. */
  const POPOVER_THRESHOLD = 10;

  let popoverOpen = $state(false);
  let filter = $state('');
  let popoverRoot: HTMLDivElement | null = $state(null);

  const useNativeSelect = $derived(models.items.length <= POPOVER_THRESHOLD);

  const filtered = $derived.by(() => {
    const q = filter.trim().toLowerCase();
    if (q.length === 0) return models.items;
    return models.items.filter(
      (m) => m.id.toLowerCase().includes(q) || m.label.toLowerCase().includes(q),
    );
  });

  const selectedLabel = $derived.by(() => {
    const found = models.items.find((m) => m.id === value);
    return found?.label ?? value ?? '';
  });

  function handleNativeChange(event: Event): void {
    const target = event.currentTarget as HTMLSelectElement;
    value = target.value;
    oninput?.(target.value);
  }

  function openPopover(): void {
    if (popoverOpen) return;
    popoverOpen = true;
    filter = '';
    models.maybeRefresh();
  }

  function pickModel(modelId: string): void {
    value = modelId;
    oninput?.(modelId);
    popoverOpen = false;
  }

  function onPopoverKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      popoverOpen = false;
    }
  }
</script>

{#if models.items.length === 0}
  <span class="text-ink-muted text-xs italic">No models available</span>
{:else if useNativeSelect}
  <label class="inline-flex items-center gap-2">
    <span class="sr-only">Model</span>
    <select
      {value}
      onchange={handleNativeChange}
      class="bg-background-app text-ink-body border-hairline focus:border-hairline-strong rounded-lg border px-2 py-1 text-xs outline-none motion-safe:transition-colors motion-safe:duration-150"
    >
      {#each models.items as m (m.id)}
        <option value={m.id}>{m.label || m.id}</option>
      {/each}
    </select>
  </label>
{:else}
  <div bind:this={popoverRoot} class="relative">
    <button
      type="button"
      onclick={openPopover}
      aria-haspopup="listbox"
      aria-expanded={popoverOpen}
      class="text-ink-body hover:text-ink-strong border-hairline hover:border-hairline-strong bg-background-app inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs motion-safe:transition-colors motion-safe:duration-150"
    >
      <span class="max-w-[200px] truncate">{selectedLabel || 'Select model'}</span>
      <svg
        width="9"
        height="9"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M4 6l4 4 4-4" />
      </svg>
    </button>
    {#if popoverOpen}
      <button
        type="button"
        class="fixed inset-0 z-30 cursor-default"
        aria-label="Close model picker"
        onclick={() => (popoverOpen = false)}
      ></button>
      <div
        role="listbox"
        tabindex="-1"
        aria-label="Models"
        onkeydown={onPopoverKeydown}
        class="bg-background-elevated border-hairline absolute bottom-full z-40 mb-2 flex max-h-72 w-72 flex-col overflow-hidden rounded-2xl border shadow-lg backdrop-blur-sm"
      >
        <div class="border-hairline border-b p-2">
          <input
            type="search"
            bind:value={filter}
            placeholder="Filter models"
            aria-label="Filter models"
            class="bg-background-app text-ink-body placeholder:text-ink-placeholder border-hairline focus:border-hairline-strong block w-full rounded-md border px-2 py-1 text-xs outline-none"
          />
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto p-1">
          {#each filtered as m (m.id)}
            <button
              type="button"
              role="option"
              aria-selected={m.id === value}
              onclick={() => pickModel(m.id)}
              class="text-ink-body hover:bg-background-app aria-selected:bg-accent-selection aria-selected:text-ink-strong flex w-full flex-col items-start gap-0.5 rounded-lg px-2 py-1.5 text-start"
            >
              <span class="text-xs">{m.label || m.id}</span>
              {#if m.label && m.label !== m.id}
                <span class="text-ink-muted font-mono text-[11px]">{m.id}</span>
              {/if}
            </button>
          {:else}
            <p class="text-ink-muted px-2 py-3 text-xs">No matching models.</p>
          {/each}
        </div>
      </div>
    {/if}
  </div>
{/if}
