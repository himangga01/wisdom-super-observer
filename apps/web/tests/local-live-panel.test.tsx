// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {LocalLivePanel} from '../src/features/connections/local-live-panel';
import {localDeviceView} from '../src/lib/tvt/local-device-api';
const tenant='10000000-0000-4000-8000-000000000001';
const connection='20000000-0000-4000-8000-000000000001';
const store='30000000-0000-4000-8000-000000000001';
const inventory=localDeviceView({connection_id:connection,device_id:'50000000-0000-4000-8000-000000000001',store_id:store,connection_generation:1,inventory_revision:1,inventory_state:'AVAILABLE',observed_at:'2026-10-04T00:00:00Z',channels:[{id:'60000000-0000-4000-8000-000000000001',ordinal:7,label:'Channel 7'}],request_id:'40000000-0000-4000-8000-000000000001'},{connectionId:connection,storeId:store,generation:1});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});
function renderPanel(){
  const send=vi.fn();vi.stubGlobal('fetch',send);
  render(<LocalLivePanel tenantId={tenant} inventory={inventory} csrf="csrf" disabled={false}/>);
  return {send,video:screen.getByLabelText<HTMLVideoElement>('CCTV 실시간 영상')};
}
it('stretches the live video to fill its 16:9 player box like the official app default',()=>{
  const {send,video}=renderPanel();
  expect(video.tagName).toBe('VIDEO');
  expect(video).toHaveClass('object-fill','aspect-video','w-full');
  expect(video).not.toHaveClass('object-contain');
  expect(send).not.toHaveBeenCalled();
});
it('keeps the live video muted, autoplaying and inline',()=>{
  const {send,video}=renderPanel();
  expect(video.muted).toBe(true);
  expect(video.autoplay).toBe(true);
  expect(video).toHaveAttribute('playsinline');
  expect(send).not.toHaveBeenCalled();
});

it.each(['main','sub'] as const)('opens the selected %s quality while defaulting to high quality',async(stream)=>{
  class Peer{close=vi.fn();addTransceiver=()=>({setCodecPreferences:vi.fn()});}
  vi.stubGlobal('RTCPeerConnection',Peer);
  vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/VP8',clockRate:90000}]})});
  const {send}=renderPanel();
  send.mockResolvedValue(new Response(null,{status:503}));
  const quality=screen.getByRole('combobox',{name:'영상 화질'});
  expect(quality).toHaveValue('main');
  expect(screen.getByRole('option',{name:'고화질'})).toBeInTheDocument();
  expect(screen.getByRole('option',{name:'저화질'})).toBeInTheDocument();
  if(stream==='sub')fireEvent.change(quality,{target:{value:'sub'}});
  fireEvent.click(screen.getByRole('button',{name:'실시간 재생'}));
  await waitFor(()=>expect(send).toHaveBeenCalledTimes(1));
  expect(JSON.parse(send.mock.calls[0][1].body).stream).toBe(stream);
});

it.each([
  ['LOCAL_DEVICE_NO_SIGNAL',504,'영상 신호 없음 · 채널에 카메라가 연결되어 있는지 확인하세요.'],
  ['LOCAL_DEVICE_UPSTREAM_REJECTED',502,'영상을 연결하지 못했습니다. 채널을 확인한 뒤 다시 시도하세요.'],
  ['LOCAL_DEVICE_DEADLINE_EXCEEDED',504,'영상을 연결하지 못했습니다. 채널을 확인한 뒤 다시 시도하세요.'],
])('shows the precise reason for %s without automatic retry',async(code,status,copy)=>{
  class Peer{close=vi.fn();addTransceiver=()=>({setCodecPreferences:vi.fn()});}
  vi.stubGlobal('RTCPeerConnection',Peer);
  vi.stubGlobal('RTCRtpReceiver',{getCapabilities:()=>({codecs:[{mimeType:'video/VP8',clockRate:90000}]})});
  const {send}=renderPanel();
  send.mockResolvedValue(new Response(JSON.stringify({error:{code,message:'private-marker'},request_id:'request-1'}),{status:status as number}));
  fireEvent.click(screen.getByRole('button',{name:'실시간 재생'}));
  expect(await screen.findByText(copy)).toBeInTheDocument();expect(send).toHaveBeenCalledTimes(1);
});
