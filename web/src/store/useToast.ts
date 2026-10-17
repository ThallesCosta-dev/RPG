import { create } from "zustand"

export interface Toast {
  id: number
  tipo: "erro" | "info" | "ok"
  texto: string
}

interface ToastStore {
  toasts: Toast[]
  mostrar(texto: string, tipo?: Toast["tipo"], duracaoMs?: number): void
  fechar(id: number): void
}

let proximoId = 1

export const useToast = create<ToastStore>((set, get) => ({
  toasts: [],
  mostrar(texto, tipo = "info", duracaoMs = 5000) {
    const id = proximoId++
    set({ toasts: [...get().toasts, { id, tipo, texto }] })
    setTimeout(() => get().fechar(id), duracaoMs)
  },
  fechar(id) {
    set({ toasts: get().toasts.filter((t) => t.id !== id) })
  },
}))
