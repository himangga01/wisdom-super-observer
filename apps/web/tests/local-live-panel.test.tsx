// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {LocalLivePanel} from '../src/features/connections/local-live-panel';
import {localDeviceView} from '../src/lib/tvt/local-device-api';
const tenant='10000000-0000-4000-8000-000000000001';
const connection='20000000-0000-4000-8000-000000000001';
const store='30000000-0000-4000-8000-000000000001';
const inventory=localDeviceView({connection_id:connection,device_id:'50000000-0000-4000-8000-000000000001',store_id:store,connection_generation:1,inventory_revision:1,inventory_state:'AVAILABLE',observed_at:'2026-10-04T00:00:00Z',channels:[{id:'60000000-0000-4000-8000-000000000001',ordinal:7,label:'Channel 7'}],request_id:'40000000-0000-4000-8000-000000000001'},{connectionId:connection,storeId:store,generation:1});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
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
