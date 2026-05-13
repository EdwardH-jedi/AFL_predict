import { TEAMS, teamBrand } from "@/lib/teams";

interface CrestProps {
  code: string | null | undefined;
  size?: number;
}

export function Crest({ code, size = 32 }: CrestProps) {
  const brand = code && TEAMS[code.toUpperCase()] ? TEAMS[code.toUpperCase()] : teamBrand(code);
  return (
    <div
      className="crest"
      title={brand.name}
      style={{
        width: size,
        height: size,
        background: `linear-gradient(135deg, ${brand.color} 0%, ${brand.color}cc 100%)`,
        fontSize: size * 0.34,
        color: brand.accent,
      }}
    >
      {brand.abbr}
    </div>
  );
}
