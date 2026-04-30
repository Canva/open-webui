/**
 * Ambient module declarations for untyped third-party imports.
 *
 * This file deliberately has no top-level `import` / `export` so the
 * TypeScript compiler treats it as a script (ambient) file rather than
 * an external module. `declare module 'name'` only registers the module
 * globally when the containing file is ambient; in a module file it is
 * read as an internal augmentation and the declarations don't escape.
 *
 * `app.d.ts` has top-level imports (it pulls in `User`, `ThemeId`, etc.
 * for the SvelteKit `App` interface bodies) and so cannot host these.
 */

declare module 'katex/contrib/mhchem';
declare module 'katex/dist/katex.min.css';
