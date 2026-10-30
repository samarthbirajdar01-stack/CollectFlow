/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#12223b",
        navy: "#10213a",
        brand: "#3568e8",
        mint: "#21a582",
      },
    },
  },
  plugins: [],
};
