import {NextRequest} from 'next/server';
import {proxyLocalWall} from '../../../../lib/tvt/local-live-wall-proxy';
export const dynamic='force-dynamic';
export const runtime='nodejs';
type Context={params:Promise<{segments?:string[]}>};
export async function GET(request:NextRequest,context:Context){return proxyLocalWall(request,(await context.params).segments??[]);}
export async function POST(request:NextRequest,context:Context){return proxyLocalWall(request,(await context.params).segments??[]);}
