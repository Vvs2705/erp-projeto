/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f5f7fa',
          100: '#eaeef4',
          200: '#d0daf2',
          300: '#a6bbe3',
          400: '#7395d0',
          500: '#4a6fa5',
          600: '#3b5984',
          700: '#304769',
          800: '#263750',
          900: '#1b263b',
          950: '#0f172a',
        },
        slate: {
          950: '#0b0f19',
        }
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
