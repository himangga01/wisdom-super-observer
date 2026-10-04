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
const live=()=>{
  vi.mocked(api.startLocalLive).mockResolvedValue({lease:{id:'lease'}} as never);
  vi.mocked(api.offerLocalLive).mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.mocked(api.stopLocalLive).mockResolvedValue({} as never);
  const peer=new Peer();const updates:string[]=[];
  return {peer,updates,player:new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection)};
};
it('retires a late start result when stopped before negotiation finishes',async()=>{
  let finish!:(value:unknown)=>void;
  vi.mocked(api.startLocalLive).mockImplementation(()=>new Promise(resolve=>{finish=resolve as typeof finish;}));
  vi.mocked(api.stopLocalLive).mockResolvedValue({} as never);
  const peer=new Peer();const updates:string[]=[];
  const player=new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  const started=player.start();await player.stop();finish({lease:{id:'lease'}});await started;
  expect(api.stopLocalLive).toHaveBeenCalledWith(binding,'lease','csrf');
  expect(api.offerLocalLive).not.toHaveBeenCalled();expect(updates).not.toContain('playing');
});
it('keeps negotiation distinct from playback and closes the owned peer on authority failure',async()=>{
  vi.mocked(api.startLocalLive).mockResolvedValue({lease:{id:'lease'}} as never);
  vi.mocked(api.offerLocalLive).mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.mocked(api.stopLocalLive).mockResolvedValue({} as never);
  const peer=new Peer();const updates:string[]=[];const player=new LocalLivePlayer(binding,'csrf',{state:s=>updates.push(s),stream:vi.fn()},()=>peer as unknown as RTCPeerConnection);
  await player.start();expect(peer.addTransceiver).toHaveBeenCalledWith('video',{direction:'recvonly'});expect(updates).not.toContain('playing');
  expect(peer.preferences).toHaveBeenCalledWith([{mimeType:'video/VP8',clockRate:90000}]);
  peer.connectionState='failed';peer.onconnectionstatechange?.();await player.stop();
  expect(peer.close).toHaveBeenCalledTimes(1);expect(api.stopLocalLive).toHaveBeenCalledTimes(1);
});
it('reports playing only after the first browser frame and scoped server confirmation',async()=>{
  vi.mocked(api.startLocalLive).mockResolvedValue({lease:{id:'lease'}} as never);
  vi.mocked(api.offerLocalLive).mockResolvedValue({type:'answer',sdp:'v=0\r\n'});
  vi.mocked(api.stopLocalLive).mockResolvedValue({} as never);
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
