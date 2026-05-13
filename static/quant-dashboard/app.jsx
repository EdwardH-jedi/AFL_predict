// App composition + Tweaks + live-data re-render hook.
// Sourced from the Claude Design handoff; the only modifications versus the
// prototype are:
//   1. a `version` counter bumped on `aflDataUpdate` so components re-read
//      window.AFLData after the live overlay fetches successfully;
//   2. a live-status banner driven by window.AFLLive (freshness/readiness/Discord).
const { useEffect, useState } = React;

function App() {
  const [tweaks, setTweak] = useTweaks({
    accent: "mint",
    density: "comfortable",
    showSparklines: true,
  });

  // Bump on every aflDataUpdate event so child components re-read window.AFLData
  // after the live overlay merges remote data on top of the mock defaults.
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const handler = () => setVersion((v) => v + 1);
    window.addEventListener("aflDataUpdate", handler);
    return () => window.removeEventListener("aflDataUpdate", handler);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    const map = {
      mint:   { c: "#5ef0b7", dim: "#2fa37a", dark: "#052016" },
      azure:  { c: "#6cb6ff", dim: "#3470b8", dark: "#04132b" },
      violet: { c: "#a78bfa", dim: "#6e51c8", dark: "#150a2c" },
      amber:  { c: "#f5c45e", dim: "#a87f25", dark: "#221700" },
    };
    const a = map[tweaks.accent] || map.mint;
    root.style.setProperty("--mint", a.c);
    root.style.setProperty("--mint-dim", a.dim);
  }, [tweaks.accent]);

  return (
    <>
      <div className="app" data-density={tweaks.density} data-data-version={version}>
        <window.Sidebar/>
        <main className="main">
          <window.TopBar/>
          <window.LiveStatusBanner/>
          <div className="content">
            <window.KpiStrip/>
            <window.PerformanceSection/>
            <window.DiagnosticsSection/>
            <window.BettingSection/>
            <window.SegmentsSection/>
            <window.PredictionsTable/>
          </div>
        </main>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection title="Accent">
          <TweakRadio
            value={tweaks.accent}
            options={[
              { value: "mint", label: "Mint" },
              { value: "azure", label: "Azure" },
              { value: "violet", label: "Violet" },
              { value: "amber", label: "Amber" },
            ]}
            onChange={(v) => setTweak("accent", v)}
          />
        </TweakSection>
        <TweakSection title="Density">
          <TweakRadio
            value={tweaks.density}
            options={[
              { value: "comfortable", label: "Comfortable" },
              { value: "compact", label: "Compact" },
            ]}
            onChange={(v) => setTweak("density", v)}
          />
        </TweakSection>
        <TweakSection title="Sparklines">
          <TweakToggle
            value={tweaks.showSparklines}
            onChange={(v) => setTweak("showSparklines", v)}
            label="Show in KPI cards"
          />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
