/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        accent: '#6366f1',
        'accent-hover': '#5558e3',
      },
      borderRadius: {
        'card': '12px',
        'control': '8px',
      },
      transitionDuration: {
        DEFAULT: '.18s',
      },
      transitionTimingFunction: {
        DEFAULT: 'ease-out',
      },
    },
  },
  plugins: [],
}
