/** @type {import("tailwindcss").Config} */
export default {
  // scan all HTML inside this templates package plus any JS used for UI
  content: [
    "./*.html",
    "./**/*.html",          // covers ./frontend/**/*.html and ./memoria/**/*.html
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        "text-secondary": "#727272",
        "text-light": "#fdfdfd",
        "bg-dark": "#282828",
        "bg-surface": "#f1f1f1",
        "bg-surface2": "#fdfdfd",
        "placeholder": "#d9d9d9"
      },
      fontFamily: {
        inter: ["Inter", "sans-serif"]
      },
      borderRadius: {
        "dashboard": "32px",
        "button": "90px"
      }
    }
  },
  plugins: []
}
