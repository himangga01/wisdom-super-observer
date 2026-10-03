/* eslint-disable @next/next/no-html-link-for-pages -- Full navigation rechecks current authorization. */
"use client";
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Bootstrap } from '../../../lib/tvt/api-client';
import { DirectoryError, directoryClient, type DirectoryApi, type DirectoryView } from '../../../lib/tvt/directory-api-client';
import { DeviceList } from './DeviceList';
import { ChannelList } from './ChannelList';
import { DeviceDetail } from './DeviceDetail';
import { Shares } from './Shares';
import { emptyRead, type DirectoryReadState, type PageQuery } from './observations';

export type DirectoryPageProps = { userId: string; bootstrap: Bootstrap; csrf: string; requery: () => Promise<Bootstrap> };
type Identity = Bootstrap['identity']['accounts'][number];
type Entry = 'devices' | 'sent' | 'received';
type Slot = 'devices' | 'channels' | 'deviceDetail' | 'channelDetail' | 'sent' | 'received';
type Reads = Record<Slot, DirectoryReadState>;
type Recovery = 'web' | 'tenant' | 'account' | 'consent';
type Denial = { recovery: Recovery; message: string };
const identityKey = (identity: Identity) => JSON.stringify([identity.id,identity.region,identity.brand]);
const freshReads = (): Reads => ({ devices: emptyRead, channels: emptyRead, deviceDetail: emptyRead, channelDetail: emptyRead, sent: emptyRead, received: emptyRead });
const recoveryLinks: Record<Recovery, { href: string; label: string }> = { web: { href: '/api/auth/login', label: '웹 다시 로그인' }, tenant: { href: '/stores', label: '내 매장으로 이동' }, account: { href: '/tvt/account', label: 'TVT 계정 다시 로그인' }, consent: { href: '/tvt', label: '약관 확인' } };
function recoveryFor(error: DirectoryError): Recovery | undefined {
  if (['AUTH_REQUIRED','TOKEN_EXPIRED','DIRECTORY_REAUTHENTICATION_REQUIRED'].includes(error.code)) return 'account';
  if (['unauthenticated','authentication_required'].includes(error.code)) return 'web';
  if (['forbidden','principal_not_provisioned','FORBIDDEN'].includes(error.code)) return 'tenant';
  if (['consent_required','consent_version_changed'].includes(error.code)) return 'consent';
  if (['not_found','ACCOUNT_DENIED'].includes(error.code)) return 'account';
  if (error.code === 'csrf_rejected') return 'web';
}

