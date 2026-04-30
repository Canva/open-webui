# Svelte 5 Best Practises

> **Audience:** every agent (and every human) writing Svelte components, `.svelte.ts` modules, or SvelteKit routes for the rebuild. This is the canonical "do / don't" list for the frontend.
> **Scope:** Svelte **5** only — the runes-based version. Where Svelte 4 patterns are mentioned it is to call them out as **wrong** for new code.
> **Bias:** simplicity over cleverness. Where Svelte 5 gives you three ways to do something, the section recommends the one to reach for first and explains when (rarely) to break the rule.
> **Source of truth:** when this file conflicts with [`svelte.dev/docs/svelte`](https://svelte.dev/docs/svelte), the official docs win and this file should be patched.

---

## 0. The five rules you must internalise

If you only remember five things from this document:

1. **`let` is not reactive any more — use `$state(...)`.** Top-level `let` in a `.svelte` file is just a normal variable in Svelte 5.
2. **`$derived` is for values, `$effect` is for side effects.** If you find yourself writing `$effect(() => { x = ... })`, you wanted `$derived` and you have a bug. Effects are an _escape hatch_.
3. **Props are read-only. Don't mutate them.** If you need two-way data flow, use `$bindable` (sparingly) or a callback prop.
4. **No more `createEventDispatcher`, no more `slot`, no more `on:click`.** Use callback props (`onclick`), `$props`, and `{#snippet}` / `{@render}`.
5. **Module-level `$state` is a footgun on the server.** For shared state, prefer `setContext` / `getContext` (or `createContext`) over a global `.svelte.ts` module — it scopes per request and survives SSR.

Each of those is expanded below.

---

## 1. Runes — the whole API at a glance

| Rune                 | What it does                                                                                          | Reach-for-it when                                                                                  |
| -------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `$state(v)`          | Reactive variable. Objects/arrays become deep proxies.                                                | Anything that changes over time and the UI should react to.                                        |
| `$state.raw(v)`      | Non-proxied state. Mutations don't track; only reassignment does.                                     | Large objects/arrays you replace wholesale (API responses, big lists you re-fetch).                |
| `$state.snapshot(v)` | Frozen plain-JS clone of a proxy.                                                                     | Passing reactive state to non-Svelte code (`structuredClone`, `JSON.stringify`, third-party libs). |
| `$derived(expr)`     | Read-only-by-default value computed from other reactive values.                                       | Any value that is a pure function of other state. **This is the default tool**, not `$effect`.     |
| `$derived.by(fn)`    | Same, but with a function body for multi-line derivations.                                            | When the expression is too complex for a single line.                                              |
| `$effect(fn)`        | Run side-effects after the DOM updates; auto-tracks dependencies; auto-cleanup on teardown.           | DOM imperatively, third-party widgets, analytics, network calls fired _because_ state changed.     |
| `$effect.pre(fn)`    | Same as `$effect` but runs **before** DOM updates.                                                    | You need to read DOM measurements before Svelte mutates them (e.g. autoscroll-on-message).         |
| `$effect.root(fn)`   | Standalone effect scope outside a component lifecycle. Returns a `cleanup` fn you must call yourself. | Tests; one-off setup outside any component.                                                        |
| `$props()`           | Declare component props.                                                                              | Always, in every component that takes input.                                                       |
| `$props.id()`        | Stable per-instance ID, identical on server and client.                                               | `for` / `aria-labelledby` / `aria-describedby` linking inside a component.                         |
| `$bindable(v?)`      | Mark a prop as `bind:`-able from the parent.                                                          | Form-control wrappers (`<FancyInput bind:value>`). **Use sparingly.**                              |
| `$inspect(...)`      | Dev-only deep-reactive `console.log` that re-fires on change.                                         | Debugging only — no-ops in production builds.                                                      |
| `$inspect.trace()`   | Inside an effect or derived: log which dependency caused the latest run.                              | Debugging "why is this rerunning" mysteries.                                                       |
| `$host()`            | Reference to the host element of a Svelte custom element.                                             | Custom-element components only.                                                                    |

**Rule of thumb:** you will use `$state`, `$derived`, and `$props` constantly. `$effect` should appear maybe once every few hundred lines. Everything else is rare.

Sources: [`$state`](https://svelte.dev/docs/svelte/$state), [`$derived`](https://svelte.dev/docs/svelte/$derived), [`$effect`](https://svelte.dev/docs/svelte/$effect), [`$props`](https://svelte.dev/docs/svelte/$props), [`$bindable`](https://svelte.dev/docs/svelte/$bindable), [`$inspect`](https://svelte.dev/docs/svelte/$inspect), [`$host`](https://svelte.dev/docs/svelte/$host), [Best practices](https://svelte.dev/docs/svelte/best-practices).

---

## 2. `$state` — reactive state

### 2.1 Defaults

```svelte
<script>
  let count = $state(0);
  let user = $state({ name: 'Ada', prefs: { theme: 'dark' } });
  let todos = $state([{ text: 'ship it', done: false }]);
</script>
```

- **Primitives** are reactive variables. Read and write them like any normal variable (`count++`).
- **Objects and arrays** are wrapped in a deep `Proxy`. Mutations like `todos.push(...)`, `user.prefs.theme = 'light'`, or `todos[0].done = true` _all_ trigger updates.
- **Class instances** are _not_ proxied — see §2.4.

### 2.2 `$state.raw` — when to opt out of deep reactivity

Use `$state.raw` when you have a large object/array that you only ever **replace wholesale**, not mutate.

```svelte
<script>
  let apiResponse = $state.raw(null);

  async function refresh() {
    apiResponse = await fetch('/api/big').then((r) => r.json());
  }
</script>
```

Rule:

- Mutating raw state is a no-op. `apiResponse.foo = 1` will not update the UI.
- Reach for `$state.raw` for: API payloads you replace, lists with thousands of items you re-fetch, pre-baked tables, anything where deep proxying would cost more than the reactivity is worth.

Source: [`$state` — `$state.raw`](https://svelte.dev/docs/svelte/$state#$state.raw).

### 2.3 `$state.snapshot` — escape hatch for non-Svelte code

When you hand reactive state to something that doesn't expect a `Proxy` (`structuredClone`, `postMessage`, `IndexedDB`, a chart library that hates proxies):

```svelte
const plain = $state.snapshot(user); worker.postMessage(plain);
```

### 2.4 Classes with `$state` fields

`$state` works inside class fields. The compiler turns them into `get`/`set` accessors on the prototype, backed by private signals.

```ts
// counter.svelte.ts
export class Counter {
  count = $state(0);
  doubled = $derived(this.count * 2);

  increment = () => {
    this.count += 1;
  }; // arrow → safe to pass as event handler
  reset() {
    this.count = 0;
  } // method → caller must preserve `this`
}
```

- Class instances are **not** auto-proxied; the field-level `$state` is what makes them reactive.
- Use **arrow-function class fields** for any method you intend to pass as an event handler (`onclick={c.increment}`). A regular method loses `this` when detached.
- This is the recommended way to package "state + behaviour + derived values" together — much better than a tangle of stores or a bare object.

Source: [`$state` — Classes](https://svelte.dev/docs/svelte/$state#Classes).

### 2.5 Sharing state across files

You **cannot directly export and reassign** a primitive `$state` from a `.svelte.ts` file — the compiler rewrites reads/writes per-file, so other modules see the raw signal. Two patterns work:

```ts
// ✅ Pattern A — export an object whose properties you mutate
export const ui = $state({ sidebarOpen: true, theme: 'dark' });

// ✅ Pattern B — keep the variable private, expose getter/setter
let count = $state(0);
export function getCount() {
  return count;
}
export function increment() {
  count += 1;
}

// ❌ Silently breaks — count is exported as the underlying signal object
let count = $state(0);
export { count };
```

For non-trivial shared state, prefer a class (§2.4) over either. **Do not put per-user data in module-level `$state` in an SSR app** — the module is shared across requests; data will leak. Use context (§6.2) instead.

Sources: [Passing state across modules](https://svelte.dev/docs/svelte/$state#Passing-state-across-modules), [Replacing global state](https://svelte.dev/docs/svelte/context#Replacing-global-state).

### 2.6 Destructuring kills reactivity

```svelte
let {name} = user; // ❌ snapshot at this moment, no longer reactive let name = $derived(user.name); //
✅ stays in sync
```

Same applies to function arguments — JavaScript is pass-by-value, so a function that takes `count` gets the value at call time, not a live binding. Wrap in a getter or pass the parent object if the function needs a live read.

---

## 3. `$derived` vs `$effect` — the most important section in this file

> **If you remember nothing else: `$derived` is for _values_, `$effect` is for _side effects_. Reach for `$derived` first. Always.**

### 3.1 Use `$derived` for everything you can

```svelte
<script>
  let count = $state(0);

  // ✅ Right
  let doubled = $derived(count * 2);
  let large = $derived(count > 10);

  // ✅ Multi-line: $derived.by
  let stats = $derived.by(() => {
    const xs = items.map((i) => i.price);
    return { min: Math.min(...xs), max: Math.max(...xs) };
  });
</script>
```

Properties of `$derived`:

- **Lazy and cached.** Recomputed only when read after a dependency changed.
- **Push-pull.** Dependents are notified eagerly that the value is dirty; the recomputation only runs when something actually reads it.
- **Referentially-equal short-circuit.** If the new value `===` the old value, downstream effects/derived don't re-run.
- **Writable.** Since 5.25 you can `like += 1` an optimistic-UI pattern; the next dependency change re-derives back to the source of truth.

### 3.2 The `$effect` anti-patterns

The single biggest Svelte 5 mistake is reaching for `$effect` to do something `$derived` can do. Replace each of these on sight:

```svelte
<!-- ❌ Setting derived state in an effect -->
let doubled = $state();
$effect(() => { doubled = count * 2; });

<!-- ✅ -->
let doubled = $derived(count * 2);
```

```svelte
<!-- ❌ Linking two inputs with two effects → ping-pong loop -->
let spent = $state(0), left = $state(100);
$effect(() => { left = 100 - spent; });
$effect(() => { spent = 100 - left; });

<!-- ✅ One source of truth + a function binding -->
let spent = $state(0);
let left  = $derived(100 - spent);
function setLeft(v) { spent = 100 - v; }
// <input bind:value={() => left, setLeft} />
```

```svelte
<!-- ❌ $effect to react to a click -->
$effect(() => { if (clicked) doThing(); });

<!-- ✅ Just call it from the handler -->
<button onclick={doThing}>do it</button>
```

```svelte
<!-- ❌ console.log in $effect for debugging -->
$effect(() => console.log(count));

<!-- ✅ -->
$inspect(count);
```

### 3.3 The (small) list of legitimate `$effect` uses

You _should_ reach for `$effect` for:

1. **Imperative DOM work** Svelte can't express declaratively (canvas drawing, manual focus management, IntersectionObserver wiring).
2. **Synchronising with a third-party library** that owns its own DOM (D3, MapLibre, Monaco, ChartJS) — and even then, prefer `{@attach ...}` (see §10).
3. **Network calls fired _because_ state changed** (search-as-you-type, but debounce!).
4. **Non-DOM browser APIs** that need reactive input (WebSocket subscriptions, `localStorage` writes).
5. **Logging / analytics** that must observe state.

Even then, prefer `createSubscriber` (from `svelte/reactivity`) for "external thing → reactive value" wiring; it deduplicates subscriptions across multiple readers.

### 3.4 Effect lifecycle and cleanup

```svelte
<script>
  let ms = $state(1000);
  let count = $state(0);

  $effect(() => {
    const id = setInterval(() => count++, ms);
    return () => clearInterval(id); // runs before each re-run AND on unmount
  });
</script>
```

- **Dependencies are tracked synchronously inside the effect body.** Anything read after an `await` or inside a `setTimeout` is _not_ tracked.
- An effect that reads an object `state` does _not_ re-run when `state.value` changes — it re-runs only if `state` itself is reassigned.
- Effects do **not** run on the server. **Never** wrap effect contents in `if (browser) { ... }` — it's always client-only by design.

### 3.5 Avoiding infinite loops

If you must read and write the same state inside an effect, wrap the _entire write operation_ in `untrack`:

```svelte
import { untrack } from 'svelte';

$effect(() => {
  // re-runs when items.length changes, but the writes inside don't re-trigger us
  untrack(() => {
    items.push({ id: nextId() });
  });
});
```

`untrack` operates on _executed code_, not on the variable name — `untrack(() => arr).push(x)` does **not** work, because `.push` itself reads `length`. Wrap the whole call.

Sources: [`$effect`](https://svelte.dev/docs/svelte/$effect), [Best practices — `$effect`](https://svelte.dev/docs/svelte/best-practices#$effect).

---

## 4. `$props` — component inputs

### 4.1 The 95% case

```svelte
<script lang="ts">
  interface Props {
    title: string;
    count?: number;
    onsave: (value: string) => void;
    children: import('svelte').Snippet;
  }

  let { title, count = 0, onsave, children }: Props = $props();
</script>
```

Pattern rules:

- **Always destructure** unless you genuinely need the whole object (e.g. forwarding via spread).
- **Always type props** with an `interface Props` annotation, not `$props<Props>()`. Generic syntax on `$props()` is deliberately not supported.
- **Default values via destructuring**: `let { count = 0 } = $props();`.

### 4.2 Renaming and rest

```svelte
<script>
  // Reserved word rename
  let { class: klass, ...rest } = $props();
</script>

<button class={klass} {...rest}>...</button>
```

### 4.3 Stable per-instance IDs

```svelte
<script>
  const uid = $props.id();
</script>

<label for="{uid}-name">Name</label>
<input id="{uid}-name" />
```

`$props.id()` is SSR-stable, so it doesn't cause hydration mismatches. Use it for any element pair that needs `for` / `aria-*` linkage.

### 4.4 **Don't mutate props**

```svelte
<!-- ❌ -->
<script>
  let { object } = $props();
  // mutates parent's state with a runtime warning, AND breaks data-flow reasoning
  object.count += 1;
</script>

<!-- ✅ Communicate change via a callback -->
<script>
  let { object, onchange } = $props();
  onchange(object.count + 1);
</script>
```

If you genuinely need two-way binding (form control wrappers), use `$bindable` — see §5.

### 4.5 Always derive from props

```svelte
<script>
  let { type } = $props();

  // ✅ updates if `type` changes
  let color = $derived(type === 'danger' ? 'red' : 'green');

  // ❌ frozen at first render
  let color = type === 'danger' ? 'red' : 'green';
</script>
```

Treat every prop as if it might change next tick. If the value depends on a prop, it must be `$derived`.

Source: [`$props`](https://svelte.dev/docs/svelte/$props).

---

## 5. `$bindable` — when (rarely) you need two-way

Two-way binding is the exception, not the rule. The default is **props down, callbacks up**. Use `$bindable` only when:

- You're building a form-control wrapper (`<FancyInput bind:value>`).
- You're building a controlled-but-stateful child (`<Modal bind:open>`).

```svelte
<!-- FancyInput.svelte -->
<script>
  let { value = $bindable(''), ...rest } = $props();
</script>

<input bind:value {...rest} />
```

Parents may, but don't have to, bind:

```svelte
<FancyInput bind:value={message} />
<!-- two-way -->
<FancyInput value={initial} />
<!-- one-way; child can override locally -->
```

Don't reach for `$bindable` because it "feels easier" than threading a callback. Two-way bindings are harder to reason about; use them where the alternative is clearly worse.

Source: [`$bindable`](https://svelte.dev/docs/svelte/$bindable).

---

## 6. Component structure & file organisation

### 6.1 File layout

- **`Foo.svelte`** — presentational and stateful UI components.
- **`foo.svelte.ts`** / **`foo.svelte.js`** — modules that use runes (state, derived, classes). The `.svelte.` infix is _required_ for the compiler to recognise the runes.
- **`foo.ts`** — pure utilities, types, constants. No runes.
- **Per-route**: SvelteKit `+page.svelte`, `+page.ts`, `+layout.svelte`, etc.

Within a `.svelte` file, the conventional order:

```svelte
<script module lang="ts">
  // module-scoped exports, types, constants
</script>

<script lang="ts">
  // 1. imports
  // 2. props
  // 3. state
  // 4. derived
  // 5. functions / handlers
  // 6. effects (last — they should be the smallest section)
</script>

<!-- markup -->

<style>
  /* scoped styles */
</style>
```

### 6.2 Shared state — pick the right scope

Three options, in order of preference for **per-page / per-feature** state:

1. **Component-local `$state`.** Default. Use until you can't.
2. **Class in a `.svelte.ts` module + `setContext` at the nearest common ancestor.** Per-tree, per-request — SSR-safe.
3. **Module-level `$state` exported from a `.svelte.ts`.** Truly app-global, **client-only** state (e.g. theme that persists in `localStorage`). **Never store user/session data here in an SSR app.**

```ts
// stores/cart.svelte.ts
import { createContext } from 'svelte';

export class Cart {
  items = $state<Item[]>([]);
  total = $derived(this.items.reduce((s, i) => s + i.price, 0));

  add = (item: Item) => {
    this.items.push(item);
  };
  clear = () => {
    this.items = [];
  };
}

export const [getCart, setCart] = createContext<Cart>();
```

```svelte
<!-- routes/+layout.svelte -->
<script lang="ts">
  import { Cart, setCart } from '$lib/stores/cart.svelte';
  setCart(new Cart());
  let { children } = $props();
</script>

{@render children()}
```

```svelte
<!-- somewhere deep -->
<script lang="ts">
  import { getCart } from '$lib/stores/cart.svelte';
  const cart = getCart();
</script>

<button onclick={() => cart.add(item)}>Add</button><p>Total: {cart.total}</p>
```

**Rules for context state:**

- **Mutate, don't reassign.** `cart.items = [...]` inside a child works; `cart = newCart` from a child silently breaks the link with the parent's reference. Svelte will warn if you do this wrong.
- Use `createContext` (added 5.40) over raw `setContext` / `getContext` — it gives you typed, key-free `[get, set]` pair.

Sources: [Context](https://svelte.dev/docs/svelte/context), [Best practices — Context](https://svelte.dev/docs/svelte/best-practices#Context).

---

## 7. Events and callbacks

### 7.1 DOM events — they're just attributes now

```svelte
<!-- ✅ -->
<button onclick={handleClick}>click</button>
<button onclick={() => count++}>inc</button>

<!-- ❌ Svelte 4 -->
<button on:click={handleClick}>click</button>
```

- Event handler attributes are lowercase, no colon: `onclick`, `oninput`, `onkeydown`.
- The shorthand `<button {onclick}>` works.
- Spread-able: `<button {...props} />` will spread event handlers too.
- For capture-phase, append `capture`: `<button onclickcapture={...}>`.

### 7.2 Event modifiers — gone

`on:click|preventDefault|once={...}` is gone. Inline the equivalent:

```svelte
<!-- ✅ -->
<form
  onsubmit={(e) => {
    e.preventDefault();
    doSubmit();
  }}
>
  ...
</form>
```

For `passive`, you need an action (or now an `{@attach ...}`) — they're a binding-time concern, not a handler one.

### 7.3 Component "events" — use callback props

`createEventDispatcher` is **deprecated**. Pass callbacks as props.

```svelte
<!-- ❌ Svelte 4 -->
<script>
  import { createEventDispatcher } from 'svelte';
  const dispatch = createEventDispatcher();
</script>
<button on:click={() => dispatch('save', { id })}>save</button>

<!-- ✅ Svelte 5 -->
<script>
  let { onsave } = $props();
</script>
<button onclick={() => onsave({ id })}>save</button>
```

Conventions:

- **Name handlers `onfoo`** (lowercase, no separator) so they look like DOM event attributes.
- **Pass plain values, not `CustomEvent`s.** No more `event.detail` round-tripping.
- **Mark required** by typing the prop as `(arg: T) => void` (no `?`); optional callbacks get `?` and are called as `onsave?.(payload)`.

### 7.4 Window / document listeners

Use `<svelte:window>` and `<svelte:document>`. Don't use `onMount` to attach listeners by hand — `<svelte:window>` is automatically removed when the component unmounts.

```svelte
<svelte:window onkeydown={handleKey} />
<svelte:document onvisibilitychange={handleVis} />
```

Sources: [Migration guide — Event changes](https://svelte.dev/docs/svelte/v5-migration-guide#Event-changes), [Best practices — Events](https://svelte.dev/docs/svelte/best-practices#Events).

---

## 8. Snippets — slots are dead

`<slot>` and `<slot name="...">` are deprecated. Use `{#snippet}` and `{@render}`.

### 8.1 The `children` prop

The implicit "default slot" is now a normal prop called `children`:

```svelte
<!-- Button.svelte -->
<script>
  let { children, ...rest } = $props();
</script>
<button {...rest}>{@render children?.()}</button>

<!-- caller -->
<Button onclick={...}>Click me</Button>
```

- Use `children?.()` (optional chaining) when content is optional.
- **Never name a prop `children` if you also accept content** — it overlaps.

### 8.2 Named slots → named snippet props

```svelte
<!-- Card.svelte -->
<script>
  let { header, footer, children } = $props();
</script>

<article>
  <header>{@render header?.()}</header>
  <div>{@render children()}</div>
  <footer>{@render footer?.()}</footer>
</article>

<!-- caller -->
<Card>
  {#snippet header()}<h1>Title</h1>{/snippet}
  Body content goes here (this becomes `children`).
  {#snippet footer()}<small>—fin</small>{/snippet}
</Card>
```

### 8.3 Snippets with parameters (the old `let:` directive)

```svelte
<!-- List.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  interface Props<T> {
    items: T[];
    row: Snippet<[T]>;
    empty?: Snippet;
  }
  let { items, row, empty }: Props<unknown> = $props();
</script>

{#if items.length}
  <ul>
    {#each items as item (item.id)}<li>{@render row(item)}</li>{/each}
  </ul>
{:else}
  {@render empty?.()}
{/if}

<!-- caller -->
<List items={users}>
  {#snippet row(user)}
    <span>{user.name}</span>
  {/snippet}
  {#snippet empty()}
    <em>No users</em>
  {/snippet}
</List>
```

### 8.4 Reuse within a component

Snippets DRY up repeated markup _inside_ a single component — defining once and `{@render}`ing in multiple places — without needing a separate file.

### 8.5 Typing snippets

```ts
import type { Snippet } from 'svelte';

interface Props {
  children: Snippet; // no params
  row: Snippet<[Item]>; // one param
  cell: Snippet<[Item, number]>; // multiple params
}
```

Use `<script lang="ts" generics="T">` for components that need a generic snippet:

```svelte
<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  let { items, row }: { items: T[]; row: Snippet<[T]> } = $props();
</script>
```

Sources: [Snippets](https://svelte.dev/docs/svelte/snippet), [Migration guide — Snippets instead of slots](https://svelte.dev/docs/svelte/v5-migration-guide#Snippets-instead-of-slots).

---

## 9. Reactive collections — `svelte/reactivity`

Plain `new Map()` and `new Set()` are **not** reactive — Svelte can't proxy a Map's internals. Use the wrappers from `svelte/reactivity`:

```svelte
<script>
  import {
    SvelteMap,
    SvelteSet,
    SvelteDate,
    SvelteURL,
    SvelteURLSearchParams,
    MediaQuery,
  } from 'svelte/reactivity';

  const board = new SvelteMap(); // reactive Map
  const tags = new SvelteSet(); // reactive Set
  const now = new SvelteDate(); // re-reads in $derived/$effect on update
  const url = new SvelteURL(location); // reactive URL with reactive .searchParams
  const isWide = new MediaQuery('min-width: 800px'); // .current is reactive
</script>
```

Notes:

- `SvelteMap` / `SvelteSet` track `.has`, `.get`, `.size`, iteration, etc. **Their values are not deeply reactive**, only the collection's structure is.
- `MediaQuery.current` is the bool you read in templates; it updates when the query matches.
- Building your own external-to-reactive bridge? Use `createSubscriber` from `svelte/reactivity` — it deduplicates, handles teardown, and works with multiple consumers.

Source: [`svelte/reactivity`](https://svelte.dev/docs/svelte/svelte-reactivity).

---

## 10. Attachments — the modern `use:action`

Actions (`use:tooltip={content}`) are deprecated in favour of **attachments** (`{@attach tooltip(content)}`), available since **Svelte 5.29**.

```svelte
<script lang="ts">
  import type { Attachment } from 'svelte/attachments';
  import tippy from 'tippy.js';

  let content = $state('Hello');

  function tooltip(text: string): Attachment {
    return (element) => {
      const tip = tippy(element, { content: text });
      return tip.destroy; // cleanup on re-run / unmount
    };
  }
</script>

<input bind:value={content} />
<button {@attach tooltip(content)}>Hover me</button>
```

Why attachments, not actions:

- **Reactive parameters** — re-run automatically when `content` changes (actions needed an `update` callback).
- Can be **inline**, **factories**, or **conditional** (`{@attach enabled && fn}`).
- Work on **components** too (when the component spreads props onto an element).
- Multiple attachments per element are fine.

Need to wrap a third-party action? `import { fromAction } from 'svelte/attachments'` and `{@attach fromAction(libAction, () => params)}`.

Source: [`{@attach ...}`](https://svelte.dev/docs/svelte/@attach).

---

## 11. Stores — when to still use them

**The honest answer for new code: almost never.** Runes plus classes plus context cover everything stores used to do, with less ceremony and better TypeScript.

You may still reach for `svelte/store` (`writable`, `readable`, `derived`) when:

- You're integrating with **RxJS-style** observables and want the `$store` auto-subscribe ergonomics.
- You're consuming a **library that exposes a store** (SvelteKit's `page`, third-party legacy libraries).
- You need **manual control** over emit timing (e.g. coalescing writes from an event source) that runes can't express cleanly.

The `$store` auto-subscribe sigil still works in Svelte 5; it is the only reason a leading `$` would appear on a non-rune identifier in a component. (Don't name a `$state` variable `$foo` or you'll confuse readers and the compiler.)

For everything else, prefer:

| Was a store…                   | Use instead                                 |
| ------------------------------ | ------------------------------------------- |
| `writable(0)` for a counter    | `$state(0)`                                 |
| `derived(a, ($a) => $a * 2)`   | `$derived(a * 2)`                           |
| Cross-component shared state   | Class + context (§6.2)                      |
| Subscriptions to external APIs | `createSubscriber` (in `svelte/reactivity`) |
| Read-only computed             | `$derived` (it's read-only by default)      |

Source: [Stores — When to use stores](https://svelte.dev/docs/svelte/stores#When-to-use-stores).

---

## 12. Lifecycle and cleanup

Svelte 5 has **two** lifecycle moments: mount and destroy. There is no `beforeUpdate` / `afterUpdate` — those are deprecated and unavailable inside runes-mode components.

| Need                            | Do                                            |
| ------------------------------- | --------------------------------------------- |
| Run code after mount            | `onMount(() => { ... })` _or_ `$effect(...)`  |
| Run code before each DOM update | `$effect.pre(() => { ... })`                  |
| Run code after each DOM update  | `$effect(() => { ... })`                      |
| Cleanup on unmount              | Return a function from the effect / `onMount` |
| Wait until the DOM has updated  | `await tick();`                               |

`onMount`:

- Runs on the client only (not during SSR).
- The teardown return must come from a **synchronous** function. `onMount(async () => ... return cleanup)` won't work — wrap async work inside, or use `$effect`.

`$effect` is generally a better default than `onMount` for new code:

- Auto-tracks dependencies.
- Same teardown semantics.
- Works inside non-component contexts (e.g. inside a class field).

Source: [Lifecycle hooks](https://svelte.dev/docs/svelte/lifecycle-hooks).

---

## 13. TypeScript — the small set of rules

### 13.1 Setup

- **Use `lang="ts"`** on every `<script>`.
- **`tsconfig.json`** must set: `target ≥ ES2015`, `verbatimModuleSyntax: true`, `isolatedModules: true`.
- With Vite/SvelteKit you don't need a script preprocessor for plain TypeScript — `vitePreprocess` only matters if you use TS-specific transforms (enums, decorators).

### 13.2 Typing runes

```ts
let count = $state(0); // inferred number
let user = $state<User | null>(null);
let raw = $state.raw<Item[]>([]); // generic on $state.raw too

let doubled = $derived(count * 2); // inferred

interface Props {
  title: string;
  count?: number;
  onsave: (v: string) => void;
  children: import('svelte').Snippet;
}
let { title, count = 0, onsave, children }: Props = $props();
```

- **Don't** write `$props<Props>()` — generic syntax on `$props()` is not supported. Annotate the destructured target.
- **Do** write `$state<Foo>(initial)` if you need to widen / narrow types.

### 13.3 Generic components

```svelte
<script lang="ts" generics="T extends { id: string }">
  import type { Snippet } from 'svelte';

  interface Props {
    items: T[];
    row: Snippet<[T]>;
    onselect: (item: T) => void;
  }

  let { items, row, onselect }: Props = $props();
</script>
```

Whatever goes in `generics="..."` is what would normally go between `<...>` of a generic function — multiple type parameters, `extends`, defaults, all allowed.

### 13.4 The `Component` type and wrapper-element types

For dynamic components, use `Component<Props>` (Svelte 5's replacement for the Svelte 4 `SvelteComponent` class type), and `ComponentProps<typeof X>` to extract props from a `.svelte` file.

For wrappers around native elements, import the typed interface from `svelte/elements`:

```svelte
<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  let { children, ...rest }: HTMLButtonAttributes = $props();
</script>

<button {...rest}>{@render children?.()}</button>
```

`SvelteHTMLElements['div']` covers any element without a dedicated alias.

Source: [TypeScript](https://svelte.dev/docs/svelte/typescript).

---

## 14. Testing

### 14.1 Logic-only tests with Vitest

For functions, classes, and runes-using `.svelte.ts` modules, prefer plain Vitest. The file extension `.svelte.test.ts` enables runes inside the test:

```ts
// counter.svelte.test.ts
import { test, expect } from 'vitest';
import { Counter } from './counter.svelte';
import { flushSync } from 'svelte';

test('increment', () => {
  const c = new Counter();
  expect(c.count).toBe(0);
  c.increment();
  expect(c.count).toBe(1);
  expect(c.doubled).toBe(2);
});
```

If the code under test uses `$effect`, wrap the body in `$effect.root` (because there's no component running):

```ts
test('logger fires', () => {
  const cleanup = $effect.root(() => {
    let count = $state(0);
    const log = logger(() => count);
    flushSync();
    expect(log).toEqual([0]);
    count = 1;
    flushSync();
    expect(log).toEqual([0, 1]);
  });
  cleanup();
});
```

`flushSync()` synchronously flushes pending reactive updates so assertions can run immediately afterwards.

### 14.2 Component tests

Use Vitest + jsdom with `mount` / `unmount` from `svelte` (or `@testing-library/svelte` for ergonomics). After interacting with the DOM, call `flushSync()` so reactive updates land before assertions. **Bias toward extracting logic into testable classes/functions** rather than mounting components for everything — components should be thin presentational shells.

### 14.3 E2E

Playwright is the default in SvelteKit's `sv create`. Use it for routing, form submission, and integration paths — not for behaviour you could unit-test cheaper.

Source: [Testing](https://svelte.dev/docs/svelte/testing).

---

## 15. Performance considerations

Svelte 5 is fast by default. Things actually worth thinking about:

1. **Use `$state.raw` for big data you only reassign.** Deep-proxying a 10k-row array costs more than the reactivity buys.
2. **Window / paginate large lists.** Render what's visible. Combine `$state.raw` with a derived slice.
3. **Always key `{#each}` blocks** by stable identity: `{#each items as item (item.id)}`. Never use the index.
4. **Use `class` shorthand with arrays/objects**, not the `class:` directive: `class={['btn', isActive && 'active', { disabled: !ok }]}`.
5. **Lean on `$derived`'s referential short-circuit.** `large = $derived(count > 10)` only fires downstream when `large` flips, not on every `count` change.
6. **Avoid `$effect` for cross-state syncing.** Each effect adds setup, teardown, and a per-dep re-run.
7. **Prefer classes over deeply-nested `$state` objects** for many instances — class fields don't pay the per-instance proxy cost.
8. **Don't copy props into `$state`.** Use `$derived` of the prop, or you'll forget to keep them in sync.

Sources: [Best practices](https://svelte.dev/docs/svelte/best-practices), [`$state.raw`](https://svelte.dev/docs/svelte/$state#$state.raw).

---

## 16. Common anti-patterns — the "do not do these" list

In rough order of how often we see them:

1. **`$effect` to set derived state.** Use `$derived`. (See §3.2.)
2. **Two `$effect`s linking two pieces of state** → ping-pong loop. Pick one source of truth and `$derived` the other.
3. **Mutating a prop.** Either it's `$bindable`, or you call a callback prop. Don't silently mutate parent state.
4. **`new Map()` / `new Set()` in reactive code.** Use `SvelteMap` / `SvelteSet` from `svelte/reactivity`.
5. **`onMount(() => addEventListener(...))`.** Use `<svelte:window>` / `<svelte:document>` or `{@attach}`.
6. **`if (browser) { ... }` inside `$effect`.** Effects don't run on the server. Ever.
7. **Module-level `$state` for per-user data in an SSR app.** Leaks across requests. Use `createContext`.
8. **Exporting a primitive `let foo = $state(0)`** from a `.svelte.ts`. It silently breaks. Wrap in an object or expose a getter.
9. **`createEventDispatcher`** → callback props.
10. **`<slot>`** → snippets and `{@render}`.
11. **`use:action={...}`** → `{@attach ...}` (Svelte 5.29+).
12. **`$:` reactive declarations** in a runes-mode component → `$derived` (or `$effect`).
13. **`bind:this={el}` + `$effect`** for DOM work → `{@attach}` (cleanup is automatic, re-runs follow deps).
14. **Storing a `$derived` result in `$state` "for perf".** It's already cached.
15. **Index-based `{#each}` keys.** Always key by stable identity.
16. **`tick()` to "wait for state to update".** State is synchronous; `tick()` waits for the _DOM_.
17. **Class methods used as event handlers without arrow form.** `onclick={obj.method}` loses `this`. Use arrow-class-fields or `() => obj.method()`.

---

## 17. Quick conversion table — Svelte 4 → Svelte 5

| Svelte 4                                  | Svelte 5                                                         |
| ----------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------- |
| `let count = 0;` (top-level, reactive)    | `let count = $state(0);`                                         |
| `$: doubled = count * 2;`                 | `let doubled = $derived(count * 2);`                             |
| `$: { sideEffect(count); }`               | `$effect(() => { sideEffect(count); });`                         |
| `export let foo;`                         | `let { foo } = $props();`                                        |
| `export let foo = 'bar';`                 | `let { foo = 'bar' } = $props();`                                |
| `export { klass as class };`              | `let { class: klass } = $props();`                               |
| `$$props`, `$$restProps`                  | `let props = $props();` / `let { ...rest } = $props();`          |
| `createEventDispatcher` + `dispatch('x')` | callback prop `onx`                                              |
| `on:click={fn}`                           | `onclick={fn}`                                                   |
| `on:click                                 | preventDefault={fn}`                                             | `onclick={(e) => { e.preventDefault(); fn(e); }}` |
| `<slot />`                                | `{@render children?.()}`                                         |
| `<slot name="foo" prop={x} />`            | `{@render foo?.(x)}` + `{#snippet foo(x)}…{/snippet}`            |
| `let:item` on slotted content             | `{#snippet row(item)}…{/snippet}`                                |
| `use:foo={bar}`                           | `{@attach foo(bar)}` (or `{@attach fromAction(foo, () => bar)}`) |
| `new Component({ target, props })`        | `mount(Component, { target, props })`                            |
| `writable(0)`                             | `$state(0)` (and remove `$store` sigils)                         |
| `derived(a, ($a) => $a * 2)`              | `$derived(a * 2)`                                                |
| `beforeUpdate(fn)`                        | `$effect.pre(fn)`                                                |
| `afterUpdate(fn)`                         | `$effect(fn)`                                                    |
| `class:active={isActive}`                 | `class={['btn', isActive && 'active']}`                          |

For automation: run `npx sv migrate svelte-5`. It converts the mechanical things; it **does not** convert `createEventDispatcher` or `beforeUpdate`/`afterUpdate` — those need human judgement.

Source: [Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide).

---

## 18. References

Official:

- [Svelte 5 docs index](https://svelte.dev/docs/svelte/overview)
- [Best practices](https://svelte.dev/docs/svelte/best-practices) ← read this; everything in §0-§5 here is opinionated commentary on it
- [v5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide)
- Runes: [`$state`](https://svelte.dev/docs/svelte/$state) · [`$derived`](https://svelte.dev/docs/svelte/$derived) · [`$effect`](https://svelte.dev/docs/svelte/$effect) · [`$props`](https://svelte.dev/docs/svelte/$props) · [`$bindable`](https://svelte.dev/docs/svelte/$bindable) · [`$inspect`](https://svelte.dev/docs/svelte/$inspect) · [`$host`](https://svelte.dev/docs/svelte/$host)
- Templating: [Snippets](https://svelte.dev/docs/svelte/snippet) · [`{@render}`](https://svelte.dev/docs/svelte/@render) · [`{@attach}`](https://svelte.dev/docs/svelte/@attach)
- Runtime: [Lifecycle hooks](https://svelte.dev/docs/svelte/lifecycle-hooks) · [Context](https://svelte.dev/docs/svelte/context) · [Stores](https://svelte.dev/docs/svelte/stores)
- Modules: [`svelte/reactivity`](https://svelte.dev/docs/svelte/svelte-reactivity) · [`svelte/elements`](https://svelte.dev/docs/svelte/typescript#Typing-wrapper-components)
- Tooling: [TypeScript](https://svelte.dev/docs/svelte/typescript) · [Testing](https://svelte.dev/docs/svelte/testing)

Community write-ups consulted for opinions and anti-patterns:

- "Different ways to share state in Svelte 5" — joyofcode.xyz
- "OOP as State Management: What Svelte 5 Runes Made Obvious" — medium.com/@igortosic
- "Svelte 5 attachments vs actions: complete migration guide" — sveltetalk.com
- "Svelte 5 Patterns" series — fubits.dev
- GitHub discussions: sveltejs/svelte#10193 (when not to use `$effect`), #14697 (effect overhead), #11846 (class proxying)
