# SvelteKit Best Practises

> **Audience:** every agent (and every human) writing SvelteKit application code, route handlers, or hooks for the rebuild's frontend. This is the canonical "do / don't" list for SvelteKit-specific concerns.
> **Scope:** SvelteKit **2.x** paired with **Svelte 5** (runes mode). Where SvelteKit 1.x patterns differ, this is called out explicitly.
> **Out of scope:** Svelte 5 component-level guidance (runes, snippets, `$state` / `$derived` / `$effect` API, `bind:`, transitions). That lives in a separate doc; this file does not duplicate it.
> **Bias:** simplicity first. Pick the simplest correct primitive (a server `load` + form action) over a custom abstraction (a hand-rolled REST client, a custom store, a third-party form library) every time, and only escalate when there's a concrete reason.

---

## 0. The seven things to internalise first

If you remember nothing else from this document, remember these. Every other section flows from them.

1. **Filesystem is the router.** Routes are directories under `src/routes`; the `+`-prefixed files (`+page.svelte`, `+page.server.ts`, `+layout.svelte`, `+server.ts`, `+error.svelte`) are the only special filenames. Everything else colocated in a route directory is invisible to SvelteKit and free to use as you wish.
2. **`load` reads, actions write.** Server `load` functions in `+page.server.ts` / `+layout.server.ts` get data into the page. Form actions in the same file write data back. `+server.ts` endpoints are for reusable APIs (or non-form clients), not the default mutation path.
3. **Default to server `load` over universal `load`.** `+page.server.ts` runs only on the server, can use private env vars and the database directly, and never ships its source to the browser. Reach for `+page.ts` (universal) only when you genuinely need the function to also run in the browser — which is rare.
4. **Authentication lives in `hooks.server.ts`.** `handle` is the one place that runs on every server request, including form-action POSTs. Decode the session cookie there once, populate `event.locals.user`, and let everything downstream read from `locals` instead of re-parsing.
5. **Never mutate module-level state on the server.** A SvelteKit server is shared by every user and every request. A `let user = …` at module scope leaks across users. Per-request state goes on `event.locals`; cross-component request-scoped state goes through Svelte context (set in the root layout).
6. **`error()` and `redirect()` are called, not thrown.** SvelteKit 2 removed the `throw` requirement. Calling them throws internally; you just call. Don't wrap them in `try { … }` — the catch will swallow the redirect.
7. **Form actions are the default mutation primitive.** They progressively enhance, work without JS, are tied to a page, get session/cookie context for free, and integrate with `use:enhance` for SPA-like UX. You should be writing far more form actions than `+server.ts` POST handlers.

---

## 1. Project structure & routing conventions

### 1.1 The route file alphabet

| File                     | Runs on        | Purpose                                                                                  |
| ------------------------ | -------------- | ---------------------------------------------------------------------------------------- |
| `+page.svelte`           | server + browser | The page component. Receives `data` (from `load`) and `form` (from actions) as `$props`. |
| `+page.ts`               | server + browser | Universal `load`. Runs both during SSR and during client navigation.                     |
| `+page.server.ts`        | server only    | Server `load` and form `actions`. Can touch the DB, cookies, private env.                |
| `+layout.svelte`         | server + browser | Wraps every child route. Renders `{@render children()}`.                                 |
| `+layout.ts`             | server + browser | Universal layout `load`. Result is merged into every child page's `data`.                |
| `+layout.server.ts`      | server only    | Server layout `load`. Use for things shared across many routes (auth user, navigation).  |
| `+server.ts`             | server only    | API endpoint. Exports `GET` / `POST` / `PUT` / etc. returning `Response`.                |
| `+error.svelte`          | server + browser | Catches errors thrown in `load` (and rendering, with the experimental flag) for this subtree. |

Two rules you can lean on without thinking:

- **Anything `*.server.ts` runs only on the server.** SvelteKit will refuse to bundle it into the browser. You're safe importing the database client, secrets, Node APIs, anything.
- **Files without a `+` prefix in a route directory are ignored by the router.** Colocate your route-specific components, helpers, and types right next to the `+page` files that use them. Promote to `$lib/` only when something is reused across routes.

### 1.2 Directory layout the rebuild assumes

```
src/
  app.html                      # HTML shell — usually edit only to add <body data-sveltekit-preload-data>
  app.d.ts                      # App.Locals, App.PageData, App.Error, App.PageState type contracts
  hooks.server.ts               # handle, handleError (server)
  hooks.client.ts               # handleError (client) — optional
  hooks.ts                      # reroute, transport — optional, runs on both
  lib/
    components/                 # cross-route Svelte components
    server/                     # SERVER-ONLY: db client, auth helpers, queue, mailer
      db.ts
      auth.ts
    stores/                     # .svelte.ts modules with shared state (see §8)
    utils/                      # pure helpers usable in both server and browser
  params/                       # route param matchers (e.g. uuid.ts)
  routes/
    +layout.svelte
    +layout.server.ts           # loads `event.locals.user` once for every page
    (app)/                      # route group: authenticated app shell
      +layout.svelte
      chats/
        [id]/
          +page.svelte
          +page.server.ts
    (marketing)/                # route group: unauthenticated landing pages
      +layout.svelte
      +page.svelte
    api/
      health/+server.ts         # public JSON endpoint
```

Notes:

- **`$lib`** is an alias for `src/lib`. Always use `import { foo } from '$lib/server/db'`, never `'../../../../lib/server/db'`.
- **`$lib/server/`** is enforced server-only. Importing it from a `.svelte` file (or from any code that ends up in the browser bundle) is a compile-time error. Use this aggressively — it's free safety.
- **`$lib/`-rooted "stores"** are `.svelte.ts` modules using runes. There is no `svelte/store` `writable()` here unless you have a specific reason; see §8.

### 1.3 Route parameters, matchers, optional, rest

- **Required param:** `src/routes/chats/[id]/+page.svelte` matches `/chats/abc`, with `params.id === 'abc'`.
- **Optional param:** `src/routes/[[lang]]/home/+page.svelte` matches both `/home` and `/en/home`.
- **Rest param:** `src/routes/files/[...path]/+page.svelte` matches `/files/a/b/c`, with `params.path === 'a/b/c'`. Use this for catch-all 404s as well.
- **Matchers:** put a function in `src/params/uuid.ts` that returns `boolean`, then use `[id=uuid]` to constrain the param. Matchers run on **both** server and client, so they must be pure.

Don't reach for matchers for ad-hoc validation — if the only valid IDs are UUIDs in your database, validate at the data layer (404 if not found) and keep the matcher set small.

### 1.4 Route groups `(name)` and layout breakouts `+page@name.svelte`

- **`(group)` directories don't affect URLs.** They exist so you can apply different layouts to subsets of routes (e.g. `(app)/+layout.svelte` vs `(marketing)/+layout.svelte`) without polluting the URL.
- **Use them for layout differentiation only.** A single `(app)` group around all authenticated routes is normal; nesting four levels of `(group)/(another)/(third)` is over-engineering.
- **`+page@.svelte`** breaks out of the layout hierarchy back to the root. Useful for embed pages, OAuth callbacks, full-screen flows. **`+page@(app).svelte`** breaks out to a specific named ancestor. Reach for this rarely; it's confusing to read and easy to outgrow.

### 1.5 `+server.ts` vs `+page.server.ts` actions

A `+server.ts` and a `+page.svelte` can sit side-by-side in the same directory. SvelteKit content-negotiates: `Accept: text/html` goes to the page, everything else goes to the endpoint. This is fine but prefer separate paths — `/api/foo/+server.ts` and `/foo/+page.svelte` — because it keeps the routing model boring and grep-able.

**References**

- <https://svelte.dev/docs/kit/routing>
- <https://svelte.dev/docs/kit/advanced-routing>
- <https://svelte.dev/docs/kit/$lib>
- <https://svelte.dev/docs/kit/types>

---

## 2. Load functions: universal vs server, when to use which

### 2.1 The decision tree

