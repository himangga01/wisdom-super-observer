import {heartbeatLocalLive,LocalLiveError,offerLocalLive,reportLocalLivePlaying,startLocalLive,stopLocalLive,type LocalLiveBinding,type LocalLiveView} from './local-live-api';

export type LivePlayerState='connecting'|'negotiating'|'playing'|'stopped'|'failed';
export type LivePlayerStartupPhase='requesting'|'negotiating'|'presenting';
type Events={state:(value:LivePlayerState)=>void;stream:(value:MediaStream|null)=>void;startupPhase?:(value:LivePlayerStartupPhase)=>void};
export class LocalLivePlayer{
  private abort=new AbortController();private peer:RTCPeerConnection|null=null;private lease:string|null=null;
  private ended=false;private started=false;private heartbeat:ReturnType<typeof setInterval>|null=null;
  private renewing=false;private misses=0;private closing:Promise<void>|null=null;
  private received=false;private reporting=false;private failure:number|null=null;
  private failureReason:string|null=null;
  private requesting:Promise<LocalLiveView>|null=null;
  private acquiringPeer:Promise<RTCPeerConnection>|null=null;
  constructor(private binding:LocalLiveBinding,private csrf:string,private events:Events,private factory=()=>new RTCPeerConnection({iceServers:[]})){}
  get closed(){return this.ended;}
  /** Exact currently owned public view; this is not native identity or authority. */
  get currentLeaseId():string|null{return this.ended?null:this.lease;}
  get playbackConfirmed(){return this.received&&!this.ended;}
  /** HTTP status of the LocalLiveError that failed the start, offer or playing request (429: device busy); null otherwise. */
  get failureStatus(){return this.failure;}
  get failureCode(){return this.failureReason;}
  async presented(decodedFrames:number){
    if(this.ended||!this.lease||this.received||this.reporting||!Number.isSafeInteger(decodedFrames)||decodedFrames<1)return;
    this.reporting=true;
    try{await reportLocalLivePlaying(this.binding,this.lease,this.csrf,decodedFrames,this.abort.signal);if(!this.ended){this.received=true;this.events.state('playing');}}
    catch(error){if(!this.ended){if(error instanceof LocalLiveError){this.failure=error.status;this.failureReason=error.code;}await this.fail();}}finally{this.reporting=false;}
  }
  async start(){
    if(this.started||this.ended)return;this.started=true;this.events.state('connecting');
    if(this.ended)return;
    try{
      let acquired!:(value:RTCPeerConnection)=>void,unacquired!:(error:unknown)=>void;
      this.acquiringPeer=new Promise<RTCPeerConnection>((done,failed)=>{acquired=done;unacquired=failed;});
      let created:RTCPeerConnection;
      try{created=this.factory();acquired(created);}catch(error){unacquired(error);throw error;}
      if(this.ended){await this.stop().catch(()=>undefined);return;}
      this.peer=created;this.acquiringPeer=null;
      const codecs=RTCRtpReceiver.getCapabilities('video')?.codecs.filter(codec=>codec.mimeType.toLowerCase()==='video/vp8')??[];
      if(!codecs.length)throw new Error('Supported video codec unavailable');
      this.peer.addTransceiver('video',{direction:'recvonly'}).setCodecPreferences(codecs);
      this.events.startupPhase?.('requesting');
      if(this.ended)return;
      let accepted!:(value:LocalLiveView)=>void,refused!:(error:unknown)=>void;
      const request=new Promise<LocalLiveView>((done,failed)=>{accepted=done;refused=failed;});this.requesting=request;
      try{void startLocalLive(this.binding,this.csrf,this.abort.signal).then(accepted,refused);}catch(error){refused(error);}
      // A failed response does not prove that the original server acquisition
      // was absent. Keep this exact outcome until an owned lease is received.
      const result=await request;
      if(this.ended){await this.stop().catch(()=>undefined);return;}
      this.lease=result.lease.id;this.requesting=null;
      this.heartbeat=setInterval(()=>{void this.renew();},10000);
      const peer=this.peer;
      peer.ontrack=event=>{
        if(this.ended)return;
        if(event.track.kind!=='video'){event.track.stop();void this.fail();return;}
        this.events.stream(event.streams[0]??new MediaStream([event.track]));
      };
      // Chrome often recovers from 'disconnected' by itself; only failed/closed are terminal.
      peer.onconnectionstatechange=()=>{if(!this.ended&&['failed','closed'].includes(peer.connectionState))void this.fail();};
      this.events.startupPhase?.('negotiating');
      if(this.ended)return;
      await peer.setLocalDescription(await peer.createOffer());
      await this.gather(peer);
      if(this.ended)return;
      this.events.state('negotiating');
      if(this.ended)return;
      const description=peer.localDescription;if(!description||description.type!=='offer')throw new Error('Offer unavailable');
      const answer=await offerLocalLive(this.binding,this.lease,this.csrf,description.sdp,this.abort.signal);
      if(this.ended)return;
      await peer.setRemoteDescription(answer);
      if(!this.ended)this.events.startupPhase?.('presenting');
    }catch(error){if(!this.ended){if(error instanceof LocalLiveError){this.failure=error.status;this.failureReason=error.code;}await this.fail();}}
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
  private async fail(){await this.stop().catch(()=>undefined);this.events.state('failed');}
  stop():Promise<void>{
    if(this.closing)return this.closing;
    let resolve!:()=>void,reject!:(error:unknown)=>void;
    const original=new Promise<void>((done,failed)=>{resolve=done;reject=failed;});this.closing=original;
    const id=this.lease,request=this.requesting,peer=this.peer,acquiring=this.acquiringPeer;this.lease=null;this.peer=null;
    this.ended=true;this.abort.abort();if(this.heartbeat)clearInterval(this.heartbeat);this.heartbeat=null;
    if(peer){peer.ontrack=null;peer.onconnectionstatechange=null;}
    this.events.stream(null);this.events.state('stopped');
    const retire=async()=>{
      let originalPeer=peer;
      try{
        if(!originalPeer&&acquiring){originalPeer=await acquiring;originalPeer.ontrack=null;originalPeer.onconnectionstatechange=null;}
        const owned=id??(request?(await request).lease.id:null);
        if(owned){const value=await stopLocalLive(this.binding,owned,this.csrf);if(value.lease.id!==owned||value.lease.state!=='CLOSED')throw new Error('Original lease stop not terminal');}
      }catch(error){try{originalPeer?.close();}catch{/* Preserve the original authenticated Stop failure. */}throw error;}
      originalPeer?.close();
    };
    void retire().then(resolve,reject);
    return original;
  }
}
