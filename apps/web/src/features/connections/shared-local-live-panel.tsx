'use client';
import {useId,useLayoutEffect,useRef,useState} from 'react';
import type {LocalDeviceView} from '../../lib/tvt/local-device-api';
import {LocalLivePlayer} from '../../lib/tvt/local-live-player';
import {LiveWallGroupController} from '../../lib/tvt/live-wall-group';
import {createLocalWall,heartbeatLocalWall,readLocalWall,reserveLocalFocus,settleLocalFocus,stopLocalWall} from '../../lib/tvt/local-live-wall-api';
import {isRequested,tileState,type LiveTileState} from '../../lib/tvt/live-wall-scheduler';
import {createWallRuntime,type Feed,type LiveWallPlayerFactory,type WallRuntime} from '../monitoring/live-wall';
import {LiveVideo} from '../monitoring/live-tile';

const createLocalPlayer:LiveWallPlayerFactory=(binding,csrf,events)=>new LocalLivePlayer(binding,csrf,events);
// Retain original card cleanup across inventory, connection and credential remounts.
// Rejected cleanup remains a fence; another card must not conceal that owner.
const originalStops=new Set<Promise<void>>();
function retain(original:Promise<void>):Promise<void>{
  originalStops.add(original);
  void original.then(()=>originalStops.delete(original),()=>undefined);
  return original;
}
async function waitOriginalStops(){while(originalStops.size)await Promise.all([...originalStops]);}

async function stopCardWall(...args:Parameters<typeof stopLocalWall>){
  const value=await stopLocalWall(...args);
  if(value.wall.state==='CLOSED')return value;
  if(value.wall.state!=='STOPPING')throw new Error('Original wall cleanup unresolved');
  // Fulfilled STOPPING is not terminal. Keep this original group's stop pending
  // through bounded readback; scope never comes from a replacement component.
  const signal=AbortSignal.timeout(25_000);
  for(;;){
    signal.throwIfAborted();
    const current=await readLocalWall(args[0],args[1],signal);
    if(current.wall.state==='CLOSED')return current;
    if(current.wall.state!=='STOPPING')throw new Error('Original wall cleanup unresolved');
    await new Promise<void>((resolve,reject)=>{
      const finish=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);};
      const abort=()=>{finish();reject(signal.reason);};
      const timer=setTimeout(()=>{finish();resolve();},500);
      signal.addEventListener('abort',abort,{once:true});
      if(signal.aborted)abort();
    });
  }
}

