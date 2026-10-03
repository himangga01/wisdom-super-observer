// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import * as client from '../src/lib/tvt/directory-api-client';
import type { Bootstrap } from '../src/lib/tvt/api-client';
import { DirectoryPage, type DirectoryPageProps } from '../src/features/tvt/devices/DirectoryPage';

const tenant = '10000000-0000-4000-8000-000000000001';
const identity = '20000000-0000-4000-8000-000000000001';
const otherIdentity = '20000000-0000-4000-8000-000000000002';
const reference = { identity_id: identity, region: 'KR', brand: 'SuperLivePlus' };
const bootstrap: Bootstrap = { selected_tenant_id: tenant, profile_id: 'ui-test', brand: 'SuperLivePlus', region: 'KR', locale: 'en', timezone: 'Asia/Seoul', supported_locales: ['en'], consent: { version: 'v1', status: 'accepted', decided_at: '2026-10-03T00:00:00Z', terms: { source_reference: 'agreement/ServiceTerms_en.html', url: 'https://policy.test/terms' }, privacy: { source_reference: 'agreement/PrivacyStatement_en.html', url: 'https://policy.test/privacy' } }, identity: { state: 'linked', accounts: [{ id: identity, brand: 'SuperLivePlus', region: 'KR' }, { id: otherIdentity, brand: 'AnotherBrand', region: 'JP' }] }, menu: [{ id: 'local-account', label: 'Account', path: '/tvt/account' }] };
type RecordView = client.DirectoryView['records'][number];
type Name = RecordView['fields'][number]['name'];
function record(names: string, values: Partial<Record<Name, unknown>> = {}): RecordView {
  return { unknown_members: 0, fields: names.split(' ').map(name => ({ name: name as Name, state: Object.hasOwn(values,name) ? values[name as Name] === null ? 'null' : 'value' : 'missing', value: values[name as Name] as RecordView['fields'][number]['value'] ?? null, source_default: name === 'maxShareNum' ? '0' : name === 'type' && names.startsWith('sn name') ? 0 : null, opaque_kind: null })) };
}
const device = (name = '입구 카메라', sn = 'opaque-camera-A') => record('sn name userId devName mode createTime maxShareNum type', { sn, name });
const channels = record('sn chls', { sn: 'opaque-camera-A', chls: [record('chlIndex chlName', { chlIndex: 4, chlName: '현관' }), record('chlIndex chlName', { chlIndex: 91, chlName: '주차장' })] });
const devInfo = record('aiVersion configId customerId lang mac model name offlineTime onlineTime packContentFlag pcui sn snPlain version versionId whitelistVersion workMode checkStatus delStatus maxConnNum onlineStatus type userId checkTime devInfo capability', { name: '상세 카메라', model: 'Model-A', onlineStatus: null });
const deviceDetail = record('devInfo chlInfos', { devInfo });
const channelDetail = record('sn chlName ip model version onlineTime offlineTime chlIndex status capability', { sn: 'opaque-camera-A', chlName: '주차장 상세', chlIndex: 91, status: null });
const sharedNames = 'id sn chlName devName devMode recipientRemark createTime acceptTime chlIndex ownerType status resourceType auth devInfo';
const sent = record(sharedNames+' recipientId validData shardIds', { id: 'share-sent', devName: '보낸 카메라', recipientId: '받는 사람', validData: 7, shardIds: ['share-piece'] });
const received = record(sharedNames+' ownerId devRemark ownerRemark devType', { id: 'share-received', devName: '받은 카메라', ownerId: '보낸 사람', devRemark: '입구 메모', ownerRemark: '소유자 메모', devType: 2 });
function result(method: client.DirectoryView['method'], records: RecordView[], generation = 1, scope = reference): client.DirectoryView {
  const view: client.DirectoryView = { ...scope, method, generation, request_id: 'synthetic.ui.1', records, total: method === 'device_list' ? '999' : method.endsWith('shares') ? 12 : null, complete: null, grants_operations: false };
  const input = { ...scope, method, ...(method === 'channel_list' ? { sn_list: ['opaque-camera-A'] } : method === 'device_detail' ? { sn: 'opaque-camera-A' } : method === 'channel_detail' ? { sn: 'opaque-camera-A', chl_index: 91 } : {}) };
  // All fixtures pass the actual public source whitelist, bounds and observation parser.
  return client.directoryResponse(view, client.directoryInput(method.replaceAll('_','-') as client.DirectoryOperation, input));
}
let api: client.DirectoryApi;
beforeEach(() => {
  api = { deviceList: vi.fn(async () => result('device_list',[device()])), channelList: vi.fn(async () => result('channel_list',[channels])), deviceDetail: vi.fn(async () => result('device_detail',[deviceDetail])), channelDetail: vi.fn(async () => result('channel_detail',[channelDetail])), sentShares: vi.fn(async () => result('sent_shares',[sent])), receivedShares: vi.fn(async () => result('received_shares',[received])) };
  vi.spyOn(client,'directoryClient').mockReturnValue(api);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const props = (extra: Partial<DirectoryPageProps> = {}): DirectoryPageProps => ({ userId: 'actor-A', bootstrap, csrf: 'synthetic-csrf', requery: async () => bootstrap, ...extra });
function choose(value = identity) { fireEvent.change(screen.getByLabelText('연결된 TVT 계정'), { target: { value } }); }
async function loadDevices() { fireEvent.click(screen.getByRole('button',{ name: '기기 목록 조회' })); await screen.findByRole('button',{ name: '입구 카메라 선택' }); }
function deferred() { let resolve!: (value: client.DirectoryView) => void; let reject!: (reason: unknown) => void; const promise = new Promise<client.DirectoryView>((yes,no) => { resolve=yes; reject=no; }); return { promise,resolve,reject }; }

it('queries devices only after explicit linked identity selection and preserves native page/zero size', async () => {
  render(<DirectoryPage {...props()} />);
  expect(api.deviceList).not.toHaveBeenCalled(); choose();
  fireEvent.change(screen.getByLabelText('기기 페이지 번호'),{ target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('기기 페이지 크기'),{ target: { value: '0' } });
  await loadDevices();
  expect(api.deviceList).toHaveBeenCalledWith(tenant,{ ...reference,page_num:2,page_size:0 },expect.any(AbortSignal));
  expect(screen.getByText(/전체 목록 여부는 확인되지 않았습니다/)).toBeVisible();
  expect(screen.getByText(/999/)).toBeVisible();
  expect(client.directoryClient).toHaveBeenCalledOnce();
});
it('exposes all six readonly paths and selects the returned noncontiguous channel id', async () => {
  render(<DirectoryPage {...props()} />); choose(); await loadDevices();
  fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'}));
  fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'})); await screen.findByText('Model-A');
  fireEvent.click(screen.getByRole('button',{name:'채널 목록 조회'})); await screen.findByRole('button',{name:'주차장 선택'});
  fireEvent.click(screen.getByRole('button',{name:'주차장 선택'}));
  fireEvent.click(screen.getByRole('button',{name:'채널 상세 조회'})); await screen.findByText('주차장 상세');
  expect(api.channelList).toHaveBeenCalledWith(tenant,{...reference,sn_list:['opaque-camera-A']},expect.any(AbortSignal));
  expect(api.deviceDetail).toHaveBeenCalledWith(tenant,{...reference,sn:'opaque-camera-A',return_chl:false},expect.any(AbortSignal));
  expect(api.channelDetail).toHaveBeenCalledWith(tenant,{...reference,sn:'opaque-camera-A',chl_index:91},expect.any(AbortSignal));
  fireEvent.click(screen.getByRole('button',{name:'보낸 공유'})); fireEvent.click(screen.getByRole('button',{name:'보낸 공유 조회'})); await screen.findByText('받는 사람');
  expect(screen.queryByText('소유자 메모')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'받은 공유'})); fireEvent.click(screen.getByRole('button',{name:'받은 공유 조회'})); await screen.findByText('보낸 사람');
  expect(within(screen.getByRole('region',{name:'받은 공유 목록'})).getAllByText('소유자 메모')).toHaveLength(2);
  expect(screen.queryByText('받는 사람')).toBeNull();
  expect(api.sentShares).toHaveBeenCalledWith(tenant,{...reference,page_num:0,page_size:1000,resource_types:[]},expect.any(AbortSignal));
  expect(api.receivedShares).toHaveBeenCalledWith(tenant,{...reference,page_num:0,page_size:1000,resource_types:[]},expect.any(AbortSignal));
  expect(screen.queryByRole('button',{name:/삭제|제어|재생|공유 추가/})).toBeNull();
});
it.each(['pending','declined','unlinked'] as const)('issues zero calls for %s and offers recovery', state => {
  const current: Bootstrap = state === 'unlinked' ? {...bootstrap,identity:{state:'unlinked',accounts:[]}} : {...bootstrap,consent:{...bootstrap.consent,status:state}};
  render(<DirectoryPage {...props({bootstrap:current})} />);
  expect(screen.getByRole('link',{name:state==='unlinked'?'TVT 계정 연결':'약관 확인'})).toBeVisible();
  for (const method of Object.values(api)) expect(method).not.toHaveBeenCalled();
});
it('uses exact linked identity region and brand rather than shell defaults', async () => {
  const scope = {identity_id:otherIdentity,brand:'AnotherBrand',region:'JP'};
  vi.mocked(api.deviceList).mockResolvedValueOnce(result('device_list',[device()],1,scope));
  render(<DirectoryPage {...props()} />); choose(otherIdentity); await loadDevices();
  expect(api.deviceList).toHaveBeenCalledWith(tenant,{...scope,page_num:0,page_size:1000},expect.any(AbortSignal));
});
it('retains an accepted snapshot on transient and unknown refresh errors without parallel submissions', async () => {
  const refresh=deferred(); render(<DirectoryPage {...props()} />); choose(); await loadDevices();
  vi.mocked(api.deviceList).mockReturnValueOnce(refresh.promise);
  fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'}));
  expect(screen.getByRole('button',{name:'기기 새로고침'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'})); expect(api.deviceList).toHaveBeenCalledTimes(2);
  await act(async()=>refresh.reject(new client.DirectoryError(504,'UNKNOWN_OUTCOME')));
  expect(screen.getByRole('button',{name:'입구 카메라 선택'})).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent(/현재 목록을 유지/);
  expect(screen.queryByText(/기기가 없습니다/)).toBeNull();
});
it('shows missing/null/opaque observations as unavailable without source defaults or invented online status', async () => {
  devInfo.fields.find(field=>field.name==='userId')!.opaque_kind='object';
  devInfo.fields.find(field=>field.name==='userId')!.state='value';
  render(<DirectoryPage {...props()} />); choose(); await loadDevices(); fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'}));
  fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'})); await screen.findByText('Model-A');
  const section=screen.getByRole('region',{name:'기기 상세'});
  expect(within(section).getAllByText('확인할 수 없음').length).toBeGreaterThan(1);
  expect(screen.queryByText(/온라인|오프라인|unknown_members|opaque_kind|source_default/)).toBeNull();
});
it.each(['actor','tenant','identity','region','brand','consent','consentVersion','csrf','accounts','profile'] as const)('aborts and clears old context on %s replacement and ignores stale success/failure/finally', async kind => {
  const initial=props(); const mounted=render(<DirectoryPage {...initial} />); choose(); await loadDevices();
  const pending=deferred(); vi.mocked(api.deviceList).mockReturnValueOnce(pending.promise); fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'}));
  const oldSignal=vi.mocked(api.deviceList).mock.calls[1][2];
  let next=initial;
  if(kind==='identity') choose(otherIdentity);
  else { next = kind==='actor'?props({userId:'actor-B'}):kind==='tenant'?props({bootstrap:{...bootstrap,selected_tenant_id:'10000000-0000-4000-8000-000000000002'}}):kind==='region'?props({bootstrap:{...bootstrap,region:'US'}}):kind==='brand'?props({bootstrap:{...bootstrap,identity:{...bootstrap.identity,accounts:[{id:identity,region:'KR',brand:'NewBrand'}]}}}):kind==='consent'?props({bootstrap:{...bootstrap,consent:{...bootstrap.consent,status:'pending'}}}):kind==='consentVersion'?props({bootstrap:{...bootstrap,consent:{...bootstrap.consent,version:'v2'}}}):kind==='csrf'?props({csrf:'new-csrf'}):kind==='profile'?props({bootstrap:{...bootstrap,profile_id:'next-profile'}}):props({bootstrap:{...bootstrap,identity:{...bootstrap.identity,accounts:[bootstrap.identity.accounts[0]]}}}); mounted.rerender(<DirectoryPage {...next} />); }
  expect(oldSignal.aborted).toBe(true);
  expect(screen.queryByRole('button',{name:'입구 카메라 선택'})).toBeNull();
  if(kind!=='consent') { if(kind!=='identity') choose(); const newer=deferred(); vi.mocked(api.deviceList).mockReturnValueOnce(newer.promise); fireEvent.click(screen.getByRole('button',{name:'기기 목록 조회'})); await act(async()=>pending.resolve(result('device_list',[device('오래된 카메라')]))); expect(screen.queryByText('오래된 카메라')).toBeNull(); expect(screen.getByRole('button',{name:'기기 목록 조회'})).toBeDisabled(); await act(async()=>newer.reject(new client.DirectoryError(503,'ACCOUNT_UNAVAILABLE'))); expect(screen.getByRole('alert')).toBeVisible(); }
  else { await act(async()=>pending.reject(new client.DirectoryError(401,'AUTH_REQUIRED'))); expect(screen.queryByRole('alert')).toBeNull(); }
});
it.each(['unmount','logout','pagehide','tab'] as const)('cancels the entry lifetime on %s and ignores a late error', async kind => {
  const pending=deferred(); vi.mocked(api.deviceList).mockReturnValueOnce(pending.promise);
  const mounted=render(<DirectoryPage {...props()} />); choose(); fireEvent.click(screen.getByRole('button',{name:'기기 목록 조회'})); const signal=vi.mocked(api.deviceList).mock.calls[0][2];
  if(kind==='unmount') mounted.unmount();
  else if(kind==='tab') fireEvent.click(screen.getByRole('button',{name:'보낸 공유'}));
  else if(kind==='pagehide') fireEvent(window,new Event('pagehide'));
  else { const form=document.createElement('form'); form.action='/api/auth/logout'; document.body.append(form); fireEvent.submit(form); form.remove(); }
  expect(signal.aborted).toBe(true); await act(async()=>pending.reject(new client.DirectoryError(401,'AUTH_REQUIRED'))); expect(screen.queryByRole('alert')).toBeNull();
});
it.each([['AUTH_REQUIRED',401,'TVT 계정 다시 로그인'],['TOKEN_EXPIRED',401,'TVT 계정 다시 로그인'],['unauthenticated',401,'웹 다시 로그인'],['forbidden',403,'내 매장으로 이동'],['consent_required',409,'약관 확인']] as const)('clears denied snapshots and offers appropriate recovery for %s', async (code,status,label) => {
  render(<DirectoryPage {...props()} />); choose(); await loadDevices(); vi.mocked(api.deviceList).mockRejectedValueOnce(new client.DirectoryError(status,code)); fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'})); await screen.findByRole('link',{name:label}); expect(screen.queryByRole('button',{name:'입구 카메라 선택'})).toBeNull();
});
it('clears previous generation snapshots when a newer accepted observation arrives', async () => {
  render(<DirectoryPage {...props()} />); choose(); await loadDevices(); fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'})); vi.mocked(api.deviceDetail).mockResolvedValueOnce(result('device_detail',[deviceDetail],2)); fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'})); await screen.findByText('Model-A'); expect(screen.queryByRole('button',{name:'입구 카메라 선택'})).toBeNull();
});
it('does not select missing device identifiers or fabricate empty inventory completeness', async () => {
  vi.mocked(api.deviceList).mockResolvedValueOnce(result('device_list',[record('sn name userId devName mode createTime maxShareNum type',{name:'식별자 없는 카메라'})]));
  render(<DirectoryPage {...props()} />); choose(); fireEvent.click(screen.getByRole('button',{name:'기기 목록 조회'})); await screen.findByText('식별자 없는 카메라'); expect(screen.getByRole('button',{name:'식별자 없는 카메라 선택'})).toBeDisabled();
  vi.mocked(api.deviceList).mockResolvedValueOnce(result('device_list',[])); fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'})); await waitFor(()=>expect(screen.queryByText('식별자 없는 카메라')).toBeNull()); expect(screen.getByText(/조회한 페이지에 기기가 없습니다/)).toBeVisible(); expect(screen.getByText(/전체 목록 여부는 확인되지 않았습니다/)).toBeVisible();
});

it('refreshes the accepted page after form edits rather than relabeling old data', async () => {
  render(<DirectoryPage {...props()} />); choose(); await loadDevices();
  fireEvent.change(screen.getByLabelText('기기 페이지 번호'),{target:{value:'8'}});
  fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'기기 새로고침'})).toBeEnabled());
  expect(api.deviceList).toHaveBeenLastCalledWith(tenant,{...reference,page_num:0,page_size:1000},expect.any(AbortSignal));
  expect(screen.getByText(/표시 중인 페이지: 0/)).toBeVisible();
});
it.each(['success','failure'] as const)('ignores stale %s after device replacement while successor stays busy', async outcome => {
  vi.mocked(api.deviceList).mockResolvedValueOnce(result('device_list',[device(),device('뒷문 카메라','opaque-camera-B')]));
  render(<DirectoryPage {...props()} />); choose(); await loadDevices(); fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'}));
  const old=deferred(); vi.mocked(api.deviceDetail).mockReturnValueOnce(old.promise); fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'}));
  const signal=vi.mocked(api.deviceDetail).mock.calls[0][2];
  fireEvent.click(screen.getByRole('button',{name:'뒷문 카메라 선택'})); expect(signal.aborted).toBe(true);
  const next=deferred(); vi.mocked(api.deviceDetail).mockReturnValueOnce(next.promise); fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'}));
  await act(async()=>{ if(outcome==='success') old.resolve(result('device_detail',[deviceDetail])); else old.reject(new client.DirectoryError(401,'AUTH_REQUIRED')); });
  expect(screen.queryByText('Model-A')).toBeNull(); expect(screen.queryByRole('alert')).toBeNull(); expect(screen.getByRole('button',{name:'기기 상세 조회'})).toBeDisabled();
  await act(async()=>next.resolve(result('device_detail',[deviceDetail]))); expect(screen.getByText('Model-A')).toBeVisible();
});
it('cancels pending channel detail and clears its snapshot on returned channel replacement including index zero', async () => {
  const list=record('sn chls',{sn:'opaque-camera-A',chls:[record('chlIndex chlName',{chlIndex:0,chlName:'첫 채널'}),record('chlIndex chlName',{chlIndex:91,chlName:'주차장'})]});
  vi.mocked(api.channelList).mockResolvedValueOnce(result('channel_list',[list]));
  render(<DirectoryPage {...props()} />); choose(); await loadDevices(); fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'})); fireEvent.click(screen.getByRole('button',{name:'채널 목록 조회'})); await screen.findByRole('button',{name:'주차장 선택'}); fireEvent.click(screen.getByRole('button',{name:'주차장 선택'}));
  const old=deferred(); vi.mocked(api.channelDetail).mockReturnValueOnce(old.promise); fireEvent.click(screen.getByRole('button',{name:'채널 상세 조회'}));
  const signal=vi.mocked(api.channelDetail).mock.calls[0][2]; fireEvent.click(screen.getByRole('button',{name:'첫 채널 선택'})); expect(signal.aborted).toBe(true);
  vi.mocked(api.channelDetail).mockResolvedValueOnce(result('channel_detail',[record('sn chlName ip model version onlineTime offlineTime chlIndex status capability',{sn:'opaque-camera-A',chlName:'첫 채널 상세',chlIndex:0})]));
  fireEvent.click(screen.getByRole('button',{name:'채널 상세 조회'})); await screen.findByText('첫 채널 상세'); expect(api.channelDetail).toHaveBeenLastCalledWith(tenant,{...reference,sn:'opaque-camera-A',chl_index:0},expect.any(AbortSignal));
  await act(async()=>old.reject(new client.DirectoryError(401,'AUTH_REQUIRED'))); expect(screen.getByText('첫 채널 상세')).toBeVisible(); expect(screen.queryByRole('alert')).toBeNull();
});
it('new generation aborts older parallel reads so their late result cannot resurrect snapshots', async () => {
  render(<DirectoryPage {...props()} />); choose(); await loadDevices(); fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'}));
  const old=deferred(); vi.mocked(api.channelList).mockReturnValueOnce(old.promise); fireEvent.click(screen.getByRole('button',{name:'채널 목록 조회'})); const signal=vi.mocked(api.channelList).mock.calls[0][2];
  vi.mocked(api.deviceDetail).mockResolvedValueOnce(result('device_detail',[deviceDetail],2)); fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'})); await screen.findByText('Model-A'); expect(signal.aborted).toBe(true);
  await act(async()=>old.resolve(result('channel_list',[channels],1))); expect(screen.queryByRole('button',{name:'주차장 선택'})).toBeNull(); expect(screen.getByText('Model-A')).toBeVisible();
  vi.mocked(api.channelList).mockResolvedValueOnce(result('channel_list',[channels],1)); fireEvent.click(screen.getByRole('button',{name:'채널 목록 조회'})); await waitFor(()=>expect(screen.getByRole('button',{name:'채널 목록 조회'})).toBeEnabled()); expect(screen.queryByRole('button',{name:'주차장 선택'})).toBeNull();
});
it('denied access aborts other requests and authority recovery is explicit and does not renew TVT tokens', async () => {
  const requery=vi.fn(async()=>bootstrap); render(<DirectoryPage {...props({requery})} />); choose(); await loadDevices(); fireEvent.click(screen.getByRole('button',{name:'입구 카메라 선택'}));
  const other=deferred(); vi.mocked(api.channelList).mockReturnValueOnce(other.promise); fireEvent.click(screen.getByRole('button',{name:'채널 목록 조회'})); const signal=vi.mocked(api.channelList).mock.calls[0][2];
  vi.mocked(api.deviceDetail).mockRejectedValueOnce(new client.DirectoryError(401,'TOKEN_EXPIRED')); fireEvent.click(screen.getByRole('button',{name:'기기 상세 조회'})); await screen.findByRole('link',{name:'TVT 계정 다시 로그인'}); expect(signal.aborted).toBe(true); expect(requery).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'현재 계정 다시 확인'})); await waitFor(()=>expect(requery).toHaveBeenCalledOnce());
  await act(async()=>other.resolve(result('channel_list',[channels]))); expect(screen.queryByRole('button',{name:'주차장 선택'})).toBeNull(); expect(localStorage.length+sessionStorage.length).toBe(0);
});
it.each(['sent','received'] as const)('preserves %s share snapshots on refresh uncertainty without merging the directions', async direction => {
  const label=direction==='sent'?'보낸 공유':'받은 공유'; const value=direction==='sent'?'보낸 카메라':'받은 카메라'; const method=direction==='sent'?'sentShares':'receivedShares';
  render(<DirectoryPage {...props()} />); choose(); fireEvent.click(screen.getByRole('button',{name:label})); fireEvent.click(screen.getByRole('button',{name:`${label} 조회`})); await screen.findByText(value);
  vi.mocked(api[method]).mockRejectedValueOnce(new client.DirectoryError(504,'UNKNOWN_OUTCOME')); fireEvent.click(screen.getByRole('button',{name:`${label} 새로고침`})); await screen.findByRole('alert'); expect(screen.getByText(value)).toBeVisible(); expect(api[method]).toHaveBeenCalledTimes(2);
});

