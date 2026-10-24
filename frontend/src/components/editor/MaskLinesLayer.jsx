import React, { useCallback, useRef, useState } from "react";

const MIN_GAP_RATIO = 0.02; // keep the two lines from crossing/overlapping

// Two draggable horizontal lines marking the "safe zone" for body text.
// Anything above the top line or below the bottom line is treated as
// header/footer and excluded from conversion. Positions are stored (and
// reported back via onChangeRatios) as a RATIO of page height, not pixels
// — that's what lets a single adjustment on one page apply correctly to
// every page in the book, since they're not all rendered at the same
// on-screen pixel size.
export default function MaskLinesLayer({ width, height, headerRatio, footerRatio, onChangeRatios }) {
  const svgRef = useRef(null);
  const [dragging, setDragging] = useState(null); // "header" | "footer" | null

  const headerY = headerRatio * height;
  const footerY = height - footerRatio * height;

  const clientYToRatio = useCallback(
    (clientY) => {
      const rect = svgRef.current.getBoundingClientRect();
      const y = Math.min(Math.max(clientY - rect.top, 0), height);
      return y / height;
    },
    [height]
  );

  const handlePointerDown = (which) => (e) => {
    e.preventDefault();
    setDragging(which);
    e.target.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e) => {
    if (!dragging) return;
    const ratio = clientYToRatio(e.clientY);
    if (dragging === "header") {
      const maxAllowed = 1 - footerRatio - MIN_GAP_RATIO;
      onChangeRatios({ headerRatio: Math.min(Math.max(ratio, 0), maxAllowed), footerRatio });
    } else {
      const ratioFromBottom = 1 - ratio;
      const maxAllowed = 1 - headerRatio - MIN_GAP_RATIO;
      onChangeRatios({ headerRatio, footerRatio: Math.min(Math.max(ratioFromBottom, 0), maxAllowed) });
    }
  };

  const handlePointerUp = (e) => {
    setDragging(null);
    if (e.target.releasePointerCapture && e.pointerId != null) {
      try {
        e.target.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
    }
  };

  return (
    <svg
      ref={svgRef}
      className="mask-lines-layer"
      width={width}
      height={height}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
    >
      {/* dimmed excluded zones, purely visual */}
      <rect x={0} y={0} width={width} height={headerY} className="mask-lines-layer__dim" />
      <rect x={0} y={footerY} width={width} height={height - footerY} className="mask-lines-layer__dim" />

      {/* header line + drag handle */}
      <line x1={0} y1={headerY} x2={width} y2={headerY} className="mask-lines-layer__line" />
      <rect
        x={0}
        y={headerY - 6}
        width={width}
        height={12}
        className="mask-lines-layer__handle"
        onPointerDown={handlePointerDown("header")}
      />
      <text x={8} y={Math.max(headerY - 8, 12)} className="mask-lines-layer__label">
        Üst sınır
      </text>

      {/* footer line + drag handle */}
      <line x1={0} y1={footerY} x2={width} y2={footerY} className="mask-lines-layer__line" />
      <rect
        x={0}
        y={footerY - 6}
        width={width}
        height={12}
        className="mask-lines-layer__handle"
        onPointerDown={handlePointerDown("footer")}
      />
      <text x={8} y={Math.min(footerY + 18, height - 4)} className="mask-lines-layer__label">
        Alt sınır
      </text>
    </svg>
  );
}
