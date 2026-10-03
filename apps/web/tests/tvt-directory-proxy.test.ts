import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxyTvt } from "../src/lib/tvt/proxy";
import { directoryClient, directoryInputSchemas, directoryJson, directoryResponse, safeDirectoryError } from "../src/lib/tvt/directory-api-client";
const tenant = "10000000-0000-4000-8000-000000000001";
const flow = "20000000-0000-4000-8000-000000000001";
const requestId = "30000000-0000-4000-8000-000000000001";
const origin = "https://app.example.test";
const config = { WSO_PUBLIC_ORIGIN: origin, WSO_OIDC_ISSUER: "https://id.example.test", WSO_OIDC_CLIENT_ID: "local-test", WSO_OIDC_CLIENT_SECRET: "local-test-secret", WSO_AUTH_EXCHANGE_KEY: "x".repeat(32), WSO_FLOW_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"), API_INTERNAL_ORIGIN: "http://127.0.0.1:8100" };
const reference = { region: "KR", brand: "SuperLivePlus", identity_id: flow };
const bodies = { "device-list": {...reference,method:"device_list",page_num:0,page_size:1000}, "channel-list": {...reference,method:"channel_list" as const,sn_list:["opaque-SN"]}, "device-detail": {...reference,method:"device_detail",sn:"opaque-SN",return_chl:false}, "channel-detail": {...reference,method:"channel_detail",sn:"opaque-SN",chl_index:7}, "sent-shares": {...reference,method:"sent_shares",page_num:0,page_size:1000,resource_types:[]}, "received-shares": {...reference,method:"received_shares",page_num:0,page_size:1000,resource_types:[]} };
const view = {...reference,method:"device_list",generation:1,request_id:requestId,records:[],total:"0",complete:null,grants_operations:false};
function request(op: string, body: unknown = bodies[op as keyof typeof bodies], headers: Record<string, string> = {}, query = `tenant_id=${tenant}`, method = "POST", signal?: AbortSignal) {
  return new NextRequest(`${origin}/api/tvt/directory/${op}?${query}`, { method, signal, headers: { Origin: origin, Cookie: "__Host-wso-session=opaque; __Host-wso-csrf=csrf", "X-CSRF-Token": "csrf", "Content-Type": "application/json", ...headers }, ...(method === "GET" ? {} : { body: JSON.stringify(body) }) });
}
const backend = (value: unknown = view, status = 200) => vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(value), { status,headers:{"X-Request-ID":requestId} }));
beforeEach(() => Object.entries(config).forEach(([k, v]) => vi.stubEnv(k, v)));
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("forwards fixed readonly directory once with protected scope",async()=>{
 const upstream=backend(); const result=await proxyTvt(request("device-list"),["directory","device-list"],upstream);
 expect(result.status).toBe(200); expect(await result.json()).toEqual(view);
 expect(upstream).toHaveBeenCalledOnce(); expect(upstream.mock.calls[0][0]).toBe(`http://127.0.0.1:8100/api/v1/tvt/directory/device-list?tenant_id=${tenant}`);
 expect(result.headers.get("cache-control")).toContain("no-store");
});
it("authenticates and checks CSRF before reading body",async()=>{
 const upstream=backend();
 expect((await proxyTvt(request("device-list",{}, {Cookie:""}),["directory","device-list"],upstream)).status).toBe(401);
 expect((await proxyTvt(request("device-list",{}, {Origin:"https://evil.test"}),["directory","device-list"],upstream)).status).toBe(403);
 expect(upstream).not.toHaveBeenCalled();
});
it("denies arbitrary paths, methods, duplicate query and authority",async()=>{
 const upstream=backend();
 for(const [req,segments,status] of [[request("dispatch"),["directory","dispatch"],404],[request("device-list",{}, {},undefined,"GET"),["directory","device-list"],405],[request("device-list",undefined,{},`tenant_id=${tenant}&tenant_id=${tenant}`),["directory","device-list"],404],[request("device-list",{...bodies["device-list"],actor_id:tenant}),["directory","device-list"],422]] as const) expect((await proxyTvt(req,[...segments],upstream)).status).toBe(status);
 expect(upstream).not.toHaveBeenCalled();
});
it.each([{region:"other"},{identity_id:tenant},{method:"sent_shares"},{total:0},{generation:9007199254740992},{records:[{fields:[{name:"userToken",state:"value",value:"private"}],unknown_members:0}]},{grants_operations:true},{complete:true}])("rejects mismatched or unsafe view %s",async(patch)=>{
 const result=await proxyTvt(request("device-list"),["directory","device-list"],backend({...view,...patch}));
 expect(result.status).toBe(503); expect(JSON.stringify(await result.json())).not.toContain("private");
});
it("rejects duplicate keys, nonfinite, unsafe integer and deeply nested JSON",()=>{
 for(const text of ['{"method":"device_list","method":"sent_shares"}','{"value":1e999}','{"value":9007199254740992}', '['.repeat(33)+'0'+']'.repeat(33)]) expect(()=>directoryJson(text)).toThrow();
});
it("mirrors strict selectors, uniqueness and native integers",()=>{
 for(const patch of [{page_num:true},{page_size:1001},{method:"channel_list"},{generation:1}]) expect(directoryInputSchemas["device-list"].safeParse({...bodies["device-list"],...patch}).success).toBe(false);
 for(const sn_list of [["a","a"],["😀"],[" a"],["x".repeat(4097)]]) expect(directoryInputSchemas["channel-list"].safeParse({...bodies["channel-list"],sn_list}).success).toBe(false);
});
it("correlates error header/body and sanitizes exact safe error pairs",async()=>{
 const error={error:{code:"DIRECTORY_REAUTHENTICATION_REQUIRED",message:"private"},request_id:requestId};
 const result=await proxyTvt(request("device-list"),["directory","device-list"],backend(error,401));
 expect(result.status).toBe(401); expect((await result.json()).error.code).toBe("DIRECTORY_REAUTHENTICATION_REQUIRED");
 expect(safeDirectoryError(502,error).status).toBe(503);
 const mismatch=vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(error),{status:401,headers:{"X-Request-ID":tenant}}));
 expect((await proxyTvt(request("device-list"),["directory","device-list"],mismatch)).status).toBe(503);
});
it("bounds stalled result and nonsettling cancel to ten seconds",async()=>{
 vi.useFakeTimers();const upstream=vi.fn<typeof fetch>().mockResolvedValue(new Response(new ReadableStream<Uint8Array>({cancel:()=>new Promise(()=>{})})));
 const pending=proxyTvt(request("device-list"),["directory","device-list"],upstream);await vi.advanceTimersByTimeAsync(10001);
 const result=await pending;expect(result.status).toBe(504);expect((await result.json()).error.code).toBe("ACCOUNT_DEADLINE_EXCEEDED");expect(upstream).toHaveBeenCalledOnce();
});
it("typed browser client submits one same origin request without retaining source data",async()=>{
 vi.stubGlobal("window",{location:{origin}});const send=vi.fn<typeof fetch>().mockImplementation(async input=>{
 const req=input as Request;expect(req.url).toBe(`${origin}/api/tvt/directory/device-list?tenant_id=${tenant}`);expect(req.credentials).toBe("same-origin");expect(req.headers.get("x-csrf-token")).toBe("csrf");expect(await req.json()).toEqual(bodies["device-list"]);return new Response(JSON.stringify(view),{headers:{"X-Request-ID":requestId}});
 });vi.stubGlobal("fetch",send);
 expect(await directoryClient("csrf").deviceList(tenant,{...reference},new AbortController().signal)).toEqual(view);expect(send).toHaveBeenCalledOnce();
});

