import { NextRequest } from "next/server";
import { proxyConnection } from "../../../../lib/connection-proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function handle(
  request: NextRequest,
  context: { params: Promise<{ segments?: string[] }> },
) {
  return proxyConnection(request, (await context.params).segments ?? []);
}
export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
