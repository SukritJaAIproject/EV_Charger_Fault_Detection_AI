/** @type {import('tailwindcss').Config} */

const withMT = require("@material-tailwind/react/utils/withMT");
const tailwindColors = require("tailwindcss/colors");

// withMT replaces Tailwind's palette with Material Tailwind's, which has no
// slate, emerald, violet, sky or rose. Classes in those families were never
// generated, so the 1.7.0 Ground Truth and Train Model buttons rendered white
// on white. Add them back on top of the Material Tailwind palette.
const MISSING_FROM_MATERIAL_TAILWIND = ["slate", "emerald", "violet", "sky", "rose"];

module.exports = withMT({
  content: [
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/data/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/theme/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/widgets/**/*.{js,ts,jsx,tsx,mdx}",
    "./backend/pdf/templates/**/*.html", // ให้ Tailwind scan เทมเพลตที่ใช้จริง
    "./src/**/*.{ts,tsx}",   
  ],
  theme: {
    extend: {
      colors: Object.fromEntries(MISSING_FROM_MATERIAL_TAILWIND.map((name) => [name, tailwindColors[name]])),
      fontFamily: {
        sans: [
          "var(--font-kanit)",
          "Kanit",
          "var(--font-jakarta)",
          "Plus Jakarta Sans",
          "sans-serif",
        ],
        mono: ["var(--font-mono)", "JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
  prefix: "tw-",
});
