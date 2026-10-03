"use client";
import { useId, useState } from 'react';
import { deviceSelector, observationText, type DirectoryReadState, type PageQuery } from './observations';

export function ReadStatus({ state }: { state: DirectoryReadState }) {
  return <>
    {state.busy && <p role="status" className="text-[var(--wso-muted)]">{state.view ? '새로고침 중입니다. 이전 조회 결과를 표시합니다.' : '조회 중입니다.'}</p>}
    {state.error && <p role="alert" className="tvt-error">{state.error}{state.view && ' 이전 조회 결과를 표시합니다.'}</p>}
    {state.view && state.page && <p className="text-xs text-[var(--wso-muted)]">표시 중인 페이지: {state.page.page_num} · 페이지 크기: {state.page.page_size}</p>}
  </>;
}
export function PageQueryFields({ label, state, onQuery }: { label: string; state: DirectoryReadState; onQuery: (page: PageQuery) => void }) {
  const id = useId();
  const [num, setNum] = useState('0'); const [size, setSize] = useState('1000'); const [error, setError] = useState('');
  const submit = () => {
    if (!/^\d+$/.test(num) || !/^\d+$/.test(size) || Number(num) > 2147483647 || Number(size) > 1000) { setError('페이지 번호와 크기를 확인하세요.'); return; }
    setError(''); onQuery({ page_num: Number(num), page_size: Number(size) });
  };
  return <div className="space-y-3">
    <form className="flex flex-wrap items-end gap-3" aria-busy={state.busy} onSubmit={event => { event.preventDefault(); submit(); }}>
      <div><label className="mb-1 block text-xs" htmlFor={`${id}-num`}>{label} 페이지 번호</label><input id={`${id}-num`} className="tvt-input max-w-40" type="number" min={0} max={2147483647} step={1} required value={num} onChange={event => setNum(event.target.value)} disabled={state.busy} /></div>
      <div><label className="mb-1 block text-xs" htmlFor={`${id}-size`}>{label} 페이지 크기</label><input id={`${id}-size`} className="tvt-input max-w-40" type="number" min={0} max={1000} step={1} required value={size} onChange={event => setSize(event.target.value)} disabled={state.busy} /></div>
      <button type="submit" className="wso-button-primary" disabled={state.busy}>{label === '기기' ? '기기 목록 조회' : `${label} 조회`}</button>
      {state.view && <button type="button" className="wso-button-secondary" disabled={state.busy} onClick={() => onQuery(state.page ?? { page_num: 0, page_size: 1000 })}>{label} 새로고침</button>}
    </form>
    {error && <p role="alert" className="tvt-error">{error}</p>}
    <ReadStatus state={state} />
  </div>;
}
export function DeviceList({ state, selected, onSelect, onQuery }: { state: DirectoryReadState; selected?: string; onSelect: (sn: string) => void; onQuery: (page: PageQuery) => void }) {
  return <section className="wso-card space-y-5 p-5" aria-label="기기 목록" aria-busy={state.busy}>
    <div><h2 className="text-lg font-semibold">기기 목록</h2><p className="mt-1 text-sm text-[var(--wso-muted)]">연결된 계정의 카메라와 녹화기를 확인하세요.</p></div>
    <PageQueryFields label="기기" state={state} onQuery={onQuery} />
    {state.view ? <>
      <p className="text-xs text-[var(--wso-muted)]">보고된 전체 수: {state.view.total ?? '확인할 수 없음'} · 전체 목록 여부는 확인되지 않았습니다.</p>
      {state.view.records.length === 0 && <p role="status">조회한 페이지에 기기가 없습니다. 다른 페이지의 기기 여부는 확인할 수 없습니다.</p>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {state.view.records.map((record, index) => {
          const sn = deviceSelector(record); const name = observationText(record, 'name');
          return <li key={index} className={`min-w-0 rounded-xl border p-4 ${selected === sn && sn ? 'border-[var(--wso-accent)] bg-[var(--wso-accent-soft)]' : 'border-[var(--wso-border)]'}`}>
            <p className="break-words font-semibold">{name}</p><p className="mt-2 break-all text-xs text-[var(--wso-muted)]">기기 식별자: {observationText(record, 'sn')}</p>
            <button type="button" className="wso-button-secondary mt-3" disabled={!sn} aria-pressed={Boolean(sn && selected === sn)} aria-label={`${name} 선택`} onClick={() => { if (sn) onSelect(sn); }}>기기 선택</button>
          </li>;
        })}
      </ul>
    </> : !state.busy && <p role="status" className="text-[var(--wso-muted)]">조회 버튼을 눌러 기기를 확인하세요.</p>}
  </section>;
}
