# Git tracking, privacy and checkout reproducibility review

Analysis date: 2026-10-11, Asia/Seoul. **The reviewed privacy/tracking rules
now pass.** No high-confidence private-material indicator was found in the
finite candidate scan. Root corrected both initial checkout blockers with
exact qualification-anchor exceptions and raw-byte attributes; this reviewer
verified their effective behavior. Final staged-blob/fresh-checkout proof is
still Root's required integration gate and is not claimed complete here.

Baseline: active worktree `codex/superlive-web-service`, HEAD
`6436748f37c799fd14ce03e1d72c86c79eda6b0f`, with existing uncommitted
Stage1/2/R193-R210 source and reports. Primary checkout main is
`211d1484aa16eb30f5d362758f149f98dec9dfdf` and has separate pre-existing document
changes. The user's current commit/main-merge/push authorization supersedes
historical no-commit session notes; this review itself performed no Git mutation.

Read shared policy, AGENTS, canonical service evidence and
[latest actual R210 report](2026-10-11-r210-live-acceptance.md). The service
provides authenticated local CCTV viewing with retained shared SUB transport,
dedicated MAIN and explicit original cleanup. R210's bounded real workflow
passed; twelve-camera/full parity/broad-suite/release claims remain qualified.
Reuse this report before applying tracking rules and refresh the final handoff
with actual staged/exported hash checks. Root owns AGENTS/canonical updates.

## Finite candidate/privacy inspection

At the initial snapshot, active-worktree candidates comprised266 files:
199 untracked files and67 modified tracked files. They were112 Markdown,
100 Python,18 TypeScript,13 TSX,18 JSON, and one each of attributes, protobuf,
MJS, TOML and lockfile. Recursive Git file enumeration expanded untracked
directories; ignored runtime/private paths were excluded.

Every candidate was below8MiB and read as text. No binary/NUL file, sensitive
capture/credential/SDK filename, PEM private-key block, AWS key form, known
API-token prefix, literal JWT or credential-bearing URL pattern was found.
Only paths/counts/categories were emitted. These closed checks do not prove
absence of every possible low-entropy, custom or encoded secret. Actual
credentials outside Git candidates were not read or used as search needles.

Primary main separately has7 Markdown candidates: modified AGENTS/service
report and5 untracked Oct8 analysis/spec documents. The same finite patterns
found no high-confidence indicator. Preserve those files during integration;
do not overwrite their historical evidence with worktree copies.

The tracked-candidate JSONs include17 public qualification receipts plus the
generated contract. Public receipts reference114 distinct visible project
paths; all exist in the tracked-or-eligible-untracked set. They are source/
qualification metadata, not vendor SDK binaries or raw captured media.

## Blocker1: required source qualification metadata is ignored

`windows_socket.py` explicitly requires hash-checked ABI, inventory and runtime
override receipts under `.superpowers/sdd`. `scripts/test-local-devices/runtime.py`
also requires service/API/web qualification receipts and a native inventory
anchor. That anchor adds two historical qualification dependencies. A fresh
checkout lacks these files under the current blanket `.superpowers/` rule,
even after all visible application source/docs are committed.

The following **nine exact existing JSON paths** were audited as proposed Git
candidates. They contain source/review/bundle hashes, statuses, counters,
bounded qualification descriptions and the development runtime-override
metadata. No credential fields, credentialed URLs, private-key/token patterns,
account/device input bodies or raw media were found. Historical actual/release
qualifiers remain intact. This is a narrow source-proof allowlist, not a reason
to track other runtime evidence or the containing directories wholesale.

```text
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-windows-socket-abi-reviewed-root-receipt.json
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-local-inventory-xml-Fix3-Fix1-reviewed-root-receipt.json
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-windows-python-crypto-runtime-override-reviewed-root-receipt.json
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W08-local-service-integration-Fix2-reviewed-root-receipt.json
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/M1-native-inventory-postpublication-source-root-receipt.json
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-local-n9000-login-field-reviewed-root-receipt.json
.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W08-local-live-taskless-first-qualified-reviewed-root-receipt.json
.superpowers/verification/local-device-api/root-receipt.json
.superpowers/verification/local-device-web/root-receipt.json
```

Recommended minimal fix: replace the blanket ignored-parent form with rules
that permit traversal of only the required parent directories, re-ignore each
parent's children, then unignore these nine leaves. Preserve every other
`.superpowers` runtime/evidence/private exclusion. Merely adding leaf exceptions
under an ignored parent will not work. Keeping existing paths and exact bytes
avoids changing approved production constants or rebuilding authority receipts.

Their metadata closure references52 project paths; no extra ignored Python
implementation dependency was found in the inspected files/dependencies/sources
graph. Private SDK/package, environment credentials, TLS and decoder runtime
installation remain external provisioning requirements and must stay untracked.
Ignored one-off preparation/launch helpers remain local workflow artifacts;
promoting supported fresh-checkout tooling would require a separate explicit
source-only inventory, not copying its private runtime directories.

