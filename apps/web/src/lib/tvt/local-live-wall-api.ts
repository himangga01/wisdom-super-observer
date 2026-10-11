import {z} from 'zod';
import type {components} from '../../../../../packages/contracts/generated/tvt';
import {LocalLiveError,localLiveRequest,type LocalLiveBinding} from './local-live-api';

export type LocalWallResponse=components['schemas']['LocalWallResponse'];
export type LocalFocusResponse=components['schemas']['LocalFocusResponse'];
const correlation=z.string().min(1).max(64).regex(/^[A-Za-z0-9_.:-]+$/);
export const localWallResponse=z.object({wall:z.object({id:z.uuid(),tenant_id:z.uuid(),expires_at:z.string().datetime({offset:true}),state:z.enum(['ACTIVE','STOPPING','CLOSED'])}).strict(),request_id:correlation}).strict();
export const localFocusInput=z.object({direction:z.enum(['FORWARD','RETURN'])}).strict();
export const localFocusSettleInput=z.object({outcome:z.enum(['CANCELLED','FAILED'])}).strict();
export const localFocusResponse=z.object({reference:z.object({id:z.uuid(),wall_id:z.uuid(),lease_id:z.uuid(),connection_id:z.uuid(),channel_id:z.uuid(),direction:z.enum(['FORWARD','RETURN']),expires_at:z.string().datetime({offset:true}),state:z.enum(['PENDING','ACTIVE','CLOSED'])}).strict(),request_id:correlation}).strict();
export function parseLocalWall(body:unknown,tenantId:string,requestId:string,wallId?:string):LocalWallResponse{
  const value=localWallResponse.parse(body);
  if(value.request_id!==requestId||value.wall.tenant_id!==tenantId||(wallId!==undefined&&value.wall.id!==wallId))throw new LocalLiveError(502);
  return value;
}
export function parseLocalFocus(body:unknown,requestId:string,scope:{wallId?:string;referenceId?:string;leaseId?:string;connectionId?:string;channelId?:string;direction?:'FORWARD'|'RETURN'}):LocalFocusResponse{
  const value=localFocusResponse.parse(body);const ref=value.reference;
  if(value.request_id!==requestId||(scope.wallId!==undefined&&ref.wall_id!==scope.wallId)||(scope.referenceId!==undefined&&ref.id!==scope.referenceId)||(scope.leaseId!==undefined&&ref.lease_id!==scope.leaseId)||(scope.connectionId!==undefined&&ref.connection_id!==scope.connectionId)||(scope.channelId!==undefined&&ref.channel_id!==scope.channelId)||(scope.direction!==undefined&&ref.direction!==scope.direction))throw new LocalLiveError(502);
  return value;
}
const wallRoute=(tenantId:string,wallId?:string,tail?:string)=>{
  z.uuid().parse(tenantId);if(wallId!==undefined)z.uuid().parse(wallId);
  return `/api/live-walls${wallId===undefined?'':`/${wallId}/${tail}`}?tenant_id=${tenantId}`;
};
export async function createLocalWall(tenantId:string,csrf:string,signal:AbortSignal):Promise<LocalWallResponse>{
  const result=await localLiveRequest(wallRoute(tenantId),csrf,signal);const view=parseLocalWall(result.body,tenantId,result.id);
  if(view.wall.state!=='ACTIVE'||Date.parse(view.wall.expires_at)<=Date.now())throw new LocalLiveError(502);return view;
}
/** Authoritative metadata for this exact original wall; a missing view is not CLOSED. */
export async function readLocalWall(tenantId:string,wallId:string,signal:AbortSignal):Promise<LocalWallResponse>{
  z.uuid().parse(tenantId);z.uuid().parse(wallId);
  const result=await localLiveRequest(`/api/live-walls/${wallId}?tenant_id=${tenantId}`,'',signal,undefined,'GET');
  return parseLocalWall(result.body,tenantId,result.id,wallId);
}
export async function heartbeatLocalWall(tenantId:string,wallId:string,csrf:string,signal:AbortSignal):Promise<LocalWallResponse>{
  const result=await localLiveRequest(wallRoute(tenantId,wallId,'heartbeat'),csrf,signal);return parseLocalWall(result.body,tenantId,result.id,wallId);
}
export async function stopLocalWall(tenantId:string,wallId:string,csrf:string):Promise<LocalWallResponse>{
  const result=await localLiveRequest(wallRoute(tenantId,wallId,'stop'),csrf,new AbortController().signal);return parseLocalWall(result.body,tenantId,result.id,wallId);
}
export async function reserveLocalFocus(binding:LocalLiveBinding,leaseId:string,direction:'FORWARD'|'RETURN',csrf:string,signal:AbortSignal):Promise<LocalFocusResponse>{
  for(const id of [binding.tenantId,binding.wallId,binding.connectionId,binding.channelId,leaseId])z.uuid().parse(id);
  const result=await localLiveRequest(`/api/live-sessions/${leaseId}/focus-reservations?tenant_id=${binding.tenantId}`,csrf,signal,localFocusInput.parse({direction}));
  const view=parseLocalFocus(result.body,result.id,{wallId:binding.wallId,leaseId,connectionId:binding.connectionId,channelId:binding.channelId,direction});
  if(view.reference.state!=='PENDING'||Date.parse(view.reference.expires_at)<=Date.now())throw new LocalLiveError(502);return view;
}
/** Terminal reference metadata does not acknowledge viewer or native cleanup. */
export async function settleLocalFocus(tenantId:string,wallId:string,referenceId:string,outcome:'CANCELLED'|'FAILED',csrf:string,signal:AbortSignal):Promise<LocalFocusResponse>{
  z.uuid().parse(referenceId);
  const result=await localLiveRequest(wallRoute(tenantId,wallId,`focus-reservations/${referenceId}/settle`),csrf,signal,localFocusSettleInput.parse({outcome}));
  return parseLocalFocus(result.body,result.id,{wallId,referenceId});
}
