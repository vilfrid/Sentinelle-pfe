/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0f4ff",
          100: "#e0eaff",
          300: "#93b0f8",
          400: "#6b93f6",
          500: "#4f7df3",
          600: "#3b68e8",
          700: "#2d57d4",
          900: "#1a3a9f",
        },
        // Theme-aware palette: the RGB triplets live in index.css and flip
        // when .light replaces .dark on <html>.
        white: "rgb(var(--c-white) / <alpha-value>)",
        gray: {
          100: "rgb(var(--c-gray-100) / <alpha-value>)",
          200: "rgb(var(--c-gray-200) / <alpha-value>)",
          300: "rgb(var(--c-gray-300) / <alpha-value>)",
          400: "rgb(var(--c-gray-400) / <alpha-value>)",
          500: "rgb(var(--c-gray-500) / <alpha-value>)",
          600: "rgb(var(--c-gray-600) / <alpha-value>)",
          700: "rgb(var(--c-gray-700) / <alpha-value>)",
        },
        dark: {
          900: "rgb(var(--c-surface-900) / <alpha-value>)",
          800: "rgb(var(--c-surface-800) / <alpha-value>)",
          700: "rgb(var(--c-surface-700) / <alpha-value>)",
          600: "rgb(var(--c-surface-600) / <alpha-value>)",
        },
      },
    },
  },
  plugins: [],
};
