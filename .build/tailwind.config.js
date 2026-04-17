/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./frontend/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ['SF Mono', 'Monaco', 'Menlo', 'Courier New', 'monospace'],
      },
    },
  },
  plugins: [],
}
