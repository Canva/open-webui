import { defineConfig, devices } from '@playwright/experimental-ct-svelte';

export default defineConfig({
  testDir: './frontend/tests/component',
  use: {
    ctPort: 3100,
    ctTemplateDir: './frontend/playwright',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
