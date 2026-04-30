/**
 * Unit tests for `src/lib/theme/persistence.ts`.
 *
 * Pinned by `m1-theming.md` § Persistence:
 *   - `writeChoice(id)` writes to BOTH the theme cookie AND localStorage
 *     in the same call so the surfaces cannot drift.
 *   - Cookie carries `Max-Age=31536000`, `Path=/`, `SameSite=Lax`.
 *   - The `Secure` cookie flag is present iff
 *     `location.protocol === 'https:'` so dev (http://localhost:5173)
 *     stays unaffected and every non-dev origin gets `Secure`
 *     automatically without env-var plumbing.
 *   - `clearChoice()` clears both surfaces (cookie via `Max-Age=0`).
 *
 * jsdom provides a writable `document.cookie` setter via a property
 * accessor; we capture writes by spying on the setter so we can assert
 * the exact attribute string the implementation produced.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { writeChoice, clearChoice } from '$lib/theme/persistence';

// Capture the writes the implementation issues to `document.cookie`.
let cookieWrites: string[];
let cookieSetSpy: MockInstance | null = null;

// Stash the original location so we can swap it for either branch and
// restore it after each test. jsdom defines `window.location` as a
// non-configurable accessor in some versions; `Object.defineProperty`
// onto the window does the trick.
let originalLocationDescriptor: PropertyDescriptor | undefined;
let originalLocalStorage: typeof window.localStorage;

beforeEach(() => {
  cookieWrites = [];
  // `Document.prototype` is where jsdom defines the `cookie` accessor.
  cookieSetSpy = vi
    .spyOn(Document.prototype, 'cookie', 'set')
    .mockImplementation(function setCookie(value: string) {
      cookieWrites.push(value);
    });

  originalLocationDescriptor = Object.getOwnPropertyDescriptor(window, 'location');
  originalLocalStorage = window.localStorage;
});

afterEach(() => {
  cookieSetSpy?.mockRestore();
  cookieSetSpy = null;
  // Restore window.location.
  if (originalLocationDescriptor) {
    Object.defineProperty(window, 'location', originalLocationDescriptor);
  }
  // Restore localStorage in case a stub leaked.
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: originalLocalStorage,
  });
});

function stubLocationProtocol(protocol: 'http:' | 'https:'): void {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { protocol } as Location,
  });
}

describe('writeChoice — cookie attributes', () => {
  it('writes the theme cookie with Max-Age=31536000 (one year), Path=/, SameSite=Lax', () => {
    stubLocationProtocol('http:');
    writeChoice('tokyo-storm');

    // The implementation may or may not also touch localStorage; we
    // only assert the cookie shape here.
    expect(cookieWrites.length).toBeGreaterThanOrEqual(1);
    const written = cookieWrites[0]!;
    expect(written).toMatch(/^theme=tokyo-storm/);
    expect(written).toMatch(/Max-Age=31536000/);
    expect(written).toMatch(/Path=\//);
    expect(written).toMatch(/SameSite=Lax/);
  });

  it('omits the Secure flag on http:// (dev)', () => {
    stubLocationProtocol('http:');
    writeChoice('tokyo-day');
    expect(cookieWrites[0]).not.toMatch(/Secure/);
  });

  it('emits the Secure flag on https:// (prod / staging)', () => {
    stubLocationProtocol('https:');
    writeChoice('tokyo-night');
    expect(cookieWrites[0]).toMatch(/Secure/);
  });
});

describe('writeChoice — localStorage mirror', () => {
  it('calls localStorage.setItem("theme", id) in the same call', () => {
    stubLocationProtocol('http:');
    const setItem = vi.fn();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: { setItem, removeItem: vi.fn(), getItem: vi.fn() } as Partial<Storage>,
    });

    writeChoice('tokyo-moon');
    expect(setItem).toHaveBeenCalledTimes(1);
    expect(setItem).toHaveBeenCalledWith('theme', 'tokyo-moon');
  });

  it('writes BOTH surfaces in the same call (cookie + localStorage)', () => {
    stubLocationProtocol('https:');
    const setItem = vi.fn();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: { setItem, removeItem: vi.fn(), getItem: vi.fn() } as Partial<Storage>,
    });

    writeChoice('tokyo-storm');

    expect(cookieWrites).toHaveLength(1);
    expect(setItem).toHaveBeenCalledTimes(1);
  });

  it('cookie write succeeds even when localStorage.setItem throws (Safari private browsing)', () => {
    stubLocationProtocol('https:');
    const throwingSetItem = vi.fn(() => {
      throw new Error('QuotaExceededError');
    });
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        setItem: throwingSetItem,
        removeItem: vi.fn(),
        getItem: vi.fn(),
      } as Partial<Storage>,
    });

    expect(() => writeChoice('tokyo-day')).not.toThrow();
    expect(cookieWrites[0]).toMatch(/^theme=tokyo-day/);
  });
});

describe('clearChoice', () => {
  it('issues a Max-Age=0 cookie write to delete the theme cookie', () => {
    stubLocationProtocol('http:');
    clearChoice();
    expect(cookieWrites.length).toBeGreaterThanOrEqual(1);
    const written = cookieWrites[0]!;
    expect(written).toMatch(/^theme=/);
    expect(written).toMatch(/Max-Age=0/);
    expect(written).toMatch(/Path=\//);
    expect(written).toMatch(/SameSite=Lax/);
  });

  it('removes localStorage["theme"] in the same call', () => {
    stubLocationProtocol('http:');
    const removeItem = vi.fn();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: { setItem: vi.fn(), removeItem, getItem: vi.fn() } as Partial<Storage>,
    });

    clearChoice();
    expect(removeItem).toHaveBeenCalledTimes(1);
    expect(removeItem).toHaveBeenCalledWith('theme');
  });

  it('emits Secure on https:// even when deleting (browser parity rule)', () => {
    stubLocationProtocol('https:');
    clearChoice();
    expect(cookieWrites[0]).toMatch(/Secure/);
  });

  it('omits Secure on http:// when deleting', () => {
    stubLocationProtocol('http:');
    clearChoice();
    expect(cookieWrites[0]).not.toMatch(/Secure/);
  });
});
