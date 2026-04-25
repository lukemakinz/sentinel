/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0b',
        surface: '#121214',
        surfaceHighlight: '#1A1A1D',
        primary: '#D4AF37', // Gold
        primaryHover: '#b8962d',
        accent: '#00E5FF', // Electric Cyan
        accentHover: '#00b8cc',
        textPrimary: '#F3F4F6',
        textSecondary: '#9CA3AF',
        textMuted: '#6B7280',
        positive: '#10B981',
        negative: '#EF4444',
        border: '#27272A',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
