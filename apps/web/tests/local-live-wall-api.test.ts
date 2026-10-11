import {afterEach,expect,it,vi} from 'vitest';
import * as api from '../src/lib/tvt/local-live-wall-api';
const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const binding={tenantId:uuid(1),connectionId:uuid(2),storeId:uuid(3),deviceId:uuid(4),channelId:uuid(5),generation:2,inventoryRevision:3,wallId:uuid(9)};
const wall={id:uuid(9),tenant_id:uuid(1),state:'ACTIVE',expires_at:'2099-10-06T00:00:30Z'};
const reference={id:uuid(10),wall_id:uuid(9),lease_id:uuid(6),connection_id:uuid(2),channel_id:uuid(5),direction:'FORWARD',state:'PENDING',expires_at:'2099-10-06T00:00:30Z'};
const reply=(body:unknown)=>new Response(JSON.stringify(body),{headers:{'X-Request-ID':'request-1'}});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();vi.useRealTimers();});
it('reads only the exact original tenant and wall via a bounded same-origin GET',async()=>{
  const send=vi.fn(async()=>reply({wall:{...wall,state:'CLOSED'},request_id:'request-1'}));vi.stubGlobal('fetch',send);
  expect((await api.readLocalWall(uuid(1),uuid(9),new AbortController().signal)).wall.state).toBe('CLOSED');
  expect(send.mock.calls[0]).toEqual([`/api/live-walls/${uuid(9)}?tenant_id=${uuid(1)}`,expect.objectContaining({method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',body:undefined,headers:undefined})]);
  for(const bad of [{...wall,id:uuid(8)},{...wall,tenant_id:uuid(8)},{...wall,private:'marker'}]){
    send.mockImplementation(async()=>reply({wall:bad,request_id:'request-1'}));await expect(api.readLocalWall(uuid(1),uuid(9),new AbortController().signal)).rejects.toThrow();
  }
  const abort=new AbortController();abort.abort();send.mockClear();await expect(api.readLocalWall(uuid(1),uuid(9),abort.signal)).rejects.toThrow();expect(send).not.toHaveBeenCalled();
});
it('test_wall_heartbeat_same_origin_and_response_scope',async()=>{
  const send=vi.fn(async()=>reply({wall,request_id:'request-1'}));vi.stubGlobal('fetch',send);
  expect(await api.heartbeatLocalWall(uuid(1),uuid(9),'csrf',new AbortController().signal)).toEqual({wall,request_id:'request-1'});
  const [url,init]=send.mock.calls[0] as unknown as [string,RequestInit];
  expect(url).toBe(`/api/live-walls/${uuid(9)}/heartbeat?tenant_id=${uuid(1)}`);
  expect(init).toMatchObject({method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',body:'{}',headers:{'X-CSRF-Token':'csrf'}});
  for(const bad of [{...wall,id:uuid(8)},{...wall,tenant_id:uuid(8)},{...wall,native_id:7}]){
    send.mockImplementation(async()=>reply({wall:bad,request_id:'request-1'}));await expect(api.heartbeatLocalWall(uuid(1),uuid(9),'csrf',new AbortController().signal)).rejects.toThrow();
  }
});
it('test_focus_wrong_direction_or_wall_denied',async()=>{
  const send=vi.fn(async()=>reply({reference,request_id:'request-1'}));vi.stubGlobal('fetch',send);
  expect((await api.reserveLocalFocus(binding,uuid(6),'FORWARD','csrf',new AbortController().signal)).reference.id).toBe(uuid(10));
  expect(send.mock.calls[0]).toEqual([`/api/live-sessions/${uuid(6)}/focus-reservations?tenant_id=${uuid(1)}`,expect.objectContaining({body:'{"direction":"FORWARD"}'})]);
  for(const bad of [{...reference,direction:'RETURN'},{...reference,wall_id:uuid(8)},{...reference,lease_id:uuid(8)},{...reference,connection_id:uuid(8)},{...reference,channel_id:uuid(8)}]){
    send.mockImplementation(async()=>reply({reference:bad,request_id:'request-1'}));await expect(api.reserveLocalFocus(binding,uuid(6),'FORWARD','csrf',new AbortController().signal)).rejects.toThrow();
  }
  send.mockImplementation(async()=>reply({reference,request_id:'wrong'}));await expect(api.reserveLocalFocus(binding,uuid(6),'FORWARD','csrf',new AbortController().signal)).rejects.toThrow();
});
it('creates and stops walls and settles only the exact public reference',async()=>{
  const send=vi.fn(async()=>reply({wall,request_id:'request-1'}));vi.stubGlobal('fetch',send);
  await api.createLocalWall(uuid(1),'csrf',new AbortController().signal);await api.stopLocalWall(uuid(1),uuid(9),'csrf');
  expect((send.mock.calls[0] as unknown as [string,RequestInit])[0]).toBe(`/api/live-walls?tenant_id=${uuid(1)}`);expect((send.mock.calls[1] as unknown as [string,RequestInit])[0]).toBe(`/api/live-walls/${uuid(9)}/stop?tenant_id=${uuid(1)}`);
  send.mockImplementation(async()=>reply({reference:{...reference,state:'CLOSED'},request_id:'request-1'}));
  const result=await api.settleLocalFocus(uuid(1),uuid(9),uuid(10),'CANCELLED','csrf',new AbortController().signal);
  expect(result.reference.state).toBe('CLOSED');expect(result).not.toHaveProperty('cleanup');
  for(const bad of [{...reference,id:uuid(8)},{...reference,wall_id:uuid(8)}]){
    send.mockImplementation(async()=>reply({reference:bad,request_id:'request-1'}));await expect(api.settleLocalFocus(uuid(1),uuid(9),uuid(10),'FAILED','csrf',new AbortController().signal)).rejects.toThrow();
  }
});
it('test_abort_and_expired_reference_no_extension',async()=>{
  const send=vi.fn(async()=>reply({reference:{...reference,expires_at:'2000-01-01T00:00:00Z'},request_id:'request-1'}));vi.stubGlobal('fetch',send);
  await expect(api.reserveLocalFocus(binding,uuid(6),'FORWARD','csrf',new AbortController().signal)).rejects.toThrow();expect(send).toHaveBeenCalledTimes(1);
  send.mockClear();const abort=new AbortController();abort.abort();await expect(api.heartbeatLocalWall(uuid(1),uuid(9),'csrf',abort.signal)).rejects.toThrow();expect(send).not.toHaveBeenCalled();
});
it('bounds stalled fetch at 25s and streamed public replies at 262144 bytes',async()=>{
  let expire!:()=>void;
  vi.spyOn(AbortSignal,'timeout').mockImplementation(ms=>{expect(ms).toBe(25000);const controller=new AbortController();expire=()=>controller.abort();return controller.signal;});
  vi.stubGlobal('fetch',()=>new Promise(()=>{}));const pending=api.heartbeatLocalWall(uuid(1),uuid(9),'csrf',new AbortController().signal);expire();await expect(pending).rejects.toThrow();
  let cancelled=false;vi.stubGlobal('fetch',async()=>new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array(262145));},cancel(){cancelled=true;}}),{headers:{'X-Request-ID':'request-1'}}));
  await expect(api.heartbeatLocalWall(uuid(1),uuid(9),'csrf',new AbortController().signal)).rejects.toThrow();expect(cancelled).toBe(true);
});
it('cancels an unread reply when its correlation header is invalid',async()=>{
  let cancelled=false;vi.stubGlobal('fetch',async()=>new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array(1));},cancel(){cancelled=true;}})));
  await expect(api.heartbeatLocalWall(uuid(1),uuid(9),'csrf',new AbortController().signal)).rejects.toThrow();expect(cancelled).toBe(true);
});
