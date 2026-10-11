import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import type {LocalLiveBinding} from '../src/lib/tvt/local-live-api';
import type {LocalFocusResponse, LocalWallResponse} from '../src/lib/tvt/local-live-wall-api';
import {LiveWallGroupController, type LiveWallGroupApi} from '../src/lib/tvt/live-wall-group';

const loadController=async()=> {
  return LiveWallGroupController;
};
const wallId='70000000-0000-4000-8000-000000000001';
const refId='80000000-0000-4000-8000-000000000001';
const leaseId='90000000-0000-4000-8000-000000000001';
const binding:LocalLiveBinding={tenantId:'10000000-0000-4000-8000-000000000001',connectionId:'20000000-0000-4000-8000-000000000001',storeId:'30000000-0000-4000-8000-000000000001',deviceId:'40000000-0000-4000-8000-000000000001',channelId:'50000000-0000-4000-8000-000000000001',generation:1,inventoryRevision:1,wallId};
const wall=(state:LocalWallResponse['wall']['state']='ACTIVE'):LocalWallResponse=>({wall:{id:wallId,tenant_id:binding.tenantId,expires_at:new Date(Date.now()+30_000).toISOString(),state},request_id:'wall'});
const focus=(direction:'FORWARD'|'RETURN'='FORWARD'):LocalFocusResponse=>({reference:{id:refId,wall_id:wallId,lease_id:leaseId,connection_id:binding.connectionId,channel_id:binding.channelId,direction,expires_at:new Date(Date.now()+20_000).toISOString(),state:'PENDING'},request_id:'ref'});
const api=()=>({create:vi.fn<LiveWallGroupApi['create']>(async()=>wall()),heartbeat:vi.fn<LiveWallGroupApi['heartbeat']>(async()=>wall()),stop:vi.fn<LiveWallGroupApi['stop']>(async()=>wall('CLOSED')),reserve:vi.fn<LiveWallGroupApi['reserve']>(async()=>focus()),settle:vi.fn<LiveWallGroupApi['settle']>(async()=>({...focus(),reference:{...focus().reference,state:'CLOSED' as const}}))});
const signal=()=>new AbortController().signal;
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(new Date('2026-10-06T00:00:00Z'));});
afterEach(()=>{vi.useRealTimers();});

