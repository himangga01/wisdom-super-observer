'use client';
import {useEffect,useId,useRef,useState} from 'react';
import type {ConnectionView} from '../../lib/connections';
import type {Store} from '../../lib/session';
import {LocalDeviceError,localDeviceMessage,readLocalDevice,verifyLocalDevice,type LocalDeviceView} from '../../lib/tvt/local-device-api';
type Props={tenantId:string;connection:ConnectionView;stores:Store[];csrf:string;disabled:boolean};
export function LocalDeviceInventory(props:Props){
  const stores=props.stores.filter(s=>s.active&&s.tenant_id===props.tenantId&&props.connection.store_ids.includes(s.id));
  const key=[props.tenantId,props.connection.id,props.connection.generation,props.connection.status,...stores.map(s=>s.id)].join('/');
  return <Inventory key={key} {...props} stores={stores}/>;
}
function Inventory({tenantId,connection,stores,csrf,disabled}:Props){
  const inputId=useId();
  const [storeId,setStoreId]=useState(stores.length===1?stores[0].id:'');
  const [view,setView]=useState<LocalDeviceView|null>(null);
  const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  const flight=useRef<AbortController|null>(null); const revision=useRef(0);
  useEffect(()=>()=>{revision.current++;flight.current?.abort();},[]);
  function select(value:string){revision.current++;flight.current?.abort();flight.current=null;setStoreId(value);setView(null);setError('');setBusy(false);}
  async function load(verify:boolean){
    if(flight.current||disabled||!storeId||connection.status==='DISCONNECTED') return;
    const controller=new AbortController();flight.current=controller;const current=++revision.current;
    setBusy(true);setView(null);setError('');
    let timedOut=false;const timeout=setTimeout(()=>{timedOut=true;controller.abort();},25000);
    try{
      const result=await (verify?verifyLocalDevice(tenantId,connection,storeId,csrf,controller.signal):readLocalDevice(tenantId,connection,storeId,controller.signal));
      if(current===revision.current&&!controller.signal.aborted)setView(result);
    }catch(reason){
      if(current===revision.current)setError(timedOut?localDeviceMessage(504):controller.signal.aborted?'기기 확인을 취소했습니다.':localDeviceMessage(reason instanceof LocalDeviceError?reason.status:503));
    }finally{clearTimeout(timeout);if(current===revision.current){flight.current=null;setBusy(false);}}
  }
  const unavailable=!storeId||connection.status==='DISCONNECTED';
  return <section className="mt-5 border-t border-[var(--wso-border)] pt-4" aria-label={`${connection.alias} 장치 정보`} aria-busy={busy}>
    <label htmlFor={inputId} className="block text-sm font-medium">확인할 매장</label>
    <select id={inputId} value={storeId} onChange={e=>select(e.target.value)} disabled={disabled||busy||!stores.length} className="mt-2 w-full rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2">
      {!storeId&&<option value="">매장을 선택하세요</option>}
      {stores.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
    {!stores.length&&<p className="mt-2 text-sm text-[var(--wso-muted)]">연결 수정에서 매장을 지정한 뒤 기기를 확인하세요.</p>}
    {connection.status==='DISCONNECTED'&&<p className="mt-2 text-sm">연결 정보를 다시 저장한 뒤 확인하세요.</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className="wso-button-primary" disabled={disabled||busy||unavailable} onClick={()=>void load(true)}>기기 확인</button>
      <button type="button" className="wso-button-secondary" disabled={disabled||busy||unavailable} onClick={()=>void load(false)}>저장된 채널</button>
      {busy&&<button type="button" className="wso-button-secondary" onClick={()=>flight.current?.abort()}>확인 취소</button>}
    </div>
    {busy&&<p role="status" className="mt-3 text-sm">장치 정보를 확인하고 있습니다.</p>}
    {error&&<p role="alert" className="mt-3 text-sm text-[#A52A2A]">{error}</p>}
    {view&&<div className="mt-3 space-y-2 text-sm">
      <p role="status">{view.inventory_state==='AVAILABLE'?`장치 정보 확인됨 · ${view.channels.length}개 채널`:view.inventory_state==='STALE'?'연결 정보가 변경되었습니다. 기기를 다시 확인하세요.':'아직 확인된 장치 정보가 없습니다.'}</p>
      {view.inventory_state==='AVAILABLE'&&<><p className="text-[var(--wso-muted)]">채널 정보 확인 결과입니다. 영상 재생 상태는 별도로 확인됩니다.</p><ul className="grid gap-2 sm:grid-cols-2">{view.channels.map(c=><li key={c.id} className="rounded-lg border border-[var(--wso-border)] px-3 py-2">{c.ordinal}번 채널</li>)}</ul></>}
    </div>}
  </section>;
}
