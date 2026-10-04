import {afterEach,expect,it,vi} from 'vitest';
import {NextRequest} from 'next/server';
vi.mock('server-only',()=>({}));
import {proxyLocalLive} from '../src/lib/tvt/local-live-proxy';
const origin='https://web.example';const uuid=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const env={WSO_PUBLIC_ORIGIN:origin,API_INTERNAL_ORIGIN:'https://api.example',WSO_OIDC_ISSUER:'https://issuer.example',WSO_OIDC_CLIENT_ID:'web',WSO_OIDC_CLIENT_SECRET:'inert-secret',WSO_AUTH_EXCHANGE_KEY:'a'.repeat(32),WSO_FLOW_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url')};
function setup(){for(const [name,value]of Object.entries(env))vi.stubEnv(name,value);}
function request(headers:Record<string,string>={},body:unknown={}){return new NextRequest(`${origin}/api/live-sessions/${uuid(1)}/stop?tenant_id=${uuid(2)}`,{method:'POST',headers:{Origin:origin,Cookie:'__Host-wso-session=session; __Host-wso-csrf=csrf','X-CSRF-Token':'csrf','Content-Type':'application/json',...headers},body:JSON.stringify(body)});}
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});
it.each<Record<string,string>>([{Cookie:''},{Origin:'https://foreign.example'},{'X-CSRF-Token':'wrong'}])('fences auth before media dispatch',async headers=>{
  setup();const send=vi.fn();expect([401,403]).toContain((await proxyLocalLive(request(headers),[uuid(1),'stop'],send)).status);expect(send).not.toHaveBeenCalled();
});
it('rejects arbitrary connection selectors and secrets on control routes',async()=>{
  setup();const send=vi.fn();const result=await proxyLocalLive(request({},{serial:'private-marker'}),[uuid(1),'stop'],send);expect(result.status).toBe(422);expect(send).not.toHaveBeenCalled();expect(await result.text()).not.toContain('private-marker');
});
it('redacts upstream failure and keeps strict no-store without retry',async()=>{
  setup();const send=vi.fn(async()=>new Response('private-marker',{status:502}));const result=await proxyLocalLive(request(),[uuid(1),'stop'],send);expect(result.status).toBe(502);expect(result.headers.get('Cache-Control')).toContain('no-store');expect(await result.text()).not.toContain('private-marker');expect(send).toHaveBeenCalledTimes(1);
});
