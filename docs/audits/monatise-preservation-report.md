# Monatise development preservation audit

Audit date: 12 October 2026. Repository:
[Patrick8552/monatise-live](https://github.com/Patrick8552/monatise-live).
Development branch:
[research/databento-cme-foundation](https://github.com/Patrick8552/monatise-live/tree/research/databento-cme-foundation).
Implementation checkpoint: `3ce3d384df03aeffd90efa79c7cf33bde9f320eb`.
The preservation commit containing this report is the Phase 6 starting commit;
its exact SHA and final remote read-back are recorded in the delivery and private
`preservation-v1/remote-verification.json`. There is no automatic merge to main.

## Scope and findings

The active tree was initially clean, with **561 tracked files** and no useful
untracked non-ignored files awaiting staging. Its canonical production source,
configuration templates, engines/adapters, broker/risk/approval/execution guards,
Gold/index/crypto infrastructure, tests/fixtures and Phase 1–5 reports were
already committed locally. The five main research implementation commits were
not on a remote research branch. Older isolated histories were also local only.

Discovery inspected local repository candidates to depth six under the Codex
project directory, excluding Git objects, environments, dependency/build caches
and symlinks. It found 23 repository candidates, including 17 checkouts with the
expected GitHub origin and the frozen selector's separate local-origin checkout.
Relevant research checkouts and their active branches were clean. Older public
production/topic histories were already represented on GitHub or in canonical
history. Retired histories are preserved privately instead of being republished:
some predate removal of private material from public development history.
Other projects, social assets, cloud-only artifacts and historical prototypes are
not certified as a complete Monatise archive. No obsolete branch is activated.

Five earlier source histories were imported into the active repository without
changing their original trees/commits, then pushed atomically under their original
names. Remote heads and representative source documents were read back from
GitHub:

| GitHub branch | Verified preserved SHA |
|---|---|
| [codex/databento-phase1](https://github.com/Patrick8552/monatise-live/tree/codex/databento-phase1) | `0851fb7c7b5340e1e0f8d038e30215d6b15ed2ec` |
| [codex/broker-xauusd-phase3](https://github.com/Patrick8552/monatise-live/tree/codex/broker-xauusd-phase3) | `ce1ee530effe68080ac2e81d1a29b80200b0d54b` |
| [codex/broker-xauusd-phase4](https://github.com/Patrick8552/monatise-live/tree/codex/broker-xauusd-phase4) | `890b8f7deba379931a3ce7df5b6e6fb5760f2d73` |
| [codex/databento-gc-research](https://github.com/Patrick8552/monatise-live/tree/codex/databento-gc-research) | `a144db7f89e7bb3bb5748b83660d51243f69dc51` |
| [codex/gold-h1-fib-f0-shadow](https://github.com/Patrick8552/monatise-live/tree/codex/gold-h1-fib-f0-shadow) | `f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35` |

Their source includes earlier acquisition/registry/native archive/CAS/replay,
broker observation/retrospective modules, exporter source, original methodology
and tests that are not all in the current checkout. Branch preservation avoids
copying incompatible shared changes into current engines. The frozen selector
remains original, separate and unmodified.

## Reviewed artifact classification

| Class | Preservation decision |
|---|---|
| Already committed | All 561 active Phase 5 tracked files, canonical source/configurations, locks, tests, architecture, earlier phase reports/validation and the separately preserved original research branches. No duplicate implementation commit. |
| Useful and safe | Original final H1 design specification; earlier unexecuted extension-study protocol/readme and header-only observation ledger. Four exact copies now under `docs/research-archive/`, with SHA-256 and historical status. |
| Requires sanitization | Development continuity, request/provenance/hash inventory, aggregate validation and backup status. Whitelisted metadata only: no market record bytes/prices, account identities, authorization receipts, keys or private payment details copied into these new documents. |
| Private/licensed | Native DBN and partial quarantined downloads, detailed normalized/derived/replay/quality outputs, broker/GC diagnostics, acquisition/source/billing/provider/account receipts, private reports and retired history bundles. Preserve in authenticated encrypted local backup; keep originals. |
| Temporary/reproducible | Virtual environments, dependency/bytecode/test caches, disposable PG/Redis clusters, intermediate probes and duplicate transient outputs. No public staging and no cleanup/deletion required. Some existing reports/probes were conservatively included in the private snapshot. |

New reviewed files: `docs/monatise-development-continuity.md`, this report,
`docs/audits/monatise-preservation-validation.json`, `docs/continuity/` manifests
and private-backup instructions, `docs/research-archive/` index and four original
design/protocol files, `scripts/verify_private_research_backup.py` and
`tests/research/test_private_backup.py`. The utility is an offline archive
verifier; it cannot download data, extract to original locations or contact a
production service. Existing `.gitignore` and all 561 original files are unchanged.

The original superseded M15 specification, private review manifests, deployment/
account diagnostics and restricted provider exports remain private. They were
not silently discarded or mistaken for implemented production capabilities.

## Reproducibility evidence

The [continuity record](../monatise-development-continuity.md) maps exact phase
commits, architecture, decisions, reuse, frozen contracts, GIL hierarchy and
Phase 6 prerequisites. Existing audit/runbooks are indexed through the
[artifact inventory](../continuity/artifact-inventory.json), which retains the
Phase 5 file hashes. The [acquisition manifest](../continuity/acquisition-manifest.json)
preserves **32 exact request specifications**: 24 complete GC, six complete ES/NQ
and two previously quarantined GC attempts. Dataset/schema/native contracts,
integer UTC bounds, exclusive ends, record/byte limits, request/archive hashes,
local clocks, availability assumptions and unknown billing status are retained.
All thirty complete archive hashes were rechecked against their actual local bytes.

Five saved deterministic replay pairs were rehashed and matched: frozen expanded
GC, Phase 3A ledger, Phase 3B forensics, Phase 4 preview and Phase 5 preview.
The actual frozen replay was parsed again: **557 assessments, 69 valid constrained
Fibonacci assessments, 12 distinct valid H1 episodes, zero qualified Gold setups**.
Trade win rate remains null. Previous results and denominators were not rewritten.

The hash audit distinguishes the Phase 5 logical input digest
`6a43e6e372068be8f2ae42b91651e1100125a7d700c37e83822de72e68dd0d75`
from its serialized private file digest
`9e42a4f371969b39d3bef76c19668897ffa7086ed15ec885878b86aa157ee10c`.
This clarifies earlier report wording without changing saved acceptance files.
Genuine observations, retrospective diagnostics, engineering fixtures and
production-certified inputs remain separate classifications.

## Private backup and unresolved gaps

The detailed private inventory covers **2,144 existing files / 1,894,180,245 bytes**.
An **AES-256-GCM authenticated local snapshot** includes those files plus recovery
metadata, private source-history bundles and task instructions: **2,166 files /
1,907,759,603 bytes**, compressed/encrypted to **381,769,917 bytes**. Every archived
member was decrypted/authenticated and matched to its independently saved hash.
Files/directories use owner-only modes; credentials are excluded. Native archives,
replays and private ledgers were neither relocated nor modified.

See [backup format, paths and verification/recovery instructions](../continuity/private-evidence-backup.md).
**Off-device backup and separate recovery-key escrow remain unverified.** No
external destination was supplied. The local encrypted package is a recovery
copy on the same host; it does not establish disaster recovery. New final
preservation receipts need the next private backup checkpoint. API/broker keys
remain outside the package and require their own secure credential management.

Other reproduction blockers remain factual: exact old GC and new ES/NQ provider
billing, twenty-one Class E GC omissions, genuine broker exports and historical
session/availability/quote evidence, authentic crypto and OG options coverage,
American Greek certification and live-feed operational acceptance. Preservation
does not resolve those by downloading substitutes or relabelling fixtures.

## Validation and operational boundaries

[Machine validation](monatise-preservation-validation.json) records:

* Final offline repository suite: **2,131 passed**, zero failures/errors/skips,
  49.23 seconds. Includes the existing 2,123 cases and eight new recovery tests.
* Separate frozen selector suite: **53 passed**, zero failures/errors/skips,
  49.12 seconds; original source tree remains clean.
* Eight recovery cases cover byte/hash verification, wrong key, altered ciphertext/
  tag, changed manifest, wrong evidence hash, duplicate member and truncation.
  Authentication failure prevents archive parsing. No files are extracted.
* All 561 previously tracked files unchanged; thirty native archive hashes and
  all five replay pairs reverified. Source/mtime checks protect backup inputs.
* 190 unpublished-history blobs across current/earlier/frozen research were
  checked for the supplied credential and key/token/private-key shapes: zero
  findings. New staged artifacts receive a separate pre-push content/path review.
  This is a bounded review, not a certification of every already-public old commit.

Tests used the existing environment, generated fixtures and disposable loopback
services, with no provider charges or production credentials. No additional
dependency, execution/risk/approval/Telegram behavior, GIL hierarchy, deployed
configuration or frozen logic changed. GitHub main was rechecked at
`0f12862b8d11f6559bc77a5df1dd2a6dbd6c1b18`; pushes target research branches only.
No force-push, merge, deploy, subscription, new historical acquisition or trade.

The final delivery confirms the current research branch's preservation SHA and
remote file accessibility after push. Future development should pin that commit,
recover the private evidence, verify hashes and reconcile admission dependencies
before requesting new data. A local commit alone is never evidence of remote preservation.
