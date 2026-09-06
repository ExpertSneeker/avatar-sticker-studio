import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'

// Chromium 153 for Testing crashes on macOS while deserializing OPFS handles.
// Prefer the installed stable Chrome, with an explicit override for other environments.
const browserChannel=process.env.STUDIO_TEST_BROWSER||(process.platform==='darwin'&&existsSync('/Applications/Google Chrome.app')?'chrome':'chromium')

export default defineConfig({
  testDir: './e2e',
  timeout: 90000,
  expect: { timeout: 15000 },
  workers: 1,
  use: { channel: browserChannel, baseURL: 'http://127.0.0.1:5174', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: [
    { command: 'uv run uvicorn backend.tests.browser_app:factory --factory --host 127.0.0.1 --port 8001', cwd: '..', url: 'http://127.0.0.1:8001/api/health', reuseExistingServer: false },
    { command: 'npm run dev -- --port 5174 --strictPort', url: 'http://127.0.0.1:5174', env: { STUDIO_API_PROXY: 'http://127.0.0.1:8001' }, reuseExistingServer: false },
  ],
})
