"use client";
import { ReadStatus } from './DeviceList';
import { channelSelector, deviceSelector, listObservations, observationText, type DirectoryReadState } from './observations';

export function ChannelList({ sn, state, selected, onSelect, onQuery }: { sn: string; state: DirectoryReadState; selected?: number; onSelect: (index: number) => void; onQuery: () => void }) {
  const channels = state.view?.records.filter(record => deviceSelector(record) === sn).flatMap(record => listObservations(record, 'chls')) ?? [];
  return <section className="wso-card space-y-4 p-5" aria-label="채널 목록" aria-busy={state.busy}>
    <h2 className="text-lg font-semibold">채널 목록</h2><p className="break-all text-xs text-[var(--wso-muted)]">선택한 기기: {sn}</p>
    <button type="button" className="wso-button-secondary" disabled={state.busy} onClick={onQuery}>{state.view ? '채널 새로고침' : '채널 목록 조회'}</button>
    <ReadStatus state={state} />
    {state.view && channels.length === 0 && <p role="status">조회 결과에서 선택한 기기의 채널을 확인할 수 없습니다.</p>}
    <ul className="space-y-2">{channels.map((record, index) => {
      const channel = channelSelector(record); const name = observationText(record, 'chlName');
      return <li key={index} className="rounded-lg border border-[var(--wso-border)] p-3"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="break-words font-medium">{name}</p><p className="text-xs text-[var(--wso-muted)]">채널 번호: {observationText(record, 'chlIndex')}</p></div><button type="button" className="wso-button-secondary" disabled={channel === undefined} aria-pressed={selected === channel && channel !== undefined} aria-label={`${name} 선택`} onClick={() => { if (channel !== undefined) onSelect(channel); }}>채널 선택</button></div></li>;
    })}</ul>
  </section>;
}
