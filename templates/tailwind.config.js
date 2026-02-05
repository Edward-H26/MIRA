/** @type {import("tailwindcss").Config} */
export default {
  content: ["./*.html", "./src/**/*.{js,jsx}"],
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
