// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {ServiceShell} from '../src/components/service-shell';
import {createWallRuntime, formatClock, LiveWall, type LiveWallClock, type LiveWallPlayerEvents, type LiveWallPlayerFactory} from '../src/features/monitoring/live-wall';
import type {ConnectionView} from '../src/lib/connections';
import type {LocalLiveBinding} from '../src/lib/tvt/local-live-api';
import * as liveApi from '../src/lib/tvt/local-live-api';
import {LocalLivePlayer} from '../src/lib/tvt/local-live-player';
import * as wallScheduler from '../src/lib/tvt/live-wall-scheduler';
import * as wallApi from '../src/lib/tvt/local-live-wall-api';
import {LiveWallGroupController} from '../src/lib/tvt/live-wall-group';

const tenant='10000000-0000-4000-8000-000000000001';
const storeOne='30000000-0000-4000-8000-000000000001';
const storeTwo='30000000-0000-4000-8000-000000000002';
const storeThree='30000000-0000-4000-8000-000000000003';
const recorderOne='20000000-0000-4000-8000-000000000001';
const recorderTwo='20000000-0000-4000-8000-000000000002';
const stores=[
  {id:storeOne,tenant_id:tenant,name:'1호점',timezone:'Asia/Seoul',active:true},
  {id:storeTwo,tenant_id:tenant,name:'2호점',timezone:'Asia/Seoul',active:true},
  {id:storeThree,tenant_id:tenant,name:'3호점',timezone:'Asia/Seoul',active:true},
];
const recorder=(id:string,alias:string,storeIds:string[]):ConnectionView=>({id,tenant_id:tenant,kind:'TVT_DEVICE',alias,site:alias,status:'NOT_VERIFIED',last_success:null,generation:1,store_ids:storeIds});
const connections=[recorder(recorderOne,'1호점 녹화기',[storeOne]),recorder(recorderTwo,'2호점 녹화기',[storeTwo,storeThree])];
const device=(store:number)=>`50000000-0000-4000-8000-00000000000${store}`;
const channelId=(store:number,ordinal:number)=>`60000000-0000-4000-8000-${String(store*1000+ordinal).padStart(12,'0')}`;
const available=(connection:string,store:string,storeNumber:number,count:number)=>({
  connection_id:connection,device_id:device(storeNumber),store_id:store,connection_generation:1,inventory_revision:1,
  inventory_state:'AVAILABLE',observed_at:'2026-10-04T00:00:00Z',
  channels:Array.from({length:count},(_,index)=>({id:channelId(storeNumber,index+1),ordinal:index+1,label:`Channel ${index+1}`})),
  request_id:`inventory-${storeNumber}`,
});
const unavailable=(connection:string,store:string,storeNumber:number)=>({connection_id:connection,device_id:null,store_id:store,connection_generation:1,inventory_revision:0,inventory_state:'UNAVAILABLE',observed_at:null,channels:[],request_id:`inventory-${storeNumber}`});
const savedInventories:Record<string,{request_id:string}>={
  [`${recorderOne}/${storeOne}`]:available(recorderOne,storeOne,1,4),
  [`${recorderTwo}/${storeTwo}`]:available(recorderTwo,storeTwo,2,3),
  [`${recorderTwo}/${storeThree}`]:unavailable(recorderTwo,storeThree,3),
};

/** Serves only the saved-inventory GET endpoint; any other request is a 404 so accidental calls are visible. */
function stubInventories(inventories=savedInventories){
  const send=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(String(input),'https://wall.test');
    const match=/^\/api\/local-devices\/([^/]+)\/channels$/.exec(url.pathname);
    const body=match&&(init?.method??'GET')==='GET'?inventories[`${match[1]}/${url.searchParams.get('store_id')}`]:undefined;
    if(!body)return new Response(null,{status:404});
    return new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json','X-Request-ID':body.request_id}});
  });
  vi.stubGlobal('fetch',send);
  return send;
}

/**
 * Stands in for LocalLivePlayer: no peer, lease or network; the test drives every transition.
 * Like the real player, stop() emits stream(null) and 'stopped' at once and returns one shared
 * closing promise (the backend stop request), and fail() reports 'failed' only after that settles.
 */
class FakePlayer{
  closed=false;playbackConfirmed=false;started=false;leaseHeld=false;failureStatus:number|null=null;failureCode:string|null=null;readonly frames:number[]=[];
  private closing:Promise<void>|null=null;
  get currentLeaseId(){return this.closed||!this.started?null:this.binding.channelId;}
  constructor(readonly binding:LocalLiveBinding,readonly csrf:string,private readonly events:LiveWallPlayerEvents,private readonly settleStop:()=>Promise<void>){}
  async start(){if(this.closed||this.started)return;this.started=true;this.leaseHeld=true;this.events.state('connecting');}
  stop(){
    if(this.closing)return this.closing;
    this.closed=true;this.events.stream(null);this.events.state('stopped');
    this.closing=(this.started?this.settleStop():Promise.resolve()).then(()=>{this.leaseHeld=false;});
    return this.closing;
  }
  async presented(frames:number){this.frames.push(frames);}
  deliver(stream:MediaStream){this.events.stream(stream);}
  confirm(){this.playbackConfirmed=true;this.events.state('playing');}
  fail(){void this.stop().then(()=>this.events.state('failed'));}
  /** A start the server refused with this HTTP status (e.g. 429 while the device retires a session). */
  refuse(status:number,code:string|null=null){this.failureStatus=status;this.failureCode=code;this.fail();}
}
/** Stop requests that stay pending until released, like a backend still closing a native session. */
function heldStops(){
  const releases:(()=>void)[]=[];
  return {settle:()=>new Promise<void>(resolve=>{releases.push(resolve);}),release:(index:number)=>releases[index]()};
}
/** Deterministic scheduler timer: callbacks run only when the test advances time. */
function manualTimer(){
  let now=0;let nextId=1;const pending=new Map<number,{at:number;callback:()=>void}>();
  return {
    timer:{set:(callback:()=>void,ms:number)=>{const id=nextId++;pending.set(id,{at:now+ms,callback});return id;},clear:(handle:unknown)=>{pending.delete(handle as number);}},
    advance(ms:number){
      const until=now+ms;
      for(;;){
        let due:[number,{at:number;callback:()=>void}]|null=null;
        for(const entry of pending)if(entry[1].at<=until&&(!due||entry[1].at<due[1].at))due=entry;
        if(!due)break;
        pending.delete(due[0]);now=due[1].at;due[1].callback();
      }
      now=until;
    },
  };
}

const fixedClock:LiveWallClock={subscribe:()=>()=>undefined,read:()=>'2026-10-04 09:05:03'};
function renderWall(props:Partial<Parameters<typeof LiveWall>[0]>={},settleStop:()=>Promise<void>=()=>Promise.resolve()){
  const players:FakePlayer[]=[];
  const createPlayer=vi.fn<LiveWallPlayerFactory>((binding,csrf,events)=>{const player=new FakePlayer(binding,csrf,events,settleStop);players.push(player);return player;});
  const view=render(<LiveWall tenantId={tenant} csrf="csrf-token" stores={stores} connections={connections} createPlayer={createPlayer} clock={fixedClock} {...props}/>);
  return {...view,players,createPlayer};
}
const tileOf=(label:string)=>screen.getByLabelText(label,{selector:'video'}).closest('li') as HTMLElement;
/** Sections render at once; the saved inventories arrive asynchronously, so wait for every channel. */
const inventoriesLoaded=()=>screen.findByText('전체 채널 7');

function sharedWallApi(){
  const log:string[]=[];let sequence=0;
  const wallId='70000000-0000-4000-8000-000000000001';
  const wall=(state:'ACTIVE'|'CLOSED'='ACTIVE'):wallApi.LocalWallResponse=>({wall:{id:wallId,tenant_id:tenant,state,expires_at:new Date(Date.now()+30_000).toISOString()},request_id:'wall'});
  vi.spyOn(wallApi,'createLocalWall').mockImplementation(async()=>{log.push('create');return wall();});
  const heartbeat=vi.spyOn(wallApi,'heartbeatLocalWall').mockImplementation(async()=>{log.push('heartbeat');return wall();});
  const stop=vi.spyOn(wallApi,'stopLocalWall').mockImplementation(async()=>{log.push('stop-wall');return wall('CLOSED');});
  const reserve=vi.spyOn(wallApi,'reserveLocalFocus').mockImplementation(async(binding,lease,direction)=>{
    log.push('reserve-'+direction.toLowerCase());
    return {reference:{id:`80000000-0000-4000-8000-${String(++sequence).padStart(12,'0')}`,wall_id:wallId,lease_id:lease,connection_id:binding.connectionId,channel_id:binding.channelId,direction,state:'PENDING',expires_at:new Date(Date.now()+20_000).toISOString()},request_id:'focus'};
  });
  const settle=vi.spyOn(wallApi,'settleLocalFocus').mockImplementation(async(_tenant,_wall,id)=>{
    const ref=reserve.mock.results.flatMap(result=>result.type==='return'?[result.value]:[]);
    const values=await Promise.all(ref);const found=values.find(value=>value.reference.id===id)!;
    log.push('settle');return {...found,reference:{...found.reference,state:'CLOSED'}};
  });
  return {log,wallId,heartbeat,stop,reserve,settle};
}

