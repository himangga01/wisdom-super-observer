// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {LocalLivePanel} from '../src/features/connections/local-live-panel';
import {ConnectionsView} from '../src/features/connections/connections-view';
import type {LiveWallPlayerEvents,LiveWallPlayerFactory} from '../src/features/monitoring/live-wall';
import type {LocalLiveBinding} from '../src/lib/tvt/local-live-api';
import type {LocalDeviceView} from '../src/lib/tvt/local-device-api';
import * as wallApi from '../src/lib/tvt/local-live-wall-api';

const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const tenant=uuid(1),connection=uuid(2),store=uuid(3),wallId=uuid(9);
const inventory:LocalDeviceView={connection_id:connection,store_id:store,device_id:uuid(4),connection_generation:1,inventory_revision:1,inventory_state:'AVAILABLE',observed_at:'2026-10-09T00:00:00Z',channels:[{id:uuid(5),ordinal:1,label:'Channel 1'},{id:uuid(6),ordinal:2,label:'Channel 2'}],request_id:'inventory'};
const wall=(state:'ACTIVE'|'STOPPING'|'CLOSED'='ACTIVE'):wallApi.LocalWallResponse=>({wall:{id:wallId,tenant_id:tenant,state,expires_at:new Date(Date.now()+30000).toISOString()},request_id:'wall'});
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(reason:Error)=>void;const promise=new Promise<T>((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
class Player{
  started=false;closed=false;failureStatus:number|null=null;failureCode:string|null=null;lease:string|null=null;
  private closing:Promise<void>|null=null;
  get currentLeaseId(){return this.closed?null:this.lease;}
  constructor(readonly binding:LocalLiveBinding,readonly events:LiveWallPlayerEvents,private readonly closingResult:()=>Promise<void>,private readonly log:string[]){}
  async start(){this.started=true;this.log.push('start-'+this.binding.stream);this.events.state('connecting');}
  accept(){this.lease=uuid(20);this.events.startupPhase?.('negotiating');}
  confirm(){this.accept();this.events.state('playing');}
  stop(){if(this.closing)return this.closing;this.closed=true;this.log.push('stop-player');this.events.stream(null);this.events.state('stopped');return this.closing=this.closingResult();}
  async presented(){}
  async fail(){this.failureStatus=503;await this.stop();this.events.state('failed');}
}
function setup(close:()=>Promise<void>=()=>Promise.resolve()){
  const log:string[]=[];const players:Player[]=[];let sequence=30;
  const refs=new Map<string,wallApi.LocalFocusResponse>();
  const create=vi.spyOn(wallApi,'createLocalWall').mockImplementation(async()=>{log.push('create-wall');return wall();});
  const stop=vi.spyOn(wallApi,'stopLocalWall').mockImplementation(async()=>{log.push('stop-wall');return wall('CLOSED');});
  vi.spyOn(wallApi,'heartbeatLocalWall').mockResolvedValue(wall());
  const reserve=vi.spyOn(wallApi,'reserveLocalFocus').mockImplementation(async(binding,lease,direction)=>{
    log.push('reserve-'+direction);
    const value:wallApi.LocalFocusResponse={reference:{id:uuid(++sequence),wall_id:wallId,lease_id:lease,connection_id:binding.connectionId,channel_id:binding.channelId,direction,state:'PENDING',expires_at:new Date(Date.now()+20000).toISOString()},request_id:'focus'};
    refs.set(value.reference.id,value);return value;
  });
  const settle=vi.spyOn(wallApi,'settleLocalFocus').mockImplementation(async(_tenant,_wall,id)=>{const value=refs.get(id)!;return {...value,reference:{...value.reference,state:'CLOSED'}};});
  const createPlayer:LiveWallPlayerFactory=(binding,_csrf,events)=>{const player=new Player(binding,events,close,log);players.push(player);return player;};
  const props={tenantId:tenant,inventory,csrf:'csrf',disabled:false,sharedMode:true,createPlayer};
  return {log,players,create,stop,reserve,settle,props};
}
beforeEach(()=>{vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined);});
afterEach(async()=>{await act(async()=>cleanup());vi.restoreAllMocks();vi.unstubAllGlobals();});
const play=()=>fireEvent.click(screen.getByRole('button',{name:'실시간 재생'}));
const stop=()=>fireEvent.click(screen.getByRole('button',{name:'영상 중지'}));
const quality=(value:string)=>fireEvent.change(screen.getByRole('combobox',{name:'영상 화질'}),{target:{value}});

it('creates a server wall for shared low quality before starting its scoped sub player',async()=>{
  const h=setup();render(<LocalLivePanel {...h.props}/>);quality('sub');play();
  await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  expect(h.log).toEqual(['create-wall','start-sub']);
  expect(h.players[0].binding).toMatchObject({wallId,stream:'sub',channelId:uuid(5)});
  expect(h.players[0].binding.focusRefId).toBeUndefined();
});
it('bootstraps high quality with sub and reserves FORWARD before awaiting its original Stop',async()=>{
  const closing=deferred<void>();const h=setup(()=>closing.promise);const view=render(<LocalLivePanel {...h.props}/>);play();
  await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  expect(h.players[0].binding.stream).toBe('sub');expect(h.reserve).not.toHaveBeenCalled();
  act(()=>h.players[0].accept());await waitFor(()=>expect(h.players).toHaveLength(2));
  expect(h.log.indexOf('reserve-FORWARD')).toBeLessThan(h.log.indexOf('stop-player'));
  expect(h.players[1].binding).toMatchObject({wallId,stream:'main',focusRefId:uuid(31)});expect(h.players[1].started).toBe(false);
  await act(async()=>closing.resolve());await waitFor(()=>expect(h.players[1].started).toBe(true));
  await act(async()=>view.unmount());
});
it('returns a live high quality card via RETURN before starting the authorized sub replacement',async()=>{
  const h=setup();render(<LocalLivePanel {...h.props}/>);play();await waitFor(()=>expect(h.players).toHaveLength(1));
  act(()=>h.players[0].accept());await waitFor(()=>expect(h.players[1]?.started).toBe(true));act(()=>h.players[1].confirm());
  quality('sub');await waitFor(()=>expect(h.players[2]?.started).toBe(true));
  expect(h.reserve.mock.calls.map(call=>call[2])).toEqual(['FORWARD','RETURN']);
  expect(h.players[2].binding).toMatchObject({stream:'sub',wallId,focusRefId:uuid(32)});
  expect(h.log.indexOf('reserve-RETURN')).toBeLessThan(h.log.lastIndexOf('stop-player'));
});
it('rapid Play and Stop while wall creation is pending retires the returned original without a player',async()=>{
  const h=setup();const creating=deferred<wallApi.LocalWallResponse>();h.create.mockReturnValue(creating.promise);
  render(<LocalLivePanel {...h.props}/>);play();play();await waitFor(()=>expect(h.create).toHaveBeenCalledTimes(1));stop();play();
  await act(async()=>creating.resolve(wall()));await waitFor(()=>expect(h.stop).toHaveBeenCalledTimes(1));
  expect(h.players).toHaveLength(0);expect(h.create).toHaveBeenCalledTimes(1);
});
it('cancels a pending FORWARD reservation on Stop without constructing main',async()=>{
  const h=setup();const reserved=deferred<wallApi.LocalFocusResponse>();h.reserve.mockReturnValue(reserved.promise);
  h.settle.mockResolvedValue({reference:{id:uuid(31),wall_id:wallId,lease_id:uuid(20),connection_id:connection,channel_id:uuid(5),direction:'FORWARD',state:'CLOSED',expires_at:new Date(Date.now()+20000).toISOString()},request_id:'focus'});
  render(<LocalLivePanel {...h.props}/>);play();await waitFor(()=>expect(h.players).toHaveLength(1));act(()=>h.players[0].accept());
  await waitFor(()=>expect(h.reserve).toHaveBeenCalledTimes(1));stop();
  await act(async()=>reserved.resolve({reference:{id:uuid(31),wall_id:wallId,lease_id:uuid(20),connection_id:connection,channel_id:uuid(5),direction:'FORWARD',state:'PENDING',expires_at:new Date(Date.now()+20000).toISOString()},request_id:'focus'}));
  await waitFor(()=>expect(h.settle).toHaveBeenCalled());expect(h.players).toHaveLength(1);expect(h.players[0].closed).toBe(true);
});
it.each(['inventory','credentials'] as const)('waits original player and wall cleanup before %s replacement starts',async(kind)=>{
  const closing=deferred<void>();const wallClosing=deferred<wallApi.LocalWallResponse>();const h=setup(()=>closing.promise);
  const view=render(<LocalLivePanel {...h.props}/>);quality('sub');play();await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  h.stop.mockReturnValueOnce(wallClosing.promise);
  view.rerender(<LocalLivePanel {...h.props} inventory={kind==='inventory'?{...inventory,inventory_revision:2}:inventory} csrf={kind==='credentials'?'new-csrf':'csrf'}/>);quality('sub');play();
  await act(async()=>closing.resolve());expect(h.players).toHaveLength(1);
  await act(async()=>wallClosing.resolve(wall('CLOSED')));await waitFor(()=>expect(h.players[1]?.started).toBe(true));
  expect(h.players[1].binding.inventoryRevision).toBe(kind==='inventory'?2:1);
});
it('retires the private wall on terminal startup failure and allows only explicit retry',async()=>{
  const h=setup();render(<LocalLivePanel {...h.props}/>);quality('sub');play();await waitFor(()=>expect(h.players).toHaveLength(1));
  await act(async()=>h.players[0].fail());await waitFor(()=>expect(h.stop).toHaveBeenCalledTimes(1));
  expect(screen.getByRole('status')).toHaveTextContent('영상을 연결하지 못했습니다');expect(h.players).toHaveLength(1);
});
it('propagates server shared mode through the connection card and inventory to the wall request',async()=>{
  const h=setup();const closed=vi.fn(),negotiated=vi.fn();
  class Peer{
    iceGatheringState='complete';connectionState='new';localDescription={type:'offer',sdp:'v=0\r\n'};
    close(){closed();}addTransceiver(){return {setCodecPreferences(){}};}
    async createOffer(){return this.localDescription;}async setLocalDescription(){}async setRemoteDescription(){negotiated();}
  }
  vi.stubGlobal('RTCPeerConnection',Peer);vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/VP8'}]})});
  const owner={tenant_id:tenant,actor_user_id:uuid(8),connection_id:connection,store_id:store};
  const lease={id:uuid(20),owner,device:{...owner,device_id:inventory.device_id,channel_id:uuid(5)},channel:uuid(5),kind:'live',state:'NEGOTIATING',expires_at:'2026-10-11T00:00:30Z',heartbeat_at:'2026-10-11T00:00:00Z',connection_generation:1,inventory_revision:1,grant_revision:1};
  // This positive wiring fixture owns a real parsed lease and proves its exact
  // CLOSED reply. An issued-start 503 intentionally retains an unknown owner.
  const send=vi.fn(async(input:RequestInfo|URL)=>{
    const url=new URL(String(input),'https://card.test');
    const body=url.pathname.endsWith('/channels')?inventory
      :url.pathname==='/api/live-sessions'?{lease,request_id:'start'}
      :url.pathname===`/api/live-sessions/${lease.id}/webrtc-offer`?{type:'answer',sdp:'v=0\r\n',request_id:'offer'}
      :url.pathname===`/api/live-sessions/${lease.id}/stop`?{lease:{...lease,state:'CLOSED'},request_id:'stop'}:null;
    return body?new Response(JSON.stringify(body),{headers:{'X-Request-ID':body.request_id}}):new Response(null,{status:503});
  });vi.stubGlobal('fetch',send);
  render(<ConnectionsView tenantId={tenant} initial={[{id:connection,tenant_id:tenant,kind:'TVT_DEVICE',alias:'Recorder',site:'Store',status:'NOT_VERIFIED',last_success:null,generation:1,store_ids:[store]}]} stores={[{id:store,tenant_id:tenant,name:'Store',timezone:'Asia/Seoul',active:true}]} csrf="csrf" sharedMode/>);
  fireEvent.click(screen.getByRole('button',{name:'저장된 채널'}));await screen.findByRole('button',{name:'실시간 재생'});quality('sub');play();
  await waitFor(()=>expect(h.create).toHaveBeenCalledTimes(1));
  await waitFor(()=>expect(negotiated).toHaveBeenCalledTimes(1));expect(send).toHaveBeenCalledTimes(3);
  expect(JSON.parse((send.mock.calls[1] as unknown as [string,RequestInit])[1].body as string)).toMatchObject({wall_id:wallId,stream:'sub'});
  stop();await waitFor(()=>expect(h.stop).toHaveBeenCalledTimes(1));expect(closed).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[3][0]).toBe(`/api/live-sessions/${lease.id}/stop?tenant_id=${tenant}`);
});

