# Private fixed directory RPC

Analysis date: 2026-10-03. Source baseline: `b25df5268a6ff7b524232c7c62cf52bb1583061d` plus the nine-file W07 directory RPC candidate. This is transport implementation evidence, with a synthetic directory worker. Protected SQL composition remains gated by root review of the worker sources. MATCHED=0; release_ready=false.

## API-side interface

The existing `AccountRpcClient` owns one verified mTLS channel, one callback registry and one close operation. Its account six and flow eight methods remain available. Directory methods use that same channel:

| Direct method | Exact body class | Fixed protobuf method |
| --- | --- | --- |
| `directory_device_list` | `DeviceListRequest` | `DirectoryBridgeV1.DeviceList` |
| `directory_channel_list` | `ChannelListRequest` | `DirectoryBridgeV1.ChannelList` |
| `directory_device_detail` | `DeviceDetailRequest` | `DirectoryBridgeV1.DeviceDetail` |
| `directory_channel_detail` | `ChannelDetailRequest` | `DirectoryBridgeV1.ChannelDetail` |
| `directory_sent_shares` | `SentSharesRequest` | `DirectoryBridgeV1.SentShares` |
| `directory_received_shares` | `ReceivedSharesRequest` | `DirectoryBridgeV1.ReceivedShares` |

Every method takes `(ticket: str, body: ExactRequest, *, deadline_ms: int, correlation_id: str) -> DirectoryView`. The directory budget is 1–10000 milliseconds. The UUID/region/brand/method in the safe result must match the exact requested scope; request_id must match correlation_id. Generation must be positive, complete must be null, and grants_operations must be false. Scope in the body is a requested selector; SQL ticket admission remains responsible for authority. No retry, DC adoption, token renewal or operation grant occurs in transport.

The API client continues to consume only `WSO_TVT_BRIDGE_ENDPOINT`, `WSO_TVT_BRIDGE_CA_FILE`, `WSO_TVT_BRIDGE_CLIENT_CERT_FILE`, and `WSO_TVT_BRIDGE_CLIENT_KEY_FILE`. Reuse its existing lifecycle; constructing one client per request would discard its owned cancellation and capacity state.

## Worker configuration

`AccountRpcServer(..., directory_worker: DirectoryWorker | None = None)` is additive. A directory worker implements `execute(method, ticket, body, *, deadline_ms, correlation_id) -> DirectoryView`. All twenty methods share the original verified peer SAN gate, gRPC capacity, SessionPool, callback registry, epoch retirement and once disposer. An absent directory worker returns ACCOUNT_UNAVAILABLE while preserving the original account and optional flow surfaces.

Only worker bootstrap reads optional `WSO_TVT_DIRECTORY_PROFILE_FILE`. When absent, no directory admission or executor is constructed. When present, it must name a UTF-8 JSON file containing 1–64 mappings with exactly these four keys:

```json
[{"region":"eu","brand":"tvt","profile_id":"deployment-profile","consent_version":"v1"}]
```

Mappings are frozen DirectoryPolicy instances in an immutable tuple. Region/brand pairs must be unique and exactly equal the existing configured AccountEndpoint pairs. Empty, partial, extra-key, duplicate-key, malformed, overbound, invalid scope and mismatched mappings fail startup. The file does not contain endpoints, user tokens or a flow HMAC key. Existing `WSO_WORKER_DATABASE_URL` and FileKeyProvider/`WSO_CONNECTION_KEY_FILE` are reused by worker-only DirectoryAdmission and DirectoryWorkerExecutor construction. The directory feature does not require W06 flow key configuration.

Bootstrap registers admission and executor disposers before returning the server. DirectoryWorkerExecutor.close(deadline_ms=1000) succeeds by returning None and reports quarantine by raising. False or an unexpected return value does not prove disposal. All registered callbacks are attempted once; uncertainty keeps server cleanup false and retains original callbacks in a private startup quarantine when startup cannot return an owner. Repeated disposal preserves uncertainty. No worker recreation or process sweep occurs.