/** Actual runtime/player with server cleanup ordered at their asynchronous API boundaries. */
async function stopOrderRuntime(){
  const api=sharedWallApi();const time=manualTimer();const players:LocalLivePlayer[]=[];
  const order:string[]=[];let wallClosed=false;let sequence=0;
  const leases=new Map<string,{id:string;binding:LocalLiveBinding;state:'NEGOTIATING'|'CLOSED'}>();
  const waiting:(()=>void)[]=[];
  const reply=(binding:LocalLiveBinding,id:string,state:'NEGOTIATING'|'CLOSED')=>{
    const owner={tenant_id:binding.tenantId,actor_user_id:'80000000-0000-4000-8000-000000000001',connection_id:binding.connectionId,store_id:binding.storeId};
    return liveApi.localLiveResponse.parse({lease:{id,owner,device:{...owner,device_id:binding.deviceId,channel_id:binding.channelId},channel:binding.channelId,kind:'live',state,expires_at:'2026-10-11T00:00:30Z',heartbeat_at:'2026-10-11T00:00:00Z',connection_generation:1,inventory_revision:1,grant_revision:1},request_id:'stop-order'});
  };
  vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/VP8',clockRate:90000}]})});
  class Peer {
    iceGatheringState='complete';connectionState='new';localDescription={type:'offer',sdp:'v=0\r\n'};
    ontrack=null;onconnectionstatechange=null;
    addTransceiver=()=>({setCodecPreferences:()=>undefined});createOffer=async()=>this.localDescription;
    setLocalDescription=async()=>undefined;setRemoteDescription=async()=>undefined;close=()=>{order.push('peer-close');};
  }
  const create=vi.spyOn(wallApi,'createLocalWall').getMockImplementation()!;
  vi.spyOn(wallApi,'createLocalWall').mockImplementation(async(...args)=>{wallClosed=false;return create(...args);});
  vi.spyOn(liveApi,'startLocalLive').mockImplementation(async binding=>{
    if(wallClosed)throw new liveApi.LocalLiveError(404);
    const id=`90000000-0000-4000-8000-${String(++sequence).padStart(12,'0')}`;
    leases.set(id,{id,binding,state:'NEGOTIATING'});return reply(binding,id,'NEGOTIATING');
  });
  vi.spyOn(liveApi,'offerLocalLive').mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.spyOn(liveApi,'stopLocalLive').mockImplementation(async(binding,id)=>{
    order.push('lease-stop-request');await new Promise<void>(resolve=>waiting.push(resolve));
    const original=leases.get(id);
    if(wallClosed||!original||original.binding!==binding){order.push('lease-stop-denied');throw new liveApi.LocalLiveError(404,'LOCAL_DEVICE_DENIED');}
    original.state='CLOSED';order.push('lease-CLOSED');return reply(binding,id,'CLOSED');
  });
  const wallStop=api.stop.getMockImplementation()!;
  api.stop.mockImplementation(async(...args)=>{
    wallClosed=true;for(const original of leases.values())original.state='CLOSED';
    order.push('wall-CLOSED');return wallStop(...args);
  });
  const group=new LiveWallGroupController({tenantId:tenant,csrf:'csrf',timer:time.timer});
  const runtime=createWallRuntime(()=>undefined,time.timer,group);
  const binding:LocalLiveBinding={tenantId:tenant,connectionId:recorderOne,storeId:storeOne,deviceId:device(1),channelId:channelId(1,1),generation:1,inventoryRevision:1};
  runtime.configure({csrf:'csrf',tiles:new Map([['original',{id:'original',label:'original',ordinal:1,storeId:storeOne,binding}]]),createPlayer:(binding,csrf,events)=>{
    const player=new LocalLivePlayer(binding,csrf,events,()=>new Peer() as unknown as RTCPeerConnection);players.push(player);return player;
  }});
  runtime.play(['original']);await waitFor(()=>expect(players[0]?.currentLeaseId).toBeTypeOf('string'));
  return {runtime,group,players,api,order,release:()=>{for(const finish of waiting.splice(0))finish();}};
}

it.each(['manual','unmount','heartbeat'] as const)('R210 orders %s original lease Stop before shared wall teardown',async trigger=>{
  const h=await stopOrderRuntime();let closing:Promise<void>;
  if(trigger==='heartbeat'){
    h.api.heartbeat.mockRejectedValue(new Error('wall heartbeat invalidated'));
    await h.group.heartbeat().catch(()=>undefined);closing=h.runtime.stopAll();
  }else closing=trigger==='unmount'?h.runtime.dispose():h.runtime.stopAll();
  try{
    expect(h.runtime.stopping).toBe(true);expect(h.runtime.stopAll()).toBe(closing);
    expect(h.api.stop).not.toHaveBeenCalled();h.runtime.play(['original']);
    expect(h.players).toHaveLength(1);
  }finally{h.release();await closing.catch(()=>undefined);}
  expect(h.order).not.toContain('lease-stop-denied');
  expect(h.order.indexOf('lease-CLOSED')).toBeLessThan(h.order.indexOf('wall-CLOSED'));
  expect(h.api.stop).toHaveBeenCalledTimes(1);
  if(trigger==='manual'){
    expect(h.runtime.stopping).toBe(false);h.runtime.play(['original']);
    await waitFor(()=>expect(h.players).toHaveLength(2));const final=h.runtime.dispose();h.release();await final;
  }
});

it('returns confirmed MAIN to SUB when the server refuses obsolete FORWARD settlement',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  const settled=api.settle.getMockImplementation()!;
  let attachedForward:string|undefined=undefined;
  api.settle.mockImplementation((tenant,wall,id,outcome,csrf,signal)=>{
    if(id===attachedForward)return Promise.reject(new Error('obsolete consumed FORWARD 404'));
    return settled(tenant,wall,id,outcome,csrf,signal);
  });
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(players[1]?.started).toBe(true));act(()=>players[1].confirm());
  attachedForward=players[1].binding.focusRefId;expect(attachedForward).toBeDefined();
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));await waitFor(()=>expect(players[2]?.started).toBe(true));
  expect(players[2].binding.stream).toBe('sub');act(()=>players[2].confirm());
  expect(api.settle.mock.calls.some(call=>call[2]===attachedForward)).toBe(false);
  expect(api.reserve.mock.calls.map(call=>call[2])).toEqual(['FORWARD','RETURN']);
});

