// Line icons in the style of Apple's design-resources row: 1.6px strokes, rounded joins.
const base = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' }

const paths = {
  logo: <path d="M5 12.5l4.5 4.5L19 7.5" strokeWidth="2.6" />,
  command: <><rect x="3.5" y="3.5" width="7" height="7" rx="2" /><rect x="13.5" y="3.5" width="7" height="7" rx="2" /><rect x="3.5" y="13.5" width="7" height="7" rx="2" /><rect x="13.5" y="13.5" width="7" height="7" rx="2" /></>,
  inbox: <><path d="M3.5 13l3-8h11l3 8v6h-17v-6z" /><path d="M3.5 13h5l1.5 2.5h4L15.5 13h5" /></>,
  simulator: <path d="M9.5 3.5h5M10.5 3.5v5.5L5 19c-.5 1 .2 1.5 1.2 1.5h11.6c1 0 1.7-.5 1.2-1.5l-5.5-10V3.5M7.5 14.5h9" />,
  knowledge: <><path d="M4 5c2.5-1.3 5.5-1.3 8 0v15c-2.5-1.3-5.5-1.3-8 0V5z" /><path d="M12 5c2.5-1.3 5.5-1.3 8 0v15c-2.5-1.3-5.5-1.3-8 0" /></>,
  metrics: <path d="M4 20V12M9.5 20V5M15 20v-9M20 20H3" />,
  audit: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  admin: <><circle cx="12" cy="12" r="3" /><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M18.7 5.3l-1.8 1.8M7.1 16.9l-1.8 1.8" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5 5" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" /></>,
  moon: <path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z" />,
  menu: <path d="M4 8h16M4 16h16" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  alert: <><path d="M12 8v5" /><path d="M12 16.5v.1" /><circle cx="12" cy="12" r="9" /></>,
  block: <><circle cx="12" cy="12" r="9" /><path d="M6 6l12 12" /></>,
  shield: <path d="M12 3l7.5 3v5.5c0 4.5-3.2 8.2-7.5 9.5-4.3-1.3-7.5-5-7.5-9.5V6L12 3z" />,
  bolt: <path d="M13 3L5 13.5h6L10 21l8-10.5h-6L13 3z" />,
  doc: <><path d="M6.5 3.5h7l4 4v13h-11v-17z" /><path d="M13.5 3.5v4h4M9 12h6M9 15.5h6" /></>,
  person: <><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" /></>,
  refresh: <><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" /><path d="M19.5 4v4h-4" /></>,
  play: <path d="M8 5.5v13l10.5-6.5L8 5.5z" />,
  arrowLeft: <path d="M14.5 6l-6 6 6 6" />,
  chevron: <path d="M9.5 6l6 6-6 6" />,
  lock: <><rect x="5" y="10.5" width="14" height="10" rx="2.5" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /></>,
  power: <><path d="M12 3v8" /><path d="M7 6.5a7.5 7.5 0 1 0 10 0" /></>,
  bell: <><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15l1.5-2z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>,
  bellOff: <><path d="M6 16.5V11a6 6 0 0 1 9.5-4.9M18 11v5.5l1.5 2H8" /><path d="M10 20.5a2 2 0 0 0 4 0M4 4l16 16" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  download: <><path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" /><path d="M5 19.5h14" /></>,
  trash: <><path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13" /></>,
  note: <><path d="M5 4.5h14v11l-4.5 4.5H5v-15.5z" /><path d="M14.5 20v-4.5H19M8.5 9h7M8.5 12.5h4" /></>,
  enter: <path d="M19 5v7.5a2 2 0 0 1-2 2H6M9.5 11L6 14.5 9.5 18" />,
}

export default function Icon({ name, size = 20, className = '', ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={className} {...base} {...rest}>
      {paths[name]}
    </svg>
  )
}