## Closed wire rules

The proto is additive: DirectoryBridgeV1 has six explicit requests with RpcContext field 1 and query_json field 2, and DirectoryReply carries exactly public_json field 1 or failure_code field 2. Existing messages/services/field numbers and literal RpcContext reservations 5 through 15 remain unchanged. SQL authority fields stay outside the envelope.

Canonical private query JSON has a 65536-byte maximum; its envelope permits 1024 additional bytes. Reply envelopes have a 1 MiB maximum. Account/flow requests retain their original 32768-byte bound and replies their 524288-byte bound despite the larger global gRPC ceiling. Directory JSON rejects duplicate keys, nonfinite numbers, extra fields and lexical nesting above 32. Safe observation traversal bounds depth to 12 and nodes to 50000, rejects duplicate observation names and inconsistent presence/opaque states, and checks scalar observation strings at 4096 UTF-8 bytes. Exact classes and raw model dictionaries are checked before serialization can discard constructed private extensions.

Directory failures reuse the fixed account vocabulary and add ACCOUNT_QUARANTINED (503), DIRECTORY_REAUTHENTICATION_REQUIRED (401), ACCOUNT_TRANSPORT_FAILED (502), and ACCOUNT_CANCELLED (409). Unknown codes become ACCOUNT_UNAVAILABLE (503). TOKEN_EXPIRED and AUTH_REQUIRED remain distinct. Failure statuses are reconstructed locally; exception text and raw upstream data never enter the reply. A deadline after dispatch becomes UNKNOWN_OUTCOME. One caller budget covers input encoding, TLS/connect, remote admission/execution, projection and result decoding; cancellation cannot publish a late success.

## Executed verification and limits

The focused suite comprises `test_directory_rpc.py` and the concretely affected original `test_account_flow_rpc.py`. It executed 122 cases with zero failures: actual in-process verified TLS for all six directory paths, existing flow methods and account profile, hostile replies/requests, scope/class/presence binding, malformed frames, TLS CA/SAN/name rejection, large safe query/reply, original per-method bounds, one original deadline, shared capacity, client/server close and disposer/bootstrap uncertainty. Bootstrap uses synthetic owned resources, with no protected SQL or vendor calls.

Pinned grpcio-tools 1.84.0 regeneration, repeated byte identity, structural comparison of every old message/service, Ruff/format, strict production mypy with the existing generated-code exemption, source/artifact custody and private18 scan are recorded in `.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-directory-rpc-report.md` and its packet. Root independent review, protected worker Fix1 approval, final server/Chrome acceptance and any current vendor/phone/APK parity acceptance remain outstanding.

## W07 RPC Fix1 review correction (2026-10-03)

Independent review identified I1: a raw UTF-8 query below65536 bytes could expand beyond65536 bytes when converted to required ASCII canonical JSON. The decoder assigned its parsed result before that policy check, then returned it after the check failed. Fix1 assigns the final result only after canonical validation succeeds. New codec and actual fixed ChannelList mTLS regressions prove ACCOUNT_INPUT_INVALID and zero worker invocation for this non-ASCII expansion case. Accepted below-bound queries and original account bounds remain covered by the focused Fix1 verification packet.

The original122-case evidence and its worker hash are historical and retained unchanged. Root has separately accepted protected worker Fix1 source SHA-256 `56d029bfc0f99468ea4ce51a2fb8abf3fda99dcac045ecce0ae99a417175fcc1`, with unchanged constructor/execute/close interfaces. The RPC Fix1 evidence still uses a synthetic worker; protected SQL composition was not executed. Current command readsets record the accepted worker and independently authorized pyproject.toml changes separately from the original consumed dependencies. See the separate W07-directory-rpc-Fix1 report/READY/source manifests under the same SDD directory. MATCHED=0; release_ready=false.
