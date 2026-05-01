import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Construction Analyzer",
  description:
    "Cursor-style IDE for structural-engineering project intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-brand-surface text-brand-ink antialiased">
        {children}
      </body>
    </html>
  );
}
