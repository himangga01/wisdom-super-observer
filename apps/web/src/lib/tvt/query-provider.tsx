"use client";
import { useEffect, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
export type TvtScope = { userId: string; tenantId: string; identityId?: string; storeId?: string; deviceId?: string };
export const startupKey = (scope: TvtScope) => ["tvt", scope.userId, scope.tenantId, scope.identityId ?? null, scope.storeId ?? null, scope.deviceId ?? null, "bootstrap"] as const;
export function TvtQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
  useEffect(() => {
    const clear = () => { void client.cancelQueries(); client.clear(); };
    const logout = (event: Event) => {
      if (event.target instanceof HTMLFormElement && new URL(event.target.action).pathname === "/api/auth/logout") clear();
    };
    document.addEventListener("submit", logout, true);
    window.addEventListener("pagehide", clear);
    return () => { document.removeEventListener("submit", logout, true); window.removeEventListener("pagehide", clear); clear(); };
  }, [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