it('unmount cleanup fences a newly mounted card until both original Stops settle',async()=>{
  const closing=deferred<void>();const wallClosing=deferred<wallApi.LocalWallResponse>();const h=setup(()=>closing.promise);
  const view=render(<LocalLivePanel {...h.props}/>);quality('sub');play();await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  h.stop.mockReturnValueOnce(wallClosing.promise);view.unmount();
  render(<LocalLivePanel {...h.props}/>);quality('sub');play();expect(h.players[0].closed).toBe(true);
  await act(async()=>wallClosing.resolve(wall('CLOSED')));expect(h.players).toHaveLength(1);
  await act(async()=>closing.resolve());await waitFor(()=>expect(h.players[1]?.started).toBe(true));
});
it('selects a different channel only after the old private wall is stopped',async()=>{
  const h=setup();render(<LocalLivePanel {...h.props}/>);quality('sub');play();await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  expect(screen.getByRole('combobox',{name:'영상 채널'})).toBeDisabled();stop();
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'영상 채널'})).toBeEnabled());
  fireEvent.change(screen.getByRole('combobox',{name:'영상 채널'}),{target:{value:uuid(6)}});play();await waitFor(()=>expect(h.players[1]?.started).toBe(true));
  expect(h.players[1].binding.channelId).toBe(uuid(6));expect(h.stop).toHaveBeenCalledTimes(1);
});

