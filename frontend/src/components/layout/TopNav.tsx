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
        {/* Flask + pill + medical cross + robot */}
        <svg viewBox="0 0 50 32" width="44" height="28" fill="none" xmlns="http://www.w3.org/2000/svg">
          {/* Flask */}
          <path d="M14 3v10L7 24a2 2 0 001.8 2.8h16.4A2 2 0 0027 24L20 13V3" stroke="#FED766" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M11 3h12" stroke="#FED766" strokeWidth="1.8" strokeLinecap="round"/>
          {/* Bubbles */}
          <circle cx="13" cy="22" r="1.4" fill="#07A0C3" opacity="0.9"/>
          <circle cx="18" cy="24.5" r="1" fill="#07A0C3" opacity="0.7"/>
          <circle cx="21.5" cy="21.5" r="1.1" fill="#07A0C3" opacity="0.85"/>
          {/* Pill capsule falling into flask (tilted) */}
          <g transform="translate(17.5,6.5) rotate(25)">
            <rect x="-5.5" y="-2.2" width="5.5" height="4.4" fill="#07A0C3" opacity="0.95"/>
            <path d="M-5.5,-2.2 a2.2,2.2 0 0,0 0,4.4 z" fill="#07A0C3" opacity="0.95"/>
            <rect x="0" y="-2.2" width="5.5" height="4.4" fill="white" opacity="0.9"/>
            <path d="M5.5,-2.2 a2.2,2.2 0 0,1 0,4.4 z" fill="white" opacity="0.9"/>
            <line x1="0" y1="-2.2" x2="0" y2="2.2" stroke="#07A0C3" strokeWidth="0.5"/>
          </g>
          {/* Medical plus (top-left of flask) */}
          <rect x="4" y="5"   width="1.6" height="5.5" rx="0.7" fill="#e84040" opacity="0.9"/>
          <rect x="2" y="6.8" width="5.5" height="1.6" rx="0.7" fill="#e84040" opacity="0.9"/>
          {/* Robot antenna */}
          <line x1="43" y1="14" x2="43" y2="10" stroke="#07A0C3" strokeWidth="1.2" strokeLinecap="round"/>
          <circle cx="43" cy="9" r="1.3" fill="#07A0C3"/>
          {/* Robot head */}
          <rect x="37.5" y="14" width="11" height="9" rx="2.2" fill="#07A0C3"/>
          {/* Eyes */}
          <circle cx="40.5" cy="18" r="1.4" fill="white" opacity="0.95"/>
          <circle cx="45.5" cy="18" r="1.4" fill="white" opacity="0.95"/>
          {/* Pupils */}
          <circle cx="41" cy="18.3" r="0.6" fill="#086788"/>
          <circle cx="46" cy="18.3" r="0.6" fill="#086788"/>
          {/* Smile */}
          <path d="M40 21.5 Q43 23 47 21.5" stroke="white" strokeWidth="0.8" strokeLinecap="round" fill="none" opacity="0.75"/>
          {/* Medical cross on robot forehead */}
          <rect x="42.2" y="15" width="1.2" height="3.5" rx="0.5" fill="white" opacity="0.85"/>
          <rect x="40.8" y="16.2" width="4" height="1.2" rx="0.5" fill="white" opacity="0.85"/>
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
