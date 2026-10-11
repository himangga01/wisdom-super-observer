import 'server-only';
import {randomUUID} from 'node:crypto';
import {NextRequest,NextResponse} from 'next/server';
import {z} from 'zod';
import {CSRF_COOKIE,SESSION_COOKIE,equalSecret,privateResponse,readAuthConfig} from '../auth';
import {boundedPrivateJson,withinAbort} from './local-device-proxy';
import {localLiveAnswer,localLiveInput,localLiveOffer,localLiveResponse,localLiveStarted,parseLocalLive,parseLocalLiveFailure} from './local-live-api';
import {localFocusInput,parseLocalFocus} from './local-live-wall-api';
const correlation=z.string().min(1).max(64).regex(/^[A-Za-z0-9_.:-]+$/);
function json(body:unknown,status:number,id:string){const value=privateResponse(NextResponse.json(body,{status}));value.headers.set('X-Request-ID',id);value.headers.set('Vary','Cookie');return value;}
function failed(status:number,id:string,code='LOCAL_DEVICE_UNAVAILABLE'){return json({error:{code,message:'Live request failed'},request_id:id},status,id);}
export async function proxyLocalLive(request:NextRequest,segments:string[],backendFetch:typeof fetch=fetch){
  let id=randomUUID() as string;const timer=AbortSignal.timeout(25000);const signal=AbortSignal.any([timer,request.signal]);
  try{
    const start=segments.length===0;const action=segments[1];const read=segments.length===1;
    if((!start&&!z.uuid().safeParse(segments[0]).success)||(!start&&!read&&(segments.length!==2||!['heartbeat','stop','webrtc-offer','playing','focus-reservations'].includes(action)))||request.nextUrl.pathname.endsWith('/')||/[%\\]/.test(request.nextUrl.pathname))return failed(404,id);
    if(request.method!==(read?'GET':'POST'))return failed(405,id);
    const query=request.nextUrl.searchParams;const tenant=query.get('tenant_id');const connection=query.get('connection_id');
    if(!z.uuid().safeParse(tenant).success||query.size!==(start?2:1)||(start&&!z.uuid().safeParse(connection).success))return failed(404,id);
    const session=request.cookies.get(SESSION_COOKIE)?.value;if(!session)return failed(401,id);
    const config=readAuthConfig();const csrf=request.cookies.get(CSRF_COOKIE)?.value??'';let input:unknown;
    if(!read){
      if(request.nextUrl.origin!==config.publicOrigin||request.headers.get('origin')!==config.publicOrigin||!csrf||!equalSecret(csrf,request.headers.get('x-csrf-token')??''))return failed(403,id);
      if(!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get('content-type')??''))return failed(422,id);
      try{const body=await boundedPrivateJson(new Response(request.body,{headers:request.headers}),action==='webrtc-offer'?262144:4096,signal);input=(start?localLiveInput:action==='webrtc-offer'?localLiveOffer:action==='playing'?localLiveStarted:action==='focus-reservations'?localFocusInput:z.object({}).strict()).parse(body);}
      catch{return failed(signal.aborted?504:422,id);}
    }
    const upstream=await withinAbort(backendFetch(`${config.apiOrigin}/api/v1/tvt/live-sessions${start?'':'/'+segments.join('/')}?tenant_id=${tenant}${start?`&connection_id=${connection}`:''}`,{method:request.method,cache:'no-store',redirect:'error',signal,headers:{Cookie:`${SESSION_COOKIE}=${session}`,...(!read?{Origin:config.publicOrigin,'X-CSRF-Token':csrf,'Content-Type':'application/json'}:{})},...(!read?{body:JSON.stringify(input)}:{})}),signal);
    try{
    if(!upstream.ok){
      let code:string|null=null;
      try{code=parseLocalLiveFailure(await boundedPrivateJson(upstream,4096,signal),upstream.status);}catch{void upstream.body?.cancel().catch(()=>undefined);}
      return failed([401,403,404,409,422,429,502,503,504].includes(upstream.status)?upstream.status:503,id,code??'LOCAL_DEVICE_UNAVAILABLE');
    }
    id=correlation.parse(upstream.headers.get('X-Request-ID'));const body=await boundedPrivateJson(upstream,262144,signal);
    let result:unknown;
    if(action==='focus-reservations'){result=parseLocalFocus(body,id,{leaseId:segments[0],direction:localFocusInput.parse(input).direction});}
    else if(action==='webrtc-offer'){const answer=localLiveAnswer.parse(body);if(answer.request_id!==id)throw new Error('Correlation');result=answer;}
    else{
      const view=localLiveResponse.parse(body);if(view.request_id!==id||view.lease.owner.tenant_id!==tenant||(!start&&view.lease.id!==segments[0]))throw new Error('Scope');
      if(start){const selection=localLiveInput.parse(input);parseLocalLive(view,{tenantId:tenant!,connectionId:connection!,storeId:selection.store_id,deviceId:selection.device_id,channelId:selection.channel_id,generation:selection.expected_generation,inventoryRevision:selection.inventory_revision},id);}
      result=view;
    }
    signal.throwIfAborted();return json(result,200,id);
    }finally{void upstream.body?.cancel().catch(()=>undefined);}
  }catch{return failed(signal.aborted?504:503,id);}
}
