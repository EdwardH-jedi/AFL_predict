/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Design tokens ported verbatim from the claude.ai handoff bundle.
        "bg-0": "#080d1a",
        "bg-1": "#111b30",
        "bg-2": "#192541",
        "bg-3": "#223152",
        "bg-4": "#2c3e66",
        line: "#2a3a5c",
        "line-strong": "#3a4d75",
        text: "#e6ecf7",
        "text-dim": "#93a0bd",
        "text-mute": "#5a6782",
        accent: "#7dd3fc",
        green: "#10b981",
        "green-dim": "#064e3b",
        red: "#ef4444",
        "red-dim": "#4c1d24",
        amber: "#f59e0b",
        purple: "#a78bfa",
        fire: "#fb923c",
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
