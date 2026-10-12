/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['variant', [
    // Matches the two ways dark is selected: an explicit toggle, and the OS
    // setting when no explicit choice has been stamped.
    '&:is([data-theme="dark"] *)',
    '@media (prefers-color-scheme: dark) { &:is(:root:not([data-theme="light"]) *) }',
  ]],
  theme: {
    extend: {
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
