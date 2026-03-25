"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart2, GitCompareArrows, GitFork } from "lucide-react";

const NAV = [
  { href: "/",        label: "Simulate", icon: BarChart2 },
  { href: "/compare", label: "Compare",  icon: GitCompareArrows },
] as const;

export function TopNav() {
  const pathname = usePathname();

  return (
    <header
      className="sticky top-0 z-40 flex h-14 items-center border-b px-4 lg:px-8"
      style={{
        borderColor: "var(--border-warm)",
        background: `
          radial-gradient(ellipse 40% 80% at 20% 50%, rgba(250,240,220,0.9) 0%, transparent 70%),
          radial-gradient(ellipse 35% 70% at 75% 30%, rgba(253,250,246,0.95) 0%, transparent 70%),
          var(--cream-50)
        `,
        backgroundSize: "200% 200%",
        animation: "meshDrift 12s ease-in-out infinite",
      }}
    >
      {/* Logo */}
      <Link href="/" className="mr-6 flex flex-shrink-0 items-center gap-2">
        {/* Flask icon */}
        <svg viewBox="0 0 32 32" width="28" height="28" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 4v10L6 24a2 2 0 001.8 2.8h16.4A2 2 0 0026 24L20 14V4" stroke="#A82020" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M10 4h12" stroke="#A82020" strokeWidth="1.8" strokeLinecap="round"/>
          <circle cx="12" cy="22" r="1.5" fill="#A82020" opacity="0.7"/>
          <circle cx="17" cy="24" r="1" fill="#A82020" opacity="0.5"/>
          <circle cx="20" cy="21" r="1.2" fill="#A82020" opacity="0.6"/>
        </svg>
        <span className="hidden text-sm font-semibold sm:block" style={{ color: "var(--ink-900)" }}>
          ClinCast
        </span>
        <span
          className="hidden rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest sm:block"
          style={{ background: "rgba(139,26,26,0.08)", color: "var(--crimson-700)", border: "1px solid rgba(139,26,26,0.15)" }}
        >
          Apache 2.0
        </span>
      </Link>

      {/* Tabs */}
      <nav className="flex gap-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className="relative flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-150"
              style={{ color: active ? "var(--crimson-700)" : "var(--ink-400)" }}
            >
              <Icon size={14} />
              <span className="hidden sm:block">{label}</span>
              {active && (
                <span
                  className="absolute inset-x-1 -bottom-[1px] h-0.5 rounded-full"
                  style={{ background: "var(--crimson-700)" }}
                />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Right side */}
      <div className="ml-auto">
        <a
          href="https://github.com/Ambar-13/ClinCast"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors"
          style={{ color: "var(--ink-400)" }}
        >
          <GitFork size={15} />
          <span className="hidden sm:block">GitHub</span>
        </a>
      </div>
    </header>
  );
}
