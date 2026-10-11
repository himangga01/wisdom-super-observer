import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {isValidElement,type ReactNode} from 'react';
import {resolve} from 'node:path';
import * as fs from 'node:fs';
vi.mock('server-only',()=>({}));
vi.mock('node:fs',()=>({lstatSync:vi.fn(()=>({isSymbolicLink:()=>false,size:1000})),readFileSync:vi.fn(),realpathSync:vi.fn((path:string)=>path)}));
vi.mock('../src/lib/session',()=>({ServiceError:class extends Error{constructor(readonly status:number){super('Service unavailable');}},requireSession:vi.fn(async()=>({expires_at:'2099-10-09T00:00:00Z',memberships:[{tenant_id:'10000000-0000-4000-8000-000000000001',role:'OWNER'}]})),csrfToken:vi.fn(async()=>'csrf'),apiRequest:vi.fn(async()=>new Response(JSON.stringify({items:[]})))}));
import {ownedSharedMode} from '../src/lib/tvt/owned-shared-mode';
import ConnectionsPage from '../src/app/connections/page';
import MonitoringPage from '../src/app/monitoring/page';
import {ConnectionsView} from '../src/features/connections/connections-view';
import {LiveWall} from '../src/features/monitoring/live-wall';
const context={schemaVersion:1,proofKind:'owned-local-device-native-pipeline',role:'OWNER',baseURL:'https://localhost:3543',sharedMedia:{schemaVersion:1,enabled:true,profile:{base_originals:2,main_originals:1,viewers:12,physical_slots:16,worker_process_bytes:2147483648,native_process_bytes:536870912,decoder_process_bytes:536870912,retained_host_bytes:1073741824}}};
function find(node:ReactNode,type:unknown):Record<string,unknown>|null{
  if(Array.isArray(node))return node.map(child=>find(child,type)).find(Boolean)??null;
  if(!isValidElement<{children?:ReactNode}>(node))return null;
  return node.type===type?node.props:find(node.props.children,type);
}
beforeEach(()=>{
  vi.stubEnv('WSO_TEST_LOCAL_MEDIA_SHARED','1');
  vi.stubEnv('WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE',resolve(process.cwd(),'auth-state/local-devices-00000000000000000000000000000001/context.json'));
  vi.mocked(fs.readFileSync).mockReturnValue(JSON.stringify(context));
});
afterEach(()=>{vi.unstubAllEnvs();vi.clearAllMocks();});
it.each([[ConnectionsPage,ConnectionsView],[MonitoringPage,LiveWall]] as const)('uses the same validated server profile for %s',async(page,view)=>{
  expect(find(await page({searchParams:Promise.resolve({})}),view)?.sharedMode).toBe(true);
  vi.stubEnv('WSO_TEST_LOCAL_MEDIA_SHARED',undefined);
  expect(find(await page({searchParams:Promise.resolve({})}),view)?.sharedMode).toBe(false);
});
it('fails closed for a malformed mode, absent context, foreign path and wrong shared profile',()=>{
  vi.stubEnv('WSO_TEST_LOCAL_MEDIA_SHARED','true');expect(()=>ownedSharedMode()).toThrow('Service unavailable');
  vi.stubEnv('WSO_TEST_LOCAL_MEDIA_SHARED','1');vi.stubEnv('WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE',undefined);expect(()=>ownedSharedMode()).toThrow('Service unavailable');
  vi.stubEnv('WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE',resolve(process.cwd(),'foreign/context.json'));expect(()=>ownedSharedMode()).toThrow('Service unavailable');
  vi.stubEnv('WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE',resolve(process.cwd(),'auth-state/local-devices-00000000000000000000000000000001/context.json'));
  vi.mocked(fs.readFileSync).mockReturnValue(JSON.stringify({...context,sharedMedia:{...context.sharedMedia,profile:{...context.sharedMedia.profile,viewers:13}}}));expect(()=>ownedSharedMode()).toThrow('Service unavailable');
});
