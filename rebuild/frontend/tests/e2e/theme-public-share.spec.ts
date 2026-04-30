/**
 * Public-share theme E2E — placeholder shipping in M1.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § E2E
 * (theme-public-share.spec.ts): "ships in M1 so the M3 author doesn't
 * have to invent it; body is a one-line comment that the M3 author
 * fills in."
 *
 * The test is `test.skip(...)`'d at file scope so the suite reports it
 * as skipped (with the documented reason) rather than red. Once the
 * `/s/{token}` public-share surface lands in M3, the M3 author should:
 *
 *   1. Drop the `test.skip(...)` for the actual `test(...)`.
 *   2. Add the public layout's theme contract assertions:
 *        - `/s/{token}` honours the `theme` cookie if present
 *          (anonymous viewer who previously customised in their own
 *          authenticated session sees their pick on the share page).
 *        - When no cookie is present, falls through to the OS
 *          preference via the boot script (parametrise like
 *          `theme-os-default.spec.ts`).
 *        - The `(public)` layout's `+layout.server.ts` does NOT call
 *          `getUser` (anonymous flow) AND does NOT touch DB.
 *   3. Wire a fixture that creates a real share token via the M3
 *      backend (add to `tests/conftest.py` once the share endpoint
 *      exists).
 */

import { test } from '@playwright/test';

test.skip('public-share theme contract — placeholder for M3', async () => {
  // Intentionally empty. M3 author: see file-top docstring for the
  // assertion checklist before unskipping this test.
});