/** A single-channel adapter over the same wall/focus/player lifecycle as monitoring. */
export function SharedLocalLivePanel({tenantId,inventory,csrf,disabled,createPlayer=createLocalPlayer}:{tenantId:string;inventory:LocalDeviceView;csrf:string;disabled:boolean;createPlayer?:LiveWallPlayerFactory}){
  const channelId=useId(),qualityId=useId();
  const [channel,setChannel]=useState(inventory.channels[0]?.id??'');
  const [quality,setQuality]=useState<'main'|'sub'>('main');
  const [state,setState]=useState<LiveTileState>('idle');
  const [feeds,setFeeds]=useState<Record<string,Feed>>({});
  const [waiting,setWaiting]=useState(false),[stopping,setStopping]=useState(false);
  const [failed,setFailed]=useState(false),[noSignal,setNoSignal]=useState(false);
  const runtime=useRef<WallRuntime|null>(null);
  const intent=useRef(0),pending=useRef(false);
  const selected=useRef(channel);
  useLayoutEffect(()=>{selected.current=channel;},[channel]);
  useLayoutEffect(()=>{
    const created=createWallRuntime(setFeeds,undefined,new LiveWallGroupController({tenantId,csrf,api:{create:createLocalWall,heartbeat:heartbeatLocalWall,stop:stopCardWall,reserve:reserveLocalFocus,settle:settleLocalFocus}}));
    runtime.current=created;
    const unsubscribe=created.scheduler.subscribe(snapshot=>{
      const value=tileState(snapshot,selected.current);setState(value);
      if(value==='failed'||value==='nosignal'){
        setFailed(true);setNoSignal(value==='nosignal');pending.current=false;
        // A card failure is terminal until manual Play; retire its private wall too.
        void retain(created.stopAll()).catch(()=>undefined);
      }
    });
    const unsubscribeStopping=created.subscribeStopping(setStopping);
    return ()=>{
      unsubscribe();unsubscribeStopping();
      if(runtime.current===created)runtime.current=null;
      void retain(created.dispose()).catch(()=>undefined);
    };
  },[tenantId,csrf,createPlayer]);
  useLayoutEffect(()=>{
    const tiles=new Map(inventory.channels.map(item=>[item.id,{id:item.id,label:`${item.ordinal}번 채널`,ordinal:item.ordinal,storeId:inventory.store_id,binding:{tenantId,connectionId:inventory.connection_id,storeId:inventory.store_id,deviceId:inventory.device_id!,channelId:item.id,generation:inventory.connection_generation,inventoryRevision:inventory.inventory_revision}}]));
    runtime.current?.configure({tiles,csrf,createPlayer});
  });
  async function start(){
    const active=runtime.current;
    if(disabled||!channel||!inventory.device_id||pending.current||!active||active.stopping||isRequested(active.scheduler.getSnapshot(),channel))return;
    const generation=++intent.current;pending.current=true;setWaiting(true);setFailed(false);setNoSignal(false);
    try{
      await waitOriginalStops();
      if(generation!==intent.current||runtime.current!==active)return;
      active.focus(quality==='main'?channel:null);active.play([channel]);
    }catch{if(generation===intent.current&&runtime.current===active)setFailed(true);}
    finally{if(generation===intent.current&&runtime.current===active){pending.current=false;setWaiting(false);}}
  }
  function stop(){
    intent.current++;pending.current=false;setWaiting(false);
    const active=runtime.current;if(active)void retain(active.stopAll()).catch(()=>setFailed(true));
  }
  function selectQuality(value:'main'|'sub'){
    setQuality(value);
    runtime.current?.focus(value==='main'?channel:null);
  }
  const busy=waiting||state==='starting'||state==='queued'||state==='live';
  const feed=feeds[channel];
  const status=noSignal?'영상 신호 없음 · 채널에 카메라가 연결되어 있는지 확인하세요.':failed?'영상을 연결하지 못했습니다. 채널을 확인한 뒤 다시 시도하세요.':stopping?'영상을 중지하고 있습니다.':state==='live'?'실시간 영상 재생 중':busy?'영상 수신을 기다리고 있습니다.':'영상을 재생할 채널을 선택하세요.';
  return <section className="mt-4 space-y-3 border-t border-[var(--wso-border)] pt-4" aria-label="실시간 영상">
    <label htmlFor={channelId} className="block text-sm font-medium">영상 채널</label>
    <select id={channelId} className="w-full rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2" value={channel} disabled={disabled||busy||stopping} onChange={event=>{setChannel(event.target.value);setState('idle');setFailed(false);setNoSignal(false);}}>{inventory.channels.map(item=><option key={item.id} value={item.id}>{item.ordinal}번 채널</option>)}</select>
    <label htmlFor={qualityId} className="block text-sm font-medium">영상 화질</label>
    <select id={qualityId} className="w-full rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2" value={quality} disabled={disabled||waiting||stopping} onChange={event=>selectQuality(event.target.value==='sub'?'sub':'main')}><option value="main">고화질</option><option value="sub">저화질</option></select>
    <div className="flex flex-wrap gap-2"><button type="button" className="wso-button-primary" disabled={disabled||busy||stopping||!channel} onClick={()=>void start()}>실시간 재생</button><button type="button" className="wso-button-secondary" disabled={!busy||stopping} onClick={stop}>영상 중지</button></div>
    <LiveVideo stream={feed?.stream??null} label="CCTV 실시간 영상" fit="fill" className="aspect-video rounded-lg" onFrame={frames=>{const active=runtime.current;if(active&&feed)active.presented(channel,feed.player,frames);}}/>
    <p role="status" className="text-sm">{status}</p>
  </section>;
}
