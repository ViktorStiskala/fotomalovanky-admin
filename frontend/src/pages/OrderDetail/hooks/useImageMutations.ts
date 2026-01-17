/**
 * Custom hook for image-related mutations.
 *
 * Centralizes all the mutation logic for generating coloring/SVG,
 * selecting versions, and retrying failed versions.
 */

import { useMutation } from "@tanstack/react-query";
import {
  generateImageColoring,
  generateImageSvg,
  selectColoringVersion,
  selectSvgVersion,
  retryColoringVersion,
  retrySvgVersion,
  type ColoringSettings,
  type SvgSettings,
} from "@/lib/api";
import { getGetOrderQueryKey } from "@/api/generated/orders/orders";
import { queryClient } from "@/lib/queryClient";

interface UseImageMutationsOptions {
  imageId: number;
  shopifyId: number;
  onColoringGenerated?: () => void;
  onSvgGenerated?: () => void;
}

export function useImageMutations({
  imageId,
  shopifyId,
  onColoringGenerated,
  onSvgGenerated,
}: UseImageMutationsOptions) {
  // Generate coloring mutation
  const generateColoringMutation = useMutation({
    mutationFn: (settings: ColoringSettings) => generateImageColoring(imageId, settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
      onColoringGenerated?.();
    },
  });

  // Generate SVG mutation
  const generateSvgMutation = useMutation({
    mutationFn: (settings: SvgSettings) => generateImageSvg(imageId, settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
      onSvgGenerated?.();
    },
  });

  // Select coloring version mutation
  const selectColoringMutation = useMutation({
    mutationFn: (versionId: number) => selectColoringVersion(imageId, versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
    },
  });

  // Select SVG version mutation
  const selectSvgMutation = useMutation({
    mutationFn: (versionId: number) => selectSvgVersion(imageId, versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
    },
  });

  // Retry coloring version mutation
  const retryColoringMutation = useMutation({
    mutationFn: (versionId: number) => retryColoringVersion(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
    },
  });

  // Retry SVG version mutation
  const retrySvgMutation = useMutation({
    mutationFn: (versionId: number) => retrySvgVersion(versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
    },
  });

  return {
    generateColoringMutation,
    generateSvgMutation,
    selectColoringMutation,
    selectSvgMutation,
    retryColoringMutation,
    retrySvgMutation,
  };
}
