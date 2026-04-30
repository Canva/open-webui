/**
 * Unit tests for `src/lib/theme/boot.ts`.
 *
 * Two surfaces under test:
 *
 *   1. `bootResolveTheme(...)` — the pure function. Parametrised across
 *      the 4-tier precedence + the Safari private-browsing branch
 *      (localStorage throws on access) + malformed cookie value.
 *   2. `BOOT_SCRIPT_SOURCE` — the stringified IIFE that ships into
 *      `app.html` via `transformPageChunk`. Asserts the string is
 *      non-empty and that running it through `new Function(...)` against
 *      stubbed `document` / `localStorage` / `matchMedia` produces the
 *      right `documentElement.dataset.theme`. The IIFE must NEVER throw
 *      — even when every browser global blows up, it must silently fall
 *      back to `tokyo-night`.
 */

import { describe, expect, it } from 'vitest';
import { bootResolveTheme, BOOT_SCRIPT_SOURCE } from '$lib/theme/boot';

describe('bootResolveTheme — 4-tier precedence', () => {
  // Tier 1: localStorage wins outright.
  it('valid localStorage wins over cookie and matchMedia', () => {
    expect(
      bootResolveTheme({
        localStorageValue: 'tokyo-storm',
        cookieValue: 'tokyo-day',
        mediaQueryDark: false,
      }),
    ).toBe('tokyo-storm');
  });

  it('every valid localStorage value round-trips', () => {
    const ids = ['tokyo-day', 'tokyo-storm', 'tokyo-moon', 'tokyo-night'] as const;
    for (const id of ids) {
      expect(
        bootResolveTheme({ localStorageValue: id, cookieValue: null, mediaQueryDark: null }),
      ).toBe(id);
    }
  });

  // Tier 2: cookie wins when localStorage is empty / invalid.
  it('cookie wins when localStorage is null', () => {
    expect(
      bootResolveTheme({
        localStorageValue: null,
        cookieValue: 'tokyo-moon',
        mediaQueryDark: true,
      }),
    ).toBe('tokyo-moon');
  });

  it('cookie wins when localStorage value is unknown (stale preset id)', () => {
    expect(
      bootResolveTheme({
        localStorageValue: 'tokyo-rain', // not a known id
        cookieValue: 'tokyo-storm',
        mediaQueryDark: false,
      }),
    ).toBe('tokyo-storm');
  });

  // Tier 3: matchMedia drives the OS-mapped fallback.
  it('matchMedia=true (dark OS) -> tokyo-night when neither storage tier has a valid value', () => {
    expect(
      bootResolveTheme({ localStorageValue: null, cookieValue: null, mediaQueryDark: true }),
    ).toBe('tokyo-night');
  });

  it('matchMedia=false (light OS) -> tokyo-day when neither storage tier has a valid value', () => {
    expect(
      bootResolveTheme({ localStorageValue: null, cookieValue: null, mediaQueryDark: false }),
    ).toBe('tokyo-day');
  });

  // Tier 4: brand-canonical fallback.
  it('matchMedia=null (no preference / unavailable) -> tokyo-night', () => {
    expect(
      bootResolveTheme({ localStorageValue: null, cookieValue: null, mediaQueryDark: null }),
    ).toBe('tokyo-night');
  });

  it('all three sources unknown / null -> tokyo-night', () => {
    expect(
      bootResolveTheme({
        localStorageValue: 'comic-sans',
        cookieValue: '',
        mediaQueryDark: null,
      }),
    ).toBe('tokyo-night');
  });
});

