import type { Metadata } from "next";
import InfoPage from "@/components/InfoPage";
import { aboutEyebrow, aboutLead, aboutSections, aboutTitle } from "@/components/about";

export const metadata: Metadata = { title: "About · Tempo" };

export default function About() {
  return <InfoPage eyebrow={aboutEyebrow} title={aboutTitle} lead={aboutLead} sections={aboutSections} />;
}
