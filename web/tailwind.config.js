/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        titulo: ["var(--fonte-titulo)", "serif"],
        corpo: ["var(--fonte-corpo)", "serif"],
      },
      colors: {
        painel: "var(--painel-bg)",
        borda: "var(--painel-borda)",
        acento: "var(--acento)",
        texto: "var(--texto)",
        suave: "var(--texto-suave)",
        vida: "var(--status-vida)",
        recurso: "var(--status-recurso)",
        sanidade: "var(--status-sanidade)",
      },
    },
  },
  plugins: [],
}