it('R210 holds wall teardown behind the original player cleanup barrier',async()=>{
  const calls=api();const group=new LiveWallGroupController({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());let release!:()=>void;const owners=new Promise<void>(resolve=>{release=resolve;});
  const original=group.stopAll(owners);
  try{expect(group.isFenced).toBe(true);expect(group.stopAll()).toBe(original);expect(calls.stop).not.toHaveBeenCalled();}
  finally{release();await original;}
  expect(group.isFenced).toBe(false);expect(calls.stop).toHaveBeenCalledTimes(1);
});

it('R210 still stops the wall but retains a rejected player cleanup barrier',async()=>{
  const calls=api();const group=new LiveWallGroupController({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());const error=new Error('original lease cleanup failed');
  const owners=Promise.reject(error);void owners.catch(()=>undefined);const original=group.stopAll(owners);
  await expect(original).rejects.toBe(error);expect(calls.stop).toHaveBeenCalledTimes(1);
  expect(group.isFenced).toBe(true);expect(group.stopAll()).toBe(original);
  await expect(group.ensure(signal())).rejects.toThrow();
});

it.each(['STOPPING','foreign-wall','foreign-tenant'] as const)('R210 rejects missing same-wall CLOSED proof: %s',async kind=>{
  const calls=api();const group=new LiveWallGroupController({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  const value=wall('CLOSED');
  if(kind==='STOPPING')value.wall.state='STOPPING';
  else if(kind==='foreign-wall')value.wall.id=leaseId;
  else value.wall.tenant_id=leaseId;
  calls.stop.mockResolvedValue(value);const original=group.stopAll();
  await expect(original).rejects.toThrow();expect(group.isFenced).toBe(true);expect(group.stopAll()).toBe(original);
});

it('never settles an exact reference after its replacement lease confirmed attachment',async()=>{
  const calls=api();const group=new LiveWallGroupController({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());await group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  group.attached(refId);
  calls.settle.mockRejectedValue(new Error('obsolete consumed reference 404'));
  await expect(group.cancelFocus(refId,'CANCELLED')).resolves.toBeUndefined();
  await expect(group.stopAll()).resolves.toBeUndefined();
  expect(calls.settle).not.toHaveBeenCalled();
});

it('keeps exact in-flight pending settlement when attachment is reported concurrently',async()=>{
  const calls=api();let reject!:(error:Error)=>void;
  calls.settle.mockImplementation(()=>new Promise((_resolve,fail)=>{reject=fail;}));
  const group=new LiveWallGroupController({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());await group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  const original=group.cancelFocus(refId,'CANCELLED');const rejected=expect(original).rejects.toThrow('genuine pending cleanup');
  group.attached(refId);
  expect(group.cancelFocus(refId,'CANCELLED')).toBe(original);
  reject(new Error('genuine pending cleanup'));await rejected;
  await expect(group.stopAll()).rejects.toThrow('genuine pending cleanup');
  expect(calls.settle).toHaveBeenCalledTimes(1);
});

it('creates lazily once and heartbeats at ten seconds without renewing pending focus',async()=>{
  const Controller=await loadController();const calls=api();const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  expect(calls.create).not.toHaveBeenCalled();await Promise.all([group.ensure(signal()),group.ensure(signal())]);expect(calls.create).toHaveBeenCalledTimes(1);
  await group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  await vi.advanceTimersByTimeAsync(9999);expect(calls.heartbeat).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);expect(calls.heartbeat).toHaveBeenCalledTimes(1);expect(calls.reserve).toHaveBeenCalledTimes(1);
  await group.dispose();
});
it('expires focus at exactly twenty seconds and never extends it with wall heartbeat',async()=>{
  const Controller=await loadController();const calls=api();const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());await group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  await vi.advanceTimersByTimeAsync(19999);expect(group.isUsable(refId)).toBe(true);expect(calls.settle).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);expect(group.isUsable(refId)).toBe(false);expect(calls.settle.mock.calls[0]?.[3]).toBe('FAILED');
  await group.dispose();
});
it('does not reserve when exact current lease is missing or player is closed',async()=>{
  const Controller=await loadController();const calls=api();const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());
  await expect(group.beginFocus(binding,{currentLeaseId:null,closed:false},'FORWARD',signal())).rejects.toThrow();
  await expect(group.beginFocus(binding,{currentLeaseId:leaseId,closed:true},'FORWARD',signal())).rejects.toThrow();
  expect(calls.reserve).not.toHaveBeenCalled();await group.dispose();
});
it('retires only the original wall returned after stopped creation',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalWallResponse)=>void;
  calls.create.mockImplementation(()=>new Promise(done=>{resolve=done;}));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  const pending=group.ensure(signal());const rejected=expect(pending).rejects.toThrow();const stopping=group.stopAll();
  resolve(wall());await rejected;await stopping;expect(calls.stop.mock.calls[0]?.[1]).toBe(wallId);await group.dispose();
});
it('retains the same original group stop promise and fences STOPPING',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalWallResponse)=>void;
  calls.stop.mockImplementation(()=>new Promise(done=>{resolve=done;}));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  const original=group.stopAll();const rejected=expect(original).rejects.toThrow('Wall stop not terminal');expect(group.stopAll()).toBe(original);await expect(group.ensure(signal())).rejects.toThrow();
  resolve(wall('STOPPING'));await rejected;await expect(group.ensure(signal())).rejects.toThrow();expect(calls.create).toHaveBeenCalledTimes(1);
});
it('correlates settlement with the exact known source and direction',async()=>{
  const Controller=await loadController();const calls=api();const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  await group.ensure(signal());await group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  calls.settle.mockResolvedValue({...focus('RETURN'),reference:{...focus('RETURN').reference,state:'CLOSED'}});
  await expect(group.cancelFocus(refId,'CANCELLED')).rejects.toThrow();await group.dispose().catch(()=>undefined);
});
it('retires a late cancelled reservation without adopting it',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalFocusResponse)=>void;
  calls.reserve.mockImplementation(()=>new Promise(done=>{resolve=done;}));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  const abort=new AbortController();const pending=group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',abort.signal);
  const rejected=expect(pending).rejects.toThrow();abort.abort();resolve(focus());await rejected;
  expect(group.isUsable(refId)).toBe(false);expect(calls.settle.mock.calls[0]?.[2]).toBe(refId);await group.dispose();
});
it('heartbeat failure fences the wall and notifies its current owner',async()=>{
  const Controller=await loadController();const calls=api();const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  const failed=vi.fn();group.subscribe(failed);await group.ensure(signal());calls.heartbeat.mockRejectedValue(new Error('revoked'));
  await vi.advanceTimersByTimeAsync(10_000);expect(failed).toHaveBeenCalled();expect(calls.stop).toHaveBeenCalledTimes(1);
  await group.dispose();
});
it('keeps the same wall during a bounded heartbeat waiting for channel construction',async()=>{
  const calls=api();let resolve!:(value:LocalWallResponse)=>void;
  calls.heartbeat.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  const group=new LiveWallGroupController({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  const failed=vi.fn();group.subscribe(failed);expect(await group.ensure(signal())).toBe(wallId);
  await vi.advanceTimersByTimeAsync(10_000);
  await vi.advanceTimersByTimeAsync(1_000);
  expect(calls.stop).not.toHaveBeenCalled();expect(failed).not.toHaveBeenCalled();
  expect(group.isFenced).toBe(false);expect(await group.ensure(signal())).toBe(wallId);
  resolve(wall());await vi.advanceTimersByTimeAsync(0);
  expect(calls.heartbeat).toHaveBeenCalledTimes(1);expect(calls.create).toHaveBeenCalledTimes(1);
  expect(calls.stop).not.toHaveBeenCalled();expect(failed).not.toHaveBeenCalled();
  await group.dispose();
});
it('refuses a second pending focus for the same channel without extending the first deadline',async()=>{
  const Controller=await loadController();const calls=api();const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  await group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  await vi.advanceTimersByTimeAsync(10_000);
  await expect(group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal())).rejects.toThrow();
  expect(calls.reserve).toHaveBeenCalledTimes(1);await vi.advanceTimersByTimeAsync(10_000);expect(calls.settle).toHaveBeenCalledTimes(1);await group.dispose();
});
it('keeps a failed late-wall original cleanup fenced',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalWallResponse)=>void;
  calls.create.mockImplementation(()=>new Promise(done=>{resolve=done;}));calls.stop.mockRejectedValue(new Error('uncertain original'));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});
  const pending=group.ensure(signal());const rejected=expect(pending).rejects.toThrow();const stopped=group.stopAll();
  const failed=expect(stopped).rejects.toThrow();resolve(wall());await rejected;await failed;
  await expect(group.ensure(signal())).rejects.toThrow();expect(group.stopAll()).toBe(stopped);
});
it('aborts a stalled reservation at twenty seconds and settles its late original',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalFocusResponse)=>void;let requestSignal!:AbortSignal;
  calls.reserve.mockImplementation((_binding,_lease,_direction,_csrf,abort)=>{requestSignal=abort;return new Promise(done=>{resolve=done;});});
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  const pending=group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  const settled=pending.catch(()=>undefined);
  try {
    await vi.advanceTimersByTimeAsync(19999);expect(requestSignal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);expect(requestSignal.aborted).toBe(true);
  } finally {resolve(focus());await settled;await group.dispose();}
  expect(calls.settle.mock.calls[0]?.[3]).toBe('FAILED');
});
it('retains failed settlement for a late aborted reference behind group stop',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalFocusResponse)=>void;
  calls.reserve.mockImplementation(()=>new Promise(done=>{resolve=done;}));calls.settle.mockRejectedValue(new Error('uncertain reference'));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  const pending=group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());const rejected=expect(pending).rejects.toThrow();
  const stopping=group.stopAll();const failed=expect(stopping).rejects.toThrow();resolve(focus());await rejected;await failed;
  await expect(group.ensure(signal())).rejects.toThrow();
});
it('keeps ten-second heartbeat cadence after a slow successful response without overlap',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalWallResponse)=>void;
  calls.heartbeat.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  await vi.advanceTimersByTimeAsync(10_000);expect(calls.heartbeat).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(6_000);resolve(wall());await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(4_000);expect(calls.heartbeat).toHaveBeenCalledTimes(2);await group.dispose();
});
it('allows only one pending reservation call across different channels',async()=>{
  const Controller=await loadController();const calls=api();let resolve!:(value:LocalFocusResponse)=>void;
  calls.reserve.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  const group=new Controller({tenantId:binding.tenantId,csrf:'csrf',api:calls});await group.ensure(signal());
  const first=group.beginFocus(binding,{currentLeaseId:leaseId,closed:false},'FORWARD',signal());
  const other={...binding,channelId:'50000000-0000-4000-8000-000000000002'};
  try {await expect(group.beginFocus(other,{currentLeaseId:leaseId,closed:false},'FORWARD',signal())).rejects.toThrow();}
  finally {resolve(focus());await first;await group.dispose();}
  expect(calls.reserve).toHaveBeenCalledTimes(1);
});
