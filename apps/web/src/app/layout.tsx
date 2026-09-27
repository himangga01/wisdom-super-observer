import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./tvt.css";

export const metadata: Metadata = {
  title: "Wisdom Super Observer",
  description: "Wisdom Super Observer web service",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-slate-50 text-slate-950 antialiased">
        {children}
      </body>
    </html>
  );
}