export function DirectoryPage(props: DirectoryPageProps) {
  const { bootstrap, userId, csrf } = props;
  if (bootstrap.consent.status !== 'accepted') return <div className="wso-card space-y-4 p-6"><p role="status">현재 약관에 동의한 뒤 기기 목록을 이용하세요.</p><a className="wso-button-secondary" href="/tvt">약관 확인</a></div>;
  if (!userId) return <div className="wso-card p-6"><a className="wso-button-primary" href="/api/auth/login">웹 다시 로그인</a></div>;
  if (bootstrap.identity.state !== 'linked' || bootstrap.identity.accounts.length === 0) return <div className="wso-card space-y-4 p-6"><p role="status">연결된 TVT 계정이 없습니다.</p><a className="wso-button-secondary" href="/tvt/account">TVT 계정 연결</a></div>;
  // Structured tuples prevent ambiguous string joins. Authority and entry lifetime
  // changes remount below, clearing snapshots and aborting every owned request.
  const scope = JSON.stringify([userId,bootstrap.selected_tenant_id,bootstrap.profile_id,bootstrap.brand,bootstrap.region,bootstrap.consent.version,bootstrap.consent.status,bootstrap.identity.state,bootstrap.identity.accounts.map(item=>[item.id,item.brand,item.region]),csrf]);
  return <ActiveDirectory key={scope} {...props} />;
}
function ActiveDirectory({ bootstrap, csrf, requery }: DirectoryPageProps) {
  const [api] = useState(() => directoryClient(csrf));
  const [selected, setSelected] = useState(''); const [entry, setEntry] = useState<Entry>('devices');
  // Denial belongs to this authority lifetime, independently of disposable tabs.
  const [authorityDenial, setAuthorityDenial] = useState<Denial>();
  const [identityDenials, setIdentityDenials] = useState<Record<string,Denial>>({});
  const [left, setLeft] = useState(false);
  useEffect(() => {
    const leave = () => setLeft(true);
    const logout = (event: Event) => { if (event.target instanceof HTMLFormElement && new URL(event.target.action).pathname === '/api/auth/logout') leave(); };
    window.addEventListener('pagehide',leave); document.addEventListener('submit',logout,true);
    return () => { window.removeEventListener('pagehide',leave); document.removeEventListener('submit',logout,true); };
  }, []);
  const identity = bootstrap.identity.accounts.find(item=>item.id === selected);
  const denial = authorityDenial ?? (identity ? identityDenials[identityKey(identity)] : undefined);
  if (left) return <p role="status" className="wso-card p-6">페이지를 다시 열어 현재 계정을 확인하세요.</p>;
  return <section className="space-y-4" aria-label="TVT 기기 디렉터리" lang="ko">
    <div className="wso-card space-y-3 p-5"><h1 className="text-xl font-semibold">기기 및 공유</h1><label htmlFor="directory-identity" className="block font-medium">연결된 TVT 계정</label><select id="directory-identity" className="tvt-input" value={selected} onChange={event=>setSelected(event.target.value)}><option value="">계정을 선택하세요</option>{bootstrap.identity.accounts.map(item=><option key={item.id} value={item.id}>{item.id} · {item.brand} · {item.region}</option>)}</select><p className="text-xs text-[var(--wso-muted)]">계정을 선택하고 조회 버튼을 눌러 최신 정보를 확인하세요.</p></div>
    {identity && <>
      <nav aria-label="기기 및 공유 보기" className="flex flex-wrap gap-2">{(['devices','sent','received'] as const).map(tab=><button type="button" key={tab} className={`wso-button-secondary ${entry===tab ? 'bg-[var(--wso-accent-soft)]' : ''}`} aria-pressed={entry===tab} onClick={()=>setEntry(tab)}>{tab==='devices'?'기기':tab==='sent'?'보낸 공유':'받은 공유'}</button>)}</nav>
    </>}
    {denial ? <RecoveryPanel key={authorityDenial ? 'authority' : identityKey(identity!)} denial={denial} requery={requery} /> : identity && <DirectoryEntry key={JSON.stringify([identity.id,identity.region,identity.brand,entry])} api={api} tenant={bootstrap.selected_tenant_id} identity={identity} entry={entry} onDenied={(next,identityOnly)=>{ if(identityOnly) setIdentityDenials(value=>({...value,[identityKey(identity)]:next})); else setAuthorityDenial(next); }} />}
  </section>;
}
function RecoveryPanel({ denial, requery }: { denial: Denial; requery: () => Promise<Bootstrap> }) {
  const [message, setMessage] = useState(denial.message); const [checking, setChecking] = useState(false);
  const alive = useRef(true); const checkingLock = useRef(false);
  useEffect(() => { alive.current=true; return () => { alive.current=false; }; }, []);
  async function checkAuthority() {
    if (checkingLock.current || !alive.current) return;
    checkingLock.current=true; setChecking(true);
    try { await requery(); } catch { if (alive.current) setMessage('현재 계정과 권한을 확인할 수 없습니다. 페이지를 다시 열어주세요.'); }
    finally { if (alive.current) { checkingLock.current=false; setChecking(false); } }
  }
  return <div className="wso-card space-y-4 p-6"><p role="alert" className="tvt-error">{message}</p><div className="flex flex-wrap gap-3"><a className="wso-button-primary" href={recoveryLinks[denial.recovery].href}>{recoveryLinks[denial.recovery].label}</a><button type="button" className="wso-button-secondary" disabled={checking} onClick={()=>void checkAuthority()}>현재 계정 다시 확인</button></div>{checking && <p role="status">현재 계정과 권한을 확인합니다.</p>}</div>;
}
function DirectoryEntry({ api, tenant, identity, entry, onDenied }: { api: DirectoryApi; tenant: string; identity: Identity; entry: Entry; onDenied: (denial: Denial, identityOnly: boolean) => void }) {
  const [reads, setReads] = useState<Reads>(freshReads); const [sn, setSn] = useState<string>(); const [channel, setChannel] = useState<number>();
  const pending = useRef(new Map<Slot,AbortController>()); const alive = useRef(true); const generation = useRef<number | undefined>(undefined);
  const blocked = useRef(false);
  const cancel = useCallback(() => { for (const controller of pending.current.values()) controller.abort(); pending.current.clear(); }, []);
  useEffect(() => {
    alive.current=true;
    const leave = () => { alive.current=false; cancel(); };
    const logout = (event: Event) => { if (event.target instanceof HTMLFormElement && new URL(event.target.action).pathname === '/api/auth/logout') leave(); };
    window.addEventListener('pagehide',leave); document.addEventListener('submit',logout,true);
    return () => { window.removeEventListener('pagehide',leave); document.removeEventListener('submit',logout,true); leave(); };
  }, [cancel]);
  const reference = { identity_id: identity.id, region: identity.region, brand: identity.brand };
  async function run(slot: Slot, operation: (signal: AbortSignal) => Promise<DirectoryView>, page?: PageQuery) {
    if (!alive.current || blocked.current || pending.current.has(slot)) return;
    const controller = new AbortController(); pending.current.set(slot,controller);
    const current = () => alive.current && !controller.signal.aborted && pending.current.get(slot) === controller;
    setReads(value=>({...value,[slot]:{...value[slot],busy:true,error:undefined}}));
    try {
      const view = await operation(controller.signal);
      if (!current()) return;
      if (generation.current !== undefined && view.generation < generation.current) return;
      const changed = generation.current !== undefined && view.generation !== generation.current;
      generation.current=view.generation;
      if (changed) { for (const [other, active] of pending.current) if (other !== slot) { active.abort(); pending.current.delete(other); } }
      setReads(value=>({...changed ? freshReads() : value,[slot]:{view,busy:false,page}}));
    } catch (cause) {
      if (!current()) return;
      const error = cause instanceof DirectoryError ? cause : new DirectoryError(503,'ACCOUNT_UNAVAILABLE');
      const nextRecovery = recoveryFor(error);
      if (nextRecovery) { blocked.current=true; cancel(); setReads(freshReads()); setSn(undefined); setChannel(undefined); onDenied({recovery:nextRecovery,message:error.message},nextRecovery==='account' || error.code==='FORBIDDEN'); }
      else setReads(value=>({...value,[slot]:{...value[slot],busy:false,error:error.message}}));
    } finally {
      if (current()) { pending.current.delete(slot); setReads(value=>({...value,[slot]:{...value[slot],busy:false}})); }
    }
  }
  function selectDevice(next: string) {
    if (next === sn) return;
    for (const slot of ['channels','deviceDetail','channelDetail'] as const) { pending.current.get(slot)?.abort(); pending.current.delete(slot); }
    setSn(next); setChannel(undefined); setReads(value=>({...value,channels:emptyRead,deviceDetail:emptyRead,channelDetail:emptyRead}));
  }
  function selectChannel(next: number) {
    if (next === channel) return;
    pending.current.get('channelDetail')?.abort(); pending.current.delete('channelDetail');
    setChannel(next); setReads(value=>({...value,channelDetail:emptyRead}));
  }
  if (entry !== 'devices') return <Shares direction={entry} state={reads[entry]} onQuery={page=>void run(entry,signal=>entry==='sent'?api.sentShares(tenant,{...reference,...page,resource_types:[]},signal):api.receivedShares(tenant,{...reference,...page,resource_types:[]},signal),page)} />;
  return <div className="space-y-4">
    <DeviceList state={reads.devices} selected={sn} onSelect={selectDevice} onQuery={page=>void run('devices',signal=>api.deviceList(tenant,{...reference,...page},signal),page)} />
    {sn && <div className="grid items-start gap-4 xl:grid-cols-2">
      <ChannelList sn={sn} state={reads.channels} selected={channel} onSelect={selectChannel} onQuery={()=>void run('channels',signal=>api.channelList(tenant,{...reference,sn_list:[sn]},signal))} />
      <DeviceDetail sn={sn} channel={channel} deviceState={reads.deviceDetail} channelState={reads.channelDetail} onDeviceQuery={()=>void run('deviceDetail',signal=>api.deviceDetail(tenant,{...reference,sn,return_chl:false},signal))} onChannelQuery={()=>{ if(channel!==undefined) void run('channelDetail',signal=>api.channelDetail(tenant,{...reference,sn,chl_index:channel},signal)); }} />
    </div>}
  </div>;
}
