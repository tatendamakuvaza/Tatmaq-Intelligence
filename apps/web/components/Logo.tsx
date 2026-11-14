import { useId } from "react";

// A white tile with three rising bars in the brand gradient: it reads clearly on the
// blue band, the sidebar and the top bar, which is where the mark always sits.
export function LogoMark({ size = 28 }: { size?: number }) {
  const gradient = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" style={{ flex: "none" }}>
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1E4470" />
          <stop offset="1" stopColor="#B08D57" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="#fff" />
      <rect x="7" y="17" width="4.5" height="8" rx="1.4" fill={`url(#${gradient})`} />
      <rect x="13.5" y="12" width="4.5" height="13" rx="1.4" fill={`url(#${gradient})`} />
      <rect x="20" y="8.5" width="4.5" height="16.5" rx="1.4" fill={`url(#${gradient})`} />
      <circle cx="9.2" cy="9.4" r="2.5" fill="#C8A97A" />
    </svg>
  );
}

export function Brand({ size = 32 }: { size?: number }) {
  return (
    <div className="brand">
      <LogoMark size={size} />
      <div>
        TATMAQ
        <small>Intelligence</small>
      </div>
    </div>
  );
}
