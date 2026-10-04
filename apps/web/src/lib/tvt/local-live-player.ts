import {heartbeatLocalLive,LocalLiveError,offerLocalLive,reportLocalLivePlaying,startLocalLive,stopLocalLive,type LocalLiveBinding} from './local-live-api';

export type LivePlayerState='connecting'|'negotiating'|'playing'|'stopped'|'failed';
type Events={state:(value:LivePlayerState)=>void;stream:(value:MediaStream|null)=>void};
export class LocalLivePlayer{
  private abort=new AbortController();private peer:RTCPeerConnection|null=null;private lease:string|null=null;
  private ended=false;private started=false;private heartbeat:ReturnType<typeof setInterval>|null=null;
  private renewing=false;private misses=0;private closing:Promise<void>|null=null;
  private received=false;private reporting=false;
  constructor(private binding:LocalLiveBinding,private csrf:string,private events:Events,private factory=()=>new RTCPeerConnection({iceServers:[]})){}
  get closed(){return this.ended;}
  get playbackConfirmed(){return this.received&&!this.ended;}
  async presented(decodedFrames:number){
    if(this.ended||!this.lease||this.received||this.reporting||!Number.isSafeInteger(decodedFrames)||decodedFrames<1)return;
    this.reporting=true;
    try{await reportLocalLivePlaying(this.binding,this.lease,this.csrf,decodedFrames,this.abort.signal);if(!this.ended){this.received=true;this.events.state('playing');}}
    catch{if(!this.ended)await this.fail();}finally{this.reporting=false;}
  }
  async start(){
    if(this.started||this.ended)return;this.started=true;this.events.state('connecting');
    try{
      this.peer=this.factory();
      const codecs=RTCRtpReceiver.getCapabilities('video')?.codecs.filter(codec=>codec.mimeType.toLowerCase()==='video/vp8')??[];
      if(!codecs.length)throw new Error('Supported video codec unavailable');
      this.peer.addTransceiver('video',{direction:'recvonly'}).setCodecPreferences(codecs);
      const result=await startLocalLive(this.binding,this.csrf,this.abort.signal);
      if(this.ended){await stopLocalLive(this.binding,result.lease.id,this.csrf).catch(()=>undefined);return;}
      this.lease=result.lease.id;
      this.heartbeat=setInterval(()=>{void this.renew();},10000);
      const peer=this.peer;
      peer.ontrack=event=>{
        if(this.ended)return;
        if(event.track.kind!=='video'){event.track.stop();void this.fail();return;}
        this.events.stream(event.streams[0]??new MediaStream([event.track]));
      };
      // Chrome often recovers from 'disconnected' by itself; only failed/closed are terminal.
      peer.onconnectionstatechange=()=>{if(!this.ended&&['failed','closed'].includes(peer.connectionState))void this.fail();};
      await peer.setLocalDescription(await peer.createOffer());
      await this.gather(peer);
      if(this.ended)return;
      this.events.state('negotiating');
      const description=peer.localDescription;if(!description||description.type!=='offer')throw new Error('Offer unavailable');
      const answer=await offerLocalLive(this.binding,this.lease,this.csrf,description.sdp,this.abort.signal);
      if(this.ended)return;
      await peer.setRemoteDescription(answer);
    }catch{if(!this.ended)await this.fail();}
  }
  private async gather(peer:RTCPeerConnection){
    if(peer.iceGatheringState==='complete')return;
    await new Promise<void>((resolve,reject)=>{
      const finish=(error?:Error)=>{clearTimeout(timer);peer.removeEventListener('icegatheringstatechange',changed);this.abort.signal.removeEventListener('abort',cancelled);if(error)reject(error);else resolve();};
      const changed=()=>{if(peer.iceGatheringState==='complete')finish();};
      const cancelled=()=>finish(new Error('Cancelled'));
      const timer=setTimeout(()=>finish(new Error('ICE deadline')),8000);
      peer.addEventListener('icegatheringstatechange',changed);this.abort.signal.addEventListener('abort',cancelled,{once:true});
      if(this.abort.signal.aborted)cancelled();else changed();
    });
  }
  private async renew(){
    if(this.ended||this.renewing||!this.lease)return;this.renewing=true;let terminal=false;
    try{const value=await heartbeatLocalLive(this.binding,this.lease,this.csrf,this.abort.signal);terminal=['STOPPING','CLOSED'].includes(value.lease.state);if(!terminal)this.misses=0;}
    // 404/403 are authoritative (lease revoked, access forbidden); network errors and 5xx are transient misses.
    catch(error){if(error instanceof LocalLiveError&&(error.status===404||error.status===403))terminal=true;else this.misses+=1;}finally{this.renewing=false;}
    // A closing, revoked or forbidden lease ends playback at once; one missed beat is ridden out (10 s beats, 30 s TTL).
    if(!this.ended&&(terminal||this.misses>=2))await this.fail();
  }
  private async fail(){await this.stop();this.events.state('failed');}
  stop():Promise<void>{
    if(this.closing)return this.closing;
    this.ended=true;this.abort.abort();if(this.heartbeat)clearInterval(this.heartbeat);this.heartbeat=null;
    if(this.peer){this.peer.ontrack=null;this.peer.onconnectionstatechange=null;this.peer.close();this.peer=null;}
    this.events.stream(null);this.events.state('stopped');
    const id=this.lease;this.lease=null;
    this.closing=id?stopLocalLive(this.binding,id,this.csrf).then(()=>undefined).catch(()=>undefined):Promise.resolve();
    return this.closing;
  }
}
