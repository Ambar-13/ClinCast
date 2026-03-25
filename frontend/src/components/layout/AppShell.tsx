import type { ReactNode } from "react";
import { TopNav } from "@/components/layout/TopNav";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen" style={{ background: "var(--cream-50)" }}>
      <TopNav />
      <main className="pb-12">{children}</main>
    </div>
  );
}