it('test_last_tile_focus_and_return_reserve_before_stop',async()=>{
  stubInventories();const api=sharedWallApi();const stops=heldStops();const {players}=renderWall({sharedMode:true},()=>{
    api.log.push('stop-player');return stops.settle();
  });await inventoriesLoaded();expect(api.log).toEqual([]);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  expect(players[0].binding.wallId).toBe(api.wallId);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  await waitFor(()=>expect(players).toHaveLength(2));
  expect(api.log.indexOf('reserve-forward')).toBeLessThan(api.log.indexOf('stop-player'));expect(players[1].started).toBe(false);
  expect(players[1].binding.focusRefId).toBeDefined();await act(async()=>stops.release(0));act(()=>players[1].confirm());
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));await waitFor(()=>expect(players).toHaveLength(3));
  expect(api.log.indexOf('reserve-return')).toBeLessThan(api.log.lastIndexOf('stop-player'));expect(players[2].started).toBe(false);
  await act(async()=>stops.release(1));act(()=>players[2].confirm());
  expect(players.filter(player=>!player.closed&&player.started)).toEqual([players[2]]);
  const counters={attempted:2,accepted:api.reserve.mock.calls.length,presented:players.filter(player=>player.binding.focusRefId&&player.playbackConfirmed).length,cancelled:api.settle.mock.calls.filter(call=>call[3]==='CANCELLED').length,settled:api.settle.mock.results.filter(result=>result.type==='return').length};
  expect(counters).toEqual({attempted:2,accepted:2,presented:2,cancelled:0,settled:0});
});
it('test_expired_focus_does_not_open_new_current_player',async()=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const stops=heldStops();
  const {players}=renderWall({sharedMode:true,timer:time.timer},stops.settle);await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(players).toHaveLength(2));
  await act(async()=>time.advance(20_000));expect(players[1].closed).toBe(true);
  await act(async()=>stops.release(0));expect(players[1].started).toBe(false);
  await act(async()=>time.advance(60_000));expect(players).toHaveLength(2);expect(api.settle).toHaveBeenCalled();
});
it('test_wall_heartbeat_failure_and_tab_dispose_fence_all',async()=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const view=renderWall({sharedMode:true,timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));await waitFor(()=>expect(view.players[0]?.started).toBe(true));
  api.heartbeat.mockRejectedValue(new Error('revoked'));await act(async()=>time.advance(10_000));
  expect(view.players.every(player=>player.closed)).toBe(true);expect(api.stop).toHaveBeenCalledTimes(1);
  view.unmount();await act(async()=>time.advance(60_000));expect(view.players).toHaveLength(1);
});
it('test_stopped_tile_does_not_publish_upstream_disconnect',async()=>{
  stubInventories();const {players}=renderWall();await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  expect(within(tileOf('1호점 1번 채널')).getByText('영상 재생 중지')).toBeVisible();
  expect(screen.queryByText(/상위.*연결.*해제|녹화기.*연결.*해제/)).toBeNull();
});
it('test_return_cannot_leave_main_active',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(players[1]?.started).toBe(true));act(()=>players[1].confirm());
  api.reserve.mockRejectedValueOnce(new Error('return expired'));
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));await waitFor(()=>expect(players[1].closed).toBe(true));
  expect(players.filter(player=>!player.closed&&player.started)).toEqual([]);expect(api.settle).not.toHaveBeenCalled();
  await waitFor(()=>expect(players.every(player=>!player.leaseHeld)).toBe(true));
  expect(within(tileOf('1호점 1번 채널')).getByText('연결 실패')).toBeVisible();expect(players).toHaveLength(2);
});
it('test_ten_rapid_requests_report_attempted_and_settled_counts',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  const reserve=api.reserve.getMockImplementation()!;let resolve!:(value:wallApi.LocalFocusResponse)=>void;
  api.reserve.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  let attempted=0;
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));attempted++;
  await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(1));
  for(let index=1;index<10;index++){
    fireEvent.click(screen.getByRole('button',{name:index%2?'통합 관제':'1호점 1번 채널 크게 보기'}));attempted++;
  }
  const args=api.reserve.mock.calls[0];await act(async()=>resolve(await reserve(...args)));
  await waitFor(()=>expect(api.settle).toHaveBeenCalledTimes(1));
  await Promise.all(api.settle.mock.results.flatMap(result=>result.type==='return'?[result.value]:[]));
  const acknowledged=api.reserve.mock.calls.length;
  const presented=players.filter(player=>player.binding.focusRefId&&player.playbackConfirmed).length;
  const cancelled=api.settle.mock.calls.filter(call=>call[3]==='CANCELLED').length;
  const settled=api.settle.mock.results.filter(result=>result.type==='return').length;
  expect({attempted,acknowledged,presented,cancelled,settled}).toEqual({attempted:10,acknowledged:1,presented:0,cancelled:1,settled:1});
  expect(players).toHaveLength(1);expect(players[0].closed).toBe(false);
});
it('a cancelled late reservation never stops a newer manual current player',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  const reserve=api.reserve.getMockImplementation()!;let resolve!:(value:wallApi.LocalFocusResponse)=>void;
  let resolveNew!:(value:wallApi.LocalFocusResponse)=>void;
  api.reserve.mockImplementationOnce(()=>new Promise(done=>{resolve=done;})).mockImplementationOnce(()=>new Promise(done=>{resolveNew=done;}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[1]?.started).toBe(true));act(()=>players[1].confirm());
  await act(async()=>resolve(await reserve(...api.reserve.mock.calls[0])));await waitFor(()=>expect(api.settle).toHaveBeenCalledTimes(1));
  await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(2));
  expect(players[0].closed).toBe(true);expect(players[1].closed).toBe(false);expect(players).toHaveLength(2);
  await act(async()=>resolveNew(await reserve(...api.reserve.mock.calls[1])));
  await waitFor(()=>expect(players[2]?.started).toBe(true));act(()=>players[2].confirm());
  expect(players[2].binding.focusRefId).not.toBe(players[1].binding.focusRefId);
});
it('expires the original focus as FAILED even when expiry listener stops its player',async()=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const stops=heldStops();
  const {players}=renderWall({sharedMode:true,timer:time.timer},stops.settle);await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(players).toHaveLength(2));
  await act(async()=>time.advance(20_000));expect(api.settle.mock.calls[0]?.[3]).toBe('FAILED');
  await act(async()=>stops.release(0));
});
it('shows group cleanup pending and prevents new Play while the original Stop is held',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  const stop=api.stop.getMockImplementation()!;let resolve!:(value:wallApi.LocalWallResponse)=>void;
  api.stop.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  fireEvent.click(screen.getByRole('button',{name:'전체 정지'}));
  expect(screen.getByText('영상 재생 중지 · 정리 확인 중')).toBeVisible();
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await act(async()=>Promise.resolve());
  expect(players).toHaveLength(1);await act(async()=>resolve(await stop(...api.stop.mock.calls[0])));
  expect(screen.queryByText('영상 재생 중지 · 정리 확인 중')).toBeNull();expect(screen.getByRole('button',{name:'전체 재생'})).toBeEnabled();
});
it('shared focus BUSY settles its original reference without unreferenced retries',async()=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const {players}=renderWall({sharedMode:true,timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(players[1]?.started).toBe(true));
  await act(async()=>players[1].refuse(429));await waitFor(()=>expect(api.settle).toHaveBeenCalled());
  expect(api.settle.mock.calls[0]?.[3]).toBe('FAILED');
  await act(async()=>time.advance(60_000));expect(players).toHaveLength(2);expect(players[1].closed).toBe(true);expect(screen.getAllByText('연결 실패')[0]).toBeVisible();
});
it('returns old focus to an accepted sub before reserving a different main',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));await waitFor(()=>expect(players[1]?.started).toBe(true));act(()=>players[1].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(players[2]?.started).toBe(true));act(()=>players[2].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 크게 보기'}));
  await waitFor(()=>expect(players[3]?.started).toBe(true));
  expect(players[3].binding.stream).toBe('sub');expect(players[1].closed).toBe(false);
  expect(api.reserve.mock.calls.map(call=>call[2])).toEqual(['FORWARD','RETURN']);
  act(()=>players[3].confirm());await waitFor(()=>expect(players[4]?.started).toBe(true));
  expect(api.reserve.mock.calls.map(call=>call[2])).toEqual(['FORWARD','RETURN','FORWARD']);
  expect(players[4].binding.channelId).toBe(channelId(1,2));act(()=>players[4].confirm());
  expect(players.filter(player=>!player.closed&&player.started)).toEqual([players[3],players[4]]);
});
it('expires a queued focus behind another startup and settles Stop All without reviving it',async()=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const {players}=renderWall({sharedMode:true,timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));await waitFor(()=>expect(players[1]?.started).toBe(true));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(1));
  expect(players).toHaveLength(2);await act(async()=>time.advance(20_000));
  expect(screen.getAllByText('연결 실패')[0]).toBeVisible();expect(api.settle.mock.calls[0]?.[3]).toBe('FAILED');
  act(()=>players[1].confirm());expect(players).toHaveLength(2);
  fireEvent.click(screen.getByRole('button',{name:'전체 정지'}));await waitFor(()=>expect(screen.queryByText('영상 재생 중지 · 정리 확인 중')).toBeNull());
});
it('shared manual Play in idle focus starts sub before reserving FORWARD and original Stop',async()=>{
  stubInventories();const api=sharedWallApi();const stops=heldStops();const {players}=renderWall({sharedMode:true},()=>{api.log.push('stop-player');return stops.settle();});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await act(async()=>Promise.resolve());
  expect(players).toHaveLength(0);expect(api.log).toEqual([]);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));
  expect(players[0].binding.stream).toBe('sub');expect(players[0].binding.focusRefId).toBeUndefined();expect(api.reserve).not.toHaveBeenCalled();
  act(()=>players[0].confirm());await waitFor(()=>expect(players).toHaveLength(2));
  expect(api.log.indexOf('reserve-forward')).toBeLessThan(api.log.indexOf('stop-player'));
  expect(players[1].binding.stream).toBe('main');expect(players[1].binding.focusRefId).toBeDefined();expect(players[1].started).toBe(false);
  await act(async()=>stops.release(0));act(()=>players[1].confirm());expect(players[1].started).toBe(true);
});
it('shared focused manual Play cancelled before sub acceptance never reserves or starts main',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall({sharedMode:true});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));
  expect(players[0].binding.stream).toBe('sub');
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));act(()=>players[0].confirm());await act(async()=>Promise.resolve());
  expect(api.reserve).not.toHaveBeenCalled();expect(players).toHaveLength(1);expect(players[0].closed).toBe(true);
});
it('legacy focused manual Play retains no-ref main without creating a shared wall',async()=>{
  stubInventories();const api=sharedWallApi();const {players}=renderWall();await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  expect(players[0].binding.stream).toBe('main');expect(players[0].binding.wallId).toBeUndefined();expect(players[0].binding.focusRefId).toBeUndefined();expect(api.log).toEqual([]);
});

/** Real wall, scheduler and player; only validated HTTP results and the browser peer are inert. */
async function timedRealWall(sharedMode=false){
  stubInventories({[`${recorderOne}/${storeOne}`]:available(recorderOne,storeOne,1,2)});
  const time=manualTimer();const players:LocalLivePlayer[]=[];
  const starts:{binding:LocalLiveBinding;resolve:(value:liveApi.LocalLiveView)=>void;reject:(error:Error)=>void}[]=[];
  const offers:{resolve:(value:{type:'answer';sdp:string})=>void}[]=[];
  const stops:{id:string;resolve:()=>void}[]=[];
  let holdStops=false;
  const reply=(binding:LocalLiveBinding,state:'NEGOTIATING'|'PLAYING'|'CLOSED'='NEGOTIATING'):liveApi.LocalLiveView=>{
    const owner={tenant_id:binding.tenantId,actor_user_id:'80000000-0000-4000-8000-000000000001',connection_id:binding.connectionId,store_id:binding.storeId};
    return liveApi.localLiveResponse.parse({lease:{id:binding.channelId,owner,device:{...owner,device_id:binding.deviceId,channel_id:binding.channelId},channel:binding.channelId,kind:'live',state,expires_at:'2026-10-05T00:00:30Z',heartbeat_at:'2026-10-05T00:00:00Z',connection_generation:1,inventory_revision:1,grant_revision:1},request_id:'timed-start'});
  };
  vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/VP8',clockRate:90000}]})});
  class Peer {
    iceGatheringState='complete';connectionState='new';localDescription={type:'offer',sdp:'v=0\r\n'};
    ontrack=null;onconnectionstatechange=null;
    addTransceiver=()=>({setCodecPreferences:()=>undefined});createOffer=async()=>this.localDescription;
    setLocalDescription=async()=>undefined;setRemoteDescription=async()=>undefined;close=()=>undefined;
  }
  vi.spyOn(liveApi,'startLocalLive').mockImplementation(binding=>new Promise((resolve,reject)=>starts.push({binding,resolve,reject})));
  vi.spyOn(liveApi,'offerLocalLive').mockImplementation(()=>new Promise(resolve=>offers.push({resolve})));
  vi.spyOn(liveApi,'reportLocalLivePlaying').mockImplementation(async binding=>reply(binding,'PLAYING'));
  vi.spyOn(liveApi,'stopLocalLive').mockImplementation(async(binding,id)=>{
    if(holdStops)await new Promise<void>(resolve=>stops.push({id,resolve}));
    return reply(binding,'CLOSED');
  });
  const actualScheduler=wallScheduler.createLiveWallScheduler;
  let scheduler!:wallScheduler.LiveWallScheduler;
  vi.spyOn(wallScheduler,'createLiveWallScheduler').mockImplementation(options=>{scheduler=actualScheduler(options);return scheduler;});
  const createPlayer:LiveWallPlayerFactory=(binding,csrf,events)=>{
    const player=new LocalLivePlayer(binding,csrf,events,()=>new Peer() as unknown as RTCPeerConnection);
    players.push(player);return player;
  };
  const view=renderWall({stores:[stores[0]],connections:[connections[0]],createPlayer,timer:time.timer,sharedMode});
  await screen.findByText('전체 채널 2');
  return {...view,time,players,starts,offers,stops,scheduler,holdStops:()=>{holdStops=true;},
    accept:async(index:number)=>{await act(async()=>starts[index].resolve(reply(starts[index].binding)));},
    negotiate:async(index:number)=>{await act(async()=>offers[index].resolve({type:'answer',sdp:'v=0\r\n'}));},
  };
}

