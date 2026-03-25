import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "@/components/layout/Providers";

const geistSans = localFont({
  src: "./GeistVF.woff",
  variable: "--font-inter",
  display: "swap",
  weight: "100 900",
});

const geistMono = localFont({
  src: "./GeistMonoVF.woff",
  variable: "--font-jetbrains-mono",
  display: "swap",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "ClinCast",
  description: "Open-source behavioral simulation engine for clinical trials. Apache 2.0.",
  themeColor: "#086788",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