const denialCases = [['AUTH_REQUIRED',401,'TVT 계정 다시 로그인'],['TOKEN_EXPIRED',401,'TVT 계정 다시 로그인'],['unauthenticated',401,'웹 다시 로그인'],['forbidden',403,'내 매장으로 이동'],['consent_required',409,'약관 확인']] as const;
const callCount = () => Object.values(api).reduce((count,method)=>count+vi.mocked(method).mock.calls.length,0);
async function denyAfterSnapshot(code: string,status: number,label: string) {
  choose(); await loadDevices(); vi.mocked(api.deviceList).mockRejectedValueOnce(new client.DirectoryError(status,code)); fireEvent.click(screen.getByRole('button',{name:'기기 새로고침'})); await screen.findByRole('link',{name:label});
  expect(callCount()).toBe(2); expect(screen.queryByRole('button',{name:'입구 카메라 선택'})).toBeNull();
}
it.each(denialCases)('retains %s denial across tab switch/back under unchanged Bootstrap with zero further reads', async (code,status,label) => {
  render(<DirectoryPage {...props()} />); await denyAfterSnapshot(code,status,label);
  fireEvent.click(screen.getByRole('button',{name:'보낸 공유'}));
  const query=screen.queryByRole('button',{name:'보낸 공유 조회'}); if(query) await act(async()=>fireEvent.click(query));
  expect(callCount()).toBe(2); expect(screen.getByRole('link',{name:label})).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'기기'}));
  expect(screen.queryByRole('button',{name:'기기 목록 조회'})).toBeNull(); expect(screen.getByRole('link',{name:label})).toBeVisible(); expect(callCount()).toBe(2);
});
it.each(denialCases)('retains %s denial on deselect/reselect of the same identity under unchanged Bootstrap', async (code,status,label) => {
  render(<DirectoryPage {...props()} />); await denyAfterSnapshot(code,status,label); choose(''); choose();
  const query=screen.queryByRole('button',{name:'기기 목록 조회'}); if(query) await act(async()=>fireEvent.click(query));
  expect(callCount()).toBe(2); expect(screen.getByRole('link',{name:label})).toBeVisible(); expect(screen.queryByRole('button',{name:'입구 카메라 선택'})).toBeNull();
});
it.each([['AUTH_REQUIRED',401,'TVT 계정 다시 로그인'],['TOKEN_EXPIRED',401,'TVT 계정 다시 로그인'],['DIRECTORY_REAUTHENTICATION_REQUIRED',401,'TVT 계정 다시 로그인'],['ACCOUNT_DENIED',404,'TVT 계정 다시 로그인'],['not_found',404,'TVT 계정 다시 로그인'],['FORBIDDEN',403,'내 매장으로 이동']] as const)('limits identity %s denial to its exact identity and retains it when returning from another identity', async (code,status,label) => {
  render(<DirectoryPage {...props()} />); await denyAfterSnapshot(code,status,label);
  choose(otherIdentity); expect(screen.queryByRole('link',{name:label})).toBeNull(); expect(api.deviceList).toHaveBeenCalledTimes(2);
  vi.mocked(api.deviceList).mockResolvedValueOnce(result('device_list',[device('다른 계정 카메라')],1,{identity_id:otherIdentity,brand:'AnotherBrand',region:'JP'}));
  fireEvent.click(screen.getByRole('button',{name:'기기 목록 조회'})); await screen.findByRole('button',{name:'다른 계정 카메라 선택'});
  expect(api.deviceList).toHaveBeenLastCalledWith(tenant,{identity_id:otherIdentity,brand:'AnotherBrand',region:'JP',page_num:0,page_size:1000},expect.any(AbortSignal));
  choose(); expect(screen.getByRole('link',{name:label})).toBeVisible(); expect(screen.queryByRole('button',{name:'기기 목록 조회'})).toBeNull(); expect(callCount()).toBe(3);
});
it.each(denialCases.slice(2))('retains global %s denial across different identity selection and explicit unchanged authority requery', async (code,status,label) => {
  const requery=vi.fn(async()=>bootstrap); render(<DirectoryPage {...props({requery})} />); await denyAfterSnapshot(code,status,label); choose(otherIdentity);
  const query=screen.queryByRole('button',{name:'기기 목록 조회'}); if(query) await act(async()=>fireEvent.click(query));
  expect(callCount()).toBe(2); expect(screen.getByRole('link',{name:label})).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'현재 계정 다시 확인'})); await waitFor(()=>expect(requery).toHaveBeenCalledOnce());
  expect(screen.getByRole('link',{name:label})).toBeVisible(); expect(screen.queryByRole('button',{name:'기기 목록 조회'})).toBeNull(); expect(callCount()).toBe(2);
});
it.each(['actor','tenant','csrf','consentVersion'] as const)('admits explicit new authority context %s after a denial while keeping its directory empty until requested', async kind => {
  const mounted=render(<DirectoryPage {...props()} />); await denyAfterSnapshot('unauthenticated',401,'웹 다시 로그인');
  const next=kind==='actor'?props({userId:'actor-B'}):kind==='tenant'?props({bootstrap:{...bootstrap,selected_tenant_id:'10000000-0000-4000-8000-000000000002'}}):kind==='csrf'?props({csrf:'new-authority-csrf'}):props({bootstrap:{...bootstrap,consent:{...bootstrap.consent,version:'v2'}}});
  mounted.rerender(<DirectoryPage {...next} />); expect(screen.queryByRole('link',{name:'웹 다시 로그인'})).toBeNull(); expect(screen.queryByRole('button',{name:'입구 카메라 선택'})).toBeNull(); expect(callCount()).toBe(2);
  choose(); expect(callCount()).toBe(2); await loadDevices(); expect(callCount()).toBe(3);
});
it('keeps global recovery requery busy across tabs and identity deselection without duplicate revalidation', async () => {
  let resolve!: (value: Bootstrap)=>void; const pending=new Promise<Bootstrap>(yes=>{resolve=yes;});
  const requery=vi.fn(()=>pending); render(<DirectoryPage {...props({requery})} />); await denyAfterSnapshot('forbidden',403,'내 매장으로 이동');
  fireEvent.click(screen.getByRole('button',{name:'현재 계정 다시 확인'}));
  fireEvent.click(screen.getByRole('button',{name:'받은 공유'})); choose('');
  expect(screen.getByRole('link',{name:'내 매장으로 이동'})).toBeVisible(); expect(screen.getByRole('button',{name:'현재 계정 다시 확인'})).toBeDisabled();
  choose(otherIdentity); fireEvent.click(screen.getByRole('button',{name:'현재 계정 다시 확인'})); expect(requery).toHaveBeenCalledOnce();
  await act(async()=>resolve(bootstrap)); expect(screen.getByRole('button',{name:'현재 계정 다시 확인'})).toBeEnabled(); expect(screen.queryByRole('button',{name:'받은 공유 조회'})).toBeNull(); expect(callCount()).toBe(2);
});
it.each(['success','failure'] as const)('ignores stale recovery requery %s after identity replacement and cannot unlock successor recovery', async outcome => {
  let oldResolve!: (value:Bootstrap)=>void; let oldReject!: (reason:unknown)=>void; const old=new Promise<Bootstrap>((yes,no)=>{oldResolve=yes;oldReject=no;});
  let nextResolve!: (value:Bootstrap)=>void; const next=new Promise<Bootstrap>(yes=>{nextResolve=yes;});
  const requery=vi.fn<()=>Promise<Bootstrap>>().mockReturnValueOnce(old).mockReturnValueOnce(next);
  render(<DirectoryPage {...props({requery})} />); await denyAfterSnapshot('TOKEN_EXPIRED',401,'TVT 계정 다시 로그인'); fireEvent.click(screen.getByRole('button',{name:'현재 계정 다시 확인'}));
  choose(otherIdentity); expect(screen.queryByRole('alert')).toBeNull(); choose(); fireEvent.click(screen.getByRole('button',{name:'현재 계정 다시 확인'}));
  await act(async()=>{ if(outcome==='success') oldResolve(bootstrap); else oldReject(new Error('synthetic stale recovery failure')); });
  expect(screen.getByRole('button',{name:'현재 계정 다시 확인'})).toBeDisabled(); expect(screen.queryByText(/현재 계정과 권한을 확인할 수 없습니다/)).toBeNull(); expect(callCount()).toBe(2);
  await act(async()=>nextResolve(bootstrap)); expect(screen.getByRole('button',{name:'현재 계정 다시 확인'})).toBeEnabled(); expect(screen.getByRole('link',{name:'TVT 계정 다시 로그인'})).toBeVisible();
});
