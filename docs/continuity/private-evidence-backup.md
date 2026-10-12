# Private research evidence preservation and recovery

GitHub preserves reviewed source, tests, design, sanitized requests/hashes and
decisions. Restricted evidence stays in a separate authenticated encrypted local
snapshot. No raw exchange records, private provider/account receipts, API keys,
broker credentials or detailed licensed replay prices were uploaded.

## Snapshot and status

The original files were neither deleted nor relocated. The existing evidence
inventory covers 2,144 files / 1,894,180,245 bytes. A local encrypted recovery
package includes those files plus source-history bundles, task instructions,
private inventories and recovery metadata: **2,166 files / 1,907,759,603 bytes**.
Every included file was read back, authenticated and matched to its SHA-256.
Source hashes and modification times were checked around copying.

Private paths, relative to the research workspace:

* Snapshot: `private-reports/preservation-v1/backup/monatise-through-phase5.tar.gz.aes256gcm`
* Detailed manifest: `private-reports/preservation-v1/backup-manifest.json`
* Verification receipt: `private-reports/preservation-v1/backup-receipt.json`
* Recovery key: `private-reports/credentials/research-backup-v1.key`

Snapshot size: 381,769,917 bytes. SHA-256:
`f8b57d0e60177ba1f2b41d3fabe425b27a7b20ce35c14306557c4117862a25ef`.
Private manifest SHA-256:
`f833b9caf06cf8417958f5f98ecef3f45e9b4305ea0f02b12bd462e20834775f`.

The archive is mode 0400, its directory 0700, and the binary recovery key and
manifest 0600. The key contains 32 cryptographically random bytes and is never
printed. Known credential files/namespaces are excluded from the payload;
confidential evidence/logs and retired history bundles remain restricted.
No encryption keys or credentials are committed.

**Independent backup and separate key escrow are not verified.** Both current
copies reside on the same host. No external destination was supplied or accessed.
This protects a local copy's contents but does not protect against losing the
host/key together. Copy the encrypted package and private manifest to a reviewed
encrypted external/private backup destination and escrow the key separately.
Verify a read-back and recovery on another machine before declaring disaster
recovery complete. Do not publish the key, manifest or provider records.

The snapshot is the Phase 5 evidence checkpoint. The final preservation commit,
remote-verification receipt and subsequent test logs are later artifacts;
GitHub preserves their sanitized summaries, and the detailed local receipts need
inclusion in the next private backup checkpoint. No previous evidence was replaced.

## Verify without extraction

Use the existing locked environment (`cryptography` was already a dependency):

```sh
.venv/bin/python scripts/verify_private_research_backup.py \
  --backup private-reports/preservation-v1/backup/monatise-through-phase5.tar.gz.aes256gcm \
  --key-file private-reports/credentials/research-backup-v1.key \
  --manifest private-reports/preservation-v1/backup-manifest.json
```

The verifier prints only aggregate counts and hashes. It authenticates the entire
GCM ciphertext before parsing the tar stream, then checks every member against
the separately saved manifest. It rejects duplicate/unexpected/non-file members,
wrong keys, altered ciphertext/tags, missing evidence and mismatched sizes/hashes.
It never extracts files, connects to a provider or reads a production credential.
Eight synthetic offline cases test successful verification and those rejection
boundaries. Verification proves byte recovery; it is not market-data certification.

## Portable container format

The byte layout is the literal ASCII bytes `MONATISE-RESEARCH-BACKUP`, one version
byte `0x01`, a random 12-byte nonce, AES-256-GCM ciphertext, then a 16-byte GCM tag.
The magic/version plus nonce is authenticated additional data. The binary key
file is exactly 32 bytes. The plaintext is a gzip-compressed POSIX tar stream.
There is no password-derived key, provider dependency or proprietary service.

Tar contains `manifest.json` and regular files named `evidence/00000000`,
`evidence/00000001`, etc. Their positions correspond to `files` in the manifest,
which retains original paths, groups, lengths, modes and SHA-256. Numeric member
names prevent automatic extraction into production or original directories.

For recovery, first run the verifier against the independently preserved hashes.
Decrypt with the documented format and existing `cryptography` AES/GCM API into
an owner-only temporary file; authenticate the complete tag before renaming or
using any plaintext. Validate the same member inventory, then recover selected
numbered members into a new owner-only staging directory. Map each to its manifest
path only after review. Never restore over a live checkout/store or execute an
archived acquisition/deployment helper automatically. Original paths are provenance,
not authority to write on another machine. Restored billing quarantine and clock
semantics remain unchanged.

The source-history bundle preserves current research and frozen references;
two additional private bundles preserve retired framework/control histories.
Retired histories can contain material removed from public history and must not
be pushed wholesale. Use the public continuity/source branch map for active work.
