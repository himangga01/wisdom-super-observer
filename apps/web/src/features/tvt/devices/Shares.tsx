"use client";
import { PageQueryFields } from './DeviceList';
import { ObservationFields } from './DeviceDetail';
import { observationText, type DirectoryReadState, type ObservationName, type PageQuery } from './observations';

const common: readonly (readonly [ObservationName,string])[] = [['sn','기기 식별자'],['chlName','채널 이름'],['chlIndex','채널 번호'],['recipientRemark','수신자 메모'],['createTime','생성 시각'],['acceptTime','수락 시각'],['resourceType','리소스 유형 값'],['status','상태 값']];
const sent: readonly (readonly [ObservationName,string])[] = [['recipientId','받는 계정'],['validData','유효 기간 값']];
const received: readonly (readonly [ObservationName,string])[] = [['ownerId','보낸 계정'],['devRemark','기기 메모'],['ownerRemark','소유자 메모'],['devType','기기 유형 값']];
export function Shares({ direction, state, onQuery }: { direction: 'sent' | 'received'; state: DirectoryReadState; onQuery: (page: PageQuery) => void }) {
  const label = direction === 'sent' ? '보낸 공유' : '받은 공유';
  return <section className="wso-card space-y-5 p-5" aria-label={`${label} 목록`} aria-busy={state.busy}>
    <div><h2 className="text-lg font-semibold">{label}</h2><p className="mt-1 text-sm text-[var(--wso-muted)]">공유된 기기 정보를 확인하세요.</p></div>
    <PageQueryFields label={label} state={state} onQuery={onQuery} />
    {state.view && <>
      <p className="text-xs text-[var(--wso-muted)]">보고된 전체 수: {state.view.total ?? '확인할 수 없음'} · 전체 목록 여부는 확인되지 않았습니다.</p>
      {state.view.records.length === 0 && <p role="status">조회한 페이지에 공유가 없습니다.</p>}
      <ul className="space-y-3">{state.view.records.map((record,index) => <li key={index} className="rounded-xl border border-[var(--wso-border)] p-4"><h3 className="mb-4 break-words font-semibold">{observationText(record,'devName')}</h3><ObservationFields record={record} fields={[...common,...(direction==='sent'?sent:received)]} /></li>)}</ul>
    </>}
  </section>;
}
