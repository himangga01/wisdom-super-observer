import {afterEach,expect,it,vi} from 'vitest';
import {NextRequest} from 'next/server';
vi.mock('server-only',()=>({}));
import {proxyLocalLive} from '../src/lib/tvt/local-live-proxy';
const origin='https://web.example';const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const env={WSO_PUBLIC_ORIGIN:origin,API_INTERNAL_ORIGIN:'https://api.example',WSO_OIDC_ISSUER:'https://issuer.example',WSO_OIDC_CLIENT_ID:'web',WSO_OIDC_CLIENT_SECRET:'inert-secret',WSO_AUTH_EXCHANGE_KEY:'a'.repeat(32),WSO_FLOW_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url')};
function setup(){for(const [name,value]of Object.entries(env))vi.stubEnv(name,value);}
function request(headers:Record<string,string>={},body:unknown={}){return new NextRequest(`${origin}/api/live-sessions/${uuid(1)}/stop?tenant_id=${uuid(2)}`,{method:'POST',headers:{Origin:origin,Cookie:'__Host-wso-session=session; __Host-wso-csrf=csrf','X-CSRF-Token':'csrf','Content-Type':'application/json',...headers},body:JSON.stringify(body)});}
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
it('accepts explicit focus reservation path and correlates source lease and direction',async()=>{
  setup();const reference={id:uuid(10),wall_id:uuid(9),lease_id:uuid(1),connection_id:uuid(3),channel_id:uuid(4),direction:'FORWARD',state:'PENDING',expires_at:'2099-10-06T00:00:30Z'};
  const req=()=>new NextRequest(`${origin}/api/live-sessions/${uuid(1)}/focus-reservations?tenant_id=${uuid(2)}`,{method:'POST',headers:{Origin:origin,Cookie:'__Host-wso-session=session; __Host-wso-csrf=csrf','X-CSRF-Token':'csrf','Content-Type':'application/json'},body:'{"direction":"FORWARD"}'});
  const send=vi.fn(async()=>new Response(JSON.stringify({reference,request_id:'request-1'}),{headers:{'X-Request-ID':'request-1'}}));
  const result=await proxyLocalLive(req(),[uuid(1),'focus-reservations'],send);expect(result.status).toBe(200);expect(await result.json()).toEqual({reference,request_id:'request-1'});
  for(const bad of [{...reference,lease_id:uuid(8)},{...reference,direction:'RETURN'},{...reference,native_id:1}]){
    send.mockImplementation(async()=>new Response(JSON.stringify({reference:bad,request_id:'request-1'}),{headers:{'X-Request-ID':'request-1'}}));expect((await proxyLocalLive(req(),[uuid(1),'focus-reservations'],send)).status).toBe(503);
  }
});
it.each<{name:string;headers:Record<string,string>}>([
  {name:'missing correlation header',headers:{}},
  {name:'oversized declared content length',headers:{'X-Request-ID':'request-1','Content-Length':'262145'}},
])('cancels the exact unread focus reply on $name',async({headers})=>{
  setup();let cancelled=false;
  const upstream=new Response(new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new Uint8Array(1));},cancel(){cancelled=true;}}),{headers});
  const req=new NextRequest(`${origin}/api/live-sessions/${uuid(1)}/focus-reservations?tenant_id=${uuid(2)}`,{method:'POST',headers:{Origin:origin,Cookie:'__Host-wso-session=session; __Host-wso-csrf=csrf','X-CSRF-Token':'csrf','Content-Type':'application/json'},body:'{"direction":"FORWARD"}'});
  try{
    const result=await proxyLocalLive(req,[uuid(1),'focus-reservations'],async()=>upstream);
    expect(result.status).toBe(503);expect(result.headers.get('Cache-Control')).toContain('no-store');expect(result.headers.get('Vary')).toBe('Cookie');
    expect((await result.json()).error.code).toBe('LOCAL_DEVICE_UNAVAILABLE');expect(cancelled).toBe(true);
  }finally{await upstream.body?.cancel();}
});
it.each<Record<string,string>>([{Cookie:''},{Origin:'https://foreign.example'},{'X-CSRF-Token':'wrong'}])('fences auth before media dispatch',async headers=>{
  setup();const send=vi.fn();expect([401,403]).toContain((await proxyLocalLive(request(headers),[uuid(1),'stop'],send)).status);expect(send).not.toHaveBeenCalled();
});
it('rejects arbitrary connection selectors and secrets on control routes',async()=>{
  setup();const send=vi.fn();const result=await proxyLocalLive(request({},{serial:'private-marker'}),[uuid(1),'stop'],send);expect(result.status).toBe(422);expect(send).not.toHaveBeenCalled();expect(await result.text()).not.toContain('private-marker');
});
it('redacts upstream failure and keeps strict no-store without retry',async()=>{
  setup();const send=vi.fn(async()=>new Response('private-marker',{status:502}));const result=await proxyLocalLive(request(),[uuid(1),'stop'],send);expect(result.status).toBe(502);expect(result.headers.get('Cache-Control')).toContain('no-store');expect(await result.text()).not.toContain('private-marker');expect(send).toHaveBeenCalledTimes(1);
});