it("rejects canonical escaped selector bodies above 65536 before backend",async()=>{
 const body={...bodies["channel-list"],sn_list:Array.from({length:17},(_,index)=>"가".repeat(700)+index)};
 const upstream=backend();expect((await proxyTvt(request("channel-list",body),["directory","channel-list"],upstream)).status).toBe(422);expect(upstream).not.toHaveBeenCalled();
});

const missing=(name:string,source_default:string|number|null=null)=>({name,state:"missing",value:null,source_default,opaque_kind:null});
const record=(fields:unknown[])=>({fields,unknown_members:0});
const methodViews={
 "device-list":view,
 "channel-list":{...view,method:"channel_list",total:null},
 "device-detail":{...view,method:"device_detail",total:null,records:[record([missing("devInfo"),missing("chlInfos")])]},
 "channel-detail":{...view,method:"channel_detail",total:null,records:[record("sn chlName ip model version onlineTime offlineTime chlIndex status capability".split(" ").map(name=>missing(name)))]},
 "sent-shares":{...view,method:"sent_shares",total:0},
 "received-shares":{...view,method:"received_shares",total:0},
};
it.each(Object.entries(bodies))("forwards fixed six %s and validates operation total/detail",async(op,body)=>{
 const result=await proxyTvt(request(op,body),["directory",op],backend(methodViews[op as keyof typeof methodViews]));expect(result.status).toBe(200);expect(await result.json()).toEqual(methodViews[op as keyof typeof methodViews]);
});
it("preserves source SN, returned channel index, null and unknown presence",()=>{
 const channel=record([{...missing("chlIndex"),state:"value",value:7},{...missing("chlName"),state:"null"}]);
 const device=record([{...missing("sn"),state:"value",value:"opaque-SN"},{...missing("chls"),state:"value",value:[channel]}]);
 const result=directoryResponse({...methodViews["channel-list"],records:[device]},bodies["channel-list"],requestId);
 expect(result.records[0]).toEqual(device);expect(result.complete).toBeNull();expect(result.grants_operations).toBe(false);
});
it("accepts directory-only 1MiB policy while preserving old small bounds",async()=>{
 const fields="sn name userId devName mode createTime maxShareNum type".split(" ").map(name=>missing(name,name==="maxShareNum"?"0":name==="type"?0:null));
 const data={...view,records:Array.from({length:20},()=>record(fields.map(field=>field.name==="name"?{...field,state:"value",value:"x".repeat(4000)}:field)))};
 expect(JSON.stringify(data).length).toBeGreaterThan(65536);expect((await proxyTvt(request("device-list"),["directory","device-list"],backend(data))).status).toBe(200);
 const response=vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(data),{headers:{"X-Request-ID":requestId,"Content-Length":"1048577"}}));expect((await proxyTvt(request("device-list"),["directory","device-list"],response)).status).toBe(503);
});
it("request abort settles without backend retry",async()=>{
 const controller=new AbortController();const upstream=vi.fn<typeof fetch>().mockImplementation(()=>new Promise(()=>{}));const pending=proxyTvt(request("device-list",undefined,{},undefined,"POST",controller.signal),["directory","device-list"],upstream);controller.abort();const response=await pending;expect(response.status).toBe(504);expect(upstream.mock.calls.length).toBeLessThanOrEqual(1);
});

it("typed client maps invalid selector scope to safe errors before fetch",async()=>{
 vi.stubGlobal("window",{location:{origin}});const send=vi.fn<typeof fetch>();vi.stubGlobal("fetch",send);
 await expect(directoryClient("csrf").deviceList("https://private.invalid",reference,new AbortController().signal)).rejects.toMatchObject({status:422,code:"validation_error"});expect(send).not.toHaveBeenCalled();
});
