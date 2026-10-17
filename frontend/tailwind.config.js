/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    // Include shared packages for class detection
    "/packages/shizuha-ui/src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
      },
      // PLAT-684 (Org Chart 2.0 Phase 4): data-driven "live-feel" motion. Applied
      // via `motion-safe:` variants in the JSX so prefers-reduced-motion disables
      // them. Animation is keyed to live snapshot workload, never decorative.
      keyframes: {
        // In-progress beacon: an expanding ring that conveys active work.
        'activity-ring': {
          '0%':   { transform: 'scale(0.85)', opacity: '0.7' },
          '70%':  { transform: 'scale(1.6)',  opacity: '0' },
          '100%': { transform: 'scale(1.6)',  opacity: '0' },
        },
        // Task-flow: a token gliding along the stage lane (eng→review→qa→merge).
        'flow-dash': {
          '0%':   { backgroundPosition: '0 0' },
          '100%': { backgroundPosition: '32px 0' },
        },
        'flow-token': {
          '0%':   { left: '0%',   opacity: '0' },
          '10%':  { opacity: '1' },
          '90%':  { opacity: '1' },
          '100%': { left: '100%', opacity: '0' },
        },
      },
      animation: {
        'activity-ring': 'activity-ring 1.6s ease-out infinite',
        'flow-dash': 'flow-dash 0.8s linear infinite',
        'flow-token': 'flow-token 2.2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
