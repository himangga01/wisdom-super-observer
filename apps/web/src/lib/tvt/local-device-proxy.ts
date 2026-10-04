import 'server-only';
import {randomUUID} from 'node:crypto';
import {NextRequest,NextResponse} from 'next/server';
import {z} from 'zod';
import {CSRF_COOKIE,SESSION_COOKIE,equalSecret,privateResponse,readAuthConfig} from '../auth';
import {localDeviceView,localVerifyInput} from './local-device-api';
const requestIdSchema=z.string().min(1).max(64).regex(/^[A-Za-z0-9_.:-]+$/);
function json(value:unknown,status:number,id:string){const result=privateResponse(NextResponse.json(value,{status}));result.headers.set('Vary','Cookie');result.headers.set('X-Request-ID',id);return result;}
function failure(status:number,id:string){return json({error:{code:({401:'authentication_required',403:'csrf_rejected',404:'LOCAL_DEVICE_DENIED',405:'method_not_allowed',409:'LOCAL_DEVICE_GENERATION_CONFLICT',422:'LOCAL_DEVICE_INPUT_INVALID',429:'LOCAL_DEVICE_BUSY',502:'LOCAL_DEVICE_PROTOCOL_INVALID',503:'LOCAL_DEVICE_UNAVAILABLE',504:'LOCAL_DEVICE_DEADLINE_EXCEEDED'} as Record<number,string>)[status]??'LOCAL_DEVICE_UNAVAILABLE',message:'Local device request failed'},request_id:id},status,id);}
async function within<T>(promise:Promise<T>,signal:AbortSignal):Promise<T>{
  signal.throwIfAborted();let abort!:()=>void;
  const cancelled=new Promise<never>((_resolve,reject)=>{abort=()=>reject(new Error('Cancelled'));signal.addEventListener('abort',abort,{once:true});});
  try{return await Promise.race([promise,cancelled]);}finally{signal.removeEventListener('abort',abort);}
}
async function body(response:Response,max:number,signal:AbortSignal):Promise<unknown>{
  const length=response.headers.get('content-length');if(length!==null&&(!/^\d+$/.test(length)||Number(length)>max))throw new Error('Invalid body');
  if(!response.body)throw new Error('Invalid body');
  const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  const abort=()=>{void reader.cancel().catch(()=>undefined);};signal.addEventListener('abort',abort,{once:true});
  try{while(true){const next=await within(reader.read(),signal);signal.throwIfAborted();if(next.done)break;size+=next.value.length;if(size>max)throw new Error('Invalid body');chunks.push(next.value);}}
  finally{signal.removeEventListener('abort',abort);void reader.cancel().catch(()=>undefined);}
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
}
export async function proxyLocalDevice(request:NextRequest,segments:string[],backendFetch:typeof fetch=fetch){
  let id=randomUUID() as string;const timeout=new AbortController();const signal=AbortSignal.any([request.signal,timeout.signal]);const timer=setTimeout(()=>timeout.abort(),25000);
  try{
    const verify=segments.length===2&&segments[1]==='verify';const read=segments.length===2&&segments[1]==='channels';const list=segments.length===0;
    const params=request.nextUrl.searchParams;const tenant=params.get('tenant_id');let store=params.get('store_id');
    if((!verify&&!read&&!list)||(!list&&!z.uuid().safeParse(segments[0]).success)||!z.uuid().safeParse(tenant).success||request.nextUrl.pathname.endsWith('/')||/[%\\]/.test(request.nextUrl.pathname)||params.size!==(verify?1:2)||(!verify&&!z.uuid().safeParse(store).success))return failure(404,id);
    if(request.method!==(verify?'POST':'GET'))return failure(405,id);
    const session=request.cookies.get(SESSION_COOKIE)?.value;if(!session)return failure(401,id);
    const config=readAuthConfig();let payload:z.infer<typeof localVerifyInput>|undefined;
    const csrf=request.cookies.get(CSRF_COOKIE)?.value??'';
    if(verify){
      if(request.nextUrl.origin!==config.publicOrigin||request.headers.get('origin')!==config.publicOrigin||!csrf||!equalSecret(csrf,request.headers.get('x-csrf-token')??''))return failure(403,id);
      if(!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get('content-type')??''))return failure(422,id);
      try{payload=localVerifyInput.parse(await body(new Response(request.body,{headers:request.headers}),4096,signal));store=payload.store_id;}
      catch{return failure(signal.aborted?504:422,id);}
    }
    const query=`tenant_id=${tenant}${verify?'':`&store_id=${store}`}`;
    const response=await within(backendFetch(`${config.apiOrigin}/api/v1/tvt/local-devices${list?'':'/'+segments.join('/')}?${query}`,{method:request.method,cache:'no-store',redirect:'error',signal,headers:{Cookie:`${SESSION_COOKIE}=${session}`,...(verify?{Origin:config.publicOrigin,'X-CSRF-Token':csrf,'Content-Type':'application/json'}:{})},...(payload?{body:JSON.stringify(payload)}:{})}),signal);
    const correlation=response.headers.get('X-Request-ID');
    if(requestIdSchema.safeParse(correlation).success)id=correlation!;
    if(!response.ok){void response.body?.cancel().catch(()=>undefined);return failure([401,403,404,409,422,429,502,503,504].includes(response.status)?response.status:503,id);}
    if(!requestIdSchema.safeParse(correlation).success)return failure(503,id);
    const data=await body(response,1048576,signal);
    const result=list?z.array(z.unknown()).max(1000).parse(data).map(value=>{
      const connectionId=z.object({connection_id:z.uuid()}).parse(value).connection_id;
      return localDeviceView(value,{connectionId,storeId:store!},id);
    }):localDeviceView(data,{connectionId:segments[0],storeId:store!,generation:payload?.expected_generation},id);
    if(Array.isArray(result)&&new Set(result.map(v=>v.connection_id)).size!==result.length)throw new Error('Duplicate devices');
    signal.throwIfAborted();return json(result,200,id);
  }catch{return failure(signal.aborted?504:503,id);}finally{clearTimeout(timer);timeout.abort();}
}
