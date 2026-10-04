import {z} from 'zod';
import type {ConnectionView} from '../connections';
const integer=z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
export const localVerifyInput=z.object({store_id:z.uuid(),expected_generation:integer.positive()}).strict();
const channel=z.object({id:z.uuid(),ordinal:integer.min(1).max(256),label:z.string().max(11)}).strict().refine(v=>v.label===`Channel ${v.ordinal}`);
export const localDeviceSchema=z.object({
  connection_id:z.uuid(),device_id:z.uuid().nullable(),store_id:z.uuid(),
  connection_generation:integer.positive(),inventory_revision:integer,
  inventory_state:z.enum(['UNAVAILABLE','AVAILABLE','STALE']),
  observed_at:z.string().datetime({offset:true}).nullable(),channels:z.array(channel).max(256),
  request_id:z.string().min(1).max(64).regex(/^[A-Za-z0-9_.:-]+$/),
}).strict().superRefine((v,ctx)=>{
  if(v.inventory_state==='AVAILABLE' ? !v.device_id||!v.observed_at||v.inventory_revision<1 : v.channels.length>0) ctx.addIssue({code:'custom',message:'Invalid inventory'});
  if(new Set(v.channels.map(c=>c.id)).size!==v.channels.length||new Set(v.channels.map(c=>c.ordinal)).size!==v.channels.length) ctx.addIssue({code:'custom',message:'Duplicate channels'});
});
export type LocalDeviceView=z.infer<typeof localDeviceSchema>;
export type LocalBinding={connectionId:string;storeId:string;generation?:number};
export function localDeviceView(data:unknown,binding:LocalBinding,requestId?:string):LocalDeviceView {
  const v=localDeviceSchema.parse(data);
  if(v.connection_id!==binding.connectionId||v.store_id!==binding.storeId||(requestId!==undefined&&v.request_id!==requestId)) throw new Error('Invalid local device response');
  if(binding.generation!==undefined&&v.connection_generation!==binding.generation)throw new LocalDeviceError(409);
  return v;
}
export class LocalDeviceError extends Error {
  constructor(readonly status:number){super('Local device request failed');}
}
export const localDeviceMessage=(status:number)=>({
  401:'로그인이 만료되었습니다. 다시 로그인하세요.',403:'기기 확인은 조직 소유자만 사용할 수 있습니다.',
  404:'연결이나 매장을 사용할 수 없습니다.',409:'연결 정보가 변경되었거나 요청이 취소되었습니다. 최신 정보를 확인하세요.',
  422:'연결 정보와 선택한 매장을 확인하세요.',429:'기기를 확인하는 작업이 진행 중입니다. 잠시 후 다시 시도하세요.',
  502:'장치 응답을 확인할 수 없습니다. 연결 정보를 확인하세요.',503:'장치 확인 서비스를 사용할 수 없습니다.',
  504:'장치 확인 시간이 초과되었습니다. 연결 상태를 확인하세요.',
}[status]??'장치 정보를 확인할 수 없습니다.');
async function fetchView(tenantId:string,connection:ConnectionView,storeId:string,csrf:string,signal:AbortSignal,verify:boolean){
  if(!z.uuid().safeParse(tenantId).success||tenantId!==connection.tenant_id||!z.uuid().safeParse(connection.id).success||connection.kind!=='TVT_DEVICE'||connection.status==='DISCONNECTED'||!connection.store_ids.includes(storeId)) throw new LocalDeviceError(422);
  const body=localVerifyInput.parse({store_id:storeId,expected_generation:connection.generation});
  const url=`/api/local-devices/${connection.id}/${verify?'verify':'channels'}?tenant_id=${encodeURIComponent(tenantId)}${verify?'':`&store_id=${encodeURIComponent(storeId)}`}`;
  const response=await fetch(url,{method:verify?'POST':'GET',headers:verify?{'Content-Type':'application/json','X-CSRF-Token':csrf}:undefined,body:verify?JSON.stringify(body):undefined,credentials:'same-origin',cache:'no-store',redirect:'error',signal});
  signal.throwIfAborted();
  if(!response.ok) throw new LocalDeviceError(response.status);
  const requestId=response.headers.get('X-Request-ID');
  if(!requestId) throw new LocalDeviceError(503);
  const data=await response.json(); signal.throwIfAborted();
  return localDeviceView(data,{connectionId:connection.id,storeId,generation:connection.generation},requestId);
}
export const verifyLocalDevice=(tenantId:string,connection:ConnectionView,storeId:string,csrf:string,signal:AbortSignal)=>fetchView(tenantId,connection,storeId,csrf,signal,true);
export const readLocalDevice=(tenantId:string,connection:ConnectionView,storeId:string,signal:AbortSignal)=>fetchView(tenantId,connection,storeId,'',signal,false);
