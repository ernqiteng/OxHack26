"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const links = [
  { label: "About", href: "/#about" },
  { label: "Tiger Data", href: "/tiger-data/" },
  { label: "Vultr", href: "/vultr/" },
];

export default function Nav() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 0);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`intro-rise fixed inset-x-0 top-0 z-50 h-16 border-b bg-background transition-colors duration-300 ${
        scrolled ? "border-brand" : "border-transparent"
      }`}
    >
      <nav className="mx-auto flex h-full max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link href="/" aria-label="Tempo home" className="shrink-0">
          <img src="/logo.png" alt="Tempo logo" className="h-10 w-10" />
        </Link>
        <ul className="flex items-center gap-4 font-sans text-xs font-semibold tracking-[0.1em] uppercase sm:gap-10 sm:text-sm">
          {links.map((link) => {
            const active = pathname.replace(/\/?$/, "/") === link.href;
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={`transition-colors hover:text-foreground ${
                    active ? "text-foreground" : "text-text-secondary"
                  }`}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="w-10 shrink-0" aria-hidden />
      </nav>
    </header>
  );
}
