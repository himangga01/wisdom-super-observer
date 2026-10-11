// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import type {LocalDeviceView} from '../src/lib/tvt/local-device-api';
import type {LiveWallPlayerFactory} from '../src/features/monitoring/live-wall';
const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const inventory:LocalDeviceView={connection_id:uuid(2),store_id:uuid(3),device_id:uuid(4),connection_generation:1,inventory_revision:1,inventory_state:'AVAILABLE',observed_at:'2026-10-09T00:00:00Z',channels:[{id:uuid(5),ordinal:1,label:'Channel 1'}],request_id:'inventory'};
const wall=(state:string,tenant=uuid(1))=>({wall:{id:uuid(9),tenant_id:tenant,state,expires_at:'2099-10-09T00:00:00Z'},request_id:'wall'});
const reply=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'X-Request-ID':'wall'}});
afterEach(async()=>{await act(async()=>cleanup());vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
it.each(['upstream failure','deadline','foreign scope','unknown active state'] as const)('retains the original STOPPING fence after %s readback across cancellation and remount',async(outcome)=>{
  // Each failure owns a fresh client module so an intentionally retained rejected
  // fence from another case cannot prevent this case from creating its original.
  vi.resetModules();const {SharedLocalLivePanel}=await import('../src/features/connections/shared-local-live-panel');
  const expirations:AbortController[]=[];
  if(outcome==='deadline')vi.spyOn(AbortSignal,'timeout').mockImplementation(()=>{const controller=new AbortController();expirations.push(controller);return controller.signal;});
  const send=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    if(String(input).includes('/stop?'))return reply(wall('STOPPING'));
    if(init?.method==='GET'){
      if(outcome==='deadline')return await new Promise<Response>(()=>{});
      if(outcome==='upstream failure')return reply({},503);
      return reply(wall(outcome==='unknown active state'?'ACTIVE':'CLOSED',outcome==='foreign scope'?uuid(8):uuid(1)));
    }
    return reply(wall('ACTIVE'));
  });vi.stubGlobal('fetch',send);
  let starts=0;
  const createPlayer:LiveWallPlayerFactory=(_binding,_csrf,events)=>({closed:false,currentLeaseId:null,failureCode:null,failureStatus:null,async start(){starts++;events.state('connecting');},async stop(){events.state('stopped');},async presented(){}});
  const props={tenantId:uuid(1),inventory,csrf:'csrf',disabled:false,createPlayer};
  const view=render(<SharedLocalLivePanel {...props}/>);
  fireEvent.change(screen.getByRole('combobox',{name:'영상 화질'}),{target:{value:'sub'}});fireEvent.click(screen.getByRole('button',{name:'실시간 재생'}));await waitFor(()=>expect(starts).toBe(1));
  fireEvent.click(screen.getByRole('button',{name:'영상 중지'}));await waitFor(()=>expect(send.mock.calls.some(call=>call[1]?.method==='GET')).toBe(true));
  if(outcome==='deadline'){
    view.unmount();render(<SharedLocalLivePanel {...props} csrf="new-csrf"/>);fireEvent.click(screen.getByRole('button',{name:'실시간 재생'}));
    // Cancellation must not release or retarget the pending original readback.
    fireEvent.click(screen.getByRole('button',{name:'영상 중지'}));await act(async()=>expirations.forEach(controller=>controller.abort()));
  }else{await act(async()=>{});view.unmount();render(<SharedLocalLivePanel {...props} csrf="new-csrf"/>);}
  await waitFor(()=>expect(screen.getByRole('button',{name:'실시간 재생'})).toBeEnabled());fireEvent.click(screen.getByRole('button',{name:'실시간 재생'}));
  await screen.findByText('영상을 연결하지 못했습니다. 채널을 확인한 뒤 다시 시도하세요.');
  expect(starts).toBe(1);expect(send.mock.calls.filter(call=>call[1]?.method==='POST'&&!String(call[0]).includes('/stop?'))).toHaveLength(1);
  const reads=send.mock.calls.filter(call=>call[1]?.method==='GET');expect(reads).toHaveLength(1);expect(String(reads[0][0])).toBe(`/api/live-walls/${uuid(9)}?tenant_id=${uuid(1)}`);
});

it('keeps repeated STOPPING readback fenced and releases only after a later exact CLOSED view',async()=>{
  vi.resetModules();const {SharedLocalLivePanel}=await import('../src/features/connections/shared-local-live-panel');vi.useFakeTimers();
  let reads=0,starts=0;
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>String(input).includes('/stop?')?reply(wall('STOPPING')):init?.method==='GET'?reply(wall(++reads===1?'STOPPING':'CLOSED')):reply(wall('ACTIVE')));
  const createPlayer:LiveWallPlayerFactory=(_binding,_csrf,events)=>({closed:false,currentLeaseId:null,failureCode:null,failureStatus:null,async start(){starts++;events.state('connecting');},async stop(){events.state('stopped');},async presented(){}});
  const props={tenantId:uuid(1),inventory,csrf:'csrf',disabled:false,createPlayer};const view=render(<SharedLocalLivePanel {...props}/>);
  await act(async()=>fireEvent.click(screen.getByRole('button',{name:'실시간 재생'})));expect(starts).toBe(1);
  await act(async()=>fireEvent.click(screen.getByRole('button',{name:'영상 중지'})));expect(reads).toBe(1);
  view.unmount();render(<SharedLocalLivePanel {...props} inventory={{...inventory,inventory_revision:2}}/>);await act(async()=>fireEvent.click(screen.getByRole('button',{name:'실시간 재생'})));
  await act(async()=>vi.advanceTimersByTimeAsync(499));expect(starts).toBe(1);expect(reads).toBe(1);
  await act(async()=>vi.advanceTimersByTimeAsync(1));expect(reads).toBe(2);expect(starts).toBe(2);
});