it.each([
  ['LOCAL_DEVICE_NO_SIGNAL',504],['LOCAL_DEVICE_BUSY',429],
  ['LOCAL_DEVICE_UPSTREAM_REJECTED',502],['LOCAL_DEVICE_DENIED',404],
  ['LOCAL_DEVICE_DEADLINE_EXCEEDED',504],
])('forwards the known %s code with its matching status and redacts upstream text',async(code,status)=>{
  setup();const send=vi.fn(async()=>new Response(JSON.stringify({error:{code,message:'private-marker'},request_id:'upstream-1'}),{status:status as number}));
  const result=await proxyLocalLive(request(),[uuid(1),'stop'],send);
  expect(result.status).toBe(status);expect((await result.json()).error.code).toBe(code);
  expect(send).toHaveBeenCalledTimes(1);expect(result.headers.get('Cache-Control')).toContain('no-store');
});
it.each([
  {error:{code:'UNKNOWN',message:'secret'},request_id:'upstream-1'},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'secret'},request_id:'upstream-1',private:'secret'},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'secret',private:'secret'},request_id:'upstream-1'},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'secret'}},
  {error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'x'.repeat(4096)},request_id:'upstream-1'},
])('masks unknown, malformed and oversized upstream codes',async payload=>{
  setup();const result=await proxyLocalLive(request(),[uuid(1),'stop'],async()=>new Response(JSON.stringify(payload),{status:504}));
  expect(result.status).toBe(504);expect((await result.json()).error.code).toBe('LOCAL_DEVICE_UNAVAILABLE');
});
it('masks a known code paired with the wrong HTTP status',async()=>{
  setup();const result=await proxyLocalLive(request(),[uuid(1),'stop'],async()=>new Response(JSON.stringify({error:{code:'LOCAL_DEVICE_NO_SIGNAL',message:'private-marker'},request_id:'upstream-1'}),{status:429}));
  expect(result.status).toBe(429);expect((await result.json()).error.code).toBe('LOCAL_DEVICE_UNAVAILABLE');
});
it('bounds streaming failures without trusting a content-length header',async()=>{
  setup();let cancelled=false;
  const body=new ReadableStream<Uint8Array>({start(controller){controller.enqueue(new TextEncoder().encode(' '.repeat(4097)));},cancel(){cancelled=true;}});
  const result=await proxyLocalLive(request(),[uuid(1),'stop'],async()=>new Response(body,{status:504}));
  expect((await result.json()).error.code).toBe('LOCAL_DEVICE_UNAVAILABLE');expect(cancelled).toBe(true);
});
