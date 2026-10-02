import type { ReactNode } from "react";
import type { Bootstrap } from "../../../lib/tvt/api-client";
export function allowedLocalPath(path: string, bootstrap: Bootstrap) {
  return path === "/tvt" || bootstrap.menu.some(item => item.path === path && ((item.id === "local-settings" && path === "/tvt/settings") || (item.id === "local-account" && path === "/tvt/account")));
}
export function DeepLinkResolver({ path, bootstrap, children }: { path: string; bootstrap: Bootstrap; children: ReactNode }) {
  if (!allowedLocalPath(path, bootstrap)) return <div className="wso-card p-6"><p role="alert">이 페이지를 사용할 수 없습니다.</p><a className="wso-button-secondary mt-4" href={`/tvt?tenant_id=${encodeURIComponent(bootstrap.selected_tenant_id)}`}>SuperLivePlus 홈으로 이동</a></div>;
  return children;
}
