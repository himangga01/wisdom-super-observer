import {afterEach,expect,it,vi} from 'vitest';
import {NextRequest} from 'next/server';
import {proxyLocalDevice} from '../src/lib/tvt/local-device-proxy';
const tenant='10000000-0000-4000-8000-000000000001',id='20000000-0000-4000-8000-000000000001',store='30000000-0000-4000-8000-000000000001',rid='40000000-0000-4000-8000-000000000001';
const config={WSO_PUBLIC_ORIGIN:'https://app.example.com',WSO_OIDC_ISSUER:'https://id.example.com',WSO_OIDC_CLIENT_ID:'web',WSO_OIDC_CLIENT_SECRET:'secret',WSO_AUTH_EXCHANGE_KEY:'x'.repeat(32),WSO_FLOW_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url'),API_INTERNAL_ORIGIN:'http://127.0.0.1:8100'};
const view={connection_id:id,device_id:'50000000-0000-4000-8000-000000000001',store_id:store,connection_generation:1,inventory_revision:1,inventory_state:'AVAILABLE',observed_at:'2026-10-04T00:00:00Z',channels:[],request_id:rid};
function request(body:unknown={store_id:store,expected_generation:1},headers:Record<string,string>={}){return new NextRequest(`${config.WSO_PUBLIC_ORIGIN}/api/local-devices/${id}/verify?tenant_id=${tenant}`,{method:'POST',headers:{Origin:config.WSO_PUBLIC_ORIGIN,Cookie:'__Host-wso-session=opaque; __Host-wso-csrf=correct','X-CSRF-Token':'correct','Content-Type':'application/json',...headers},body:JSON.stringify(body)});}
function setup(){for(const [k,v] of Object.entries(config))vi.stubEnv(k,v);}
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
it('forwards only selectors and protected auth, returning correlated private-cache response',async()=>{
  setup();const send=vi.fn(async()=>new Response(JSON.stringify(view),{headers:{'X-Request-ID':rid}}));
  const result=await proxyLocalDevice(request(),[id,'verify'],send);
  expect(result.status).toBe(200);expect(await result.json()).toEqual(view);expect(result.headers.get('Cache-Control')).toContain('no-store');expect(result.headers.get('Vary')).toBe('Cookie');
  expect(send).toHaveBeenCalledTimes(1);const [url,options]=send.mock.calls[0] as unknown as [string,RequestInit];
  expect(url).toBe(`${config.API_INTERNAL_ORIGIN}/api/v1/tvt/local-devices/${id}/verify?tenant_id=${tenant}`);expect(JSON.parse(options.body as string)).toEqual({store_id:store,expected_generation:1});
});
it.each<Record<string,string>>([{Cookie:''},{Origin:'https://foreign.example'},{'X-CSRF-Token':'wrong'}])('denies auth/CSRF before upstream %j',async headers=>{
  setup();const send=vi.fn();const result=await proxyLocalDevice(request(undefined,headers),[id,'verify'],send);expect([401,403]).toContain(result.status);expect(send).not.toHaveBeenCalled();
});
it.each([{store_id:store,expected_generation:1,serial:'PRIVATE-MARKER'},{store_id:store,expected_generation:2**53}])('rejects private and unsafe input locally',async body=>{
  setup();const send=vi.fn();const response=await proxyLocalDevice(request(body),[id,'verify'],send);expect(response.status).toBe(422);expect(await response.text()).not.toContain('PRIVATE-MARKER');expect(send).not.toHaveBeenCalled();
});
it.each([{...view,store_id:id},{...view,connection_generation:2},{...view,password:'PRIVATE-MARKER'},{...view,request_id:'wrong'}])('rejects wrong scope or private upstream data',async body=>{
  setup();const result=await proxyLocalDevice(request(),[id,'verify'],async()=>new Response(JSON.stringify(body),{headers:{'X-Request-ID':rid}}));expect(result.status).toBe(503);expect(await result.text()).not.toContain('PRIVATE-MARKER');
});
it('discards upstream exception content and does not retry failures',async()=>{
  setup();const send=vi.fn(async()=>new Response('PRIVATE-MARKER',{status:502}));const result=await proxyLocalDevice(request(),[id,'verify'],send);expect(result.status).toBe(502);expect(await result.text()).not.toContain('PRIVATE-MARKER');expect(send).toHaveBeenCalledTimes(1);
});
it('bounds large upstream streams and cancels their reader',async()=>{
  setup();const cancel=vi.fn();let sent=false;
  const stream=new ReadableStream({pull(controller){if(!sent){sent=true;controller.enqueue(new Uint8Array(1048577));}},cancel});
  const result=await proxyLocalDevice(request(),[id,'verify'],async()=>new Response(stream,{headers:{'X-Request-ID':rid}}));
  expect(result.status).toBe(503);expect(cancel).toHaveBeenCalled();
});
it('abandons a pending fetch when the original request is cancelled',async()=>{
  setup();const controller=new AbortController();let started!:(value?:unknown)=>void;const called=new Promise(resolve=>{started=resolve;});
  const send=vi.fn((_url:RequestInfo|URL,options?:RequestInit)=>{started();expect(options?.signal).toBeDefined();return new Promise<Response>(()=>{});});
  const pending=proxyLocalDevice(new NextRequest(request(),{signal:controller.signal}),[id,'verify'],send);
  await called;controller.abort();const result=await pending;
  expect(result.status).toBe(504);expect(send).toHaveBeenCalledTimes(1);
});
it('reads a saved inventory with exact store scope and no credential body',async()=>{
  setup();const read=new NextRequest(`${config.WSO_PUBLIC_ORIGIN}/api/local-devices/${id}/channels?tenant_id=${tenant}&store_id=${store}`,{headers:{Cookie:'__Host-wso-session=opaque'}});
  const send=vi.fn(async()=>new Response(JSON.stringify(view),{headers:{'X-Request-ID':rid}}));
  const result=await proxyLocalDevice(read,[id,'channels'],send);
  expect(result.status).toBe(200);const [,options]=send.mock.calls[0] as unknown as [string,RequestInit];expect(options.method).toBe('GET');expect(options.body).toBeUndefined();
});
it('rejects foreign or duplicate devices in a store list',async()=>{
  setup();for(const list of [[view,{...view,store_id:id}],[view,view]]){
    const read=new NextRequest(`${config.WSO_PUBLIC_ORIGIN}/api/local-devices?tenant_id=${tenant}&store_id=${store}`,{headers:{Cookie:'__Host-wso-session=opaque'}});
    const result=await proxyLocalDevice(read,[],async()=>new Response(JSON.stringify(list),{headers:{'X-Request-ID':rid}}));expect(result.status).toBe(503);
  }
});
it('rejects unexpected routes and query selectors before upstream',async()=>{
  setup();const send=vi.fn();const extra=new NextRequest(`${config.WSO_PUBLIC_ORIGIN}/api/local-devices?tenant_id=${tenant}&store_id=${store}&serial=PRIVATE-MARKER`,{headers:{Cookie:'__Host-wso-session=opaque'}});
  expect((await proxyLocalDevice(extra,[],send)).status).toBe(404);
  expect((await proxyLocalDevice(request(),[id,'delete'],send)).status).toBe(404);expect(send).not.toHaveBeenCalled();
});
