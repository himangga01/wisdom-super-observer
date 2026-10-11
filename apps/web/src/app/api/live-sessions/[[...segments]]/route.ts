import {NextRequest} from 'next/server';
import {proxyLocalLive} from '../../../../lib/tvt/local-live-proxy';
export const runtime='nodejs';
export const dynamic='force-dynamic';
type Context={params:Promise<{segments?:string[]}>};
export async function GET(request:NextRequest,context:Context){return proxyLocalLive(request,(await context.params).segments??[]);}
export async function POST(request:NextRequest,context:Context){return proxyLocalLive(request,(await context.params).segments??[]);}
