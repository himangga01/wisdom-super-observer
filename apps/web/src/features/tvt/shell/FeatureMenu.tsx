import type { Bootstrap } from "../../../lib/tvt/api-client";
export function FeatureMenu({ bootstrap, path }: { bootstrap: Bootstrap; path: string }) {
  return <nav aria-label="SuperLivePlus 메뉴" className="flex flex-wrap gap-3">
    <a className="wso-button-secondary" href={`/tvt?tenant_id=${encodeURIComponent(bootstrap.selected_tenant_id)}`} aria-current={path === "/tvt" ? "page" : undefined}>홈</a>
    {bootstrap.menu.filter(item => (item.id === "local-settings" && item.path === "/tvt/settings") || (item.id === "local-account" && item.path === "/tvt/account") || (item.id === "local-devices" && item.label === "Devices" && item.path === "/tvt/devices")).map(item => <a className="wso-button-secondary" key={item.id} href={`${item.path}?tenant_id=${encodeURIComponent(bootstrap.selected_tenant_id)}`} aria-current={path === item.path ? "page" : undefined}>{item.id === "local-devices" ? "장치" : item.id === "local-account" ? "계정" : "설정"}</a>)}
  </nav>;
}
