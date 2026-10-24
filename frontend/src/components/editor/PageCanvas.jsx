import React, { useEffect, useState } from "react";
import { fetchEditorPageInfo, editorPageImageSrc } from "../../api.js";
import MaskLinesLayer from "./MaskLinesLayer.jsx";
import HyphenHighlightLayer from "./HyphenHighlightLayer.jsx";
import BoundingBoxLayer from "./BoundingBoxLayer.jsx";

const DISPLAY_WIDTH = 640; // fixed CSS px — the coordinate math below is
// built around this, not the image's native pixel size, so the render DPI
// (image quality) and the on-screen coordinate space are independent of
// each other.

export default function PageCanvas({
  uploadId,
  pageIndex,
  headerRatio,
  footerRatio,
  onChangeRatios,
  showHyphenHighlights = true,
  regions = [],
  onAddRegion,
  onRemoveRegion,
  autoBbox,
  autoBboxKey,
  onAutoResolved,
}) {
  const [pageInfo, setPageInfo] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setPageInfo(null);
    setError(null);
    fetchEditorPageInfo(uploadId, pageIndex)
      .then((info) => {
        if (!cancelled) setPageInfo(info);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Sayfa yüklenemedi.");
      });
    return () => {
      cancelled = true;
    };
  }, [uploadId, pageIndex]);

  if (error) {
    return <div className="page-canvas page-canvas--error">{error}</div>;
  }
  if (!pageInfo) {
    return <div className="page-canvas page-canvas--loading">Sayfa yükleniyor…</div>;
  }

  const displayHeight = DISPLAY_WIDTH * (pageInfo.height_pt / pageInfo.width_pt);

  return (
    <div className="page-canvas" style={{ width: DISPLAY_WIDTH, height: displayHeight }}>
      <img
        className="page-canvas__image"
        src={editorPageImageSrc(uploadId, pageIndex, 150)}
        alt={`Sayfa ${pageIndex + 1}`}
        width={DISPLAY_WIDTH}
        height={displayHeight}
        draggable={false}
      />
      {onAddRegion && (
        <BoundingBoxLayer
          uploadId={uploadId}
          pageIndex={pageIndex}
          width={DISPLAY_WIDTH}
          height={displayHeight}
          pageWidthPt={pageInfo.width_pt}
          pageHeightPt={pageInfo.height_pt}
          regions={regions}
          onAddRegion={onAddRegion}
          onRemoveRegion={onRemoveRegion}
          autoBbox={autoBbox}
          autoBboxKey={autoBboxKey}
          onAutoResolved={onAutoResolved}
        />
      )}
      <MaskLinesLayer
        width={DISPLAY_WIDTH}
        height={displayHeight}
        headerRatio={headerRatio}
        footerRatio={footerRatio}
        onChangeRatios={onChangeRatios}
      />
      {showHyphenHighlights && (
        <HyphenHighlightLayer
          uploadId={uploadId}
          pageIndex={pageIndex}
          width={DISPLAY_WIDTH}
          height={displayHeight}
          pageWidthPt={pageInfo.width_pt}
          pageHeightPt={pageInfo.height_pt}
        />
      )}
    </div>
  );
}
