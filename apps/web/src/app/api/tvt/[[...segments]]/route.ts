import { NextRequest } from "next/server";
import { proxyTvt } from "../../../../lib/tvt/proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function handle(request: NextRequest, context: { params: Promise<{ segments?: string[] }> }) {
  return proxyTvt(request, (await context.params).segments ?? []);
}
export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE, handle as HEAD, handle as OPTIONS };
