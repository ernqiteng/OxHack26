import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SelectionProvider } from "@/lib/selection";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata = {
  title: "Tempo",
  description: "Battery trading for the GB electricity market, with a timing audit for every decision.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <SelectionProvider>{children}</SelectionProvider>
      </body>
    </html>
  );
}
