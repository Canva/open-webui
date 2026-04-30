import type { User } from '$lib/types/user';
import type { ThemeId } from '$lib/theme/presets';

declare global {
  namespace App {
    interface Locals {
      user: User | null;
      /**
       * Active theme for this request. Resolved by `hooks.server.ts`
       * from the `theme` cookie if valid; falls back to the brand
       * default (`tokyo-night`) otherwise. Emitted on `<html data-
       * theme>` via `transformPageChunk` so first paint is correct
       * with no JS.
       */
      theme: ThemeId;
      /**
       * Whether `theme` came from a valid cookie (`'explicit'`) or
       * from the SSR fallback (`'fallback'`). The (app) layout uses
       * this to decide whether the matchMedia `$effect` may
       * non-persistently re-resolve after hydration.
       *
       * Note: the store's user-facing `source` getter has finer
       * granularity (`'explicit' | 'os' | 'default'`) because it can
       * also see the matchMedia result. The server cannot — the
       * `Sec-CH-Prefers-Color-Scheme` header is not universally sent.
       */
      themeSource: 'explicit' | 'fallback';
    }
    interface PageData {
      user: User | null;
      theme: ThemeId;
      themeSource: 'explicit' | 'fallback';
    }
    interface Error {}
    interface PageState {}
    interface Platform {}
  }
}

export {};
