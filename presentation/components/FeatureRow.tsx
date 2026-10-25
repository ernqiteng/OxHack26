import Reveal from "@/components/Reveal";

type FeatureRowProps = {
  id?: string;
  number: string;
  title: string;
  points: React.ReactNode[];
  diagram: React.ReactNode;
  reverse?: boolean;
};

export default function FeatureRow({ id, number, title, points, diagram, reverse }: FeatureRowProps) {
  return (
    <Reveal id={id} className="grid scroll-mt-24 items-center gap-10 lg:grid-cols-2 lg:gap-16">
      <div className={reverse ? "lg:order-2" : undefined}>
        <p className="font-mono text-xs tracking-[0.2em] text-text-secondary uppercase">{number}</p>
        <h3 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">{title}</h3>
        <ul className="mt-6 space-y-3 font-sans leading-relaxed">
          {points.map((point, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
              <span>{point}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="overflow-hidden rounded-xl border border-border-light bg-surface p-4 shadow-sm sm:p-6">
        {diagram}
      </div>
    </Reveal>
  );
}
