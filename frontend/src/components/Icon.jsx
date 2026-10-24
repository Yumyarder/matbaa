import React from "react";

// The few drawn marks Haşiye uses where Gece Matbaası sets a text glyph
// (×, ←, ✓): one stroke weight, square ends, sized by the text around them.
const PATHS = {
  close: "M4 4l8 8M12 4l-8 8",
  back: "M10 3L5 8l5 5",
  next: "M2 8h11M9 4l4 4-4 4",
  check: "M3.5 8.5l3 3 6-7",
};

export default function Icon({ name, size = 12, title }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden={title ? undefined : "true"}
         role={title ? "img" : undefined} focusable="false" className={`icon icon--${name}`}>
      {title && <title>{title}</title>}
      <path d={PATHS[name]} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" strokeLinejoin="miter" />
    </svg>
  );
}
