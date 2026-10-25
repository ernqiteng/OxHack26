"use client";

import { motion, useReducedMotion } from "motion/react";

type RevealProps = { children: React.ReactNode; className?: string; id?: string };

export default function Reveal({ children, className, id }: RevealProps) {
  const reduced = useReducedMotion();

  if (reduced) {
    return (
      <div id={id} className={className}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      id={id}
      className={className}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6, ease: [0, 0, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}
