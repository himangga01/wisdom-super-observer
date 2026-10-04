// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {ServiceShell} from '../src/components/service-shell';
import {formatClock, LiveWall, type LiveWallClock, type LiveWallPlayerEvents, type LiveWallPlayerFactory} from '../src/features/monitoring/live-wall';
import type {ConnectionView} from '../src/lib/connections';
import type {LocalLiveBinding} from '../src/lib/tvt/local-live-api';

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
  closed=false;playbackConfirmed=false;started=false;failureStatus:number|null=null;readonly frames:number[]=[];
  private closing:Promise<void>|null=null;
  constructor(readonly binding:LocalLiveBinding,readonly csrf:string,private readonly events:LiveWallPlayerEvents,private readonly settleStop:()=>Promise<void>){}
  async start(){this.started=true;this.events.state('connecting');}
  stop(){
    if(this.closing)return this.closing;
    this.closed=true;this.events.stream(null);this.events.state('stopped');
    this.closing=this.settleStop();
    return this.closing;
  }
  async presented(frames:number){this.frames.push(frames);}
  deliver(stream:MediaStream){this.events.stream(stream);}
  confirm(){this.playbackConfirmed=true;this.events.state('playing');}
  fail(){void this.stop().then(()=>this.events.state('failed'));}
  /** A start the server refused with this HTTP status (e.g. 429 while the device retires a session). */
  refuse(status:number){this.failureStatus=status;this.fail();}
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
  expect(players[0].binding).toEqual({tenantId:tenant,connectionId:recorderOne,storeId:storeOne,deviceId:device(1),channelId:channelId(1,1),generation:1,inventoryRevision:1});
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
  expect(createPlayer).toHaveBeenCalledTimes(2);
  expect(screen.getByText('실시간 2')).toBeVisible();
  expect(screen.getByText('재생 대기 5')).toBeVisible();
  expect(within(screen.getByRole('region',{name:'1호점'})).getByText('4채널 · 실시간 2')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'전체 정지'}));
  expect(players.every(player=>player.closed)).toBe(true);
  expect(video.srcObject).toBeNull();
  expect(screen.getByRole('button',{name:'전체 재생'})).toBeVisible();
  expect(screen.getByText('실시간 0')).toBeVisible();
  expect(screen.getByText('재생 대기 0')).toBeVisible();
});

it('gives the enlarged channel priority over the least-recently-started live tile',async()=>{
  stubInventories();const {players}=renderWall();
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  act(()=>players[0].confirm());
  act(()=>players[1].confirm());
  fireEvent.click(screen.getByRole('button',{name:'2호점 2번 채널 크게 보기'}));
  expect(players[0].closed).toBe(true);
  expect(players[1].closed).toBe(false);
  expect(players).toHaveLength(3);
  expect(players[2].binding.channelId).toBe(channelId(2,2));
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
  expect(within(tile).getByText('정지됨')).toBeVisible();
});

it('waits out a busy device instead of failing every tile, then plays once starts are accepted',async()=>{
  stubInventories();const time=manualTimer();const {createPlayer,players}=renderWall({timer:time.timer});
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
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
  // The fourth start is accepted: the tile goes live and the next tile starts without a cool-down.
  expect(createPlayer).toHaveBeenCalledTimes(4);
  act(()=>players[3].confirm());
  expect(within(first).getByText('LIVE')).toBeVisible();
  expect(createPlayer).toHaveBeenCalledTimes(5);
  expect(players[4].binding.channelId).toBe(channelId(1,2));
  act(()=>players[4].confirm());
  expect(screen.getByText('실시간 2')).toBeVisible();
  expect(screen.getByText('재생 대기 5')).toBeVisible();
  expect(screen.queryAllByText('연결 실패')).toHaveLength(0);
  // A real (non-429) failure afterwards still uses the single retry path and shows on its tile.
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
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

it('opens the next session only after the previous stop has settled (promote and focus preemption)',async()=>{
  stubInventories();
  const stops=heldStops();
  const {players,createPlayer}=renderWall({},stops.settle);
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  act(()=>players[0].confirm());
  act(()=>players[1].confirm());
  // A user stop promotes the next queued tile: it shows 연결 중 at once, but its session waits for the closing one.
  fireEvent.click(screen.getByRole('button',{name:'1호점 1번 채널 중지'}));
  expect(players[0].closed).toBe(true);
  expect(createPlayer).toHaveBeenCalledTimes(3);
  expect(players[2].binding.channelId).toBe(channelId(1,3));
  expect(within(tileOf('1호점 3번 채널')).getByText('연결 중')).toBeVisible();
  await act(async()=>{await Promise.resolve();});
  expect(players[2].started).toBe(false);
  await act(async()=>{stops.release(0);});
  await waitFor(()=>expect(players[2].started).toBe(true));
  // Focus preemption waits the same way for the yielding tile's stop.
  act(()=>players[2].confirm());
  fireEvent.click(screen.getByRole('button',{name:'2호점 2번 채널 크게 보기'}));
  expect(players[1].closed).toBe(true);
  expect(players[3].binding.channelId).toBe(channelId(2,2));
  await act(async()=>{await Promise.resolve();});
  expect(players[3].started).toBe(false);
  await act(async()=>{stops.release(1);});
  await waitFor(()=>expect(players[3].started).toBe(true));
});

it('drops LIVE as soon as a live player stops itself, before its failure report settles',async()=>{
  stubInventories();
  const stops=heldStops();
  const {players,createPlayer}=renderWall({},stops.settle);
  await inventoriesLoaded();
  fireEvent.click(screen.getByRole('button',{name:'전체 재생'}));
  act(()=>players[0].confirm());
  act(()=>players[1].confirm());
  const tile=tileOf('1호점 1번 채널');
  expect(within(tile).getByText('LIVE')).toBeVisible();
  // Emits stream(null) and 'stopped' now; 'failed' only arrives once the held stop request settles.
  await act(async()=>{players[0].fail();});
  expect(within(tile).queryByText('LIVE')).toBeNull();
  expect(within(tile).getByText('연결 실패')).toBeVisible();
  expect(screen.getByText('실시간 1')).toBeVisible();
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
