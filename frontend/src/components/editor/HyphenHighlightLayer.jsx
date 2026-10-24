import React, { useEffect, useState } from "react";
import { fetchHyphenFlags } from "../../api.js";

// Purely visual, read-only confirmation layer: highlights every
// line-ending word the conversion engine will treat as a mid-word line
// break ("çarşaf-" → rejoined with the next line/page, hyphen dropped).
// Entirely non-interactive (pointer-events: none throughout, see CSS) so
// it never gets in the way of MaskLinesLayer's dragging above it.
export default function HyphenHighlightLayer({ uploadId, pageIndex, width, height, pageWidthPt, pageHeightPt }) {
  const [flags, setFlags] = useState([]);

  useEffect(() => {
    let cancelled = false;
    setFlags([]);
    fetchHyphenFlags(uploadId, pageIndex)
      .then((data) => {
        if (!cancelled) setFlags(data.flags || []);
      })
      .catch(() => {
        if (!cancelled) setFlags([]);
      });
    return () => {
      cancelled = true;
    };
  }, [uploadId, pageIndex]);

  if (!pageWidthPt || !pageHeightPt || flags.length === 0) return null;

  const scaleX = width / pageWidthPt;
  const scaleY = height / pageHeightPt;
  const PAD = 2; // a couple px of breathing room around the word's bbox

  return (
    <svg className="hyphen-highlight-layer" width={width} height={height}>
      {flags.map((f, i) => {
        const [x0, y0, x1, y1] = f.bbox;
        return (
          <rect
            key={i}
            x={x0 * scaleX - PAD}
            y={y0 * scaleY - PAD}
            width={(x1 - x0) * scaleX + PAD * 2}
            height={(y1 - y0) * scaleY + PAD * 2}
            rx={2}
            className="hyphen-highlight-layer__mark"
          >
            <title>{`"${f.text}" — sonraki satırla birleştirilecek`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