it('shared focus keeps the real requesting sub alive until exact acceptance then reserves before Stop',async()=>{
  const api=sharedWallApi();const h=await timedRealWall(true);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(h.starts).toHaveLength(1));
  expect(h.players[0].currentLeaseId).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await act(async()=>Promise.resolve());
  expect(h.players[0].closed).toBe(false);expect(api.reserve).not.toHaveBeenCalled();
  h.holdStops();await h.accept(0);await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(1));
  expect(api.reserve.mock.calls[0]?.[1]).toBe(channelId(1,1));expect(api.reserve.mock.calls[0]?.[2]).toBe('FORWARD');
  expect(h.players[0].closed).toBe(true);expect(h.stops).toHaveLength(1);expect(h.starts).toHaveLength(1);
  await act(async()=>h.stops[0].resolve());await waitFor(()=>expect(h.starts).toHaveLength(2));
  expect(h.starts[1].binding.stream).toBe('main');expect(h.starts[1].binding.focusRefId).toBeDefined();
  await h.accept(1);
});
it('shared queued focus preserves the requested sub and promotes only after its real lease accepts',async()=>{
  const api=sharedWallApi();const h=await timedRealWall(true);
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));await waitFor(()=>expect(h.starts).toHaveLength(1));
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 크게 보기'}));await act(async()=>Promise.resolve());
  expect(api.reserve).not.toHaveBeenCalled();expect(h.players).toHaveLength(1);
  await h.accept(0);await h.negotiate(0);await act(async()=>h.players[0].presented(1));await waitFor(()=>expect(h.starts).toHaveLength(2));
  expect(h.starts[1].binding.stream).toBe('sub');expect(h.players[1].currentLeaseId).toBeNull();
  h.holdStops();await h.accept(1);await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(1));
  expect(api.reserve.mock.calls[0]?.[1]).toBe(channelId(1,2));expect(h.stops[0].id).toBe(channelId(1,2));expect(h.starts).toHaveLength(2);
  await act(async()=>h.stops[0].resolve());await waitFor(()=>expect(h.starts).toHaveLength(3));expect(h.starts[2].binding.stream).toBe('main');
  expect(h.starts[2].binding.focusRefId).toBeDefined();await h.accept(2);expect(h.players[0].closed).toBe(false);
});
it.each(['close','stop'] as const)('cancels real requesting shared promotion on %s before acceptance',async action=>{
  const api=sharedWallApi();const h=await timedRealWall(true);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(h.starts).toHaveLength(1));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await act(async()=>Promise.resolve());
  expect(h.players[0].closed).toBe(false);expect(h.players[0].currentLeaseId).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:action==='close'?'통합 관제':'1호점 1번 채널 중지'}));
  await h.accept(0);await act(async()=>Promise.resolve());
  expect(api.reserve).not.toHaveBeenCalled();expect(h.starts).toHaveLength(1);expect(h.players[0].closed).toBe(action==='stop');
});
it.each(['close','stop'] as const)('cancels real queued shared promotion on %s without reviving idle focus',async action=>{
  const api=sharedWallApi();const h=await timedRealWall(true);
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));await waitFor(()=>expect(h.starts).toHaveLength(1));
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 크게 보기'}));await act(async()=>Promise.resolve());
  fireEvent.click(screen.getByRole('button',{name:action==='close'?'통합 관제':'1호점 2번 채널 중지'}));
  await h.accept(0);await h.negotiate(0);await act(async()=>h.players[0].presented(1));
  if(action==='close') {await waitFor(()=>expect(h.starts).toHaveLength(2));await h.accept(1);expect(h.starts[1].binding.stream).toBe('sub');}
  else expect(h.starts).toHaveLength(1);
  expect(api.reserve).not.toHaveBeenCalled();
});
it('real deferred focus acceptance waits for the previous RETURN and original main reap',async()=>{
  const api=sharedWallApi();const h=await timedRealWall(true);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(h.starts).toHaveLength(1));
  await h.accept(0);await h.negotiate(0);await act(async()=>h.players[0].presented(1));
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));await waitFor(()=>expect(h.starts).toHaveLength(2));
  await h.accept(1);await h.negotiate(1);await act(async()=>h.players[1].presented(1));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));await waitFor(()=>expect(h.starts).toHaveLength(3));
  await h.accept(2);await h.negotiate(2);await act(async()=>h.players[2].presented(1));
  // Inject an ordinary requested sub restart through the actual scheduler to
  // exercise acceptance while a different current main still owns RETURN.
  const b=Object.keys(h.scheduler.getSnapshot().states).find(id=>id.endsWith(channelId(1,2)))!;
  act(()=>{h.scheduler.requestStop(b);h.scheduler.requestPlay([b]);});await waitFor(()=>expect(h.starts).toHaveLength(4));
  expect(h.players[3].currentLeaseId).toBeNull();h.holdStops();
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 크게 보기'}));await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(2));
  await h.accept(3);await h.negotiate(3);await act(async()=>h.players[3].presented(1));
  expect(api.reserve.mock.calls.map(call=>call[2])).toEqual(['FORWARD','RETURN']);
  expect(h.players[3].closed).toBe(false);expect(h.starts).toHaveLength(4);expect(h.stops[0].id).toBe(channelId(1,1));
  await act(async()=>h.stops[0].resolve());await waitFor(()=>expect(h.starts).toHaveLength(5));
  await h.accept(4);await waitFor(()=>expect(api.reserve).toHaveBeenCalledTimes(3));
  expect(api.reserve.mock.calls.map(call=>call[2])).toEqual(['FORWARD','RETURN','FORWARD']);expect(h.starts[4].binding.stream).toBe('sub');
  await h.negotiate(4);await act(async()=>h.players[4].presented(1));expect(h.starts).toHaveLength(5);
  await act(async()=>h.stops[1].resolve());await waitFor(()=>expect(h.starts).toHaveLength(6));
  expect(h.starts[5].binding.stream).toBe('main');expect(h.starts[5].binding.focusRefId).toBeDefined();await h.accept(5);
});

it.each(['heartbeat','button'] as const)('publishes %s cleanup through held original owners and clears only after CLOSED',async trigger=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const stops=heldStops();const {players}=renderWall({sharedMode:true,timer:time.timer},stops.settle);await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  const stop=api.stop.getMockImplementation()!;let resolve!:(value:wallApi.LocalWallResponse)=>void;
  api.stop.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  if(trigger==='heartbeat') {api.heartbeat.mockRejectedValue(new Error('revoked'));await act(async()=>time.advance(10_000));}
  else fireEvent.click(screen.getByRole('button',{name:'전체 정지'}));
  expect(screen.getByText('영상 재생 중지 · 정리 확인 중')).toBeVisible();expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
  expect(api.stop).not.toHaveBeenCalled();
  await act(async()=>stops.release(0));await waitFor(()=>expect(resolve).toBeTypeOf('function'));
  expect(screen.getByText('영상 재생 중지 · 정리 확인 중')).toBeVisible();expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
  await act(async()=>resolve(await stop(...api.stop.mock.calls[0])));
  await waitFor(()=>expect(screen.queryByText('영상 재생 중지 · 정리 확인 중')).toBeNull());
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeEnabled();expect(api.stop).toHaveBeenCalledTimes(1);
});
it.each(['heartbeat-rejected','heartbeat-STOPPING','button-rejected','button-STOPPING'] as const)('renders the retained cleanup fence for %s',async scenario=>{
  stubInventories();const api=sharedWallApi();const time=manualTimer();const {players}=renderWall({sharedMode:true,timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await waitFor(()=>expect(players[0]?.started).toBe(true));act(()=>players[0].confirm());
  if(scenario.endsWith('rejected'))api.stop.mockRejectedValue(new Error('uncertain cleanup'));
  else {const stop=api.stop.getMockImplementation()!;api.stop.mockImplementation(async(...args)=>{const value=await stop(...args);return {...value,wall:{...value.wall,state:'STOPPING'}};});}
  if(scenario.startsWith('heartbeat')) {api.heartbeat.mockRejectedValue(new Error('revoked'));await act(async()=>time.advance(10_000));}
  else fireEvent.click(screen.getByRole('button',{name:'전체 정지'}));
  await act(async()=>Promise.resolve());
  expect(screen.getByText('영상 재생 중지 · 정리 확인 중')).toBeVisible();expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));await act(async()=>time.advance(60_000));
  expect(players).toHaveLength(1);expect(api.stop).toHaveBeenCalledTimes(1);expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
});

it('preserves real NO_SIGNAL while fencing an issued start without cleanup proof',async()=>{
  const h=await timedRealWall();fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  await act(async()=>{h.time.advance(16_000);h.starts[0].reject(new liveApi.LocalLiveError(504,'LOCAL_DEVICE_NO_SIGNAL'));});
  expect(within(tileOf('1호점 1번 채널')).getByText('영상 신호 없음')).toBeVisible();
  expect(h.scheduler.getSnapshot().retrying).toEqual([]);expect(h.scheduler.getSnapshot().coolingDown).toBe(false);
  expect(h.starts.map(s=>s.binding.channelId)).toEqual([channelId(1,1)]);
  await expect(h.players[0].stop()).rejects.toMatchObject({status:504,code:'LOCAL_DEVICE_NO_SIGNAL'});
  act(()=>h.time.advance(60_000));
  expect(h.starts).toHaveLength(1);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));await act(async()=>Promise.resolve());
  expect(h.starts).toHaveLength(1);expect(h.players[0].failureCode).toBe('LOCAL_DEVICE_NO_SIGNAL');
  expect(h.scheduler.getSnapshot().retrying).toEqual([]);expect(h.scheduler.getSnapshot().coolingDown).toBe(false);
});

it('gives delayed accepted starts separate negotiation and first-presentation budgets',async()=>{
  const h=await timedRealWall();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  act(()=>h.time.advance(24_000));expect(h.players[0].closed).toBe(false);await h.accept(0);
  act(()=>h.time.advance(24_000));await h.negotiate(0);
  act(()=>h.time.advance(14_000));await act(async()=>h.players[0].presented(1));
  expect(screen.getByText('실시간 1')).toBeVisible();expect(h.starts).toHaveLength(1);
  expect(h.scheduler.getSnapshot().retrying).toEqual([]);expect(h.scheduler.getSnapshot().coolingDown).toBe(false);
});

