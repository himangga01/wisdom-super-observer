import {afterEach,expect,it,vi} from 'vitest';
import {LocalLiveError,parseLocalLive,startLocalLive} from '../src/lib/tvt/local-live-api';

const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const binding={tenantId:uuid(1),connectionId:uuid(2),storeId:uuid(3),deviceId:uuid(4),channelId:uuid(5),generation:2,inventoryRevision:3};
const lease={id:uuid(6),owner:{tenant_id:uuid(1),actor_user_id:uuid(7),connection_id:uuid(2),store_id:uuid(3)},device:{tenant_id:uuid(1),actor_user_id:uuid(7),connection_id:uuid(2),store_id:uuid(3),device_id:uuid(4),channel_id:uuid(5)},channel:uuid(5),kind:'live',state:'NEGOTIATING',expires_at:'2026-10-04T00:00:30Z',heartbeat_at:'2026-10-04T00:00:00Z',connection_generation:2,inventory_revision:3,grant_revision:1};
afterEach(()=>vi.unstubAllGlobals());
it('accepts only the requested local media scope and safe lease projection',()=>{
  const body={lease,request_id:'request-1'};
  expect(parseLocalLive(body,binding,'request-1').lease.id).toBe(uuid(6));
  for(const bad of [
    {...lease,owner:{...lease.owner,connection_id:uuid(8)}},
    {...lease,device:{...lease.device,channel_id:uuid(8)}},
    {...lease,connection_generation:1}, {...lease,inventory_revision:4},
    {...lease,grant_revision:2**53}, {...lease,secret:'never-public'},
    {...lease,expires_at:'2026-10-03T00:00:00Z'},
  ]) expect(()=>parseLocalLive({lease:bad,request_id:'request-1'},binding,'request-1')).toThrow();
  expect(()=>parseLocalLive(body,binding,'another-request')).toThrow();
});
it('starts once with bounded selectors and rejects mismatched reply correlation',async()=>{
  const send=vi.fn(async()=>new Response(JSON.stringify({lease,request_id:'request-1'}),{headers:{'X-Request-ID':'request-1'}}));
  vi.stubGlobal('fetch',send);
  await startLocalLive(binding,'csrf',new AbortController().signal);
  expect(send).toHaveBeenCalledTimes(1);
  const [url,init]=send.mock.calls[0] as unknown as [string,RequestInit];
  expect(url).toBe(`/api/live-sessions?tenant_id=${uuid(1)}&connection_id=${uuid(2)}`);
  expect(JSON.parse(init.body as string)).toEqual({store_id:uuid(3),device_id:uuid(4),channel_id:uuid(5),expected_generation:2,inventory_revision:3,stream:'main'});
  expect(init.redirect).toBe('error');
  send.mockImplementation(async()=>new Response(JSON.stringify({lease,request_id:'foreign'}),{headers:{'X-Request-ID':'request-1'}}));
  await expect(startLocalLive(binding,'csrf',new AbortController().signal)).rejects.toThrow();
});

it('sends an explicitly selected sub stream to the live endpoint',async()=>{
  const send=vi.fn(async()=>new Response(JSON.stringify({lease,request_id:'request-1'}),{headers:{'X-Request-ID':'request-1'}}));
  vi.stubGlobal('fetch',send);
  await startLocalLive({...binding,stream:'sub'},'csrf',new AbortController().signal);
  const [,init]=send.mock.calls[0] as unknown as [string,RequestInit];
  expect(JSON.parse(init.body as string).stream).toBe('sub');
});

it('test_optional_fields_legacy_omitted and explicit shared fields retained',async()=>{
  const send=vi.fn(async()=>new Response(JSON.stringify({lease,request_id:'request-1'}),{headers:{'X-Request-ID':'request-1'}}));
  vi.stubGlobal('fetch',send);
  await startLocalLive(binding,'csrf',new AbortController().signal);
  expect(JSON.parse((send.mock.calls[0] as unknown as [string,RequestInit])[1].body as string)).not.toHaveProperty('wall_id');
  await startLocalLive({...binding,wallId:uuid(9),focusRefId:uuid(10)},'csrf',new AbortController().signal);
  expect(JSON.parse((send.mock.calls[1] as unknown as [string,RequestInit])[1].body as string)).toMatchObject({wall_id:uuid(9),focus_ref_id:uuid(10)});
});

it.each([
  ['LOCAL_DEVICE_NO_SIGNAL',504],['LOCAL_DEVICE_BUSY',429],
  ['LOCAL_DEVICE_UPSTREAM_REJECTED',502],['LOCAL_DEVICE_DEADLINE_EXCEEDED',504],
])('carries the validated %s error code without upstream text',async(code,status)=>{
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({error:{code,message:'private-marker'},request_id:'request-1'}),{status:status as number}));
  const failure=await startLocalLive(binding,'csrf',new AbortController().signal).catch(error=>error);
  expect(failure).toBeInstanceOf(LocalLiveError);expect(failure.status).toBe(status);expect(failure.code).toBe(code);expect(failure.message).not.toContain('private-marker');
});
it.each([
  {error:{code:'UNKNOWN',message:'secret'},request_id:'request-1'},
  {error:{code:'LOCAL_DEVICE_BUSY',message:'secret'},request_id:'request-1'},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'secret'},request_id:'request-1',extra:true},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'secret',extra:true},request_id:'request-1'},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'x'.repeat(4096)},request_id:'request-1'},
])('preserves HTTP status with a null code for invalid or oversized error JSON',async payload=>{
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify(payload),{status:504}));
  await expect(startLocalLive(binding,'csrf',new AbortController().signal)).rejects.toMatchObject({status:504,code:null});
});
it('bounds a streamed error and cancels its reader',async()=>{
  let cancelled=false;
  const body=new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new Uint8Array(4097));},cancel(){cancelled=true;}});
  vi.stubGlobal('fetch',async()=>new Response(body,{status:504}));
  await expect(startLocalLive(binding,'csrf',new AbortController().signal)).rejects.toMatchObject({status:504,code:null});expect(cancelled).toBe(true);
});
