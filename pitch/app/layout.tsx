import type { Metadata } from "next";
import localFont from "next/font/local";
import { Nav } from "@/components/Nav";
import { Progress } from "@/components/Progress";
import "./globals.css";

// Bundled (latin subset, from Google Fonts, OFL) so a build never depends on fetching fonts: next/font/google
// failed intermittently. Baskerville and Plex Sans are variable fonts; Plex Mono is two static weights.
const serif = localFont({
  src: [{ path: "./fonts/libre-baskerville.woff2", weight: "400 700" }],
  variable: "--font-baskerville",
});
const sans = localFont({
  src: [{ path: "./fonts/ibm-plex-sans.woff2", weight: "400 600" }],
  variable: "--font-plex-sans",
});
const mono = localFont({
  src: [
    { path: "./fonts/ibm-plex-mono-400.woff2", weight: "400" },
    { path: "./fonts/ibm-plex-mono-500.woff2", weight: "500" },
  ],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "Tempo",
  description: "Forecasts GB electricity prices, decides when a battery should charge, sell or hold, and proves it picked the right moment.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body className="antialiased">
        <Nav />
        <Progress />
        {children}
      </body>
    </html>
  );
}