it('starts the HTTP clock only after a held original Stop settles',async()=>{
  const h=await timedRealWall();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  await h.accept(0);await h.negotiate(0);await act(async()=>h.players[0].presented(1));
  h.holdStops();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));
  act(()=>h.time.advance(24_000));expect(h.starts).toHaveLength(1);expect(h.players[1].closed).toBe(false);
  await act(async()=>h.stops[0].resolve());expect(h.starts).toHaveLength(2);
  await act(async()=>{h.time.advance(24_000);h.starts[1].reject(new liveApi.LocalLiveError(504,'LOCAL_DEVICE_NO_SIGNAL'));});
  expect(within(tileOf('1호점 2번 채널')).getByText('영상 신호 없음')).toBeVisible();
  expect(h.scheduler.getSnapshot().retrying).toEqual([]);expect(h.scheduler.getSnapshot().coolingDown).toBe(false);
});

it.each(['request','negotiation','presentation'] as const)('bounds a real player with no %s result without inventing NO_SIGNAL',async phase=>{
  const h=await timedRealWall();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  if(phase!=='request')await h.accept(0);
  if(phase==='presentation')await h.negotiate(0);
  const bound=phase==='request'?26_000:phase==='negotiation'?35_000:40_000;
  act(()=>h.time.advance(bound-1));expect(h.players[0].closed).toBe(false);
  await act(async()=>h.time.advance(1));
  expect(h.players[0].closed).toBe(true);expect(h.players[0].failureCode).toBeNull();
  expect(within(tileOf('1호점 1번 채널')).getByText('연결 실패')).toBeVisible();
  expect(screen.queryByText('영상 신호 없음')).toBeNull();
  if(phase==='request'){
    await act(async()=>h.time.advance(3_000));expect(h.starts).toHaveLength(1);
    await act(async()=>h.time.advance(26_000));
    expect(h.players.every(player=>player.closed)).toBe(true);expect(h.scheduler.getSnapshot().retrying).toEqual([]);
    await act(async()=>h.time.advance(60_000));expect(h.starts).toHaveLength(1);
  }
});

it('retires a late accepted lease after the request fallback without negotiating it',async()=>{
  const h=await timedRealWall();h.holdStops();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  await act(async()=>h.time.advance(26_000));expect(h.players[0].closed).toBe(true);
  await h.accept(0);expect(h.stops.map(stop=>stop.id)).toEqual([channelId(1,1)]);expect(h.offers).toHaveLength(0);
  expect(within(tileOf('1호점 1번 채널')).getByText('연결 실패')).toBeVisible();
  await act(async()=>h.stops[0].resolve());expect(h.players[0].closed).toBe(true);
});

it('bounds a held Stop wait while retaining the original barrier after timeout and retry',async()=>{
  const h=await timedRealWall();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  await h.accept(0);await h.negotiate(0);await act(async()=>h.players[0].presented(1));
  h.holdStops();fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));
  act(()=>h.time.advance(25_999));expect(h.players[1].closed).toBe(false);expect(h.starts).toHaveLength(1);
  await act(async()=>h.time.advance(1));expect(h.players[1].closed).toBe(true);
  await act(async()=>h.time.advance(3_000));expect(h.starts).toHaveLength(1);
  await act(async()=>h.stops[0].resolve());expect(h.starts).toHaveLength(2);
  expect(h.players[1].closed).toBe(true);expect(h.players.at(-1)!.closed).toBe(false);
});

