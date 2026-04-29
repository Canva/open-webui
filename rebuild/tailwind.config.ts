import type { Config } from 'tailwindcss';

// Tailwind 4 does not require content globs (the v4 engine scans imported
// files automatically via @tailwindcss/vite). This config is kept as a
// surface for future plugin registration (e.g. typography, container queries).
export default {} satisfies Config;
