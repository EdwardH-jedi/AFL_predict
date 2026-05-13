export interface TabDef {
  id: string;
  label: string;
  short: string;
  badge?: string | number;
}

interface TabNavProps {
  tabs: TabDef[];
  current: string;
  onSelect: (id: string) => void;
}

export function TabNav({ tabs, current, onSelect }: TabNavProps) {
  return (
    <nav
      style={{
        maxWidth: 1320,
        margin: "0 auto",
        padding: "0 24px",
        borderBottom: "1px solid var(--line)",
        display: "flex",
        gap: 2,
        overflowX: "auto",
        background: "var(--bg-0)",
        position: "sticky",
        top: 65,
        zIndex: 19,
      }}
    >
      {tabs.map((tab) => {
        const active = current === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onSelect(tab.id)}
            style={{
              padding: "13px 16px",
              background: "transparent",
              border: "none",
              borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}`,
              color: active ? "var(--text)" : "var(--text-dim)",
              fontFamily: "inherit",
              fontSize: 13,
              fontWeight: active ? 600 : 500,
              cursor: "pointer",
              transition: "color 120ms, border-color 120ms",
              display: "flex",
              alignItems: "center",
              gap: 8,
              whiteSpace: "nowrap",
            }}
          >
            <span>{tab.label}</span>
            {tab.badge != null && tab.badge !== "" && (
              <span
                style={{
                  background: active ? "rgba(125,211,252,0.15)" : "var(--bg-3)",
                  color: active ? "var(--accent)" : "var(--text-mute)",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 10,
                  fontWeight: 600,
                  padding: "1px 6px",
                  borderRadius: 4,
                  minWidth: 16,
                  textAlign: "center",
                }}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
