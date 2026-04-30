<script lang="ts" module>
  /**
   * GitHub-style alert detection helper. Reads the leading `[!TYPE]`
   * sigil from a blockquote token's text and returns the parsed alert,
   * or `false` if the blockquote isn't an alert.
   *
   * Exported from `<script module>` so the parent `Tokens.svelte` can
   * call it without instantiating an `AlertRenderer`. The companion
   * runtime component below consumes the returned `AlertData`.
   */
  import { marked, type Token } from 'marked';

  export type AlertType = 'NOTE' | 'TIP' | 'IMPORTANT' | 'WARNING' | 'CAUTION';

  export interface AlertData {
    type: AlertType;
    text: string;
    tokens: Token[];
  }

  const ALERT_RE = /^(?:\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\])\s*?\n*/;

  export function alertComponent(token: Token): AlertData | false {
    const text = (token as { text?: string }).text ?? '';
    const matches = text.match(ALERT_RE);
    if (!matches) return false;
    const alertType = matches[1] as AlertType;
    const newText = text.replace(ALERT_RE, '');
    return {
      type: alertType,
      text: newText,
      tokens: marked.lexer(newText),
    };
  }
</script>

<script lang="ts">
  /**
   * Renders a GitHub-style alert blockquote. The legacy fork used a
   * coloured side-stripe (`border-l-4`) per alert type; that is a
   * project-banned anti-pattern (see PROJECT.md § Project-specific
   * absolute bans, "no side-stripe borders"). The rebuild uses a
   * full hairline + a coloured leading icon so the alert reads as a
   * deliberate panel rather than an unstyled blockquote.
   *
   * Background uses `bg-background-elevated` to lift the alert out of
   * the message column without breaking the flat-until-floating rule
   * (see DESIGN.md § elevation): the alert is part of the page flow
   * and gets no shadow.
   *
   * Icon glyphs are inline SVG so the markdown subtree stays icon-set
   * agnostic; if M3+ wires a shared `Icon` component these inline
   * paths are the obvious swap target.
   */
  import Tokens from './Tokens.svelte';

  interface Props {
    alert: AlertData;
  }

  const { alert }: Props = $props();

  /**
   * Per-type token mapping. Status hues come from `DESIGN.json` via the
   * M1 `text-status-*` utilities. `NOTE` gets the chrome accent
   * (`text-accent-mention`) because Mention Sky is the chrome's only
   * decorative hue; matching it for `NOTE` keeps the surface coherent.
   */
  type AlertTheme = {
    icon: 'info' | 'tip' | 'star' | 'caution' | 'warning';
    iconColor: string;
    label: string;
  };

  const THEME: Record<AlertType, AlertTheme> = {
    NOTE: { icon: 'info', iconColor: 'text-accent-mention', label: 'Note' },
    TIP: { icon: 'tip', iconColor: 'text-status-success', label: 'Tip' },
    IMPORTANT: { icon: 'star', iconColor: 'text-status-danger', label: 'Important' },
    WARNING: { icon: 'warning', iconColor: 'text-status-warning', label: 'Warning' },
    CAUTION: { icon: 'caution', iconColor: 'text-status-danger', label: 'Caution' },
  };

  const theme = $derived(THEME[alert.type]);

  // marked's `Token[]` is render-compatible with `Tokens.svelte`'s expected
  // input. No re-typing needed; pass the lex output through.
  const lexedTokens = $derived(alert.tokens);
</script>

<aside
  class="border-hairline bg-background-elevated my-2 rounded-xl border px-4 py-3"
  role="note"
  aria-label={theme.label}
>
  <header class="mb-1 flex items-center gap-1.5 text-sm font-medium {theme.iconColor}">
    {#if theme.icon === 'info'}
      <svg
        viewBox="0 0 16 16"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <circle cx="8" cy="8" r="6.5" />
        <path d="M8 7v4" />
        <circle cx="8" cy="4.75" r="0.75" fill="currentColor" stroke="none" />
      </svg>
    {:else if theme.icon === 'tip'}
      <svg
        viewBox="0 0 16 16"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path
          d="M8 1.5a4.5 4.5 0 0 0-2.7 8.1V11a1 1 0 0 0 1 1h3.4a1 1 0 0 0 1-1V9.6A4.5 4.5 0 0 0 8 1.5Z"
        />
        <path d="M6 14.25h4" />
      </svg>
    {:else if theme.icon === 'star'}
      <svg
        viewBox="0 0 16 16"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path
          d="M8 1.75 9.95 5.7l4.35.63-3.15 3.07.74 4.35L8 11.7l-3.89 2.05.74-4.35L1.7 6.33l4.35-.63Z"
        />
      </svg>
    {:else if theme.icon === 'warning'}
      <svg
        viewBox="0 0 16 16"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M8 2 1.75 13h12.5L8 2Z" />
        <path d="M8 6.5v3.25" />
        <circle cx="8" cy="11.5" r="0.6" fill="currentColor" stroke="none" />
      </svg>
    {:else}
      <svg
        viewBox="0 0 16 16"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <circle cx="8" cy="8" r="6.5" />
        <path d="M8 4.5v4M8 11.25v.5" />
      </svg>
    {/if}
    <span>{theme.label}</span>
  </header>
  <div class="text-ink-body">
    <Tokens tokens={lexedTokens} />
  </div>
</aside>
