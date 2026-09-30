"use client";
import { useEffect } from "react";
export function SessionRefresh({ expiresAt }: { expiresAt: string }) {
  useEffect(() => {
    const onShow = (event: PageTransitionEvent) => { if (event.persisted) window.location.reload(); };
    const onFocus = () => { if (Date.parse(expiresAt) <= Date.now()) window.location.reload(); };
    window.addEventListener("pageshow", onShow);
    window.addEventListener("focus", onFocus);
    const timer = window.setTimeout(() => window.location.reload(), Math.min(2_147_483_647, Math.max(0, Date.parse(expiresAt) - Date.now())));
    return () => { clearTimeout(timer); window.removeEventListener("pageshow", onShow); window.removeEventListener("focus", onFocus); };
  }, [expiresAt]);
  return null;
}