it('switches a playing grid sub stream to main and back only after the original stop settles',async()=>{
  stubInventories();const stops=heldStops();const {players}=renderWall({},stops.settle);
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  expect(players[0].binding.stream).toBe('sub');
  act(()=>players[0].confirm());
  expect(within(tileOf('1호점 1번 채널')).getByText('저화질')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  expect(players[0].closed).toBe(true);
  expect(players[1].binding.stream).toBe('main');expect(players[1].started).toBe(false);
  expect(screen.getByText('고화질')).toBeVisible();
  await act(async()=>{stops.release(0);});
  expect(players[1].started).toBe(true);act(()=>players[1].confirm());
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  expect(players[1].closed).toBe(true);
  expect(players[2].binding.stream).toBe('sub');expect(players[2].started).toBe(false);
  await act(async()=>{stops.release(1);});
  expect(players[2].started).toBe(true);act(()=>players[2].confirm());
  expect(within(tileOf('1호점 1번 채널')).getByText('LIVE')).toBeVisible();
  expect(within(tileOf('1호점 1번 채널')).getByText('저화질')).toBeVisible();
  expect(players.filter(p=>!p.closed&&p.started)).toEqual([players[2]]);
});

it('does not revive a focused channel stopped by the user, and manual focused play chooses main',async()=>{
  stubInventories();const {players}=renderWall();await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  expect(players[0].binding.stream).toBe('main');act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  await act(async()=>{await Promise.resolve();});
  expect(players).toHaveLength(1);expect(players[0].closed).toBe(true);
  expect(within(tileOf('1호점 1번 채널')).getByText('영상 재생 중지')).toBeVisible();
});

it('requeues a busy main switch and keeps the focused stream selection on the next attempt',async()=>{
  stubInventories();const time=manualTimer();const {players}=renderWall({timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  await act(async()=>{await Promise.resolve();});
  expect(players[1].binding.stream).toBe('main');
  await act(async()=>{players[1].refuse(429,'LOCAL_DEVICE_BUSY');});
  expect(screen.getByText('재생 대기 (장치 사용 중)')).toBeVisible();
  expect(screen.queryByText('연결 실패')).toBeNull();
  act(()=>time.advance(3_000));
  expect(players[2].binding.stream).toBe('main');
  act(()=>players[2].confirm());expect(screen.getByText('실시간 1')).toBeVisible();
});

it('leaves exactly one current live session and no old leases after ten rapid enlarge/return cycles',async()=>{
  stubInventories();const stops=heldStops();const {players,unmount}=renderWall({},stops.settle);
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));act(()=>players[0].confirm());
  for(let i=0;i<10;i++){
    fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
    fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  }
  expect(players[0].closed).toBe(true);
  expect(players.filter(p=>p.started)).toHaveLength(1);
  expect(players.filter(p=>!p.closed)).toHaveLength(1);
  expect(players.filter(p=>p.leaseHeld)).toEqual([players[0]]);
  const current=players.at(-1)!;expect(current.binding.stream).toBe('sub');
  // Stale stream/frame/PLAYING events must neither attach a feed nor start another tile.
  act(()=>{players[0].deliver({id:'stale'} as MediaStream);players[0].confirm();});
  expect(screen.getByText('실시간 0')).toBeVisible();
  await act(async()=>{stops.release(0);});
  expect(current.started).toBe(true);act(()=>current.confirm());
  expect(screen.getByText('실시간 1')).toBeVisible();
  expect(players.filter(p=>!p.closed&&p.started)).toEqual([current]);
  expect(players.filter(p=>p.leaseHeld)).toEqual([current]);
  unmount();expect(current.closed).toBe(true);
  await act(async()=>{stops.release(1);});
  expect(players.filter(p=>p.leaseHeld)).toHaveLength(0);
});

it('retains real player late-start cleanup before restarting through ten rapid focus cycles',async()=>{
  stubInventories();const time=manualTimer();
  class Peer {
    iceGatheringState='complete';connectionState='new';localDescription={type:'offer',sdp:'v=0\r\n'};
    ontrack=null;onconnectionstatechange=null;closed=false;
    addTransceiver=()=>({setCodecPreferences:()=>undefined});createOffer=async()=>this.localDescription;
    setLocalDescription=async()=>undefined;setRemoteDescription=async()=>undefined;close=()=>{this.closed=true;};
  }
  vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/VP8',clockRate:90000}]})});
  const peers:Peer[]=[];const players:LocalLivePlayer[]=[];const requestedStreams:string[]=[];
  const firstLease='70000000-0000-4000-8000-000000000001';
  const finalLease='70000000-0000-4000-8000-000000000002';
  const owner={tenant_id:tenant,actor_user_id:'80000000-0000-4000-8000-000000000001',connection_id:recorderOne,store_id:storeOne};
  const lease=(id:string,state='NEGOTIATING')=>({id,owner,device:{...owner,device_id:device(1),channel_id:channelId(1,1)},channel:channelId(1,1),kind:'live',state,expires_at:'2026-10-05T00:00:30Z',heartbeat_at:'2026-10-05T00:00:00Z',connection_generation:1,inventory_revision:1,grant_revision:1});
  const reply=(id:string,state='NEGOTIATING')=>liveApi.localLiveResponse.parse({lease:lease(id,state),request_id:'request-1'});
  let releaseStart!:()=>void;let releaseLateStop!:()=>void;
  let activeLease:string|null=null;let starts=0;let offers=0;const retired:string[]=[];
  // Hold the API result at the player's boundary, after response validation.
  // Holding fetch itself would only exercise aborted JSON parsing, which cannot
  // deliver a lease result to the player's original late-result cleanup branch.
  vi.spyOn(liveApi,'startLocalLive').mockImplementation(async binding=>{
    requestedStreams.push(binding.stream!);starts++;
    if(activeLease)throw new liveApi.LocalLiveError(429,'LOCAL_DEVICE_BUSY');
    activeLease=starts===1?firstLease:finalLease;
    if(starts===1)return new Promise(resolve=>{releaseStart=()=>resolve(reply(firstLease));});
    return reply(finalLease);
  });
  vi.spyOn(liveApi,'stopLocalLive').mockImplementation(async(_binding,id)=>{
    const finish=()=>{retired.push(id);activeLease=null;return reply(id,'CLOSED');};
    if(id===firstLease)return new Promise(resolve=>{releaseLateStop=()=>resolve(finish());});
    return finish();
  });
  vi.spyOn(liveApi,'offerLocalLive').mockImplementation(async()=>{offers++;return {type:'answer',sdp:'v=0\r\n'};});
  vi.spyOn(liveApi,'reportLocalLivePlaying').mockImplementation(async(_binding,id)=>reply(id,'PLAYING'));
  const createPlayer:LiveWallPlayerFactory=(binding,csrf,events)=>{
    const player=new LocalLivePlayer(binding,csrf,events,()=>{const peer=new Peer();peers.push(peer);return peer as unknown as RTCPeerConnection;});
    players.push(player);return player;
  };
  const {unmount}=renderWall({createPlayer,timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  expect(requestedStreams).toEqual(['sub']);
  for(let i=0;i<10;i++){
    fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
    fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  }
  await act(async()=>Promise.resolve());
  expect(requestedStreams).toEqual(['sub']);expect(offers).toBe(0);
  expect(players.filter(p=>!p.closed)).toHaveLength(1);expect(peers).toHaveLength(1);expect(peers[0].closed).toBe(false);
  await act(async()=>{releaseStart();});
  await waitFor(()=>expect(releaseLateStop).toBeTypeOf('function'));
  expect(activeLease).toBe(firstLease);expect(retired).toEqual([]);
  await act(async()=>{releaseLateStop();});expect(retired).toEqual([firstLease]);
  act(()=>time.advance(3_000));await waitFor(()=>expect(offers).toBe(1));
  await act(async()=>{await players.at(-1)!.presented(1);});
  expect(screen.getByText('실시간 1')).toBeVisible();
  expect(requestedStreams).toEqual(['sub','sub']);
  expect(activeLease).toBe(finalLease);expect(players.filter(p=>!p.closed)).toHaveLength(1);
  unmount();await waitFor(()=>expect(activeLease).toBeNull());
  expect(retired).toEqual([firstLease,finalLease]);expect(peers.every(p=>p.closed)).toBe(true);
});

it('isolates no signal, immediately starts the next tile without cooldown, and waits for manual retry',async()=>{
  stubInventories();const time=manualTimer();const {players}=renderWall({timer:time.timer});await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  await act(async()=>{players[0].refuse(504,'LOCAL_DEVICE_NO_SIGNAL');});
  expect(within(tileOf('1호점 1번 채널')).getByText('영상 신호 없음')).toBeVisible();
  expect(players[1].started).toBe(true);
  for(let i=1;i<7;i++)act(()=>players[i].confirm());
  expect(screen.getByText('실시간 6')).toBeVisible();
  act(()=>time.advance(60_000));expect(players).toHaveLength(7);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  expect(players[7].started).toBe(true);expect(players[7].binding.stream).toBe('sub');
  act(()=>players[7].confirm());expect(screen.getByText('실시간 7')).toBeVisible();
});

it('switches a full wall live tile before admitting a queued channel and preserves the other fifteen players',async()=>{
  stubInventories({[`${recorderOne}/${storeOne}`]:available(recorderOne,storeOne,1,17)});
  const stops=heldStops();const time=manualTimer();const {players}=renderWall({stores:[stores[0]],connections:[connections[0]],timer:time.timer},stops.settle);
  await screen.findByText('전체 채널 17');
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  for(let i=0;i<16;i++)act(()=>players[i].confirm());
  expect(players).toHaveLength(16);
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 크게 보기'}));
  expect(players).toHaveLength(17);
  expect(players[16].binding.channelId).toBe(channelId(1,1));
  expect(players[16].binding.stream).toBe('main');expect(players[16].started).toBe(false);
  expect(players.slice(1,16).every(p=>!p.closed)).toBe(true);
  await act(async()=>{stops.release(0);});
  expect(players[16].started).toBe(true);act(()=>players[16].confirm());
  expect(screen.getByText('실시간 16')).toBeVisible();expect(screen.getByText('재생 대기 1')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  expect(players[17].binding.channelId).toBe(channelId(1,1));
  expect(players[17].binding.stream).toBe('sub');expect(players[17].started).toBe(false);
  await act(async()=>{stops.release(1);});
  expect(players[17].started).toBe(true);
  // A STOPPING row can still refuse the replacement. Its retry must retain
  // the returning tile's place ahead of the ordinary seventeenth waiter.
  await act(async()=>{players[17].refuse(429,'LOCAL_DEVICE_BUSY');});
  expect(within(tileOf('1호점 1번 채널')).getByText('재생 대기 (장치 사용 중)')).toBeVisible();
  await act(async()=>{stops.release(2);});
  act(()=>time.advance(3_000));
  expect(players[18].binding.channelId).toBe(channelId(1,1));
  expect(players[18].binding.stream).toBe('sub');act(()=>players[18].confirm());
  expect(screen.getByText('실시간 16')).toBeVisible();expect(screen.getByText('재생 대기 1')).toBeVisible();
  expect(players.slice(1,16).every(p=>!p.closed)).toBe(true);
});

it('returns queued channel eighteen through busy before older channel seventeen while awaiting each original stop',async()=>{
  stubInventories({[`${recorderOne}/${storeOne}`]:available(recorderOne,storeOne,1,18)});
  const stops=heldStops();const time=manualTimer();
  const {players}=renderWall({stores:[stores[0]],connections:[connections[0]],timer:time.timer},stops.settle);
  await screen.findByText('전체 채널 18');
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  for(let i=0;i<16;i++)act(()=>players[i].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 18번 채널 크게 보기'}));
  expect(players[0].closed).toBe(true);
  expect(players[16].binding.channelId).toBe(channelId(1,18));
  expect(players[16].binding.stream).toBe('main');expect(players[16].started).toBe(false);
  await act(async()=>{stops.release(0);});
  expect(players[16].started).toBe(true);act(()=>players[16].confirm());
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  expect(players[16].closed).toBe(true);
  expect(players[17].binding.channelId).toBe(channelId(1,18));
  expect(players[17].binding.stream).toBe('sub');expect(players[17].started).toBe(false);
  await act(async()=>{stops.release(1);});
  expect(players[17].started).toBe(true);
  await act(async()=>{players[17].refuse(429,'LOCAL_DEVICE_BUSY');});
  expect(within(tileOf('1호점 18번 채널')).getByText('재생 대기 (장치 사용 중)')).toBeVisible();
  act(()=>time.advance(3_000));
  expect(players[18].binding.channelId).toBe(channelId(1,18));
  expect(players[18].binding.stream).toBe('sub');expect(players[18].started).toBe(false);
  expect(players.slice(1,16).every(p=>!p.closed&&p.leaseHeld)).toBe(true);
  // Cooldown expiry cannot bypass the refused replacement's original Stop.
  expect(players[17].leaseHeld).toBe(true);
  await act(async()=>{stops.release(2);});
  expect(players[17].leaseHeld).toBe(false);expect(players[18].started).toBe(true);
  act(()=>players[18].confirm());expect(screen.getByText('실시간 16')).toBeVisible();
  expect(screen.getByText('재생 대기 2')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 중지'}));
  expect(players[19].binding.channelId).toBe(channelId(1,17));expect(players[19].started).toBe(false);
  await act(async()=>{stops.release(3);});act(()=>players[19].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 3번 채널 중지'}));
  expect(players[20].binding.channelId).toBe(channelId(1,1));expect(players[20].started).toBe(false);
  await act(async()=>{stops.release(4);});act(()=>players[20].confirm());
  expect(screen.getByText('실시간 16')).toBeVisible();
  expect(players.filter(p=>p.leaseHeld)).toHaveLength(16);
});

const frameCallbacks:VideoFrameRequestCallback[]=[];
beforeEach(()=>{
  frameCallbacks.length=0;
  // jsdom has no media pipeline: record frame callbacks so the test can present a frame explicitly.
  Object.assign(HTMLVideoElement.prototype,{
    requestVideoFrameCallback(callback:VideoFrameRequestCallback){frameCallbacks.push(callback);return frameCallbacks.length;},
    cancelVideoFrameCallback(){},
  });
  vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined);
});
afterEach(()=>{
  cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();
  const prototype=HTMLVideoElement.prototype as {requestVideoFrameCallback?:unknown;cancelVideoFrameCallback?:unknown};
  delete prototype.requestVideoFrameCallback;delete prototype.cancelVideoFrameCallback;
});

it('formats the control-room clock as local YYYY-MM-DD HH:MM:SS',()=>{
  expect(formatClock(new Date(2026,9,4,9,5,3))).toBe('2026-10-04 09:05:03');
  expect(formatClock(new Date(2026,11,31,23,59,59))).toBe('2026-12-31 23:59:59');
});

it('renders a section per store with tiles from the saved inventories and never plays on load',async()=>{
  const send=stubInventories();
  const {createPlayer}=renderWall();
  await inventoriesLoaded();
  const first=screen.getByRole('region',{name:'1호점'});
  const second=screen.getByRole('region',{name:'2호점'});
  expect(within(first).getAllByRole('listitem')).toHaveLength(4);
  expect(within(second).getAllByRole('listitem')).toHaveLength(3);
  expect(within(first).getByText('1호점 녹화기')).toBeVisible();
  expect(within(first).getByText('4채널 · 실시간 0')).toBeVisible();
  expect(within(second).getByText('CH 03')).toBeVisible();
  const video=within(first).getByLabelText<HTMLVideoElement>('1호점 2번 채널',{selector:'video'});
  expect(video).toHaveClass('object-fill');
  expect(video.muted).toBe(true);expect(video.autoplay).toBe(true);expect(video).toHaveAttribute('playsinline');
  expect(within(first).getAllByText('정지됨')).toHaveLength(4);
  expect(within(tileOf('1호점 2번 채널')).getByText('2번 채널')).toBeVisible();
  expect(within(first).getByRole('button',{name:'1호점 2번 채널 재생'})).toBeVisible();
  const third=screen.getByRole('region',{name:'3호점'});
  expect(within(third).getByText(/기기 확인/)).toBeVisible();
  expect(within(third).getByRole('link',{name:/연결 관리/})).toHaveAttribute('href',`/connections?tenant_id=${tenant}`);
  expect(screen.getByRole('heading',{level:1,name:'통합 관제'})).toBeVisible();
  expect(screen.getByText('모든 매장의 모든 채널을 한 화면에서 실시간으로 확인합니다.')).toBeVisible();
  expect(screen.getByText('실시간 0')).toBeVisible();
  expect(screen.getByText('재생 대기 0')).toBeVisible();
  expect(screen.getByText('전체 채널 7')).toBeVisible();
  expect(screen.getByText('2026-10-04 09:05:03')).toBeVisible();
  const filter=screen.getByRole('group',{name:'매장 선택'});
  expect(within(filter).getByRole('button',{name:'전체 매장 · 7'})).toHaveAttribute('aria-pressed','true');
  expect(within(filter).getByRole('button',{name:'1호점 · 4'})).toHaveAttribute('aria-pressed','false');
  expect(within(filter).getByRole('button',{name:'2호점 · 3'})).toBeVisible();
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeEnabled();
  expect(send).toHaveBeenCalledTimes(3);
  for(const [url,init] of send.mock.calls){
    expect(String(url)).toMatch(/^\/api\/local-devices\/[0-9a-f-]{36}\/channels\?tenant_id=/);
    expect(init?.method).toBe('GET');
  }
  expect(createPlayer).not.toHaveBeenCalled();
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
});

it('changes the grid column count with the layout switch',async()=>{
  stubInventories();renderWall();
  await inventoriesLoaded();
  const list=screen.getByRole('list',{name:'1호점 채널'});
  const layout=screen.getByRole('group',{name:'화면 배치'});
  expect(list).toHaveAttribute('data-columns','auto');
  expect(within(layout).getByRole('button',{name:'자동'})).toHaveAttribute('aria-pressed','true');
  expect(list).toHaveClass('grid','gap-3','grid-cols-1','sm:grid-cols-2','lg:grid-cols-3','xl:grid-cols-4');
  fireEvent.click(within(layout).getByRole('button',{name:'2열'}));
  expect(list).toHaveAttribute('data-columns','2');
  expect(within(layout).getByRole('button',{name:'2열'})).toHaveAttribute('aria-pressed','true');
  expect(within(layout).getByRole('button',{name:'자동'})).toHaveAttribute('aria-pressed','false');
  expect(list).toHaveClass('grid-cols-1','sm:grid-cols-2');
  expect(list).not.toHaveClass('lg:grid-cols-3');
  fireEvent.click(within(layout).getByRole('button',{name:'3열'}));
  expect(list).toHaveAttribute('data-columns','3');
  expect(list).toHaveClass('lg:grid-cols-3');
  fireEvent.click(within(layout).getByRole('button',{name:'4열'}));
  expect(list).toHaveAttribute('data-columns','4');
  expect(list).toHaveClass('lg:grid-cols-4');
  expect(screen.getByRole('list',{name:'2호점 채널'})).toHaveAttribute('data-columns','4');
});

it('filters the wall to one store with the chips and the section shortcut',async()=>{
  stubInventories();renderWall();
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'2호점 · 3'}));
  expect(screen.queryByRole('region',{name:'1호점'})).toBeNull();
  const second=screen.getByRole('region',{name:'2호점'});
  expect(screen.getByRole('button',{name:'2호점 · 3'})).toHaveAttribute('aria-pressed','true');
  expect(screen.getByRole('button',{name:'전체 매장 · 7'})).toHaveAttribute('aria-pressed','false');
  fireEvent.click(within(second).getByRole('button',{name:'전체 매장 보기'}));
  const first=screen.getByRole('region',{name:'1호점'});
  expect(screen.getByRole('region',{name:'2호점'})).toBeVisible();
  fireEvent.click(within(first).getByRole('button',{name:'이 매장만 보기'}));
  expect(screen.queryByRole('region',{name:'2호점'})).toBeNull();
  expect(screen.getByRole('button',{name:'1호점 · 4'})).toHaveAttribute('aria-pressed','true');
  fireEvent.click(screen.getByRole('button',{name:'전체 매장 · 7'}));
  expect(screen.getByRole('region',{name:'3호점'})).toBeVisible();
});

it('opens a focused channel with a fit toggle and filmstrip, and returns without starting playback',async()=>{
  stubInventories();const {createPlayer}=renderWall();
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 크게 보기'}));
  const back=screen.getByRole('button',{name:'통합 관제'});
  expect(back).toHaveFocus();
  expect(screen.getByRole('heading',{name:'1호점 2번 채널'})).toBeVisible();
  expect(screen.queryByRole('region',{name:'2호점'})).toBeNull();
  const video=screen.getByLabelText('1호점 2번 채널',{selector:'video'});
  expect(video).toHaveClass('object-fill');
  const fit=screen.getByRole('group',{name:'화면 맞춤'});
  expect(within(fit).getByRole('button',{name:'화면 채우기'})).toHaveAttribute('aria-pressed','true');
  fireEvent.click(within(fit).getByRole('button',{name:'원본 비율'}));
  expect(video).toHaveClass('object-contain');
  expect(video).not.toHaveClass('object-fill');
  expect(within(fit).getByRole('button',{name:'원본 비율'})).toHaveAttribute('aria-pressed','true');
  expect(screen.getByRole('button',{name:'1호점 2번 채널 재생'})).toBeVisible();
  const strip=screen.getByRole('navigation',{name:'채널 목록'});
  expect(within(strip).getAllByRole('button')).toHaveLength(7);
  expect(within(strip).getByText('1호점')).toBeVisible();
  expect(within(strip).getByRole('button',{name:'1호점 2번 채널 크게 보기'})).toHaveAttribute('aria-current','true');
  fireEvent.click(within(strip).getByRole('button',{name:'2호점 1번 채널 크게 보기'}));
  expect(screen.getByRole('heading',{name:'2호점 1번 채널'})).toBeVisible();
  expect(screen.getByLabelText('2호점 1번 채널',{selector:'video'})).toHaveClass('object-contain');
  fireEvent.click(screen.getByRole('button',{name:'통합 관제'}));
  expect(screen.getByRole('region',{name:'1호점'})).toBeVisible();
  expect(screen.getByRole('button',{name:'2호점 1번 채널 크게 보기'})).toHaveFocus();
  fireEvent.click(screen.getByRole('button',{name:'1호점 3번 채널 크게 보기'}));
  fireEvent.keyDown(screen.getByRole('button',{name:'통합 관제'}),{key:'Escape'});
  expect(screen.getByRole('region',{name:'2호점'})).toBeVisible();
  expect(screen.getByRole('button',{name:'1호점 3번 채널 크게 보기'})).toHaveFocus();
  expect(createPlayer).not.toHaveBeenCalled();
});

it('plays all tiles on request, one start at a time within the backend capacity',async()=>{
  stubInventories();const {createPlayer,players}=renderWall();
  await inventoriesLoaded();
  expect(createPlayer).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  expect(createPlayer).toHaveBeenCalledTimes(1);
  expect(players[0].binding).toEqual({tenantId:tenant,connectionId:recorderOne,storeId:storeOne,deviceId:device(1),channelId:channelId(1,1),generation:1,inventoryRevision:1,stream:'sub'});
  expect(players[0].csrf).toBe('csrf-token');
  expect(players[0].started).toBe(true);
  expect(within(tileOf('1호점 1번 채널')).getByText('연결 중')).toBeVisible();
  expect(within(tileOf('1호점 2번 채널')).getByText('대기 순서 1')).toBeVisible();
  expect(within(tileOf('2호점 3번 채널')).getByText('대기 순서 6')).toBeVisible();
  expect(screen.getByText('재생 대기 6')).toBeVisible();
  const stream={id:'fake-stream'} as unknown as MediaStream;
  act(()=>players[0].deliver(stream));
  const video=screen.getByLabelText<HTMLVideoElement>('1호점 1번 채널',{selector:'video'});
  expect(video.srcObject).toBe(stream);
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  expect(frameCallbacks).toHaveLength(1);
  act(()=>frameCallbacks[0](0,{presentedFrames:3} as VideoFrameCallbackMetadata));
  expect(players[0].frames).toEqual([3]);
  expect(createPlayer).toHaveBeenCalledTimes(1);
  act(()=>players[0].confirm());
  expect(within(tileOf('1호점 1번 채널')).getByText('LIVE')).toBeVisible();
  expect(createPlayer).toHaveBeenCalledTimes(2);
  expect(players[1].binding.channelId).toBe(channelId(1,2));
  act(()=>players[1].confirm());
  expect(createPlayer).toHaveBeenCalledTimes(3);
  expect(screen.getByText('실시간 2')).toBeVisible();
  expect(screen.getByText('재생 대기 4')).toBeVisible();
  expect(within(screen.getByRole('region',{name:'1호점'})).getByText('4채널 · 실시간 2')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'전체 정지'}));
  expect(players.every(player=>player.closed)).toBe(true);
  expect(video.srcObject).toBeNull();
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeVisible();
  expect(screen.getByText('실시간 0')).toBeVisible();
  expect(screen.getByText('재생 대기 0')).toBeVisible();
});

it('gives an enlarged queued channel priority without preempting live tiles while sixteen slots remain',async()=>{
  stubInventories();const {players}=renderWall();
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  act(()=>players[0].confirm());
  act(()=>players[1].confirm());
  fireEvent.click(screen.getByRole('button',{name:'2호점 2번 채널 크게 보기'}));
  expect(players[0].closed).toBe(false);
  expect(players[1].closed).toBe(false);
  expect(players).toHaveLength(3);
  act(()=>players[2].confirm());
  expect(players[3].binding.channelId).toBe(channelId(2,2));
  expect(players[3].binding.stream).toBe('main');
  expect(screen.getByRole('button',{name:'2호점 2번 채널 중지'})).toBeVisible();
});

it('plays one tile from its own button and shows a failure only on that tile',async()=>{
  stubInventories();const time=manualTimer();const {createPlayer,players}=renderWall({timer:time.timer});
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'2호점 3번 채널 재생'}));
  expect(createPlayer).toHaveBeenCalledTimes(1);
  expect(players[0].binding.channelId).toBe(channelId(2,3));
  const tile=tileOf('2호점 3번 채널');
  expect(within(tile).getByRole('button',{name:'2호점 3번 채널 중지'})).toBeVisible();
  await act(async()=>{players[0].fail();});
  expect(within(tile).getByText('연결 실패')).toBeVisible();
  expect(screen.getAllByText('연결 실패')).toHaveLength(1);
  // An explicit retry still waits out the cool-down that follows every failed start.
  fireEvent.click(within(tile).getByRole('button',{name:'2호점 3번 채널 다시 시도'}));
  expect(within(tile).getByText('재생 대기')).toBeVisible();
  expect(createPlayer).toHaveBeenCalledTimes(1);
  act(()=>time.advance(3_000));
  expect(createPlayer).toHaveBeenCalledTimes(2);
  expect(within(tile).getByText('연결 중')).toBeVisible();
  fireEvent.click(within(tile).getByRole('button',{name:'2호점 3번 채널 중지'}));
  expect(players[1].closed).toBe(true);
  expect(within(tile).getByText('영상 재생 중지')).toBeVisible();
});

