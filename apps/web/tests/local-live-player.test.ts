import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {LocalLivePlayer} from '../src/lib/tvt/local-live-player';
import * as api from '../src/lib/tvt/local-live-api';
vi.mock('../src/lib/tvt/local-live-api',async original=>({...await original<object>(),startLocalLive:vi.fn(),heartbeatLocalLive:vi.fn(),stopLocalLive:vi.fn(),offerLocalLive:vi.fn(),reportLocalLivePlaying:vi.fn()}));
const binding={tenantId:'t',connectionId:'c',storeId:'s',deviceId:'d',channelId:'ch',generation:1,inventoryRevision:1};
class Peer{
  iceGatheringState='complete';connectionState='new';localDescription={type:'offer',sdp:'v=0\r\n'};
  ontrack:((event:unknown)=>void)|null=null;onconnectionstatechange:(()=>void)|null=null;
  preferences=vi.fn();addTransceiver=vi.fn(()=>({setCodecPreferences:this.preferences}));createOffer=vi.fn(async()=>this.localDescription);setLocalDescription=vi.fn(async()=>{});setRemoteDescription=vi.fn(async()=>{});close=vi.fn();
}
beforeEach(()=>vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/H264',clockRate:90000},{mimeType:'video/VP8',clockRate:90000}]})}));
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals();});
const stoppedView=(id='lease'):api.LocalLiveView=>{
  const owner={tenant_id:binding.tenantId,actor_user_id:'80000000-0000-4000-8000-000000000001',connection_id:binding.connectionId,store_id:binding.storeId};
  return {lease:{id,owner,device:{...owner,device_id:binding.deviceId,channel_id:binding.channelId},channel:binding.channelId,kind:'live',state:'CLOSED',expires_at:'2026-10-11T00:00:30Z',heartbeat_at:'2026-10-11T00:00:00Z',connection_generation:1,inventory_revision:1,grant_revision:1},request_id:'original-stop'};
};
const live=()=>{
  vi.mocked(api.startLocalLive).mockResolvedValue({lease:{id:'lease'}} as never);
  vi.mocked(api.offerLocalLive).mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.mocked(api.stopLocalLive).mockResolvedValue(stoppedView());
  const peer=new Peer();const updates:string[]=[];
  return {peer,updates,player:new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection)};
};
it('test_readonly_lease_id_follows_exact_current_player and original stop promise',async()=>{
  const {player}=live();
  expect(player.currentLeaseId).toBeNull();
  await player.start();expect(player.currentLeaseId).toBe('lease');
  const stopping=player.stop();expect(player.currentLeaseId).toBeNull();expect(player.stop()).toBe(stopping);
  expect(Object.getOwnPropertyDescriptor(LocalLivePlayer.prototype,'currentLeaseId')?.set).toBeUndefined();
  await stopping;
});
it('does not publish a current view during the synchronous stopped notification',async()=>{
  live();const peer=new Peer();let current:string|null|undefined;
  const player=new LocalLivePlayer(binding,'csrf',{state:state=>{if(state==='stopped')current=player.currentLeaseId;},stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  await player.start();await player.stop();expect(current).toBeNull();
});
it('retires a late start result when stopped before negotiation finishes',async()=>{
  let finish!:(value:unknown)=>void;
  vi.mocked(api.startLocalLive).mockImplementation(()=>new Promise(resolve=>{finish=resolve as typeof finish;}));
  vi.mocked(api.stopLocalLive).mockResolvedValue(stoppedView());
  const peer=new Peer();const updates:string[]=[];
  const player=new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  const started=player.start();const original=player.stop();finish({lease:{id:'lease'}});await started;await original;
  expect(api.stopLocalLive).toHaveBeenCalledWith(binding,'lease','csrf');
  expect(api.offerLocalLive).not.toHaveBeenCalled();expect(updates).not.toContain('playing');
});
it('keeps negotiation distinct from playback and closes the owned peer on authority failure',async()=>{
  vi.mocked(api.startLocalLive).mockResolvedValue({lease:{id:'lease'}} as never);
  vi.mocked(api.offerLocalLive).mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.mocked(api.stopLocalLive).mockResolvedValue(stoppedView());
  const peer=new Peer();const updates:string[]=[];const player=new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  await player.start();expect(peer.addTransceiver).toHaveBeenCalledWith('video',{direction:'recvonly'});expect(updates).not.toContain('playing');
  expect(peer.preferences).toHaveBeenCalledWith([{mimeType:'video/VP8',clockRate:90000}]);
  peer.connectionState='failed';peer.onconnectionstatechange?.();await player.stop();
  expect(peer.close).toHaveBeenCalledTimes(1);expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});
it('reports playing only after the first browser frame and scoped server confirmation',async()=>{
  vi.mocked(api.startLocalLive).mockResolvedValue({lease:{id:'lease'}} as never);
  vi.mocked(api.offerLocalLive).mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.mocked(api.stopLocalLive).mockResolvedValue(stoppedView());
  let confirm!:(value:never)=>void;vi.mocked(api.reportLocalLivePlaying).mockImplementation(()=>new Promise(resolve=>{confirm=resolve;}));
  const peer=new Peer();const updates:string[]=[];const player=new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  try{await player.start();const playing=player.presented(1);expect(updates).not.toContain('playing');confirm({} as never);await playing;expect(updates).toContain('playing');expect(api.reportLocalLivePlaying).toHaveBeenCalledTimes(1);}finally{await player.stop();}
});
it('rides out a transient disconnected state and fails only on failed or closed',async()=>{
  const {peer,updates,player}=live();
  await player.start();
  peer.connectionState='disconnected';peer.onconnectionstatechange?.();
  peer.connectionState='connected';peer.onconnectionstatechange?.();
  await Promise.resolve();
  expect(player.closed).toBe(false);expect(peer.close).not.toHaveBeenCalled();expect(api.stopLocalLive).not.toHaveBeenCalled();expect(updates).not.toContain('failed');
  peer.connectionState='closed';peer.onconnectionstatechange?.();
  await vi.waitFor(()=>expect(updates).toContain('failed'));
  expect(peer.close).toHaveBeenCalledTimes(1);expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});
it('tolerates one missed heartbeat, resets on success and fails after two consecutive misses',async()=>{
  vi.useFakeTimers();
  // Transient misses: 5xx answers and network errors (fetch rejects with TypeError).
  vi.mocked(api.heartbeatLocalLive).mockRejectedValueOnce(new api.LocalLiveError(503)).mockResolvedValueOnce({lease:{id:'lease',state:'NEGOTIATING'}} as never).mockRejectedValueOnce(new TypeError('Failed to fetch')).mockRejectedValueOnce(new api.LocalLiveError(502));
  const {peer,updates,player}=live();
  await player.start();
  for(let beat=1;beat<=3;beat++){
    await vi.advanceTimersByTimeAsync(10000);
    expect(api.heartbeatLocalLive).toHaveBeenCalledTimes(beat);expect(player.closed).toBe(false);expect(updates).not.toContain('failed');expect(api.stopLocalLive).not.toHaveBeenCalled();
  }
  await vi.advanceTimersByTimeAsync(10000);
  expect(api.heartbeatLocalLive).toHaveBeenCalledTimes(4);expect(updates).toContain('failed');
  expect(peer.close).toHaveBeenCalledTimes(1);expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});
it.each(['STOPPING','CLOSED'])('fails at once when a heartbeat reports a %s lease',async state=>{
  vi.useFakeTimers();
  vi.mocked(api.heartbeatLocalLive).mockResolvedValueOnce({lease:{id:'lease',state}} as never);
  const {peer,updates,player}=live();
  await player.start();
  await vi.advanceTimersByTimeAsync(10000);
  expect(api.heartbeatLocalLive).toHaveBeenCalledTimes(1);expect(updates).toContain('failed');
  expect(peer.close).toHaveBeenCalledTimes(1);expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});
it.each([404,403])('ends playback at once when a heartbeat is refused with HTTP %i',async status=>{
  vi.useFakeTimers();
  vi.mocked(api.heartbeatLocalLive).mockRejectedValueOnce(new api.LocalLiveError(status));
  const {peer,updates,player}=live();
  await player.start();
  await vi.advanceTimersByTimeAsync(10000);
  expect(api.heartbeatLocalLive).toHaveBeenCalledTimes(1);expect(updates).toContain('failed');
  expect(peer.close).toHaveBeenCalledTimes(1);expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});
it('exposes the HTTP status of a refused start and no failure status after a successful one',async()=>{
  vi.mocked(api.startLocalLive).mockRejectedValueOnce(new api.LocalLiveError(429));
  const peer=new Peer();const updates:string[]=[];
  const refused=new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  expect(refused.failureStatus).toBeNull();
  await refused.start();
  expect(refused.failureStatus).toBe(429);
  expect(updates).toEqual(['connecting','stopped','failed']);
  expect(api.stopLocalLive).not.toHaveBeenCalled();
  const {player}=live();
  await player.start();
  expect(player.failureStatus).toBeNull();
  await player.stop();
  expect(player.failureStatus).toBeNull();
});
it('records the HTTP status when the offer or the playing report is refused, and nothing for other errors',async()=>{
  const offered=live();
  vi.mocked(api.offerLocalLive).mockRejectedValueOnce(new api.LocalLiveError(503));
  await offered.player.start();
  expect(offered.player.failureStatus).toBe(503);expect(offered.updates).toContain('failed');
  const reported=live();
  vi.mocked(api.reportLocalLivePlaying).mockRejectedValueOnce(new api.LocalLiveError(409));
  await reported.player.start();await reported.player.presented(1);
  expect(reported.player.failureStatus).toBe(409);expect(reported.updates).toContain('failed');
  const offline=live();
  vi.mocked(api.startLocalLive).mockRejectedValueOnce(new TypeError('Failed to fetch'));
  await offline.player.start();
  expect(offline.player.failureStatus).toBeNull();expect(offline.updates).toContain('failed');
});

it.each(['start','offer','playing'])('exposes the no-signal code for a refused %s and closes once',async action=>{
  const {peer,updates,player}=live();
  const failed=action==='start'?api.startLocalLive:action==='offer'?api.offerLocalLive:api.reportLocalLivePlaying;
  const error=new api.LocalLiveError(504,'LOCAL_DEVICE_NO_SIGNAL');vi.mocked(failed).mockRejectedValueOnce(error);
  expect(player.failureCode).toBeNull();await player.start();if(action==='playing')await player.presented(1);
  expect(player.failureStatus).toBe(504);expect(player.failureCode).toBe('LOCAL_DEVICE_NO_SIGNAL');expect(updates).toContain('failed');expect(peer.close).toHaveBeenCalledTimes(1);
  if(action==='start')await expect(player.stop()).rejects.toBe(error);else await player.stop();
  expect(player.failureCode).toBe('LOCAL_DEVICE_NO_SIGNAL');
});

it('authenticates original Stop before peer closure can retire its lease',async()=>{
  const {player,peer}=live();const order:string[]=[];let retired=false;
  peer.close.mockImplementation(()=>{retired=true;order.push('peer-close');});
  vi.mocked(api.stopLocalLive).mockImplementation(async()=>{
    if(retired){order.push('denied-stop');throw new api.LocalLiveError(404,'LOCAL_DEVICE_DENIED');}
    order.push('lease-CLOSED');retired=true;return {lease:{id:'lease',state:'CLOSED'}} as never;
  });
  await player.start();await player.stop();
  expect(order).toEqual(['lease-CLOSED','peer-close']);
});

it('quiesces immediately but retains the original peer until Stop confirms CLOSED',async()=>{
  vi.useFakeTimers();const {player,peer,updates}=live();
  let finish!:(value:api.LocalLiveView)=>void;
  vi.mocked(api.stopLocalLive).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  await player.start();const original=player.stop();
  expect(player.closed).toBe(true);expect(player.currentLeaseId).toBeNull();expect(updates.at(-1)).toBe('stopped');
  expect(peer.close).not.toHaveBeenCalled();expect(player.stop()).toBe(original);
  await vi.advanceTimersByTimeAsync(20_000);expect(api.heartbeatLocalLive).not.toHaveBeenCalled();
  finish({lease:{id:'lease',state:'CLOSED'}} as never);await original;
  expect(peer.close).toHaveBeenCalledTimes(1);
});

it.each([404,403,504])('retains an original Stop HTTP %i failure instead of reporting cleanup success',async status=>{
  const {player,peer}=live();const error=new api.LocalLiveError(status);
  vi.mocked(api.stopLocalLive).mockRejectedValue(error);
  await player.start();const original=player.stop();
  await expect(original).rejects.toBe(error);expect(player.stop()).toBe(original);
  expect(peer.close).toHaveBeenCalledTimes(1);
});

it.each([{id:'lease',state:'STOPPING'},{id:'foreign-lease',state:'CLOSED'}])('rejects a Stop reply without exact original CLOSED proof: %j',async lease=>{
  const {player,peer}=live();vi.mocked(api.stopLocalLive).mockResolvedValue({lease} as never);
  await player.start();await expect(player.stop()).rejects.toThrow();
  expect(peer.close).toHaveBeenCalledTimes(1);
});

it('shares original Stop through a synchronous stopped callback',async()=>{
  live();const peer=new Peer();let nested:Promise<void>|undefined;let reported=false;
  const player=new LocalLivePlayer(binding,'csrf',{stream:vi.fn(),state:value=>{
    if(value==='stopped'&&!reported){reported=true;nested=player.stop();}
  }},()=>peer as unknown as RTCPeerConnection);
  await player.start();const original=player.stop();expect(nested).toBe(original);await original;
  expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});

it('retains a pending start result and its original late lease Stop',async()=>{
  const {player,peer}=live();let accepted!:(value:api.LocalLiveView)=>void;let retired!:(value:api.LocalLiveView)=>void;
  vi.mocked(api.startLocalLive).mockImplementation(()=>new Promise(resolve=>{accepted=resolve;}));
  vi.mocked(api.stopLocalLive).mockImplementation(()=>new Promise(resolve=>{retired=resolve;}));
  const started=player.start();const original=player.stop();let settled=false;void original.then(()=>{settled=true;});
  await Promise.resolve();expect(settled).toBe(false);expect(peer.close).not.toHaveBeenCalled();
  accepted({lease:{id:'lease'}} as never);await vi.waitFor(()=>expect(retired).toBeTypeOf('function'));
  expect(settled).toBe(false);expect(api.offerLocalLive).not.toHaveBeenCalled();
  retired({lease:{id:'lease',state:'CLOSED'}} as never);await original;await started;
  expect(peer.close).toHaveBeenCalledTimes(1);
});

it('R1 retains a completed lost start response instead of declaring an unknown server lease closed',async()=>{
  const {player,peer,updates}=live();let serverLeaseActive=false;
  const lost=new TypeError('Lost original start response');
  vi.mocked(api.startLocalLive).mockImplementation(async()=>{serverLeaseActive=true;throw lost;});
  await player.start();const original=player.stop();
  await expect(original).rejects.toBe(lost);expect(player.stop()).toBe(original);
  expect(serverLeaseActive).toBe(true);expect(api.stopLocalLive).not.toHaveBeenCalled();
  expect(peer.close).toHaveBeenCalledTimes(1);expect(updates).toContain('failed');
});

it('R1 stops from connecting without creating a later peer or start acquisition',async()=>{
  live();const peer=new Peer();const factory=vi.fn(()=>peer as unknown as RTCPeerConnection);let original:Promise<void>|undefined;
  const player=new LocalLivePlayer(binding,'csrf',{stream:vi.fn(),state:value=>{if(value==='connecting')original=player.stop();}},factory);
  await player.start();await original;
  expect(player.stop()).toBe(original);expect(factory).not.toHaveBeenCalled();
  expect(api.startLocalLive).not.toHaveBeenCalled();expect(peer.close).not.toHaveBeenCalled();
});

it('R1 stops from requesting without issuing the later start request',async()=>{
  live();const peer=new Peer();let original:Promise<void>|undefined;
  const player=new LocalLivePlayer(binding,'csrf',{stream:vi.fn(),state:vi.fn(),startupPhase:phase=>{if(phase==='requesting')original=player.stop();}},()=>peer as unknown as RTCPeerConnection);
  await player.start();await original;
  expect(player.stop()).toBe(original);expect(api.startLocalLive).not.toHaveBeenCalled();expect(peer.close).toHaveBeenCalledTimes(1);
});

it('R1 closes only the original peer returned after factory reentry Stop',async()=>{
  live();const peer=new Peer();let original:Promise<void>|undefined;
  const player=new LocalLivePlayer(binding,'csrf',{stream:vi.fn(),state:vi.fn()},()=>{original=player.stop();return peer as unknown as RTCPeerConnection;});
  await player.start();await original;
  expect(player.stop()).toBe(original);expect(api.startLocalLive).not.toHaveBeenCalled();expect(peer.close).toHaveBeenCalledTimes(1);
});

it('R1 retains start acquisition before a synchronous request-port Stop',async()=>{
  const {player,peer}=live();let original:Promise<void>|undefined;
  vi.mocked(api.startLocalLive).mockImplementation(()=>{original=player.stop();return Promise.resolve({lease:{id:'lease'}} as never);});
  await player.start();await original;
  expect(player.stop()).toBe(original);expect(api.stopLocalLive).toHaveBeenCalledWith(binding,'lease','csrf');
  expect(api.offerLocalLive).not.toHaveBeenCalled();expect(peer.close).toHaveBeenCalledTimes(1);
});