## Blocker2: line-ending conversion breaks approved raw hashes

Effective Git configuration is system `core.autocrlf=true`; no core.eol override
was reported. Current `.gitattributes` has only5 path rules. Of the114 public
receipt-bound paths,83 are LF,24 CRLF and7 have mixed/no-newline classification.
Only4 of those paths have explicit attributes. **80 LF hash-bound paths lack
explicit protection**, including current player/group, Core admission/types,
migrations, tests and immutable review reports. Windows checkout conversion
can therefore invalidate raw hashes despite semantically identical code.

Computed review artifact for Root application:

`WORK/git-tracking-byte-preservation-paths.json`

SHA256 `12405b1562a8139c0f523f6b1a71411062a9f5ae590c05d4e944231571d5dc17`.
It contains the exact9 anchor path/size/SHA entries and174 distinct byte-
preservation paths: public receipts, their bound paths, the nine anchors and
their visible metadata dependencies. The native factory is included. WORK is
`.superpowers/sdd/2026-10-06-multiview-stage2-shared-recorder-plan`.
This ignored JSON is review/application metadata, not a new runtime approval.

Recommended protection is an explicit `-text` entry for each computed path,
including immutable historical receipts. Existing compatible LF/CRLF rules
may remain only where their effective attributes reproduce the approved bytes;
do not blindly normalize all reviewed CRLF/LF material to one style. Appending
explicit raw-byte rules can preserve current bytes without rewriting source.
Other unrelated Git attributes should be preserved.

## Required final integration checks

Root should complete these checks after applying the narrow tracking rules:

1. Enumerate Git candidates/staged files again. Exactly the nine approved
   anchors should become eligible from `.superpowers`; runtime credentials,
   native binaries, raw media, contexts and unrelated evidence remain ignored.
2. Check effective attributes for every computed byte-preservation path.
   After staging, compare each staged blob's bytes/hash with its approved
   working-tree baseline. This catches normalization during `git add`.
3. Export/check out the candidate commit into a separate clean directory and
   hash its files. Verify the current public/native qualification closure and
   immutable receipt bytes without consulting the original worktree. Verify
   qualification-anchor presence separately from external SDK provisioning.
4. Preserve primary main's existing7 document changes before integrating.
   Review the final staged diff and resulting checkout status; commit/push
   authorization is present, but no full-test-green or release claim follows.

Historical receipts intentionally preserve earlier baselines and qualifiers;
do not rewrite them to make every historical file hash describe current source.
The current accepted closure and required immutable dependencies are the fresh-
checkout verification target. New runtime launches need a fresh full closure
after post-retirement documentation/tracking changes.

## Final read-only verification after Root's tracking changes

Root applied the exact9 anchor exceptions and174 explicit `-text` entries.
The existing nested `.superpowers/sdd/.gitignore` also contained `*`; Root
narrowly updated that file and made it eligible so a fresh checkout preserves
the required exception chain. It permits only itself, traversal of the one
qualified SDD directory and the seven named SDD JSON leaves. Its children stay
ignored by default. The two verification receipts are separately allowed by
the root rule. This bridge is source configuration, not runtime evidence.

Reviewer independently verified:

- Effective `.superpowers` eligibility is **exactly9 audited JSON anchors plus
  `.superpowers/sdd/.gitignore`**, with zero unexpected paths.
- All174 computed paths have effective Git `text=unset`; all174 current raw
  hashes still equal the review baseline. No approved content was normalized
  or rewritten by the attribute changes.
- Eight negative Git-ignore probes remain ignored: runtime credential location,
  current SDD progress, an unapproved JSON beside allowed anchors, unapproved
  verification capture, auth-state context, media capture, `.env`, and another
  unapproved SDD subtree. No credential/capture contents were read for these
  checks.
- The nine anchors retain the exact previously audited bytes/schema and
  nonsecret qualification classification. Both root and nested ignore-rule
  source were read in full; no broad exception was added.

The two initial configuration blockers are therefore resolved. Staging and
clean-checkout raw-byte validation must still follow; this audit did not stage,
commit, merge or push any file.

## Verification boundaries

Executed only read-only Git inventory/config/attribute checks, bounded filename/
content scans of eligible candidates, metadata inspection of the nine newly
authorized anchor candidates, and raw hash/line-ending classification. No
private credential directory was scanned, no SDK binary was read, and no
source/index/branch/runtime/DB mutation, tests, nested agent or commit occurred.
This report and the explicitly requested ignored path/hash artifact are the
only writes. The final staged/exported checkout is Root's next verification;
this document does not claim it has already passed.

Update log: 2026-10-11 initial candidate scan clear within stated limits;
9-anchor portability and174-path raw-byte preservation requirements delivered
to Root. Same-day follow-up verified Root's exact9+one bridge eligibility,
174 effective `-text`/unchanged raw hashes and8 ignored negative probes.
Staged/exported checkout proof remains Root's next gate.
