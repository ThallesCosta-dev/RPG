import { Navigate, Route, Routes } from "react-router-dom"
import Inicio from "./pages/Inicio"
import Sala from "./pages/Sala"
import Toasts from "./components/Toasts"

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Inicio />} />
        <Route path="/sala/:id" element={<Sala />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toasts />
    </>
  )
}
