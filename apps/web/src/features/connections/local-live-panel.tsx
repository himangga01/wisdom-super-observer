'use client';
import {useEffect,useId,useRef,useState} from 'react';
import type {LocalDeviceView} from '../../lib/tvt/local-device-api';
import {LocalLivePlayer,type LivePlayerState} from '../../lib/tvt/local-live-player';
import {SharedLocalLivePanel} from './shared-local-live-panel';
import type {LiveWallPlayerFactory} from '../monitoring/live-wall';
type Props={tenantId:string;inventory:LocalDeviceView;csrf:string;disabled:boolean;sharedMode?:boolean;createPlayer?:LiveWallPlayerFactory};
export function LocalLivePanel(props:Props){
  const {tenantId,inventory,csrf,sharedMode=false}=props;
  const key=[tenantId,inventory.connection_id,inventory.connection_generation,inventory.inventory_revision,inventory.store_id,inventory.device_id,csrf,sharedMode].join('/');
  return sharedMode?<SharedLocalLivePanel key={key} {...props}/>:<LivePanel key={key} {...props}/>;
}
function LivePanel({tenantId,inventory,csrf,disabled}:Props){
  const selectId=useId();const [channel,setChannel]=useState(inventory.channels[0]?.id??'');
  const qualityId=useId();const [quality,setQuality]=useState<'main'|'sub'>('main');
  const [status,setStatus]=useState<LivePlayerState|'playing'>('stopped');
  const [failureCode,setFailureCode]=useState<string|null>(null);
  const video=useRef<HTMLVideoElement|null>(null);const player=useRef<LocalLivePlayer|null>(null);
  const frameCallback=useRef<number|null>(null);const [presented,setPresented]=useState(0);
  useEffect(()=>()=>{void player.current?.stop();player.current=null;},[]);
  async function start(){
    if(disabled||!channel||!inventory.device_id||player.current)return;
    const active=new LocalLivePlayer({tenantId,connectionId:inventory.connection_id,storeId:inventory.store_id,deviceId:inventory.device_id,channelId:channel,generation:inventory.connection_generation,inventoryRevision:inventory.inventory_revision,stream:quality},csrf,{
      state:state=>{setFailureCode(state==='failed'?player.current?.failureCode??null:null);setStatus(state);},stream:stream=>{
        const element=video.current;if(!element)return;
        if(frameCallback.current!==null){element.cancelVideoFrameCallback(frameCallback.current);frameCallback.current=null;}
        element.srcObject=stream;
        if(stream){
          const expected=player.current;
          frameCallback.current=element.requestVideoFrameCallback((_now,metadata)=>{
            frameCallback.current=null;if(player.current!==expected||!expected||expected.closed)return;
            setPresented(metadata.presentedFrames);void expected.presented(metadata.presentedFrames);
          });
          void element.play().catch(()=>undefined);
        }
      },
    });
    setPresented(0);player.current=active;await active.start();
  }
  async function stop(){const active=player.current;player.current=null;await active?.stop();}
  const busy=['connecting','negotiating','playing'].includes(status);
  return <section className="mt-4 space-y-3 border-t border-[var(--wso-border)] pt-4" aria-label="실시간 영상">
    <label htmlFor={selectId} className="block text-sm font-medium">영상 채널</label>
    <select id={selectId} className="w-full rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2" value={channel} disabled={disabled||busy} onChange={e=>{void stop();setChannel(e.target.value);}}>{inventory.channels.map(c=><option key={c.id} value={c.id}>{c.ordinal}번 채널</option>)}</select>
    <label htmlFor={qualityId} className="block text-sm font-medium">영상 화질</label>
    <select id={qualityId} className="w-full rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2" value={quality} disabled={disabled||busy} onChange={e=>setQuality(e.target.value==='sub'?'sub':'main')}><option value="main">고화질</option><option value="sub">저화질</option></select>
    <div className="flex flex-wrap gap-2"><button type="button" className="wso-button-primary" disabled={disabled||busy||!channel} onClick={()=>{void stop().then(start);}}>실시간 재생</button><button type="button" className="wso-button-secondary" disabled={!busy} onClick={()=>void stop()}>영상 중지</button></div>
    <video ref={video} autoPlay muted playsInline controls={false} data-presented-frames={presented} aria-label="CCTV 실시간 영상" className="aspect-video w-full rounded-lg bg-black object-fill" onPlaying={()=>{if(player.current?.playbackConfirmed)setStatus('playing');}} onWaiting={()=>{if(player.current&&!player.current.closed)setStatus('negotiating');}}/>
    <p role="status" className="text-sm">{status==='failed'&&failureCode==='LOCAL_DEVICE_NO_SIGNAL'?'영상 신호 없음 · 채널에 카메라가 연결되어 있는지 확인하세요.':{connecting:'장치에 연결하고 있습니다.',negotiating:'영상 수신을 기다리고 있습니다.',playing:'실시간 영상 재생 중',stopped:'영상을 재생할 채널을 선택하세요.',failed:'영상을 연결하지 못했습니다. 채널을 확인한 뒤 다시 시도하세요.'}[status]}</p>
  </section>;
}
