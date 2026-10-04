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
export const localLiveInput=z.object({store_id:z.uuid(),device_id:z.uuid(),channel_id:z.uuid(),expected_generation:positive,inventory_revision:positive,stream:z.enum(['main','sub'])}).strict();
export const localLiveStarted=z.object({decoded_frames:positive}).strict();
export type LocalLiveBinding={tenantId:string;connectionId:string;storeId:string;deviceId:string;channelId:string;generation:number;inventoryRevision:number};
export type LocalLiveView=z.infer<typeof localLiveResponse>;
export class LocalLiveError extends Error{constructor(readonly status:number){super('Live session unavailable');}}
export function parseLocalLive(body:unknown,binding:LocalLiveBinding,requestId:string):LocalLiveView{
  const value=localLiveResponse.parse(body);const lease=value.lease;
  if(value.request_id!==requestId||lease.owner.tenant_id!==binding.tenantId||lease.owner.connection_id!==binding.connectionId||lease.owner.store_id!==binding.storeId||lease.device.device_id!==binding.deviceId||lease.channel!==binding.channelId||lease.connection_generation!==binding.generation||lease.inventory_revision!==binding.inventoryRevision)throw new LocalLiveError(502);
  return value;
}
async function request(path:string,csrf:string,signal:AbortSignal,body?:unknown){
  const timeout=AbortSignal.timeout(25000);const combined=AbortSignal.any([signal,timeout]);
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body??{}),credentials:'same-origin',cache:'no-store',redirect:'error',signal:combined});
  if(!response.ok)throw new LocalLiveError(response.status);
  const id=correlation.parse(response.headers.get('X-Request-ID'));
  const length=response.headers.get('content-length');if(length&&(!/^\d+$/.test(length)||Number(length)>262144))throw new LocalLiveError(502);
  if(!response.body)throw new LocalLiveError(502);
  const reader=response.body.getReader();const chunks:Uint8Array[]=[];let size=0;
  try{while(true){combined.throwIfAborted();const next=await reader.read();if(next.done)break;size+=next.value.length;if(size>262144)throw new LocalLiveError(502);chunks.push(next.value);}}
  finally{void reader.cancel().catch(()=>undefined);}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  combined.throwIfAborted();return {body:JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)),id};
}
const route=(binding:LocalLiveBinding,leaseId?:string,action?:string)=>{
  for(const id of [binding.tenantId,binding.connectionId,...(leaseId?[leaseId]:[])])z.uuid().parse(id);
  return `/api/live-sessions${leaseId?`/${leaseId}/${action}`:''}?tenant_id=${binding.tenantId}${leaseId?'':`&connection_id=${binding.connectionId}`}`;
};
export async function startLocalLive(binding:LocalLiveBinding,csrf:string,signal:AbortSignal){
  const input=localLiveInput.parse({store_id:binding.storeId,device_id:binding.deviceId,channel_id:binding.channelId,expected_generation:binding.generation,inventory_revision:binding.inventoryRevision,stream:'main'});
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
