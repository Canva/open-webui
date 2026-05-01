import type { User } from '$lib/types/user';
import type { ThemeId } from '$lib/theme/presets';
import type { AgentInfo } from '$lib/types/agent';
import type { ChatList, ChatRead } from '$lib/types/chat';
import type { FolderRead } from '$lib/types/folder';

/*
 * Side-effect ambient declarations for KaTeX optional packages live in
 * `frontend/src/ambient.d.ts` (a no-import script file so the
 * `declare module` statements register globally). They cannot live in
 * this file because the `import` statements above turn it into an
 * external module, which would re-scope the declarations to local
 * augmentations.
 */

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
      /**
       * Initial sidebar payload from `(app)/+layout.server.ts` (Phase
       * 3d). Optional because routes outside the `(app)` group (e.g.
       * `/401`, the public smoke landing) do not load it. The layout
       * passes it to `provideChats(...)` so the sidebar paints
       * server-side without an extra round-trip.
       */
      chats?: ChatList;
      /** Initial folder list — same lifetime as `chats`. */
      folders?: FolderRead[];
      /** Initial agent catalogue — same lifetime as `chats`. */
      agents?: AgentInfo[];
      /**
       * Server-loaded full chat for `/c/[id]` deep-links (set by
       * `(app)/c/[id]/+page.server.ts` in Phase 3d). The conversation
       * view's `$effect` calls `useActiveChat().load(data.chat.id)`
       * after hydration so the in-memory store matches the SSR'd
       * markup.
       */
      chat?: ChatRead;
    }
    interface Error {}
    interface PageState {}
    interface Platform {}
  }
}

export {};
