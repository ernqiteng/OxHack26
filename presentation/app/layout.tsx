import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Libre_Baskerville } from "next/font/google";
import IntroOverlay from "@/components/IntroOverlay";
import Nav from "@/components/Nav";
import "./globals.css";

const libreBaskerville = Libre_Baskerville({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-libre-baskerville",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "Tempo",
  icons: { icon: "/logo.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-intro="hold"
      className={`${libreBaskerville.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <body className="min-h-screen antialiased">
        <IntroOverlay />
        <Nav />
        {children}
      </body>
    </html>
  );
}
