import {afterEach,expect,it,vi} from 'vitest';
import {NextRequest} from 'next/server';
vi.mock('server-only',()=>({}));
import {proxyLocalWall} from '../src/lib/tvt/local-live-wall-proxy';
const origin='https://web.example';const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const env={WSO_PUBLIC_ORIGIN:origin,API_INTERNAL_ORIGIN:'https://api.example',WSO_OIDC_ISSUER:'https://issuer.example',WSO_OIDC_CLIENT_ID:'web',WSO_OIDC_CLIENT_SECRET:'inert-secret',WSO_AUTH_EXCHANGE_KEY:'a'.repeat(32),WSO_FLOW_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url')};
const wall={id:uuid(9),tenant_id:uuid(1),state:'ACTIVE',expires_at:'2099-10-06T00:00:30Z'};
const reference={id:uuid(10),wall_id:uuid(9),lease_id:uuid(6),connection_id:uuid(2),channel_id:uuid(5),direction:'FORWARD',state:'CLOSED',expires_at:'2000-01-01T00:00:00Z'};
function request(segments:string[]= [uuid(9),'heartbeat'],body:unknown={},headers:Record<string,string>={},query=`tenant_id=${uuid(1)}`,method='POST'){
  for(const [name,value]of Object.entries(env))vi.stubEnv(name,value);
  return new NextRequest(`${origin}/api/live-walls${segments.length?'/'+segments.join('/'):''}?${query}`,{method,headers:{Origin:origin,Cookie:'__Host-wso-session=session; __Host-wso-csrf=csrf','X-CSRF-Token':'csrf','Content-Type':'application/json',...headers},...(method==='GET'?{}:{body:JSON.stringify(body)})});
}
const reply=(body:unknown)=>new Response(JSON.stringify(body),{headers:{'X-Request-ID':'request-1'}});
afterEach(()=>{vi.unstubAllEnvs();vi.restoreAllMocks();});
it('wall heartbeat forwards only authenticated scope and no-store response',async()=>{
  const send=vi.fn(async()=>reply({wall,request_id:'request-1'}));const result=await proxyLocalWall(request(),[uuid(9),'heartbeat'],send);
  expect(result.status).toBe(200);expect(await result.json()).toEqual({wall,request_id:'request-1'});expect(result.headers.get('Cache-Control')).toContain('no-store');expect(result.headers.get('Vary')).toBe('Cookie');
  expect(send.mock.calls[0]).toEqual([`https://api.example/api/v1/tvt/live-walls/${uuid(9)}/heartbeat?tenant_id=${uuid(1)}`,expect.objectContaining({redirect:'error',cache:'no-store',body:'{}',headers:{Cookie:'__Host-wso-session=session',Origin:origin,'X-CSRF-Token':'csrf','Content-Type':'application/json'}})]);
});
it.each<Record<string,string>>([{Cookie:''},{Origin:'https://foreign.example'},{'X-CSRF-Token':'wrong'}])('fences wall session/CSRF/origin before dispatch',async headers=>{
  const send=vi.fn();const result=await proxyLocalWall(request(undefined,{},headers),[uuid(9),'heartbeat'],send);expect([401,403]).toContain(result.status);expect(send).not.toHaveBeenCalled();
});
it.each([{segments:['unknown']},{segments:[uuid(9),'focus-reservations']},{segments:[uuid(9),'focus-reservations',uuid(10),'unknown']},{segments:[uuid(9),'heartbeat','extra']}])('allowlists route before reading invalid bodies',async({segments})=>{
  const send=vi.fn();const result=await proxyLocalWall(request(segments,{secret:'private-marker'}),segments,send);expect(result.status).toBe(404);expect(send).not.toHaveBeenCalled();
});
it('validates exact queries, methods and control bodies',async()=>{
  const send=vi.fn();
  for(const [req,status]of [[request(undefined,{}, {},`tenant_id=${uuid(1)}&extra=1`),404],[request(undefined,{native_id:1}),422],[request(undefined,{}, {},undefined,'GET'),405]] as const){expect((await proxyLocalWall(req,[uuid(9),'heartbeat'],send)).status).toBe(status);}
  expect(send).not.toHaveBeenCalled();
});
it('test_no_native_identity_json_or_redirect',async()=>{

  for(const body of [{wall:{...wall,native_id:7},request_id:'request-1'},{wall:{...wall,id:uuid(8)},request_id:'request-1'},{wall:{...wall,tenant_id:uuid(8)},request_id:'request-1'},{wall,request_id:'wrong'}]){
    const result=await proxyLocalWall(request(),[uuid(9),'heartbeat'],async()=>reply(body));expect(result.status).toBe(503);expect(await result.text()).not.toContain('native_id');
  }
  const result=await proxyLocalWall(request(),[uuid(9),'heartbeat'],async()=>new Response(null,{status:302,headers:{Location:'https://private.example'}}));expect(result.status).toBe(503);expect(result.headers.get('Location')).toBeNull();
});
it('settlement permits expired CLOSED metadata without extending or claiming disconnect',async()=>{
  const segments=[uuid(9),'focus-reservations',uuid(10),'settle'];
  const result=await proxyLocalWall(request(segments,{outcome:'FAILED'}),segments,async()=>reply({reference,request_id:'request-1'}));expect(result.status).toBe(200);expect(await result.json()).toEqual({reference,request_id:'request-1'});
  const wrong=await proxyLocalWall(request(segments,{outcome:'CANCELLED'}),segments,async()=>reply({reference:{...reference,id:uuid(8)},request_id:'request-1'}));expect(wrong.status).toBe(503);
  const send=vi.fn();expect((await proxyLocalWall(request(segments,{outcome:'ATTACHED'}),segments,send)).status).toBe(422);expect(send).not.toHaveBeenCalled();
});
it('bounds request and streaming response bodies and hides errors',async()=>{
  const send=vi.fn();expect((await proxyLocalWall(request(undefined,{private:'x'.repeat(4096)}),[uuid(9),'heartbeat'],send)).status).toBe(422);expect(send).not.toHaveBeenCalled();
  let cancelled=false;const result=await proxyLocalWall(request(),[uuid(9),'heartbeat'],async()=>new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array(262145));},cancel(){cancelled=true;}}),{headers:{'X-Request-ID':'request-1'}}));expect(result.status).toBe(503);expect(cancelled).toBe(true);
});
it('cancels an unread reply when declared length exceeds the bound',async()=>{
  let cancelled=false;const result=await proxyLocalWall(request(),[uuid(9),'heartbeat'],async()=>new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array(1));},cancel(){cancelled=true;}}),{headers:{'X-Request-ID':'request-1','Content-Length':'262145'}}));
  expect(result.status).toBe(503);expect(cancelled).toBe(true);
});
