import type { Bootstrap } from "../../../lib/tvt/api-client";
export function FeatureMenu({ bootstrap, path }: { bootstrap: Bootstrap; path: string }) {
  return <nav aria-label="SuperLivePlus 메뉴" className="flex flex-wrap gap-3">
    <a className="wso-button-secondary" href={`/tvt?tenant_id=${encodeURIComponent(bootstrap.selected_tenant_id)}`} aria-current={path === "/tvt" ? "page" : undefined}>홈</a>
    {bootstrap.menu.filter(item => item.id === "local-settings" && item.path === "/tvt/settings").map(item => <a className="wso-button-secondary" key={item.id} href={`${item.path}?tenant_id=${encodeURIComponent(bootstrap.selected_tenant_id)}`} aria-current={path === item.path ? "page" : undefined}>설정</a>)}
  </nav>;
}
