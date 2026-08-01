export type Toast = { id: number; kind: 'success' | 'error' | 'info'; text: string }

export default function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  if (!toasts.length) return null
  return (
    <div className="toasts" role="status">
      {toasts.map((toast) => (
        <button key={toast.id} className={`toast ${toast.kind}`} onClick={() => onDismiss(toast.id)}>
          <i />{toast.text}
        </button>
      ))}
    </div>
  )
}