```
Need to read from the database / use a secret / use a Node-only API?
  → +page.server.ts (server load)

Need to fetch from a public third-party API the browser can also reach,
and the result is cached/CDN-friendly?
  → +page.ts (universal load) — saves a server hop on client navigation

Need to return something non-serializable (a class instance, a component constructor)?
  → +page.ts (universal load), or +page.server.ts + +page.ts together

Otherwise (the default for the rebuild)
  → +page.server.ts
```

For an app that talks to its own backend (i.e. the rebuild), **server `load` is the default**. Universal `load` is a niche tool, not a sibling primitive.

### 2.2 What server load gives you

```ts
// src/routes/chats/[id]/+page.server.ts
import { error } from '@sveltejs/kit';
import { getChat } from '$lib/server/db';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, locals, depends }) => {
  if (!locals.user) error(401, 'not logged in');

  const chat = await getChat(params.id, locals.user.id);
  if (!chat) error(404, 'chat not found');

  depends('app:chat'); // lets us invalidate('app:chat') after a mutation
  return { chat };
};
```

- `params`, `url`, `route` describe the request.
- `locals` is populated by `hooks.server.ts` — that's where session lives.
- `cookies` lets you `cookies.get(name)` and `cookies.set(name, value, { path: '/' })`.
- `fetch` is SvelteKit's enhanced `fetch`: makes credentialed in-process calls to internal `+server.ts` routes, replays responses into the SSR'd HTML so the browser doesn't re-fetch, and works with relative URLs on the server.
- The return value must be serializable with [devalue](https://github.com/rich-harris/devalue) — JSON plus `Date`, `Map`, `Set`, `BigInt`, `RegExp`, repeated/cyclical refs.

### 2.3 What universal load adds (and why you usually don't need it)

```ts
// src/routes/products/+page.ts
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const res = await fetch('https://cms.example.com/products.json');
  return { products: await res.json() };
};
```

This avoids a server hop on subsequent client navigations. Useful when:

- The data is genuinely public (no auth headers, no secrets).
- The endpoint is geographically closer to the browser than to your server (rare).
- You want to return a non-serializable value (a Svelte component constructor for dynamic content).

For this rebuild's domain (chats, channels, automations — all gated by auth and all served by our own backend), **universal load is the wrong default**. Stick with server load.

### 2.4 Combining server + universal

If you need both — e.g. fetch from the DB on the server, then wrap in a class on the client — return JSON from `+page.server.ts` and consume it in `+page.ts` via `event.data`:

```ts
// +page.server.ts
export const load = async () => ({ raw: await db.getChat(...) });

// +page.ts
import { Chat } from '$lib/Chat';
export const load = async ({ data }) => ({ chat: new Chat(data.raw) });
```

Reach for this only when the class wrapper genuinely earns its keep.

### 2.5 Layout loads: scope them carefully

Anything returned by `+layout.server.ts` is available to every child page through `data`. That's powerful and abusable. Two rules:

- **Put truly global data in the root `+layout.server.ts`** (current user, feature flags, theme).
- **Don't put per-route data in a layout** just because two routes happen to need it — the layout `load` then runs for every other route too. Compose with shared helpers in `$lib/server/` instead.

Layout `load`s **don't rerun** on every client navigation between sibling routes (they only rerun if their dependencies change). This is a feature for performance, but it has implications for auth — see §6.

### 2.6 Parallel loading & avoiding waterfalls

SvelteKit runs all `load` functions for a route concurrently. **Don't manufacture serial dependencies you don't have.** Two anti-patterns:

```ts
// BAD — serial
const parent = await parentLoad();
const data = await getData(params);

// GOOD — parallel where possible
const [parentData, data] = await Promise.all([
  parentLoad(),
  getData(params)
]);
```

Inside a single `load`, **issue independent fetches in parallel**:

```ts
// BAD
const user = await getUser(id);
const orgs = await getOrgs(id);

// GOOD
const [user, orgs] = await Promise.all([getUser(id), getOrgs(id)]);
```

If you can replace two queries with one (a join, an `IN` query), do that — the cost of an extra round trip dwarfs the cost of slightly more complex SQL.

### 2.7 Streaming with promises (server load only)

Top-level promises in a `load` return value used to be auto-awaited in SvelteKit 1. **In SvelteKit 2 they are not.** That means you can stream non-essential data like this:

```ts
// +page.server.ts
export const load = async ({ params }) => ({
  post: await loadPost(params.slug),       // blocks render
  comments: loadComments(params.slug)      // streams in afterwards
});
```

```svelte
<!-- +page.svelte -->
<h1>{data.post.title}</h1>
{#await data.comments}
  Loading comments…
{:then comments}
  {#each comments as c}<p>{c.body}</p>{/each}
{:catch err}
  Couldn't load comments: {err.message}
{/await}
```

Caveats:

- **Streaming only works in server `load`**, not universal `load` — universal `load` reruns on the client and would refetch from scratch.
- **Attach a `.catch(() => {})`** to non-fetch promises you're streaming, otherwise an unhandled rejection can crash the render. SvelteKit handles this for `event.fetch` automatically.
- **Some platforms (AWS Lambda, Firebase functions) buffer responses**, defeating streaming. If you're behind a proxy like NGINX, disable response buffering for SvelteKit routes.
- **You can't `setHeaders()` or `redirect()` from a streamed promise** — headers and status are already gone.

### 2.8 Invalidation & rerunning

- A server `load` reruns when `params`, accessed `url` properties, or accessed `searchParams` keys change.
- Or when `invalidate(url)` / `invalidateAll()` is called — typically from a `use:enhance` callback after a mutation that affects this page.
- Or when a parent's `load` (that this `load` `await parent()`s) reruns.
- Use `depends('app:foo')` to register a custom dependency, then `invalidate('app:foo')` to refresh just that.

Don't reach for `invalidateAll()` reflexively — it reruns *every* `load` for the current page, including layout loads. Targeted `invalidate(url)` is almost always what you want.

**References**

- <https://svelte.dev/docs/kit/load>
- <https://svelte.dev/docs/kit/$app-navigation>

---

## 3. Form actions vs API endpoints

### 3.1 Defaults

**Use form actions for every page-driven mutation.** Login, register, create chat, rename folder, delete channel, save settings — they all go in `+page.server.ts` as actions:

```ts
// src/routes/chats/+page.server.ts
import { fail, redirect } from '@sveltejs/kit';
import type { Actions } from './$types';

export const actions: Actions = {
  create: async ({ request, locals }) => {
    if (!locals.user) redirect(303, '/login');

    const data = await request.formData();
    const title = String(data.get('title') ?? '').trim();
    if (!title) return fail(400, { title, missing: true });

    const chat = await db.createChat({ userId: locals.user.id, title });
    redirect(303, `/chats/${chat.id}`);
  }
};
```

```svelte
<!-- src/routes/chats/+page.svelte -->
<script lang="ts">
  import { enhance } from '$app/forms';
  let { form }: { form: ActionData } = $props();
</script>

<form method="POST" action="?/create" use:enhance>
  <input name="title" value={form?.title ?? ''} required />
  {#if form?.missing}<p class="error">Title is required.</p>{/if}
  <button>Create</button>
</form>
```

**Use `+server.ts` endpoints when:**

- The endpoint must serve non-form clients (mobile app, CLI, integration partner, webhook receiver).
- The endpoint needs HTTP verbs other than `POST` (a `DELETE /api/foo/:id`, a `GET /api/health`).
- The endpoint is shared across many pages and isn't tied to a single `+page`.
- You need to stream a custom response body (CSV download, server-sent events, file proxy).

If a button is the only caller, that's a form action. If there's an API in your spec, that's a `+server.ts`. Don't write a `POST /api/chats` and a `+page.server.ts` action that both create a chat — pick one and route the form at it.

### 3.2 Default vs named actions

```ts
// All four buttons on /login post to actions on the same page
export const actions: Actions = {
  login: async (event) => { /* … */ },
  register: async (event) => { /* … */ },
  forgot: async (event) => { /* … */ }
};
```

```svelte
<form method="POST" action="?/login" use:enhance>…</form>
<form method="POST" action="?/register" use:enhance>…</form>
```

You can mix `formaction="?/register"` on a button to override the parent form's action. **You cannot mix a `default` action with named actions on the same page** — the URL `?/named` would persist past redirects and break the next default POST. Pick one style per page.

### 3.3 `fail`, `redirect`, return values

```ts
import { fail, redirect } from '@sveltejs/kit';

export const actions: Actions = {
  default: async ({ request, cookies }) => {
    const data = await request.formData();
    const email = String(data.get('email') ?? '');

    // Validation: return data the form can re-display
    if (!email.includes('@')) {
      return fail(400, { email, invalid: true });
    }

    const user = await db.findUser(email);
    if (!user) return fail(400, { email, notFound: true });

    cookies.set('sessionid', await db.createSession(user), {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      secure: !dev
    });

    // Redirect on success — form prop will not be set
    redirect(303, '/dashboard');
  }
};
```

Rules:

- **`return fail(status, data)`** for validation problems. `data` becomes `form` on the page; status becomes `page.status`. Don't include the password or anything sensitive in `data` — it's literally rendered back into the page.
- **`redirect(303, '/somewhere')`** on success that should change the URL. `303 See Other` is correct after a POST so refresh doesn't re-submit.
- **Plain `return { ok: true }`** when you want to stay on the same page and show a success state. The page rerenders and `form?.ok` is true.
- **Don't wrap `redirect()` or `error()` in `try/…catch`** — both throw internally to abort the action, and your `catch` block will swallow them. If you must, use `isHttpError` and `isRedirect` from `@sveltejs/kit` to re-throw.

### 3.4 SvelteKit 2 cookie gotcha

**You must set `path` on every `cookies.set` / `cookies.delete` / `cookies.serialize` call.** SvelteKit 1 silently picked the request's parent path; SvelteKit 2 makes you opt in. Almost always you want `path: '/'`:

```ts
cookies.set('sessionid', token, {
  path: '/',
  httpOnly: true,
  sameSite: 'lax',
  secure: !dev,
  maxAge: 60 * 60 * 24 * 30
});
```

### 3.5 `request.formData()` and file inputs

- **Always use `request.formData()`** in actions, not `request.json()` — that's the contract with `<form>`.
- **Forms with `<input type="file">` must declare `enctype="multipart/form-data"`.** SvelteKit 2 throws if you `use:enhance` a form with a file input but no `enctype`. This is a guardrail; don't disable it.
- Cast / coerce explicitly: `String(data.get('email') ?? '')`. `FormDataEntryValue` is `string | File | null`.

**References**

- <https://svelte.dev/docs/kit/form-actions>
- <https://svelte.dev/docs/kit/migrating-to-sveltekit-2#path-is-required-when-setting-cookies>

---

## 4. Progressive enhancement with `use:enhance`

### 4.1 The default behaviour

Add `use:enhance` to a `<form method="POST">` and you get:

- No full-page reload on submit.
- `form` prop and `page.form` updated on success or validation failure (when the action is on the same page as the form).
- Form element reset on success.
- `invalidateAll()` called on success, so all `load` functions on the current page rerun.
- `goto(...)` called on `redirect` responses.
- Nearest `+error.svelte` rendered on unexpected errors.
- Focus reset to the appropriate element.

For 80% of forms, that's all you need:

```svelte
<script>
  import { enhance } from '$app/forms';
  let pending = $state(false);
</script>

<form method="POST" action="?/save" use:enhance>
  <input name="title" />
  <button disabled={pending}>{pending ? 'Saving…' : 'Save'}</button>
</form>
```

### 4.2 Customising

When you need to show a spinner, optimistic UI, or override the post-submit behaviour, supply a callback that returns a callback:

```svelte
<form
  method="POST"
  action="?/save"
  use:enhance={({ formData, cancel }) => {
    pending = true;
    return async ({ result, update }) => {
      pending = false;
      // Default behaviour: update form prop, reset, invalidateAll, etc.
      await update({ reset: false });
      // Or take full control with applyAction(result):
      //   if (result.type === 'redirect') goto(result.location);
      //   else await applyAction(result);
    };
  }}
>
```

- **`update({ reset, invalidateAll })`** runs the default post-submit logic with optional opt-outs.
- **`applyAction(result)`** propagates the action's result into `page.form` / `page.status` regardless of where you submitted from. Use when the form posts to a different page's action and you still want to render the response.
- **`cancel()`** aborts the submission entirely.

### 4.3 What `use:enhance` does **not** do

- It only works on `<form method="POST">` pointing at a `+page.server.ts` action. **It will not work** on `method="GET"`, on forms pointing at `+server.ts`, or on forms outside SvelteKit's router.
- It doesn't preserve element state on rerender — see snapshots (§14) for that.
- It doesn't validate client-side — that's your job (HTML5 attributes for UX hints, server-side validation for actual security).

### 4.4 SvelteKit 2 `use:enhance` callback shape change

SvelteKit 1's callback was passed `{ form, data, action, cancel }`. SvelteKit 2 deprecated and removed `form` and `data`; use `formElement` and `formData` instead. `npx sv migrate sveltekit-2` handles this automatically.

### 4.5 When to consider Superforms

The built-in form-action workflow is enough for most forms. Reach for [Superforms](https://superforms.rocks/) **only when** at least one of:

- You have many fields with cross-field validation that benefit from a single Zod/Valibot schema for both client and server.
- You're deeply nested (arrays of objects, repeating field groups).
- You need first-class server-validation + client-rehydration without writing the wiring yourself.

For a 3-field login form, plain `use:enhance` + a hand-written check is shorter and clearer than introducing a dependency.

**References**

- <https://svelte.dev/docs/kit/form-actions#Progressive-enhancement>
- <https://svelte.dev/docs/kit/$app-forms>

---

## 5. Hooks: server, client, universal

### 5.1 The three hook files

| File              | Runs on        | Common exports                                 |
| ----------------- | -------------- | ---------------------------------------------- |
| `hooks.server.ts` | server only    | `handle`, `handleFetch`, `handleError`, `init` |
| `hooks.client.ts` | browser only   | `handleError`, `init`                          |
| `hooks.ts`        | server + browser | `reroute`, `transport`                         |

### 5.2 `handle` — your server middleware

`handle({ event, resolve })` runs once per server request and is the **only** hook that wraps every request including form-action POSTs and `+server.ts` calls. Use it to:

- Read auth cookies, populate `event.locals`.
- Set response headers (CSP, security, custom).
- Short-circuit certain paths (rare — usually `+server.ts` is cleaner).

```ts
// src/hooks.server.ts
import type { Handle } from '@sveltejs/kit';
import { sequence } from '@sveltejs/kit/hooks';
import { getUserBySession } from '$lib/server/auth';

const auth: Handle = async ({ event, resolve }) => {
  const sessionId = event.cookies.get('sessionid');
  event.locals.user = sessionId ? await getUserBySession(sessionId) : null;
  return resolve(event);
};

const securityHeaders: Handle = async ({ event, resolve }) => {
  const response = await resolve(event);
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  return response;
};

export const handle = sequence(auth, securityHeaders);
```

Use `sequence(...)` from `@sveltejs/kit/hooks` to compose multiple `Handle` functions instead of nesting them by hand.

### 5.3 `handleFetch` — rewriting server-side fetches

`event.fetch` inside a `load` or action is intercepted by `handleFetch`. Common uses:

- Bypass the public URL when the server can hit the API directly:
  ```ts
  if (request.url.startsWith('https://api.example.com/')) {
    request = new Request(request.url.replace('https://api.example.com', 'http://internal-api:8080'), request);
  }
  ```
- Forward auth cookies to subdomains (SvelteKit's automatic cookie forwarding only covers same-origin and stricter subdomains).

### 5.4 `handleError` — observability hook

`handleError({ error, event, status, message })` runs when an unexpected error escapes a `load`, action, or render. It's the place to:

- Send the error to your reporting backend (Sentry, OpenTelemetry, etc.).
- Return a custom error object that becomes `page.error` on the rendered `+error.svelte`. The returned object must satisfy `App.Error`.

Don't try to recover here — the request has already failed. Just log and shape the user-facing payload.

```ts
// src/hooks.server.ts
import type { HandleServerError } from '@sveltejs/kit';
import { logger } from '$lib/server/logger';

export const handleError: HandleServerError = ({ error, event, status, message }) => {
  const id = crypto.randomUUID();
  logger.error({ id, status, message, path: event.url.pathname, error });
  return { message: 'Internal Error', code: 'UNEXPECTED', id };
};
```

The matching `hooks.client.ts` `handleError` lets you forward client-side render errors the same way.

### 5.5 `reroute` — URL rewriting before route resolution

`reroute({ url })` lives in `src/hooks.ts` (so it runs on both server and client) and rewrites the URL **internally** before route lookup. It does not change `event.url` or what the user sees in the address bar. The classic use case is i18n with translated slugs:

```ts
// src/hooks.ts
const map: Record<string, string> = {
  '/de/ueber-uns': '/de/about',
  '/fr/a-propos': '/fr/about'
};
export const reroute = ({ url }) => map[url.pathname];
```

Not applied recursively, not applied to external URLs. Server errors return 500; client errors fall back to a full navigation.

### 5.6 What does **not** belong in hooks

- Heavy initialisation per request — do it once at module top-level (the file runs at boot) or use the `init` hook.
- Anything you'd otherwise put in a `+server.ts`. Hooks are middleware, not endpoints.
- Conditional auth logic that only protects a subset of routes — that goes in the relevant `+layout.server.ts` or `+page.server.ts`, see §6.

**References**

- <https://svelte.dev/docs/kit/hooks>
- <https://svelte.dev/docs/kit/@sveltejs-kit-hooks>

---

## 6. Authentication, sessions, cookies

### 6.1 Session vs token

| Approach | Pros | Cons | Use when |
|----------|------|------|----------|
| **Server session ID** in cookie + DB lookup per request | Immediate revocation, small cookie | DB roundtrip on every request | Default. Fine for our scale. |
| **Signed JWT** in cookie, no DB lookup | No DB hit per request, edge-deployable | Cannot revoke until expiry; rotating secrets is painful | High RPS, latency-critical, edge runtime |

For this rebuild's profile (single managed MySQL, normal request volumes), **session-ID-in-cookie** is the default. JWTs are a premature optimisation.

### 6.2 The integration pattern

1. **Login action** (`POST /login`) verifies credentials, creates a session row, sets the cookie.
2. **`hooks.server.ts` `handle`** reads the cookie on every request, looks up the session, populates `event.locals.user`.
3. **Root `+layout.server.ts` `load`** returns `{ user: locals.user }` so the user is on `page.data.user` everywhere on the client.
4. **Per-route auth checks** are done in `+page.server.ts` `load` (or in shared helpers via `getRequestEvent()`), not in `+layout.server.ts`, so cached layout loads don't bypass them.
5. **Logout action** clears the session row, then `cookies.delete('sessionid', { path: '/' })`, then `redirect(303, '/login')`.

### 6.3 Where to put auth checks

This is the most-asked SvelteKit question. The trade-off:

- **In `hooks.server.ts`** — runs on every request including `+server.ts` and form actions. Cleanest for "block /admin/* unless admin" style guards.
- **In `+layout.server.ts`** — child loads must `await parent()` to be guaranteed it ran. Otherwise loads run in parallel. Layout loads are also cached across navigations, which means a child page navigation might *not* re-trigger the layout's auth check.
- **In `+page.server.ts`** — runs every time the page loads. Most explicit, no performance pitfalls.

**Recommended pattern** for the rebuild:

```ts
// hooks.server.ts: populate locals.user on every request
event.locals.user = await getUserFromCookie(event.cookies.get('sessionid'));

// hooks.server.ts: bulk gate by URL prefix
if (event.url.pathname.startsWith('/(app)') && !event.locals.user) {
  redirect(303, `/login?redirectTo=${encodeURIComponent(event.url.pathname)}`);
}

// +page.server.ts of a sensitive route: explicit per-route check
if (!locals.user) error(401);
if (!locals.user.canEdit(thing)) error(403);
```

For hop-free shared logic, use `getRequestEvent()` from `$app/server` inside helper functions:

```ts
// $lib/server/auth.ts
import { redirect } from '@sveltejs/kit';
import { getRequestEvent } from '$app/server';

export function requireUser() {
  const { locals, url } = getRequestEvent();
  if (!locals.user) redirect(303, `/login?redirectTo=${url.pathname}${url.search}`);
  return locals.user;
}
```

Then call `const user = requireUser();` from any `load` or action without threading `event` through.

### 6.4 Cookie hygiene

```ts
cookies.set('sessionid', token, {
  path: '/',
  httpOnly: true,    // not readable from JS — protects against XSS
  sameSite: 'lax',   // not sent on most cross-site POSTs — CSRF defence
  secure: !dev,      // HTTPS-only in production
  maxAge: 60 * 60 * 24 * 30
});
```

- `httpOnly` is non-negotiable for session cookies.
- `sameSite: 'lax'` is the right default; `'strict'` breaks login flows from external links.
- `secure: !dev` enforces HTTPS in production but allows local dev over HTTP.
- Always set `path` — see §3.4.

### 6.5 SvelteKit's built-in CSRF defence

SvelteKit 2 ships CSRF protection on by default (`kit.csrf.checkOrigin: true`): any cross-origin POST/PUT/PATCH/DELETE with a form content-type is rejected. You do not need to add CSRF tokens for first-party forms.

If you have a trusted external origin that needs to POST to your app (a payment gateway redirecting back, an OAuth callback that POSTs), add it to `kit.csrf.allowedOrigins` in `svelte.config.js`. Be sparing — every entry weakens the default.

### 6.6 Auth libraries

For greenfield work, [Better Auth](https://www.better-auth.com/) and [Lucia](https://lucia-auth.com/) are the well-supported options. The rebuild uses trusted-header auth (see `rebuild.md`), so most of these libraries don't apply — the SvelteKit side just trusts the upstream proxy header in `handle` and skips the cookie/JWT machinery entirely.

**References**

- <https://svelte.dev/docs/kit/auth>
- <https://svelte.dev/docs/kit/load#Implications-for-authentication>
- <https://svelte.dev/docs/kit/load#Using-getRequestEvent>

---

## 7. Server-only modules and `$env`

### 7.1 The four `$env` modules

| Module                   | When                  | Visibility | Use for                                     |
| ------------------------ | --------------------- | ---------- | ------------------------------------------- |
| `$env/static/private`    | Build time, replaced  | Server-only | API keys, DB URL — when the value is fixed at build |
| `$env/static/public`     | Build time, replaced  | Anywhere   | `PUBLIC_*` — public config like analytics keys |
| `$env/dynamic/private`   | Runtime, `process.env` | Server-only | Secrets that vary per environment without rebuild |
| `$env/dynamic/public`    | Runtime               | Anywhere   | Public config that needs to change without rebuild |

Rules:

- **Variables prefixed `PUBLIC_`** are exposed to the browser. Everything else is private.
- **Static modules dead-code-eliminate**: importing an unused export is free in production. Prefer them when the value never changes per deploy.
- **Dynamic modules are read at request time**: a 12-Factor app can use `$env/dynamic/private` and inject env at deploy time without rebuilding.
- **Dynamic env is unavailable during prerendering** (SvelteKit 2 made this a hard error — it used to silently bake build-time values into prerendered HTML, which is wrong).

For the rebuild, `$env/dynamic/private` for runtime secrets and `$env/static/public` for build-time public config covers ~all use cases.

### 7.2 Making your own modules server-only

Two ways:

- **Filename:** `secrets.server.ts` — anywhere in the source tree, the `.server` segment makes it server-only.
- **Path:** any module under `$lib/server/` is server-only.

Importing either from code that ends up in the browser bundle is a **build-time error**, even if you only import an unrelated symbol. SvelteKit traces the entire transitive import graph. This is your friend — lean on it.

```ts
// $lib/server/db.ts — server-only
export const db = createClient(env.DATABASE_URL);

// src/routes/+page.svelte — fails to build
import { db } from '$lib/server/db';   // ← compile error
```

### 7.3 `$app/server`

`read()` from `$app/server` reads files from the filesystem at runtime. It only works server-side. Useful for shipping data files alongside your build (markdown content, JSON fixtures, schema files) — see `getRequestEvent()` in §6 for the other major export.

**References**

- <https://svelte.dev/docs/kit/server-only-modules>
- <https://svelte.dev/docs/kit/$env-static-private>
- <https://svelte.dev/docs/kit/$env-dynamic-private>

---

## 8. State management at the app level

### 8.1 The cardinal rule: no shared mutable module state on the server

```ts
// src/lib/server/wat.ts — NEVER do this
let currentUser: User | null = null;  // ← shared across every request!

export function setUser(u: User) { currentUser = u; }
```

A SvelteKit server is a long-running process. Every user shares this `currentUser` variable. The next request sees the previous user's data. This is a security incident waiting to happen.

Per-request state lives on `event.locals` (set in `handle`). Per-page state lives in returned `data`. **There is no third option** for "global server state that is per-user".

### 8.2 Cross-component request-scoped state: Svelte context

If a child component needs to read or update state owned by a layout, use `setContext` in the layout and `getContext` in the child. This is **per-render** — i.e. per-request on the server, per-mount on the client — so it's safe.

```ts
// src/lib/state/notifications.svelte.ts
import { getContext, setContext } from 'svelte';

const KEY = Symbol('notifications');

export function provideNotifications() {
  const list = $state<string[]>([]);
  setContext(KEY, list);
  return list;
}

export function useNotifications(): string[] {
  return getContext<string[]>(KEY);
}
```

```svelte
<!-- src/routes/+layout.svelte -->
<script>
  import { provideNotifications } from '$lib/state/notifications.svelte';
  const notifications = provideNotifications();
</script>

{@render children()}
```

```svelte
<!-- anywhere downstream -->
<script>
  import { useNotifications } from '$lib/state/notifications.svelte';
  const notifications = useNotifications();
</script>

<button onclick={() => notifications.push('hi')}>Add</button>
```

### 8.3 Pure client-side global state

If state genuinely lives only in the browser (theme preference, sidebar open/closed, in-memory cache that's safe to lose), a `.svelte.ts` module with `$state` is the simplest tool — but **only if SSR is disabled for the affected pages**, otherwise the same module's state is shared across all SSR users.

The safe pattern when SSR is on: **wrap the state in a function** so each consumer gets a closure-scoped reference, or use the context pattern from §8.2 even for "client-only" state. The cost is one indirection; the benefit is no foot-gun.

```ts
// $lib/state/counter.svelte.ts — SSR-safe pattern
let counter = $state(0);

export function getCounter() { return counter; }
export function setCounter(v: number) { counter = v; }
```

This is still mutable shared state on the server when rendered with SSR — only safe because **no code on the server should be calling `setCounter()`**. If you can't guarantee that, use context.

### 8.4 `page.data` and `$app/state`

`$app/state` is the SvelteKit-managed reactive object for cross-component request-scoped data that's already there:

- `page.data` — merged data from all `load` functions for the current route.
- `page.url`, `page.params`, `page.route`, `page.status`, `page.error`, `page.form`, `page.state`.
- `navigating` — current navigation, `null` when idle.
- `updated` — `true` when a new app version is detected.

These are per-request on the server, per-tab in the browser, and **already SSR-safe**. Use them freely.

```svelte
<script>
  import { page, navigating } from '$app/state';
  const title = $derived(page.data.title);
</script>

{#if navigating}<div class="spinner" />{/if}
```

In SvelteKit 1.x and Svelte 4 you used `$app/stores` (with the `$page` store). **`$app/state` was added in 2.12 and is the recommended replacement.** `npx sv migrate app-state` handles the codemod. You only need `$app/stores` if you're stuck on Svelte 4.

### 8.5 URL as state

For state that should survive a refresh, be linkable, or be SEO-visible (filters, sort, pagination, tab selection), put it in the URL. Read it in `load` from `url.searchParams`; write it via `goto('?key=value')` or by setting `<a href="?key=value">`.

**This is a hard recommendation.** It's tempting to keep "what tab is open" in client state because it's faster to write — but URL state survives refresh, is shareable, and lets the back button work intuitively. If a user might link to it, it goes in the URL.

### 8.6 No side-effects in `load`

A `load` function is conceptually pure: given inputs, return data. **Don't write to a store / global / cache from inside `load`.** The same dangers as §8.1 apply.

```ts
// BAD
export const load = async () => {
  const u = await fetchUser();
  user.set(u);  // ← shared on the server
};

// GOOD
export const load = async () => ({ user: await fetchUser() });
```

**References**

- <https://svelte.dev/docs/kit/state-management>
- <https://svelte.dev/docs/kit/$app-state>

---

## 9. Error handling

### 9.1 Expected vs unexpected errors

- **Expected errors** are anticipated outcomes you choose to surface: 404 not found, 401 unauthorised, 422 validation. Created with `error(status, msgOrObject)`. They show their full message to the user, render the nearest `+error.svelte`, and **don't go through `handleError`**.
- **Unexpected errors** are bugs and infrastructure failures: an unhandled exception, a DB outage. They get `Internal Error` shown to the user, the original message logged via `handleError`, and a 500 status.

This distinction is what stops you from accidentally leaking stack traces.

```ts
import { error } from '@sveltejs/kit';

export const load = async ({ params, locals }) => {
  if (!locals.user) error(401, 'Sign in required');
  const chat = await db.getChat(params.id);
  if (!chat) error(404, 'Chat not found');
  if (chat.userId !== locals.user.id) error(403, 'Not yours');
  return { chat };
};
```

### 9.2 `+error.svelte` placement

When `load` throws, SvelteKit walks up the route tree looking for `+error.svelte`:

```
src/routes/blog/[slug]/+error.svelte    ← tried first
src/routes/blog/+error.svelte           ← then
src/routes/+error.svelte                ← then
src/error.html                          ← static fallback
```

Important wrinkles:

- **An error thrown in a layout `+layout.server.ts` looks for the error component *above* the layout** (because the layout itself is now broken).
- **`+error.svelte` does not catch errors thrown in `handle` or `+server.ts` handlers** — those return either a JSON error or `src/error.html` based on the `Accept` header.
- **Catch-all 404s** with rest params still need a route file to be matched. See `src/routes/marx-brothers/[...path]/+page.ts` pattern in the routing docs.

### 9.3 Custom error shapes

By default `error.message` is the only field. To carry extra context (a code, a tracking ID, a user-facing hint), declare `App.Error`:

```ts
// src/app.d.ts
declare global {
  namespace App {
    interface Error {
      message: string;
      code?: string;
      id?: string;
    }
  }
}
export {};
```

Then `error(404, { message: 'Not found', code: 'CHAT_NOT_FOUND' })` works, and `handleError` returns must satisfy this same shape.

### 9.4 Don't catch what you didn't throw

```ts
// BAD — will swallow `redirect(303, '/login')`
try {
  doStuff();
  redirect(303, '/login');
} catch (e) {
  console.error(e);
  return fail(500);
}
```

`redirect()` and `error()` throw control-flow exceptions that SvelteKit catches. If you must wrap in try/catch (e.g. you own a transaction), use the type guards:

```ts
import { isHttpError, isRedirect } from '@sveltejs/kit';

try { /* ... */ }
catch (e) {
  if (isRedirect(e) || isHttpError(e)) throw e;
  // your real error handling
}
```

### 9.5 Render-time errors and `<svelte:boundary>`

By default an error during component rendering returns a 500 page. SvelteKit 2.54 / Svelte 5.53 added an experimental `kit.experimental.handleRenderingErrors` flag that wraps your routes in an error boundary so render-time errors are caught and routed through `handleError` to `+error.svelte`. Useful but still experimental — opt in deliberately.

For component-level recovery, use `<svelte:boundary>` with a `failed` snippet. Errors caught there are still passed to `handleError` first.

**References**

- <https://svelte.dev/docs/kit/errors>
- <https://svelte.dev/docs/kit/hooks#Shared-hooks-handleError>

---

## 10. Rendering: SSR, CSR, prerendering — when to choose what

### 10.1 The defaults

By default every route is **SSR'd then hydrated for CSR**. That's nearly always correct: fast first paint, full interactivity, great SEO, JS-disabled fallback works for forms.

### 10.2 The three page options

```ts
// +page.ts or +page.server.ts (or +layout to apply to a subtree)
export const ssr = true;       // server-side render? default true
export const csr = true;       // ship JS for hydration? default true
export const prerender = true; // generate static HTML at build time? default false
```

They compose:

| `ssr` | `csr` | `prerender` | Behaviour |
|-------|-------|-------------|-----------|
| `true`  | `true`  | `false` | **Default.** SSR + hydrate. |
| `true`  | `true`  | `true`  | Static HTML at build time, then hydrates. Best for marketing pages with dynamic JS islands. |
| `true`  | `false` | `true`  | Pure static, no client JS. Best for blog posts. |
| `true`  | `false` | `false` | SSR'd HTML on every request, no client JS. Rare. |
| `false` | `true`  | `false` | SPA: empty shell, JS does everything. Slow first paint, worse SEO. Avoid unless required. |
| `false` | `false` | any   | Renders nothing. Build error. |

### 10.3 When to prerender

A page is prerenderable if **two anonymous users hitting it directly get the same HTML.** That includes pages with parameters whose space is known at build time (`/[slug]` for known slugs).

Prerender:
- Marketing pages, about, pricing.
- Documentation.
- A blog if posts come from a CMS at build time.

Don't prerender:
- Anything with user-specific data.
- Anything that uses `url.searchParams` in `load`.
- Anything with form actions (POST cannot be prerendered).
- Anything that uses `$env/dynamic/*` (SvelteKit 2 hard-errors here, see §7.1).

For mostly-static sites with a few dynamic slugs, set `prerender = 'auto'` — the route is prerendered when reachable from the entry crawl, but a server fallback exists for unknown values.

### 10.4 When to disable SSR

Almost never. The reasons are narrow:

- The page uses a library that genuinely requires `window` and can't be lazy-loaded (chart libraries, map libraries — try lazy-loading them inside `onMount` first).
- The page is an authenticated dashboard where SEO doesn't matter and SSR latency dominates first paint (debatable — still usually wrong).
- You're building an embeddable widget served to other origins.

If you do, prefer disabling it on the **specific route**, not globally. Disabling at the root layout makes the entire app a SPA, with all the cost SPAs carry: blank first paint, worse Core Web Vitals, broken when JS fails.

### 10.5 When to disable CSR

Disable CSR (`export const csr = false`) for genuinely static content (marketing landing pages, blog posts, documentation). The result is a page with zero JavaScript, instant interactivity, and no hydration cost. You lose `use:enhance`, client-side routing, and `<script>` interactivity inside that page — make sure that's actually fine.

### 10.6 Streaming

See §2.7. Streaming is opt-in by returning unawaited promises from a server `load`. It's the right tool when one piece of data is slow but the rest of the page can render.

### 10.7 `trailingSlash`

Default is `'never'`: `/foo/` redirects to `/foo`. The other options are `'always'` and `'ignore'`. **Don't pick `'ignore'`** — it splits your SEO across two URLs and changes how relative paths resolve. Pick a side and stick with it; `'never'` is the right default.

**References**

- <https://svelte.dev/docs/kit/page-options>
- <https://svelte.dev/docs/kit/single-page-apps>

---

## 11. Performance

### 11.1 What SvelteKit gives you for free

- Code-splitting per route, with `<link rel="modulepreload">` injection.
- Asset hashing for permanent caching.
- Request coalescing across multiple `load` functions in one navigation.
- Concurrent execution of independent `load` functions.
- `event.fetch` data inlining: server-side fetches are serialised into the HTML so the browser doesn't refetch on hydration.
- Conservative `load` invalidation.

### 11.2 Link preloading

The default project template ships:

```html
<body data-sveltekit-preload-data="hover">
```

That preloads a link's data on hover (or `touchstart` on mobile), making most navigations feel instant. The other options:

- `data-sveltekit-preload-data="tap"` — preload on `mousedown`/`touchstart`. Use when hover false-positives are common, or the data is so hot you can't afford prefetches.
- `data-sveltekit-preload-data="false"` — disable preloading on this subtree.
- `data-sveltekit-preload-code="eager" | "viewport" | "hover" | "tap"` — preload only the **code** (cheaper than data), with the eager options especially useful for primary nav.

Apply attributes at the highest sensible level (the `<body>` for app defaults, a `<nav>` for primary navigation) and override per-link as needed. **Don't** disable preloading globally to "save bandwidth" — the user already mostly downloads the chunks during navigation; preloading just shifts when.

### 11.3 Avoiding waterfalls

The single biggest perf failure mode: serial async dependencies that should be parallel.

- Inside one `load`: `Promise.all(...)` for independent calls.
- Between `load` and `await parent()`: only `await parent()` if you actually need parent data, and put it as late as possible (see §2.6).
- Between `load` and the database: replace N queries with one (a join, an `IN`, a subquery) when the queries always go together. The DB is faster than your app for this.
- Between server and edge: prefer server `load` over universal `load` for backend calls — the server is closer to the DB than the user is.

### 11.4 Images

Use [`@sveltejs/enhanced-img`](https://svelte.dev/docs/kit/images) for any image you bundle:

```svelte
<enhanced:img src="./hero.jpg" alt="…" sizes="min(1280px, 100vw)" />
```

It auto-generates `webp`/`avif`, multiple sizes, sets intrinsic `width`/`height` (preventing layout shift), and strips EXIF. For dynamic images (user uploads, CMS), use a CDN with a Svelte-aware library like `@unpic/svelte`.

For LCP images, set `fetchpriority="high"` and don't `loading="lazy"`.

### 11.5 Code size

- Run on the latest Svelte 5 — smaller and faster than Svelte 4.
- `npm run build && npx vite-bundle-visualizer` (or `rollup-plugin-visualizer`) to find bloat.
- `import('./Heavy.svelte')` for code that only loads on rare interactions.
- Move analytics server-side via the platform adapter rather than shipping a tracker bundle.

### 11.6 Fonts

SvelteKit doesn't preload fonts by default (it can't tell which weights you actually use). For self-hosted fonts that you know are critical, add a `preload` filter to your `handle`:

```ts
const response = await resolve(event, {
  preload: ({ type, path }) => type === 'font' && path.includes('/fonts/inter-')
});
```

Subset fonts you control. Self-host instead of pulling from a third-party domain when you can — saves a DNS lookup and a TLS handshake.

### 11.7 Profile in `vite preview`, not `vite dev`

Dev mode is unminified, has HMR, and won't tell you anything useful about production performance. Always profile against `npm run build && npm run preview`.

**References**

- <https://svelte.dev/docs/kit/performance>
- <https://svelte.dev/docs/kit/link-options>
- <https://svelte.dev/docs/kit/images>

---

## 12. Testing

### 12.1 The pyramid

- **Unit tests** (Vitest): pure functions, helpers, `.svelte.ts` modules with rune logic. Fast, run on every change.
- **Component tests** (Vitest + browser mode with `vitest-browser-svelte`): individual components in a real browser via Playwright. Test behaviour, not implementation.
- **End-to-end tests** (Playwright): critical user journeys against a built app — login, create chat, send message, share link.

The 2026 inflection point: **`vitest-browser-svelte` is now the recommended way** to test Svelte components instead of `@testing-library/svelte` + `jsdom`. JSDOM doesn't faithfully implement the browser APIs that Svelte 5 runes interact with; running in a real headless browser sidesteps a class of mysterious failures.

### 12.2 Vitest setup

`npm i -D vitest @vitest/browser playwright vitest-browser-svelte` and configure two projects in `vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
  plugins: [sveltekit()],
  test: {
    workspace: [
      {
        extends: true,
        test: {
          name: 'unit',
          environment: 'node',
          include: ['src/**/*.{test,spec}.ts']
        }
      },
      {
        extends: true,
        test: {
          name: 'component',
          browser: { enabled: true, provider: 'playwright', name: 'chromium' },
          include: ['src/**/*.svelte.{test,spec}.ts']
        }
      }
    ]
  }
});
```

The `.svelte.test.ts` extension tells Vite to compile the file with the Svelte plugin so runes work in tests.

### 12.3 Playwright setup

`npm i -D @playwright/test && npx playwright install`. Tests live in `e2e/` (or `tests/`) at the project root. A typical config:

```ts
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  webServer: {
    command: 'npm run build && npm run preview',
    port: 4173,
    reuseExistingServer: !process.env.CI
  },
  testDir: 'e2e',
  use: { baseURL: 'http://localhost:4173' },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'webkit', use: { browserName: 'webkit' } }
  ],
  workers: process.env.CI ? 4 : undefined
});
```

Run E2E against `vite preview` (the production build), not `vite dev`. Dev mode behaves differently and you'll waste hours debugging fake bugs.

### 12.4 Test what users see, not what code does

- Query by role / label / text, not by class names or test IDs unless there's no other option.
- Avoid tests that break on a variable rename — that's a sign you're testing implementation.
- Mock external APIs with [MSW](https://mswjs.io/) at the network layer in unit tests. For E2E, prefer hitting a real backend (or a fixture-loaded one) so you catch integration issues.

### 12.5 What to test

| Layer | Coverage target | What to test |
|-------|-----------------|--------------|
| Pure helpers in `$lib/` | High | Every public function, including edge cases |
| `.svelte.ts` rune modules | High | State transitions, derivations |
| Components | Medium | Behaviour, not styling. Slot/snippet wiring. Form submission. |
| Server `load` and actions | Medium | Auth gates, validation paths, error returns |
| E2E flows | Low (in count, high in coverage) | Login + main workflow + logout, signup, settings save, sharing |

**References**

- <https://svelte.dev/docs/kit/testing>
- <https://playwright.dev/docs/intro>
- <https://vitest.dev/>

---

## 13. Deployment & adapters

### 13.1 Pick an adapter

| Adapter                      | Use when |
|------------------------------|----------|
| `@sveltejs/adapter-node`     | Self-host on a VM, container, Kubernetes, anything with `node`. **Default for the rebuild.** |
| `@sveltejs/adapter-static`   | Fully prerendered site / SPA hosted on any static host (S3, GitHub Pages, Cloudflare Pages). |
| `@sveltejs/adapter-vercel`   | Vercel — supports edge / serverless / ISR per route. |
| `@sveltejs/adapter-netlify`  | Netlify. |
| `@sveltejs/adapter-cloudflare` | Cloudflare Pages or Workers. |

Configure in `svelte.config.js`:

```js
import adapter from '@sveltejs/adapter-node';

export default {
  kit: {
    adapter: adapter({
      out: 'build',
      precompress: true,
      envPrefix: '',
      polyfill: false
    })
  }
};
```

### 13.2 `adapter-node` specifics

`npm run build` produces a `build/` directory. Run with `node build`. The runtime needs:

- `build/` directory.
- `package.json` (for `"type": "module"`).
- `node_modules/` with production deps installed (`npm ci --omit=dev`).

Environment variables:

- **`PORT`** (default `3000`) and **`HOST`** (default `0.0.0.0`).
- **`ORIGIN`**: must be set to the user-facing URL (e.g. `https://app.example.com`). Without it, SvelteKit's CSRF defence will reject form POSTs because it can't determine the canonical origin. Alternatively use `PROTOCOL_HEADER=x-forwarded-proto` and `HOST_HEADER=x-forwarded-host` if you sit behind a reverse proxy that sets them.
- **`BODY_SIZE_LIMIT`** (default `512K`) — raise for file uploads. `Infinity` to disable.
- **`SOCKET_PATH`** to listen on a Unix socket instead of TCP.

`.env` files are **not** auto-loaded in production. Use `node --env-file=.env build` (Node ≥ 20.6) or a process manager that injects env (systemd, Docker, Kubernetes secrets).

For compression: do it at the proxy (NGINX, Caddy, ALB), not in Node. If you must compress in Node, use `@polka/compression` because the popular `compression` package doesn't support streamed responses.

### 13.3 Behind a reverse proxy

Single-process Node is the bottleneck. The proxy handles:

- TLS termination.
- HTTP/2 (Vite ships many small chunks; HTTP/2 multiplexing matters).
- Compression.
- Static asset caching (`build/client/_app/immutable/*` is content-hashed and safe to cache forever).
- Rate limiting.

### 13.4 Containerisation

```dockerfile
# Stage 1: build
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: runtime
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/build ./build
COPY --from=build /app/package*.json ./
RUN npm ci --omit=dev
EXPOSE 3000
CMD ["node", "build"]
```

Set `ENV ORIGIN=https://your.app.example.com` (or pass it through Compose / Helm / etc.) so CSRF works.

**References**

- <https://svelte.dev/docs/kit/adapters>
- <https://svelte.dev/docs/kit/adapter-node>

---

## 14. Other primitives worth knowing

### 14.1 Snapshots

Ephemeral UI state (textarea contents, scroll positions of a sidebar, expanded state of a collapsible) is lost on navigation. Export a `snapshot` from `+page.svelte` to persist it across history navigation:

```svelte
<script>
  let comment = $state('');
  export const snapshot = {
    capture: () => comment,
    restore: (v) => comment = v
  };
</script>
```

Returned values are JSON-serialised into `sessionStorage`. Don't capture huge objects.

### 14.2 Shallow routing

`pushState` / `replaceState` from `$app/navigation` push a history entry **without triggering a full navigation**. Pair with `page.state` (typed via `App.PageState`) for things like a modal whose "open" state is in the URL but doesn't reload the page. Useful, niche.

### 14.3 Service workers

`src/service-worker.ts` is auto-registered. Cache `build` (immutable hashed files) eagerly; cache other things on demand with a network-first strategy. Don't cache HTML aggressively unless you have a versioning story — staleness is worse than a network round-trip.

### 14.4 Server-sent events / streaming responses

Return a `Response` whose body is a `ReadableStream` from a `+server.ts` handler:

```ts
export const GET: RequestHandler = () => {
  const stream = new ReadableStream({
    start(controller) {
      const enc = new TextEncoder();
      const send = (data: unknown) =>
        controller.enqueue(enc.encode(`data: ${JSON.stringify(data)}\n\n`));
      const t = setInterval(() => send({ at: Date.now() }), 1000);
      return () => clearInterval(t);
    }
  });
  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    }
  });
};
```

Caveats: `adapter-node` works; serverless adapters that buffer responses (some Lambda configs) do not.

### 14.5 Remote functions (2.24+)

Type-safe RPC-style functions you call from components. Useful for live data that doesn't fit cleanly into a `load`. Still relatively new; the rebuild defaults to `load` + form actions until a clear win emerges. If you reach for this, document why.

**References**

- <https://svelte.dev/docs/kit/snapshots>
- <https://svelte.dev/docs/kit/shallow-routing>
- <https://svelte.dev/docs/kit/service-workers>

---

## 15. Common anti-patterns (the consolidated "DON'T" list)

1. **`let foo = ...` at module scope on the server.** Per-request data goes on `event.locals`. Per-render shared data goes through context.
2. **`fetch` from inside a Svelte component on mount when a `load` would do.** `load` runs during SSR and is replayed in the browser; `onMount` runs only after hydration and forces a second round trip.
3. **Side-effects in `load`** (writing to a shared store, mutating module state). `load` returns data; the component decides what to do with it.
4. **`throw redirect(...)` or `throw error(...)`.** SvelteKit 2 doesn't want the `throw`; just call them.
5. **`try/catch` around `redirect()` or `error()`.** They throw control-flow exceptions that SvelteKit catches; your catch will swallow them.
6. **Forgetting `path` on `cookies.set/delete`.** SvelteKit 2 requires it; almost always `path: '/'`.
7. **Putting auth checks only in `+layout.server.ts`** without forcing children to `await parent()`. Layout `load`s are cached across navigations; child page loads run in parallel. A layout-only auth check is not a guarantee.
8. **Putting auth checks in `hooks.server.ts` for everything** when you have many public routes. Use `handle` for cross-cutting concerns and route-local checks for everything else.
9. **Universal `load` for backend calls in an authed app.** Server `load` is closer to the data, ships zero source to the browser, and avoids leaking your internal API URLs.
10. **`+server.ts` POST handlers as your default mutation primitive.** Form actions progressively enhance, get cookies for free, and integrate with `use:enhance`. Use `+server.ts` only when you genuinely need an API.
11. **`use:enhance` on a form posting to a `+server.ts` endpoint** — it doesn't work; SvelteKit will throw.
12. **`<input type="file">` without `enctype="multipart/form-data"`** — non-JS submissions silently lose the file; SvelteKit 2 throws on enhanced submits.
13. **Manufactured serial waits.** `await getA(); await getB();` when neither depends on the other should be `Promise.all`.
14. **`url.searchParams` in a prerendered page's `load`.** Forbidden — prerender means same HTML for every request, regardless of query.
15. **`$env/dynamic/*` in a prerendered page.** Hard error in SvelteKit 2 (was a silent stale-bake bug in 1.x).
16. **`csr = false` on the root layout.** Turns the whole app into a JS-free experience by accident; almost never what you want.
17. **`ssr = false` on the root layout** to "go SPA". Costs you SEO, first paint, JS-disabled fallback. Only do this if you've evaluated the trade and it's right for your specific use case.
18. **Using `$app/stores` in new code.** Deprecated since 2.12. Use `$app/state` (it's reactive, not a store, and works with runes).
19. **`goto()` to an external URL.** Banned in SvelteKit 2; use `window.location.href = url`.
20. **`invalidateAll()` after every mutation.** Reruns every `load`, including the layout's. Use `invalidate('app:specific-thing')` with `depends('app:specific-thing')` in the affected `load`.
21. **`$app/navigation` `goto` for a redirect from a `load` or action.** Use `redirect(303, url)` from `@sveltejs/kit` instead — `goto` only works in the browser.
22. **Reading cookies from `document.cookie`.** They're `httpOnly` for a reason. Read on the server in `load` / `handle`, return what the client needs through `data`.
23. **Long-lived `$effect` running fetches.** Effects re-run on every dep change; you'll spam your backend. Use `load` + `invalidate` / `depends` for data that needs to change with the route.

---

## 16. The agent checklist before opening a frontend PR

Run through this before you put your name on a SvelteKit change.

1. **Routing** — every new route file is `+page.svelte` / `+page.server.ts` / `+server.ts` / `+layout(.server).ts`. Helpers and components live next to the route or in `$lib`.
2. **Data flow** — `load` reads, action writes, `+server.ts` only when there's no form. No data fetched in `onMount` if a `load` could do it.
3. **Server only what must be server** — `$lib/server/` for anything sensitive, `*.server.ts` for files that import secrets. No accidental cross-imports.
4. **Auth** — `event.locals.user` is populated in `handle`, returned by the root `+layout.server.ts`, and re-checked in any sensitive `+page.server.ts`. Cookies have `path: '/'` and `httpOnly: true`.
5. **Errors** — expected errors use `error(status, ...)`, unexpected errors are logged in `handleError`. No `try/catch` around `redirect()` or `error()`. `App.Error` shape is up to date if you added fields.
6. **State** — no module-level `let` that holds per-user state on the server. Cross-component request-scoped state goes through context. `page.data` for things from `load`, URL for filters/sort.
7. **Forms** — `method="POST"`, `enctype="multipart/form-data"` if file inputs, `use:enhance`, `fail(status, data)` for validation errors with non-secret data, `redirect(303, ...)` on success.
8. **Performance** — independent fetches in `load` use `Promise.all`. Streaming used for slow non-essential data. `data-sveltekit-preload-data` left as default unless you have a reason.
9. **Page options** — `prerender = true` only where every visitor sees the same HTML; `ssr = false` only with a reason; `csr = false` only on truly static pages.
10. **Tests** — unit tests for pure helpers, component tests in `vitest-browser-svelte` for components with logic, Playwright for the user journey you just touched.
11. **Migration awareness** — no SvelteKit 1 idioms (`throw error()`, `throw redirect()`, top-level promise auto-await, cookies without `path`, `goto` to external URL, `$app/stores` in new code).
12. **`$lib/server/` boundary** — try to import a server-only module from a `.svelte` file; it should fail at build. If it succeeds, your boundary is broken.

---

## 17. References (consolidated)

Official SvelteKit docs (2.x):

- Introduction & glossary — <https://svelte.dev/docs/kit/introduction>
- Routing — <https://svelte.dev/docs/kit/routing>
- Advanced routing — <https://svelte.dev/docs/kit/advanced-routing>
- Loading data — <https://svelte.dev/docs/kit/load>
- Form actions — <https://svelte.dev/docs/kit/form-actions>
- Page options — <https://svelte.dev/docs/kit/page-options>
- State management — <https://svelte.dev/docs/kit/state-management>
- Hooks — <https://svelte.dev/docs/kit/hooks>
- Errors — <https://svelte.dev/docs/kit/errors>
- Auth — <https://svelte.dev/docs/kit/auth>
- Performance — <https://svelte.dev/docs/kit/performance>
- Link options — <https://svelte.dev/docs/kit/link-options>
- Images — <https://svelte.dev/docs/kit/images>
- Service workers — <https://svelte.dev/docs/kit/service-workers>
- Snapshots — <https://svelte.dev/docs/kit/snapshots>
- Single-page apps — <https://svelte.dev/docs/kit/single-page-apps>
- Server-only modules — <https://svelte.dev/docs/kit/server-only-modules>
- `$env/static/private` — <https://svelte.dev/docs/kit/$env-static-private>
- `$env/dynamic/private` — <https://svelte.dev/docs/kit/$env-dynamic-private>
- `$app/state` — <https://svelte.dev/docs/kit/$app-state>
- `$app/navigation` — <https://svelte.dev/docs/kit/$app-navigation>
- `$app/forms` — <https://svelte.dev/docs/kit/$app-forms>
- `$app/server` — <https://svelte.dev/docs/kit/$app-server>
- `$lib` — <https://svelte.dev/docs/kit/$lib>
- Types — <https://svelte.dev/docs/kit/types>
- Adapters overview — <https://svelte.dev/docs/kit/adapters>
- `adapter-node` — <https://svelte.dev/docs/kit/adapter-node>
- `adapter-static` — <https://svelte.dev/docs/kit/adapter-static>
- Migrating to SvelteKit 2 — <https://svelte.dev/docs/kit/migrating-to-sveltekit-2>

Selected community references:

- Mainmatter — Runes and global state do's and don'ts: <https://mainmatter.com/blog/2025/02/01/global-state-in-svelte-5/>
- Lucia auth guide: <https://lucia-auth.com/>
- Better Auth (SvelteKit integration): <https://www.better-auth.com/docs/integrations/svelte-kit>
- Superforms (when forms get complex): <https://superforms.rocks/>
- Vitest browser mode: <https://vitest.dev/guide/browser/>
- vitest-browser-svelte migration: <https://scottspence.com/posts/testing-with-vitest-browser-svelte-guide>
