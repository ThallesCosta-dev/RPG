import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App"
import "./index.css"
import { TEMAS, aplicarTema, temaEfetivo } from "./lib/tema"
import { storage } from "./lib/storage"

// `?tema=cyberpunk` força o tema (atalho para testes); fica salvo como override.
const temaUrl = new URLSearchParams(window.location.search).get("tema")
if (temaUrl && (TEMAS as string[]).includes(temaUrl)) storage.setTema(temaUrl)
aplicarTema(temaEfetivo(null))

const raiz = document.getElementById("root")
if (raiz) {
  createRoot(raiz).render(
    <BrowserRouter>
      <App />
    </BrowserRouter>,
  )
}
