import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          navy: "#0E2A47",
          "navy-soft": "#15355A",
          blue: "#185FA5",
          "blue-soft": "#E6F1FB",
          "blue-tint": "#F4F8FC",
          orange: "#F97316",
          "orange-soft": "#FFE6CF",
          "orange-tint": "#FFF6EE",
          ink: "#1F2A37",
          subtle: "#5C6B80",
          mute: "#8B95A7",
          line: "#E3E8EF",
          "line-soft": "#EEF2F7",
          surface: "#FFFFFF",
          "surface-soft": "#F6F8FB",
          warn: "#BA7517",
          "warn-soft": "#FAEEDA",
          danger: "#A32D2D",
          "danger-soft": "#FCEBEB",
          ok: "#3B6D11",
          "ok-soft": "#EAF3DE",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
        "pulse-warn": {
          "0%, 100%": {
            boxShadow: "0 0 0 0 rgba(249, 115, 22, 0.45)",
          },
          "50%": {
            boxShadow: "0 0 0 6px rgba(249, 115, 22, 0)",
          },
        },
        "pulse-highlight": {
          "0%, 100%": {
            boxShadow: "0 0 0 0 rgba(24, 95, 165, 0.45)",
          },
          "50%": {
            boxShadow: "0 0 0 8px rgba(24, 95, 165, 0)",
          },
        },
        "slide-in": {
          "0%": { transform: "translateX(20px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.25s ease-out both",
        "pulse-soft": "pulse-soft 1.6s ease-in-out infinite",
        "pulse-warn": "pulse-warn 1.6s ease-in-out infinite",
        "pulse-highlight": "pulse-highlight 1.4s ease-in-out infinite",
        "slide-in": "slide-in 0.25s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
