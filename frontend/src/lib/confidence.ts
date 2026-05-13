// Map an edge value (model_prob - implied_prob) to the design's confidence
// ladder.  Thresholds match the intent expressed in the design data:
//   ≥ 8%  → strong  (fire)
//   ≥ 5%  → moderate (green)
//   ≥ 3%  → marginal (amber)
//   else  → none     (mute)

export type ConfidenceLevel = "strong" | "moderate" | "marginal" | "none";

export function edgeToConfidence(edge: number | null | undefined): ConfidenceLevel {
  if (edge == null) return "none";
  if (edge >= 0.08) return "strong";
  if (edge >= 0.05) return "moderate";
  if (edge >= 0.03) return "marginal";
  return "none";
}
