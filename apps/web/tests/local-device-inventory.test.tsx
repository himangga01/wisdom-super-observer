// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {LocalDeviceInventory} from '../src/features/connections/local-device-inventory';
import {localDeviceView, verifyLocalDevice} from '../src/lib/tvt/local-device-api';
const tenant='10000000-0000-4000-8000-000000000001';
const id='20000000-0000-4000-8000-000000000001';
const store='30000000-0000-4000-8000-000000000001';
const requestId='40000000-0000-4000-8000-000000000001';
const connection={id,tenant_id:tenant,kind:'TVT_DEVICE' as const,alias:'본점 녹화기',site:'본점',status:'NOT_VERIFIED' as const,last_success:null,generation:1,store_ids:[store]};
const stores=[{id:store,tenant_id:tenant,name:'본점',timezone:'Asia/Seoul',active:true}];
const view={connection_id:id,device_id:'50000000-0000-4000-8000-000000000001',store_id:store,connection_generation:1,inventory_revision:1,inventory_state:'AVAILABLE',observed_at:'2026-10-04T00:00:00Z',channels:[{id:'60000000-0000-4000-8000-000000000001',ordinal:7,label:'Channel 7'}],request_id:requestId};
const reply=(body:unknown=view)=>new Response(JSON.stringify(body),{headers:{'X-Request-ID':requestId,'Content-Type':'application/json'}});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('rejects foreign scope, generation, unsafe counters and private fields',()=>{
  const binding={connectionId:id,storeId:store,generation:1};
  expect(localDeviceView(view,binding).channels[0].ordinal).toBe(7);
  for(const extra of [{connection_id:store},{store_id:id},{connection_generation:2},{inventory_revision:2**53},{serial:'private-marker'},{channels:[{...view.channels[0],label:'Channel 1'}]}]) expect(()=>localDeviceView({...view,...extra},binding)).toThrow();
});
it('sends only scoped selectors once and checks response correlation',async()=>{
  const send=vi.fn(async()=>reply());vi.stubGlobal('fetch',send);
  await verifyLocalDevice(tenant,connection,store,'csrf',new AbortController().signal);
  expect(send).toHaveBeenCalledTimes(1);
  const [url,options]=send.mock.calls[0] as unknown as [string,RequestInit];
  expect(url).toBe(`/api/local-devices/${id}/verify?tenant_id=${tenant}`);
  expect(JSON.parse(options.body as string)).toEqual({store_id:store,expected_generation:1});
  expect(options.redirect).toBe('error');
  send.mockImplementation(async()=>new Response(JSON.stringify(view),{headers:{'X-Request-ID':'wrong'}}));
  await expect(verifyLocalDevice(tenant,connection,store,'csrf',new AbortController().signal)).rejects.toThrow();
  expect(send).toHaveBeenCalledTimes(2);
});
it('shows verified inventory without claiming live video or changing connection state',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>reply()));
  render(<LocalDeviceInventory tenantId={tenant} connection={connection} stores={stores} csrf="csrf" disabled={false}/>);
  fireEvent.click(screen.getByRole('button',{name:'기기 확인'}));
  expect(await screen.findByText('7번 채널')).toBeVisible();
  expect(screen.getByText('장치 정보 확인됨 · 1개 채널')).toBeVisible();
  expect(screen.queryByRole('button',{name:/재생|라이브/})).toBeNull();
  expect(connection.status).toBe('NOT_VERIFIED');
});
it('requires an active linked store and never calls the device without one',()=>{
  const send=vi.fn();vi.stubGlobal('fetch',send);
  render(<LocalDeviceInventory tenantId={tenant} connection={{...connection,store_ids:[]}} stores={stores} csrf="csrf" disabled={false}/>);
  expect(screen.getByRole('button',{name:'기기 확인'})).toBeDisabled();
  expect(screen.getByText(/연결 수정에서 매장을 지정/)).toBeVisible();
  expect(send).not.toHaveBeenCalled();
});
it('discards an old completion after the connection generation changes',async()=>{
  let finish!:(response:Response)=>void;
  vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve;})));
  const rendered=render(<LocalDeviceInventory tenantId={tenant} connection={connection} stores={stores} csrf="csrf" disabled={false}/>);
  fireEvent.click(screen.getByRole('button',{name:'기기 확인'}));
  rendered.rerender(<LocalDeviceInventory tenantId={tenant} connection={{...connection,generation:2}} stores={stores} csrf="csrf" disabled={false}/>);
  finish(reply());
  await waitFor(()=>expect(screen.getByRole('button',{name:'기기 확인'})).toBeEnabled());
  expect(screen.queryByText('7번 채널')).toBeNull();
});
