import type { ReactNode } from "react";

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}

export function SectionHeader({ title, subtitle, right }: SectionHeaderProps) {
  return (
    <div
      className="hstack"
      style={{
        justifyContent: "space-between",
        alignItems: "flex-end",
        marginBottom: 14,
      }}
    >
      <div>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {title}
        </h2>
        {subtitle && (
          <div style={{ fontSize: 12, color: "var(--text-mute)", marginTop: 2 }}>
            {subtitle}
          </div>
        )}
      </div>
      {right}
    </div>
  );
}
