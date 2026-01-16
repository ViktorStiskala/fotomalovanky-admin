/**
 * Processing status check utilities.
 *
 * These helpers centralize the logic for checking if coloring/SVG versions
 * are in processing states, completed, or have errors.
 */

import type { ColoringVersion, SvgVersion, OrderImage } from "./api";

/**
 * Coloring statuses that indicate processing is in progress.
 */
export const COLORING_PROCESSING_STATUSES = [
  "queued",
  "processing",
  "runpod_submitting",
  "runpod_submitted",
  "runpod_queued",
  "runpod_processing",
] as const;

/**
 * SVG statuses that indicate processing is in progress.
 */
export const SVG_PROCESSING_STATUSES = ["queued", "processing", "vectorizer_processing"] as const;

/**
 * Check if any coloring version is currently being processed.
 */
export function isColoringProcessing(versions: ColoringVersion[]): boolean {
  return versions.some((cv) =>
    COLORING_PROCESSING_STATUSES.includes(
      cv.status as (typeof COLORING_PROCESSING_STATUSES)[number]
    )
  );
}

/**
 * Check if any SVG version is currently being processed.
 */
export function isSvgProcessing(versions: SvgVersion[]): boolean {
  return versions.some((sv) =>
    SVG_PROCESSING_STATUSES.includes(sv.status as (typeof SVG_PROCESSING_STATUSES)[number])
  );
}

/**
 * Check if there's at least one completed coloring version.
 */
export function hasCompletedColoring(versions: ColoringVersion[]): boolean {
  return versions.some((cv) => cv.status === "completed");
}

/**
 * Check if there's at least one completed SVG version.
 */
export function hasCompletedSvg(versions: SvgVersion[]): boolean {
  return versions.some((sv) => sv.status === "completed");
}

/**
 * Check if any version has an error status.
 */
export function hasColoringError(versions: ColoringVersion[]): boolean {
  return versions.some((cv) => cv.status === "error");
}

/**
 * Check if any SVG version has an error status.
 */
export function hasSvgError(versions: SvgVersion[]): boolean {
  return versions.some((sv) => sv.status === "error");
}

/**
 * Check if an image has been downloaded (has a URL).
 */
export function isImageDownloaded(image: OrderImage): boolean {
  return !!image.url;
}

/**
 * Check if an image is eligible for coloring generation.
 * Must be downloaded and not already have completed coloring or be processing.
 */
export function canGenerateColoring(image: OrderImage): boolean {
  if (!isImageDownloaded(image)) return false;
  const versions = image.versions.coloring;
  return !hasCompletedColoring(versions) && !isColoringProcessing(versions);
}

/**
 * Check if an image is eligible for SVG generation.
 * Must have completed coloring and not already have completed SVG or be processing.
 */
export function canGenerateSvg(image: OrderImage): boolean {
  const coloringVersions = image.versions.coloring;
  const svgVersions = image.versions.svg;
  return (
    hasCompletedColoring(coloringVersions) &&
    !hasCompletedSvg(svgVersions) &&
    !isSvgProcessing(svgVersions)
  );
}
