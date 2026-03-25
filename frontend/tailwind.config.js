/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#6366f1', dark: '#4f46e5' },
        surface: { DEFAULT: '#0f0f14', raised: '#16161e', border: '#1e1e2a' },
      },
      fontFamily: { mono: ['JetBrains Mono', 'Fira Code', 'monospace'] },
    },
  },
  plugins: [],
}
