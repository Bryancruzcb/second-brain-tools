"use client";

import {
  useEffect,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";

type Props = {
  children: ReactNode;
  className?: string;
  /** @deprecated Unused — glow is hover/focus or brief is-glowing only */
  active?: boolean;
  /** Temporary animated outline (~1.4s after nav click) */
  glow?: boolean;
  /** Border radius matched to the framed element */
  radius?: number;
  /** Compact variant for nav text links */
  compact?: boolean;
  style?: CSSProperties;
  id?: string;
};

/**
 * SVG stroke-dash outline glow.
 * Nav: hover/focus-within only. Panels: brief pulse via glow/is-glowing.
 */
export function GlowOutline({
  children,
  className = "",
  active: _active = false,
  glow = false,
  radius = 18,
  compact = false,
  style,
  id,
}: Props) {
  const blurRef = useRef<SVGRectElement>(null);
  const lineRef = useRef<SVGRectElement>(null);

  useEffect(() => {
    const rx = String(Math.max(0, radius));
    for (const el of [blurRef.current, lineRef.current]) {
      if (!el) continue;
      el.setAttribute("rx", rx);
      el.setAttribute("ry", rx);
    }
  }, [radius]);

  return (
    <div
      id={id}
      className={`glow ${compact ? "glow-compact" : "glow-panel"} ${glow ? "is-glowing" : ""} ${className}`}
      style={style}
      data-glow={glow || undefined}
    >
      {children}
      <svg
        className="glow-container"
        aria-hidden
        preserveAspectRatio="none"
      >
        <rect
          ref={blurRef}
          x="0"
          y="0"
          width="100%"
          height="100%"
          pathLength={100}
          strokeLinecap="round"
          className="glow-blur"
          rx={radius}
          ry={radius}
        />
        <rect
          ref={lineRef}
          x="0"
          y="0"
          width="100%"
          height="100%"
          pathLength={100}
          strokeLinecap="round"
          className="glow-line"
          rx={radius}
          ry={radius}
        />
      </svg>
    </div>
  );
}
