import 'server-only';
import {randomUUID} from 'node:crypto';
import {NextRequest,NextResponse} from 'next/server';
import {z} from 'zod';
import {CSRF_COOKIE,SESSION_COOKIE,equalSecret,privateResponse,readAuthConfig} from '../auth';
import {boundedPrivateJson,withinAbort} from './local-device-proxy';
import {parseLocalLiveFailure} from './local-live-api';
import {localFocusSettleInput,parseLocalFocus,parseLocalWall} from './local-live-wall-api';

const correlation=z.string().min(1).max(64).regex(/^[A-Za-z0-9_.:-]+$/);
function json(body:unknown,status:number,id:string){const response=privateResponse(NextResponse.json(body,{status}));response.headers.set('X-Request-ID',id);response.headers.set('Vary','Cookie');return response;}
function failed(status:number,id:string,code='LOCAL_DEVICE_UNAVAILABLE'){return json({error:{code,message:'Live request failed'},request_id:id},status,id);}
export async function proxyLocalWall(request:NextRequest,segments:string[],backendFetch:typeof fetch=fetch){
  let id=randomUUID() as string;const signal=AbortSignal.any([AbortSignal.timeout(25000),request.signal]);
  try{
    const create=segments.length===0;const read=segments.length===1&&z.uuid().safeParse(segments[0]).success;
    const control=segments.length===2&&z.uuid().safeParse(segments[0]).success&&['heartbeat','stop'].includes(segments[1]);
    const settle=segments.length===4&&z.uuid().safeParse(segments[0]).success&&segments[1]==='focus-reservations'&&z.uuid().safeParse(segments[2]).success&&segments[3]==='settle';
    if((!create&&!read&&!control&&!settle)||request.nextUrl.pathname.endsWith('/')||/[%\\]/.test(request.nextUrl.pathname))return failed(404,id);
    if(request.method!==(read?'GET':'POST'))return failed(405,id);
    const query=request.nextUrl.searchParams;const tenant=query.get('tenant_id');
    if(query.size!==1||!z.uuid().safeParse(tenant).success)return failed(404,id);
    const session=request.cookies.get(SESSION_COOKIE)?.value;if(!session)return failed(401,id);
    const config=readAuthConfig();const csrf=request.cookies.get(CSRF_COOKIE)?.value??'';let input:unknown;
    if(!read){
      if(request.nextUrl.origin!==config.publicOrigin||request.headers.get('origin')!==config.publicOrigin||!csrf||!equalSecret(csrf,request.headers.get('x-csrf-token')??''))return failed(403,id);
      if(!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get('content-type')??''))return failed(422,id);
      try{input=(settle?localFocusSettleInput:z.object({}).strict()).parse(await boundedPrivateJson(new Response(request.body,{headers:request.headers}),4096,signal));}catch{return failed(signal.aborted?504:422,id);}
    }
    signal.throwIfAborted();
    const upstream=await withinAbort(backendFetch(`${config.apiOrigin}/api/v1/tvt/live-walls${create?'':'/'+segments.join('/')}?tenant_id=${tenant}`,{method:request.method,cache:'no-store',redirect:'error',signal,headers:{Cookie:`${SESSION_COOKIE}=${session}`,...(!read?{Origin:config.publicOrigin,'X-CSRF-Token':csrf,'Content-Type':'application/json'}:{})},...(!read?{body:JSON.stringify(input)}:{})}),signal);
    try{
    if(!upstream.ok){let code:string|null=null;try{code=parseLocalLiveFailure(await boundedPrivateJson(upstream,4096,signal),upstream.status);}catch{void upstream.body?.cancel().catch(()=>undefined);}return failed([401,403,404,409,422,429,502,503,504].includes(upstream.status)?upstream.status:503,id,code??'LOCAL_DEVICE_UNAVAILABLE');}
    id=correlation.parse(upstream.headers.get('X-Request-ID'));const body=await boundedPrivateJson(upstream,262144,signal);
    const view=settle?parseLocalFocus(body,id,{wallId:segments[0],referenceId:segments[2]}):parseLocalWall(body,tenant!,id,create?undefined:segments[0]);
    signal.throwIfAborted();return json(view,200,id);
    }finally{void upstream.body?.cancel().catch(()=>undefined);}
  }catch{return failed(signal.aborted?504:503,id);}
}
