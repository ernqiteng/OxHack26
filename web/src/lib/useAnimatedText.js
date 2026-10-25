"use client";

import { animate } from "framer-motion";
import { useEffect, useState } from "react";

/** Typewriter reveal, as in ICHack26's summary panel. */
export function useAnimatedText(text, duration = 3) {
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    setCursor(0);
    const controls = animate(0, text.length, {
      duration,
      ease: "easeOut",
      onUpdate: (latest) => setCursor(Math.floor(latest)),
    });
    return () => controls.stop();
  }, [text, duration]);

  return text.slice(0, cursor);
}
