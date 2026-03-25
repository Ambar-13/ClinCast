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
        background: "linear-gradient(135deg, #FFFFFF 0%, #F0F9FC 100%)",
        borderBottom: "1px solid var(--border-warm)",
      }}
    >
      {/* Logo */}
      <Link href="/" className="mr-6 flex flex-shrink-0 items-center gap-2">
        {/* Flask icon */}
        <svg viewBox="0 0 32 32" width="28" height="28" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 4v10L6 24a2 2 0 001.8 2.8h16.4A2 2 0 0026 24L20 14V4" stroke="#FED766" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M10 4h12" stroke="#FED766" strokeWidth="1.8" strokeLinecap="round"/>
          <circle cx="12" cy="22" r="1.5" fill="#07A0C3" opacity="0.9"/>
          <circle cx="17" cy="24" r="1" fill="#07A0C3" opacity="0.7"/>
          <circle cx="20" cy="21" r="1.2" fill="#07A0C3" opacity="0.8"/>
        </svg>
        <span className="hidden text-sm font-semibold sm:block" style={{ color: "var(--ink-900)" }}>
          ClinCast
        </span>
        <span
          className="hidden rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest sm:block"
          style={{ background: "rgba(7,160,195,0.10)", color: "var(--primary-700)", border: "1px solid rgba(7,160,195,0.20)" }}
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
              style={{ color: active ? "var(--primary-600)" : "var(--ink-400)" }}
            >
              <Icon size={14} />
              <span className="hidden sm:block">{label}</span>
              {active && (
                <span
                  className="absolute inset-x-1 -bottom-[1px] h-0.5 rounded-full"
                  style={{ background: "var(--primary-600)" }}
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