it.each(['inventory','credentials','unmount'] as const)('retains fulfilled STOPPING across %s replacement until the exact original wall is CLOSED',async(kind)=>{
  const h=setup();const closed=deferred<Response>();const send=vi.fn(()=>closed.promise);vi.stubGlobal('fetch',send);
  const view=render(<LocalLivePanel {...h.props}/>);quality('sub');play();await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  h.stop.mockResolvedValueOnce(wall('STOPPING'));stop();await act(async()=>{});
  if(kind==='unmount'){view.unmount();render(<LocalLivePanel {...h.props}/>);}
  else view.rerender(<LocalLivePanel {...h.props} inventory={kind==='inventory'?{...inventory,inventory_revision:2}:inventory} csrf={kind==='credentials'?'new-csrf':'csrf'}/>);
  quality('sub');play();await act(async()=>{});
  expect(h.create).toHaveBeenCalledTimes(1);expect(h.players).toHaveLength(1);
  expect(send).toHaveBeenCalledWith(`/api/live-walls/${wallId}?tenant_id=${tenant}`,expect.objectContaining({method:'GET',credentials:'same-origin'}));
  await act(async()=>closed.resolve(new Response(JSON.stringify({...wall('CLOSED'),request_id:'read'}),{headers:{'X-Request-ID':'read'}})));
  await waitFor(()=>expect(h.players[1]?.started).toBe(true));
});

it('keeps a rejected original Stop fenced across unmount and prevents a new card start',async()=>{
  const closing=deferred<void>();const h=setup(()=>closing.promise);const view=render(<LocalLivePanel {...h.props}/>);quality('sub');play();await waitFor(()=>expect(h.players[0]?.started).toBe(true));
  stop();await act(async()=>closing.reject(new Error('Original cleanup unresolved')));
  expect(screen.getByRole('button',{name:'실시간 재생'})).toBeDisabled();view.unmount();
  render(<LocalLivePanel {...h.props}/>);quality('sub');play();
  await screen.findByText('영상을 연결하지 못했습니다. 채널을 확인한 뒤 다시 시도하세요.');expect(h.players).toHaveLength(1);expect(h.create).toHaveBeenCalledTimes(1);
});