it('advances past three parked busy channels while retaining their original Stop barriers and six existing players',async()=>{
  stubInventories({[`${recorderOne}/${storeOne}`]:available(recorderOne,storeOne,1,8),[`${recorderTwo}/${storeTwo}`]:available(recorderTwo,storeTwo,2,4)});
  const time=manualTimer();const stops=heldStops();const {players,unmount}=renderWall({stores:stores.slice(0,2),connections,timer:time.timer},stops.settle);
  await screen.findByText('전체 채널 12');
  for(const [index,label] of ['1호점 1번 채널','1호점 2번 채널','1호점 3번 채널','1호점 4번 채널','1호점 5번 채널','2호점 1번 채널'].entries()){
    fireEvent.click(screen.getByRole('button',{name:`${label} 재생`}));act(()=>players[index].confirm());
  }
  for(const label of ['1호점 6번 채널','1호점 7번 채널','1호점 8번 채널','2호점 2번 채널','2호점 3번 채널','2호점 4번 채널'])fireEvent.click(screen.getByRole('button',{name:`${label} 재생`}));
  for(let index=6;index<9;index++){
    expect(players[index].started).toBe(true);
    await act(async()=>{players[index].refuse(429,'LOCAL_DEVICE_BUSY');});
    expect(players).toHaveLength(index+2);
    expect(players[index+1].started).toBe(false);expect(players[index].leaseHeld).toBe(true);
    await act(async()=>{stops.release(index-6);});expect(players[index+1].started).toBe(true);
  }
  expect(players[9].binding.channelId).toBe(channelId(2,2));
  for(let index=9;index<12;index++)act(()=>players[index].confirm());
  expect(screen.getByText('실시간 9')).toBeVisible();expect(screen.getByText('재생 대기 3')).toBeVisible();
  expect(players.slice(0,6).every(player=>!player.closed&&player.leaseHeld)).toBe(true);
  const count=players.length;unmount();act(()=>time.advance(60_000));expect(players).toHaveLength(count);
});

