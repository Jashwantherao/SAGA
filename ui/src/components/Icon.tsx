import type { ReactNode } from 'react'

const paths: Record<string, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  spark: <path d="M12 2l1.6 5.2L19 9l-5.4 1.8L12 16l-1.6-5.2L5 9l5.4-1.8L12 2Zm6 13 .8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15Z" />,
  library: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16Z" /><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20M8 7h8" /></>,
  services: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="8" cy="6" r="2" /><circle cx="16" cy="12" r="2" /><circle cx="10" cy="18" r="2" /></>,
  models: <><path d="M12 3 3.5 8 12 13l8.5-5L12 3Z" /><path d="m3.5 12 8.5 5 8.5-5M3.5 16l8.5 5 8.5-5" /></>,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></>,
  warning: <><path d="M10.3 3.7 2.5 18a2 2 0 0 0 1.8 3h15.4a2 2 0 0 0 1.8-3L13.7 3.7a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4m0 4h.01" /></>,
  play: <path d="M7 4.5v15l13-7.5L7 4.5Z" />,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />,
  godot: <><circle cx="12" cy="12" r="9" /><circle cx="8.5" cy="10.5" r="1.6" /><circle cx="15.5" cy="10.5" r="1.6" /><path d="M8 15.5h8" /></>,
  trash: <><path d="M4 7h16M10 4h4M6.5 7l1 13h9l1-13" /><path d="M10 11v5m4-5v5" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="m16.5 16.5 4.5 4.5" /></>,
  chip: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>,
  film: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" /></>,
  image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="1.8" /><path d="m4 18 5.5-5 3.5 3 3-2.5 4 4" /></>,
  music: <><path d="M9 18.5V6l11-2v12.5" /><circle cx="6.5" cy="18.5" r="2.5" /><circle cx="17.5" cy="16.5" r="2.5" /></>,
  doc: <><path d="M6 2.5h8L19 7.5v14H6v-19Z" /><path d="M14 2.5v5h5M9 12h6M9 16h6" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  terminal: <><path d="m5 7 5 5-5 5" /><path d="M12 19h7" /></>,
  check: <path d="m4.5 12.5 5 5 10-11" />,
  dice: <><rect x="3.5" y="3.5" width="17" height="17" rx="4" /><circle cx="8.7" cy="8.7" r="1.2" /><circle cx="15.3" cy="8.7" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="8.7" cy="15.3" r="1.2" /><circle cx="15.3" cy="15.3" r="1.2" /></>,
  history: <><path d="M4.5 5v5h5" /><path d="M4.8 14a8 8 0 1 0 .6-6.5L4.5 10" /><path d="M12 8v4.5l3 2" /></>,
}

export default function Icon({ name }: { name: string }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>
}
