"use client";
import { ReadStatus } from './DeviceList';
import { objectObservation, observationText, type DirectoryReadState, type Observation, type ObservationName } from './observations';

export function ObservationFields({ record, fields }: { record?: Observation; fields: readonly (readonly [ObservationName, string])[] }) {
  return <dl className="grid gap-3 sm:grid-cols-2">{fields.map(([name, label]) => <div key={name} className="min-w-0"><dt className="text-xs text-[var(--wso-muted)]">{label}</dt><dd className="mt-1 break-words">{observationText(record, name)}</dd></div>)}</dl>;
}
export function DeviceDetail({ sn, channel, deviceState, channelState, onDeviceQuery, onChannelQuery }: { sn: string; channel?: number; deviceState: DirectoryReadState; channelState: DirectoryReadState; onDeviceQuery: () => void; onChannelQuery: () => void }) {
  return <div className="space-y-4">
    <section className="wso-card space-y-4 p-5" aria-label="기기 상세" aria-busy={deviceState.busy}>
      <h2 className="text-lg font-semibold">기기 상세</h2><p className="break-all text-xs text-[var(--wso-muted)]">선택한 기기: {sn}</p>
      <button type="button" className="wso-button-secondary" disabled={deviceState.busy} onClick={onDeviceQuery}>{deviceState.view ? '기기 상세 새로고침' : '기기 상세 조회'}</button>
      <ReadStatus state={deviceState} />
      {deviceState.view && <ObservationFields record={objectObservation(deviceState.view.records[0], 'devInfo')} fields={ [['name','이름'],['model','모델'],['version','버전'],['onlineStatus','상태 값'],['onlineTime','연결 시각'],['offlineTime','연결 종료 시각'],['userId','계정 참조']] } />}
    </section>
    {channel !== undefined && <section className="wso-card space-y-4 p-5" aria-label="채널 상세" aria-busy={channelState.busy}>
      <h2 className="text-lg font-semibold">채널 상세</h2><p className="text-xs text-[var(--wso-muted)]">선택한 채널 번호: {channel}</p>
      <button type="button" className="wso-button-secondary" disabled={channelState.busy} onClick={onChannelQuery}>{channelState.view ? '채널 상세 새로고침' : '채널 상세 조회'}</button>
      <ReadStatus state={channelState} />
      {channelState.view && <ObservationFields record={channelState.view.records[0]} fields={ [['chlName','채널 이름'],['chlIndex','채널 번호'],['model','모델'],['version','버전'],['status','상태 값'],['onlineTime','연결 시각'],['offlineTime','연결 종료 시각']] } />}
    </section>}
  </div>;
}
