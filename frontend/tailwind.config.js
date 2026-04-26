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
          500: "#4f7df3",
          600: "#3b68e8",
          700: "#2d57d4",
          900: "#1a3a9f",
        },
        dark: {
          900: "#0d0f14",
          800: "#13161e",
          700: "#1c2030",
          600: "#242840",
        },
      },
    },
  },
  plugins: [],
};
