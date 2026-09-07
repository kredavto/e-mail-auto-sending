/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { ink: "#142019", acid: "#d8f04c", paper: "#f2f0e9", clay: "#d56842" },
      fontFamily: { display: ["Manrope", "sans-serif"], body: ["IBM Plex Sans", "sans-serif"] },
    },
  },
  plugins: [],
};