it('retries one parked busy target without consuming its ordinary retry and permits other play requests',async()=>{
  stubInventories();const time=manualTimer();const {createPlayer,players}=renderWall({timer:time.timer});
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  const first=tileOf('1호점 1번 채널');
  // The device refuses the first three starts with HTTP 429 while it retires an earlier session.
  for(const [refusal,coolDown] of [[0,3_000],[1,6_000],[2,12_000]] as const){
    expect(createPlayer).toHaveBeenCalledTimes(refusal+1);
    expect(players[refusal].binding.channelId).toBe(channelId(1,1));
    await act(async()=>{players[refusal].refuse(429);});
    expect(within(first).getByText('재생 대기 (장치 사용 중)')).toBeVisible();
    expect(within(first).getByText('대기 순서 1')).toBeVisible();
    expect(screen.queryAllByText('연결 실패')).toHaveLength(0);
    act(()=>time.advance(coolDown-1));
    expect(createPlayer).toHaveBeenCalledTimes(refusal+1);
    act(()=>time.advance(1));
  }
  // The fourth start is accepted; another manual request starts without a cool-down.
  expect(createPlayer).toHaveBeenCalledTimes(4);
  act(()=>players[3].confirm());
  expect(within(first).getByText('LIVE')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));
  expect(createPlayer).toHaveBeenCalledTimes(5);
  expect(players[4].binding.channelId).toBe(channelId(1,2));
  act(()=>players[4].confirm());
  expect(screen.getByText('실시간 2')).toBeVisible();
  expect(screen.getByText('재생 대기 0')).toBeVisible();
  expect(screen.queryAllByText('연결 실패')).toHaveLength(0);
  // A real (non-429) failure afterwards still uses the single retry path and shows on its tile.
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 3번 채널 재생'}));
  expect(createPlayer).toHaveBeenCalledTimes(6);
  await act(async()=>{players[5].refuse(503);});
  expect(within(tileOf('1호점 3번 채널')).getByText('연결 실패')).toBeVisible();
});

it('accepts a play click in the same task that first renders the tile',async()=>{
  stubInventories();const {createPlayer}=renderWall();
  // A microtask right after the commit that adds the tile, before any passive effect could run.
  let clicked=false;
  const observer=new MutationObserver(()=>{
    const button=screen.queryByRole('button',{name:'1호점 1번 채널 재생'});
    if(!button||clicked)return;
    clicked=true;observer.disconnect();button.click();
  });
  observer.observe(document.body,{childList:true,subtree:true});
  try{await waitFor(()=>expect(createPlayer).toHaveBeenCalledTimes(1));}finally{observer.disconnect();}
  expect(createPlayer.mock.calls[0][0].channelId).toBe(channelId(1,1));
});

it('stops playback hidden by the store filter and releases every player on unmount',async()=>{
  stubInventories();const {players,unmount}=renderWall();
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  fireEvent.click(screen.getByRole('button',{name:'2호점 1번 채널 재생'}));
  expect(players).toHaveLength(1);
  fireEvent.click(screen.getByRole('button',{name:'2호점 · 3'}));
  expect(players[0].closed).toBe(true);
  expect(players).toHaveLength(2);
  expect(players[1].binding.channelId).toBe(channelId(2,1));
  unmount();
  expect(players[1].closed).toBe(true);
});

it('opens a newly requested session only after the previous stop has settled',async()=>{
  stubInventories();
  const stops=heldStops();
  const {players,createPlayer}=renderWall({},stops.settle);
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));
  expect(players[0].closed).toBe(true);
  expect(createPlayer).toHaveBeenCalledTimes(2);
  expect(players[1].binding.channelId).toBe(channelId(1,2));
  expect(within(tileOf('1호점 2번 채널')).getByText('연결 중')).toBeVisible();
  await act(async()=>{await Promise.resolve();});
  expect(players[1].started).toBe(false);
  await act(async()=>{stops.release(0);});
  await waitFor(()=>expect(players[1].started).toBe(true));
});

it('drops LIVE as soon as a live player stops itself, before its failure report settles',async()=>{
  stubInventories();
  const stops=heldStops();
  const {players,createPlayer}=renderWall({},stops.settle);
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 재생'}));
  act(()=>players[0].confirm());
  fireEvent.click(screen.getByRole('button',{name:'1호점 2번 채널 재생'}));
  act(()=>players[1].confirm());
  const tile=tileOf('1호점 1번 채널');
  expect(within(tile).getByText('LIVE')).toBeVisible();
  // Emits stream(null) and 'stopped' now; 'failed' only arrives once the held stop request settles.
  await act(async()=>{players[0].fail();});
  expect(within(tile).queryByText('LIVE')).toBeNull();
  expect(within(tile).getByText('연결 실패')).toBeVisible();
  expect(screen.getByText('실시간 1')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'1호점 3번 채널 재생'}));
  expect(createPlayer).toHaveBeenCalledTimes(3);
  expect(players[2].started).toBe(false);
  await act(async()=>{stops.release(0);});
  await waitFor(()=>expect(players[2].started).toBe(true));
  expect(within(tile).getByText('연결 실패')).toBeVisible();
});

it('names 통합 관제 in the shell header and navigation for the wall page',()=>{
  render(<ServiceShell csrf="csrf-token" active="monitoring" connectionTenant={tenant}><p>wall</p></ServiceShell>);
  expect(screen.getByText('통합 관제',{selector:'header span'})).toBeVisible();
  expect(screen.queryByText('매장 관리 / 내 매장')).toBeNull();
  const links=screen.getAllByRole('link',{name:'통합 관제'});
  expect(links.length).toBeGreaterThan(0);
  for(const link of links){
    expect(link).toHaveAttribute('href',`/monitoring?tenant_id=${tenant}`);
    expect(link).toHaveAttribute('aria-current','page');
  }
});

it('explains how to prepare channels when no TVT recorder is linked to a store',()=>{
  const send=stubInventories();
  renderWall({connections:[]});
  expect(screen.getByRole('heading',{name:'재생할 CCTV 채널이 없습니다'})).toBeVisible();
  expect(screen.getByText(/기기 확인/)).toBeVisible();
  expect(screen.getByRole('link',{name:'연결 관리로 이동'})).toHaveAttribute('href',`/connections?tenant_id=${tenant}`);
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
  expect(send).not.toHaveBeenCalled();
});

it('shows the device-check card when no saved inventory is playable',async()=>{
  stubInventories({
    [`${recorderOne}/${storeOne}`]:unavailable(recorderOne,storeOne,1),
    [`${recorderTwo}/${storeTwo}`]:unavailable(recorderTwo,storeTwo,2),
    [`${recorderTwo}/${storeThree}`]:unavailable(recorderTwo,storeThree,3),
  });
  const {createPlayer}=renderWall();
  expect(await screen.findByRole('heading',{name:'재생할 CCTV 채널이 없습니다'})).toBeVisible();
  expect(screen.getByRole('link',{name:'연결 관리로 이동'})).toHaveAttribute('href',`/connections?tenant_id=${tenant}`);
  expect(screen.queryByRole('region',{name:'1호점'})).toBeNull();
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeDisabled();
  expect(createPlayer).not.toHaveBeenCalled();
});
