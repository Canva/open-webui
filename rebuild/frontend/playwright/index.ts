import '../src/app.css';

// Playwright CT bundles this file for the browser via Vite. The previous
// version imported `msw/node` here so a Node-side MSW server could
// intercept fetch during component mounts, but `msw/node` pulls in
// `@mswjs/interceptors/ClientRequest`, which has no browser-condition
// export and so refuses to bundle. The current m0 CT suite (see
// `frontend/tests/component/layout.spec.ts`) drives components purely
// through props and never makes network calls, so no mocking layer is
// required at all here. When a future milestone introduces a CT test
// that does need to intercept requests, wire it up against `msw/browser`
// (which is what `frontend/src/lib/msw/browser.ts` already exposes via
// `startMockWorker()`) rather than re-importing the Node entry.