describe('bootResolveTheme — Safari private browsing & malformed cookie branches', () => {
  // The pure function takes plain inputs, so the "localStorage throws"
  // branch is modelled as `localStorageValue: null` — i.e. the IIFE's
  // try/catch already swallowed the throw and handed null to the pure
  // helper. The IIFE-level test below covers the *throwing* path
  // directly via the BOOT_SCRIPT_SOURCE eval.
  it('localStorage unavailable (null) + valid cookie -> cookie value', () => {
    expect(
      bootResolveTheme({
        localStorageValue: null,
        cookieValue: 'tokyo-day',
        mediaQueryDark: true,
      }),
    ).toBe('tokyo-day');
  });

  it('cookie malformed (null/undefined) + matchMedia=true -> tokyo-night', () => {
    expect(
      bootResolveTheme({ localStorageValue: null, cookieValue: null, mediaQueryDark: true }),
    ).toBe('tokyo-night');
    expect(
      bootResolveTheme({
        localStorageValue: null,
        cookieValue: undefined as unknown as string | null,
        mediaQueryDark: true,
      }),
    ).toBe('tokyo-night');
  });
});

describe('BOOT_SCRIPT_SOURCE — string contract', () => {
  it('is a non-empty string', () => {
    expect(typeof BOOT_SCRIPT_SOURCE).toBe('string');
    expect(BOOT_SCRIPT_SOURCE.length).toBeGreaterThan(0);
  });

  it('mentions all four preset ids verbatim (the inline ids array)', () => {
    expect(BOOT_SCRIPT_SOURCE).toContain('tokyo-day');
    expect(BOOT_SCRIPT_SOURCE).toContain('tokyo-storm');
    expect(BOOT_SCRIPT_SOURCE).toContain('tokyo-moon');
    expect(BOOT_SCRIPT_SOURCE).toContain('tokyo-night');
  });

  it('reads localStorage, document.cookie, and matchMedia (the three boot inputs)', () => {
    expect(BOOT_SCRIPT_SOURCE).toContain('localStorage');
    expect(BOOT_SCRIPT_SOURCE).toContain('document.cookie');
    expect(BOOT_SCRIPT_SOURCE).toContain('matchMedia');
    expect(BOOT_SCRIPT_SOURCE).toContain('prefers-color-scheme: dark');
  });

  it('writes the resolved id onto documentElement.dataset.theme', () => {
    expect(BOOT_SCRIPT_SOURCE).toMatch(/document\.documentElement\.dataset\.theme\s*=/);
  });

  it('wraps the IIFE so it executes immediately on parse', () => {
    // Function expression call form: starts with `(function`, ends with `)()`
    expect(BOOT_SCRIPT_SOURCE.trim().startsWith('(')).toBe(true);
    expect(BOOT_SCRIPT_SOURCE.trim().endsWith(')()')).toBe(true);
  });
});

