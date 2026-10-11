import {z} from 'zod';

const positive=z.number().int().min(1).max(Number.MAX_SAFE_INTEGER);
const correlation=z.string().min(1).max(64).regex(/^[A-Za-z0-9_.:-]+$/);
const owner=z.object({tenant_id:z.uuid(),actor_user_id:z.uuid(),connection_id:z.uuid(),store_id:z.uuid()}).strict();
const device=owner.extend({device_id:z.uuid(),channel_id:z.uuid()}).strict();
export const localLiveLease=z.object({
  id:z.uuid(),owner,device,channel:z.uuid(),kind:z.literal('live'),
  state:z.enum(['REQUESTED','NEGOTIATING','PLAYING','STALLED','RECONNECTING','STOPPING','CLOSED']),
  expires_at:z.string().datetime({offset:true}),heartbeat_at:z.string().datetime({offset:true}),
  connection_generation:positive,inventory_revision:positive,grant_revision:positive,
}).strict().superRefine((value,ctx)=>{
  if(Object.keys(value.owner).some(k=>value.owner[k as keyof typeof value.owner]!==value.device[k as keyof typeof value.owner])||value.channel!==value.device.channel_id||Date.parse(value.heartbeat_at)>Date.parse(value.expires_at))ctx.addIssue({code:'custom',message:'Invalid local lease'});
});
export const localLiveResponse=z.object({lease:localLiveLease,request_id:correlation}).strict();
export const localLiveOffer=z.object({type:z.literal('offer'),sdp:z.string().min(1).max(131072),offer_id:z.uuid()}).strict();
export const localLiveAnswer=z.object({type:z.literal('answer'),sdp:z.string().min(1).max(131072),request_id:correlation}).strict();
export const localLiveInput=z.object({store_id:z.uuid(),device_id:z.uuid(),channel_id:z.uuid(),expected_generation:positive,inventory_revision:positive,stream:z.enum(['main','sub']),wall_id:z.uuid().optional(),focus_ref_id:z.uuid().optional()}).strict();
export const localLiveStarted=z.object({decoded_frames:positive}).strict();
export type LocalLiveBinding={tenantId:string;connectionId:string;storeId:string;deviceId:string;channelId:string;generation:number;inventoryRevision:number;stream?:'main'|'sub';wallId?:string;focusRefId?:string};
export type LocalLiveView=z.infer<typeof localLiveResponse>;
const localDeviceFailures:Readonly<Record<string,number>>={
  LOCAL_DEVICE_INPUT_INVALID:422,LOCAL_DEVICE_DENIED:404,LOCAL_DEVICE_GENERATION_CONFLICT:409,
  LOCAL_DEVICE_BUSY:429,LOCAL_DEVICE_CANCELLED:409,LOCAL_DEVICE_PROTOCOL_INVALID:502,
  LOCAL_DEVICE_UPSTREAM_REJECTED:502,LOCAL_DEVICE_UNAVAILABLE:503,
  LOCAL_DEVICE_DEADLINE_EXCEEDED:504,LOCAL_DEVICE_NO_SIGNAL:504,
};
const localLiveFailure=z.object({error:z.object({code:z.string().max(64),message:z.string().max(4096)}).strict(),request_id:correlation}).strict();
export function parseLocalLiveFailure(body:unknown,status:number):string|null{
  const parsed=localLiveFailure.safeParse(body);if(!parsed.success)return null;
  const code=parsed.data.error.code;
  return Object.hasOwn(localDeviceFailures,code)&&localDeviceFailures[code]===status?code:null;
}
export class LocalLiveError extends Error{constructor(readonly status:number,readonly code:string|null=null){super('Live session unavailable');}}
export function parseLocalLive(body:unknown,binding:LocalLiveBinding,requestId:string):LocalLiveView{
  const value=localLiveResponse.parse(body);const lease=value.lease;
  if(value.request_id!==requestId||lease.owner.tenant_id!==binding.tenantId||lease.owner.connection_id!==binding.connectionId||lease.owner.store_id!==binding.storeId||lease.device.device_id!==binding.deviceId||lease.channel!==binding.channelId||lease.connection_generation!==binding.generation||lease.inventory_revision!==binding.inventoryRevision)throw new LocalLiveError(502);
  return value;
}
async function boundedJson(response:Response,max:number,signal:AbortSignal){
  const length=response.headers.get('content-length');if(length!==null&&(!/^\d+$/.test(length)||Number(length)>max)){void response.body?.cancel().catch(()=>undefined);throw new LocalLiveError(502);}
  if(!response.body)throw new LocalLiveError(502);
  const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  const abort=()=>{void reader.cancel().catch(()=>undefined);};signal.addEventListener('abort',abort,{once:true});
  try{while(true){signal.throwIfAborted();const next=await reader.read();signal.throwIfAborted();if(next.done)break;size+=next.value.length;if(size>max)throw new LocalLiveError(502);chunks.push(next.value);}}
  finally{signal.removeEventListener('abort',abort);void reader.cancel().catch(()=>undefined);}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  signal.throwIfAborted();return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)) as unknown;
}
export async function localLiveRequest(path:string,csrf:string,signal:AbortSignal,body?:unknown,method:'POST'|'GET'='POST'){
  const timeout=AbortSignal.timeout(25000);const combined=AbortSignal.any([signal,timeout]);
  combined.throwIfAborted();
  let cancelled!:()=>void;
  const aborted=new Promise<never>((_,reject)=>{cancelled=()=>reject(combined.reason);combined.addEventListener('abort',cancelled,{once:true});});
  let response:Response;
  try{response=await Promise.race([fetch(path,{method,headers:method==='POST'?{'Content-Type':'application/json','X-CSRF-Token':csrf}:undefined,body:method==='POST'?JSON.stringify(body??{}):undefined,credentials:'same-origin',cache:'no-store',redirect:'error',signal:combined}),aborted]);}
  finally{combined.removeEventListener('abort',cancelled);}
  try{
  if(!response.ok){
    let code:string|null=null;
    try{code=parseLocalLiveFailure(await boundedJson(response,4096,combined),response.status);}catch{void response.body?.cancel().catch(()=>undefined);}
    throw new LocalLiveError(response.status,code);
  }
  const id=correlation.parse(response.headers.get('X-Request-ID'));
  return {body:await boundedJson(response,262144,combined),id};
  }finally{void response.body?.cancel().catch(()=>undefined);}
}
const request=localLiveRequest;
const route=(binding:LocalLiveBinding,leaseId?:string,action?:string)=>{
  for(const id of [binding.tenantId,binding.connectionId,...(leaseId?[leaseId]:[])])z.uuid().parse(id);
  return `/api/live-sessions${leaseId?`/${leaseId}/${action}`:''}?tenant_id=${binding.tenantId}${leaseId?'':`&connection_id=${binding.connectionId}`}`;
};
export async function startLocalLive(binding:LocalLiveBinding,csrf:string,signal:AbortSignal){
  const input=localLiveInput.parse({store_id:binding.storeId,device_id:binding.deviceId,channel_id:binding.channelId,expected_generation:binding.generation,inventory_revision:binding.inventoryRevision,stream:binding.stream??'main',...(binding.wallId!==undefined?{wall_id:binding.wallId}:{}),...(binding.focusRefId!==undefined?{focus_ref_id:binding.focusRefId}:{})});
  const response=await request(route(binding),csrf,signal,input);return parseLocalLive(response.body,binding,response.id);
}
export async function heartbeatLocalLive(binding:LocalLiveBinding,id:string,csrf:string,signal:AbortSignal){
  const result=await request(route(binding,id,'heartbeat'),csrf,signal);const value=parseLocalLive(result.body,binding,result.id);
  if(value.lease.id!==id)throw new LocalLiveError(502);return value;
}
export async function stopLocalLive(binding:LocalLiveBinding,id:string,csrf:string){
  const result=await request(route(binding,id,'stop'),csrf,new AbortController().signal);const value=parseLocalLive(result.body,binding,result.id);
  if(value.lease.id!==id)throw new LocalLiveError(502);return value;
}
export async function reportLocalLivePlaying(binding:LocalLiveBinding,id:string,csrf:string,decodedFrames:number,signal:AbortSignal){
  const result=await request(route(binding,id,'playing'),csrf,signal,localLiveStarted.parse({decoded_frames:decodedFrames}));
  const view=parseLocalLive(result.body,binding,result.id);if(view.lease.id!==id||view.lease.state!=='PLAYING')throw new LocalLiveError(502);return view;
}
export async function offerLocalLive(binding:LocalLiveBinding,id:string,csrf:string,sdp:string,signal:AbortSignal){
  const result=await request(route(binding,id,'webrtc-offer'),csrf,signal,localLiveOffer.parse({type:'offer',sdp,offer_id:crypto.randomUUID()}));
  const answer=localLiveAnswer.parse(result.body);if(answer.request_id!==result.id)throw new LocalLiveError(502);return {type:answer.type,sdp:answer.sdp};
}
