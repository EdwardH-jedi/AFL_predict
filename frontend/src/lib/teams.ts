// Team brand palette — ported verbatim from the design bundle's data.jsx.
// Keyed by 3-letter abbreviation which matches Team.short_name on the backend.

export interface TeamBrand {
  name: string;
  abbr: string;
  color: string;
  accent: string;
}

export const TEAMS: Record<string, TeamBrand> = {
  RIC: { name: "Richmond", abbr: "RIC", color: "#000000", accent: "#FFD400" },
  CAR: { name: "Carlton", abbr: "CAR", color: "#0A1F44", accent: "#ffffff" },
  COL: { name: "Collingwood", abbr: "COL", color: "#111111", accent: "#ffffff" },
  ESS: { name: "Essendon", abbr: "ESS", color: "#C8102E", accent: "#000000" },
  GEE: { name: "Geelong", abbr: "GEE", color: "#1C3F94", accent: "#ffffff" },
  HAW: { name: "Hawthorn", abbr: "HAW", color: "#4D2004", accent: "#F6A01A" },
  MEL: { name: "Melbourne", abbr: "MEL", color: "#0F1E3D", accent: "#C8102E" },
  NTH: { name: "North Melbourne", abbr: "NTH", color: "#13386C", accent: "#ffffff" },
  STK: { name: "St Kilda", abbr: "STK", color: "#ED1B2F", accent: "#000000" },
  SYD: { name: "Sydney", abbr: "SYD", color: "#E1261C", accent: "#ffffff" },
  WCE: { name: "West Coast", abbr: "WCE", color: "#002B5C", accent: "#F2A900" },
  WBD: { name: "Western Bulldogs", abbr: "WBD", color: "#014A97", accent: "#C8102E" },
  BRL: { name: "Brisbane Lions", abbr: "BRL", color: "#7A0019", accent: "#FFD100" },
  ADE: { name: "Adelaide", abbr: "ADE", color: "#002B5C", accent: "#FFD100" },
  POR: { name: "Port Adelaide", abbr: "POR", color: "#008AAB", accent: "#000000" },
  FRE: { name: "Fremantle", abbr: "FRE", color: "#2A0D54", accent: "#ffffff" },
  GCS: { name: "Gold Coast", abbr: "GCS", color: "#D71920", accent: "#F8B31B" },
  GWS: { name: "GWS Giants", abbr: "GWS", color: "#F47920", accent: "#2B2B2B" },
};

// Fallback for teams the backend labels with something other than the 3-letter abbr.
export function teamBrand(code: string | null | undefined): TeamBrand {
  if (!code) return FALLBACK_BRAND;
  const upper = code.toUpperCase();
  return TEAMS[upper] ?? { ...FALLBACK_BRAND, abbr: upper.slice(0, 3), name: code };
}

const FALLBACK_BRAND: TeamBrand = {
  name: "Unknown",
  abbr: "?",
  color: "#192541",
  accent: "#e6ecf7",
};