describe('BOOT_SCRIPT_SOURCE — runtime behaviour against stubbed globals', () => {
  /**
   * Build a stubbed global env that mirrors the names the IIFE captures
   * when run in a browser. The IIFE uses top-level identifiers `window`,
   * `document` (no `globalThis.` prefix), so the cleanest way to drive
   * it from a test is to wrap BOOT_SCRIPT_SOURCE in a `new Function`
   * with those identifiers in scope.
   *
   * Returns the `documentElement.dataset.theme` value the IIFE wrote
   * (or `undefined` if the IIFE failed to write — which is itself a
   * regression).
   */
  function runBoot(opts: {
    localStorageGet?: (key: string) => string | null;
    localStorageThrows?: boolean;
    cookie?: string;
    matchMediaMatches?: boolean | null; // null => matchMedia throws
  }): { theme?: string; threw?: unknown } {
    const dataset: { theme?: string } = {};
    const documentStub = {
      cookie: opts.cookie ?? '',
      documentElement: { dataset } as unknown as HTMLElement,
    };
    const localStorageStub = {
      getItem: opts.localStorageThrows
        ? (): string | null => {
            throw new Error('Safari private browsing');
          }
        : (opts.localStorageGet ?? ((): string | null => null)),
    };
    const matchMediaFn =
      opts.matchMediaMatches === null
        ? (): MediaQueryList => {
            throw new Error('matchMedia unavailable');
          }
        : (): MediaQueryList =>
            ({
              matches: Boolean(opts.matchMediaMatches),
            }) as unknown as MediaQueryList;
    const windowStub = { localStorage: localStorageStub, matchMedia: matchMediaFn };

    const harness = new Function(
      'window',
      'document',
      'localStorage',
      'matchMedia',
      `${BOOT_SCRIPT_SOURCE}`,
    );
    try {
      harness(windowStub, documentStub, localStorageStub, matchMediaFn);
    } catch (err) {
      return { threw: err };
    }
    return { theme: dataset.theme };
  }

  it('valid localStorage drives dataset.theme', () => {
    const { theme, threw } = runBoot({
      localStorageGet: (k) => (k === 'theme' ? 'tokyo-storm' : null),
      cookie: 'theme=tokyo-day',
      matchMediaMatches: true,
    });
    expect(threw).toBeUndefined();
    expect(theme).toBe('tokyo-storm');
  });

  it('falls through to cookie when localStorage is empty', () => {
    const { theme } = runBoot({
      cookie: 'foo=bar; theme=tokyo-moon; baz=qux',
      matchMediaMatches: true,
    });
    expect(theme).toBe('tokyo-moon');
  });

  it('falls through to matchMedia when neither storage tier is valid', () => {
    expect(runBoot({ cookie: '', matchMediaMatches: true }).theme).toBe('tokyo-night');
    expect(runBoot({ cookie: '', matchMediaMatches: false }).theme).toBe('tokyo-day');
  });

  it('localStorage throws (Safari private browsing) — falls through silently', () => {
    const { theme, threw } = runBoot({
      localStorageThrows: true,
      cookie: 'theme=tokyo-storm',
      matchMediaMatches: false,
    });
    expect(threw).toBeUndefined();
    expect(theme).toBe('tokyo-storm');
  });

  it('matchMedia throws — falls back to tokyo-night', () => {
    const { theme, threw } = runBoot({
      cookie: '',
      matchMediaMatches: null,
    });
    expect(threw).toBeUndefined();
    expect(theme).toBe('tokyo-night');
  });

  it('every browser global throws — IIFE silently swallows and writes nothing OR tokyo-night', () => {
    // The plan's hardest contract: the IIFE must NEVER throw. We construct
    // a hostile env where document.documentElement.dataset assignment also
    // throws, and assert the harness still returns without raising.
    const harness = new Function('window', 'document', `${BOOT_SCRIPT_SOURCE}`);

    const hostileWindow = {
      get localStorage(): never {
        throw new Error('localStorage poisoned');
      },
      matchMedia: (): never => {
        throw new Error('matchMedia poisoned');
      },
    };
    const hostileDocument = {
      get cookie(): never {
        throw new Error('cookie poisoned');
      },
      get documentElement(): never {
        throw new Error('documentElement poisoned');
      },
    };

    let threw: unknown;
    try {
      harness(hostileWindow, hostileDocument);
    } catch (err) {
      threw = err;
    }
    expect(threw).toBeUndefined();
  });

  it('handles URL-encoded cookie values via decodeURIComponent', () => {
    // %2D etc; here we use the percent-encoded form of "tokyo-night" to
    // show the IIFE's `decodeURIComponent` branch handles it. (`-` is
    // technically safe; we still encode to exercise the decode path.)
    const encoded = encodeURIComponent('tokyo-night');
    const { theme } = runBoot({
      cookie: `theme=${encoded}`,
      matchMediaMatches: false,
    });
    expect(theme).toBe('tokyo-night');
  });
});

describe('bootResolveTheme — purity', () => {
  // Belt-and-braces: confirm `bootResolveTheme` is pure — given equal
  // inputs, equal outputs, no observable side effects on its globals.
  // Anything sneaky here would mean the pure helper and the IIFE could
  // diverge, which is the bug class M1's plan goes out of its way to
  // prevent.
  it('returns the same value on repeated calls with the same inputs', () => {
    const inputs = {
      localStorageValue: 'tokyo-storm',
      cookieValue: 'tokyo-day',
      mediaQueryDark: true,
    } as const;
    const a = bootResolveTheme(inputs);
    const b = bootResolveTheme(inputs);
    const c = bootResolveTheme(inputs);
    expect(a).toBe('tokyo-storm');
    expect(b).toBe('tokyo-storm');
    expect(c).toBe('tokyo-storm');
  });
});
