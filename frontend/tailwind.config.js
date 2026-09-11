/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { ink: "#202630", acid: "#e8d1a2", paper: "#f6f5f1", clay: "#967039" },
      fontFamily: { display: ["Manrope", "sans-serif"], body: ["IBM Plex Sans", "sans-serif"] },
    },
  },
  plugins: [],
};

