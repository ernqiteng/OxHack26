export type Section = {
  heading: string;
  body: React.ReactNode;
};

type InfoContentProps = {
  eyebrow: string;
  title: string;
  lead: string;
  sections: Section[];
};

export function InfoContent({ eyebrow, title, lead, sections }: InfoContentProps) {
  return (
    <>
      <p className="font-mono text-xs tracking-[0.2em] text-text-secondary uppercase">{eyebrow}</p>
      <h1 className="mt-4 text-[2.5rem] leading-[1.05] font-bold tracking-tight sm:text-[3.75rem]">
        {title}
      </h1>
      <p className="mt-6 max-w-xl font-sans text-lg leading-relaxed text-text-secondary">{lead}</p>
      {sections.map((section) => (
        <section key={section.heading} className="mt-16">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{section.heading}</h2>
          <div className="mt-4 space-y-4 font-sans leading-relaxed [&_li]:mt-2 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-5">
            {section.body}
          </div>
        </section>
      ))}
    </>
  );
}

export default function InfoPage(props: InfoContentProps) {
  return (
    <main className="mx-auto max-w-3xl px-4 pt-32 pb-24 sm:px-6">
      <InfoContent {...props} />
    </main>
  );
}
