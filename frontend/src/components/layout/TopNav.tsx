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
        {/* Flask (thick walls) + robot with medical cross */}
        <svg viewBox="0 0 44 32" width="40" height="28" fill="none" xmlns="http://www.w3.org/2000/svg">
          {/* Flask */}
          <path d="M13 3v10L6 24a2 2 0 001.8 2.8h16.4A2 2 0 0026 24L19 13V3" stroke="#FED766" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M10 3h12" stroke="#FED766" strokeWidth="2.4" strokeLinecap="round"/>
          {/* Bubbles */}
          <circle cx="12" cy="22" r="1.4" fill="#07A0C3" opacity="0.9"/>
          <circle cx="16.5" cy="24" r="1" fill="#07A0C3" opacity="0.7"/>
          <circle cx="20" cy="21.5" r="1.1" fill="#07A0C3" opacity="0.85"/>
          {/* Robot antenna */}
          <line x1="37" y1="13" x2="37" y2="9.5" stroke="#07A0C3" strokeWidth="1.2" strokeLinecap="round"/>
          <circle cx="37" cy="8.5" r="1.3" fill="#07A0C3"/>
          {/* Robot head */}
          <rect x="31.5" y="13" width="11" height="9" rx="2.2" fill="#07A0C3"/>
          {/* Eyes */}
          <circle cx="34.5" cy="17" r="1.4" fill="white" opacity="0.95"/>
          <circle cx="39.5" cy="17" r="1.4" fill="white" opacity="0.95"/>
          {/* Pupils */}
          <circle cx="35" cy="17.3" r="0.6" fill="#086788"/>
          <circle cx="40" cy="17.3" r="0.6" fill="#086788"/>
          {/* Smile */}
          <path d="M34 21 Q37 22.5 41 21" stroke="white" strokeWidth="0.8" strokeLinecap="round" fill="none" opacity="0.75"/>
          {/* Medical cross on robot forehead */}
          <rect x="36.4" y="14" width="1.2" height="3.5" rx="0.5" fill="white" opacity="0.85"/>
          <rect x="35" y="15.2" width="4" height="1.2" rx="0.5" fill="white" opacity="0.85"/>
        </svg>
        <span className="hidden text-sm font-semibold sm:block" style={{ color: "var(--ink-900)" }}>
          ClinFish
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
          href="https://github.com/Ambar-13/ClinFish"
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
