# NFS Mount for Sweeps and Runs - Implementation Notes

## Summary

Extended the NFS server to support browsing W&B sweeps and runs alongside artifacts. The implementation enables:
- Reading run metadata (config, summary, state) via `/runs/{run}/metadata.json`
- Browsing run files via `/runs/{run}/files/`
- Navigating sweeps with symlinks to runs via `/sweeps/{sweep}/runs/`

## Files Created

| File | Purpose |
|------|---------|
| `core/api/graphql/query_nfs_runs.graphql` | GraphQL query to list runs with metadata |
| `core/api/graphql/query_nfs_sweeps.graphql` | GraphQL query to list sweeps |
| `core/api/graphql/query_nfs_run_files.graphql` | GraphQL query to list files for a run |

## Files Modified

| File | Changes |
|------|---------|
| `core/internal/nfs/wandbfs_node.go` | Added 9 new node types for runs/sweeps |
| `core/internal/nfs/wandbfs_cache.go` | Added state-based TTL caching for runs/sweeps |
| `core/internal/nfs/list.go` | Added `listRuns()`, `listSweeps()`, `listRunFiles()` |
| `core/internal/nfs/wandbfs.go` | Added tree initialization and node handlers |

## Filesystem Structure

```
/
├── artifacts/          # (existing)
├── runs/
│   └── {run_name}/
│       ├── metadata.json
│       └── files/
│           └── {filename}
└── sweeps/
    └── {sweep_name}/
        └── runs/
            └── {run_name} -> ../../../runs/{run_name}  (symlink)
```

## Key Design Decisions

### State-Based TTL Caching

Runs and sweeps can be in active or terminal states. Active runs change frequently (metrics update), while finished runs are stable.

```go
const (
    terminalRunsTTL = 5 * time.Minute   // finished/crashed/failed
    activeRunsTTL   = 30 * time.Second  // running/pending
)

var terminalRunStates = map[string]bool{
    "finished": true,
    "crashed":  true,
    "failed":   true,
}
```

The cache checks if ANY run is active and uses the shorter TTL if so.

### Symlinks for Sweep Runs

Sweep runs are symlinks pointing to `/runs/{run_name}` to avoid duplicating data. This matches the artifact pattern where collections under types are symlinks.

## Bugs Found and Fixed

### Bug #1: Symlink Target Path Wrong

**Symptom:** `cd /tmp/wandb-mount/sweeps/{sweep}/runs/{run}` returns "no such file or directory"

**Root Cause:** The symlink target was `../../runs/{run}` but should be `../../../runs/{run}`.

**Path Analysis:**
```
Symlink at: /sweeps/{sweep}/runs/{run}
Parent: /sweeps/{sweep}/runs/

With ../../runs/{run}:
  ../  → /sweeps/{sweep}/
  ../  → /sweeps/
  runs/{run} → /sweeps/runs/{run}  ← WRONG!

With ../../../runs/{run}:
  ../  → /sweeps/{sweep}/
  ../  → /sweeps/
  ../  → /  (root)
  runs/{run} → /runs/{run}  ← CORRECT!
```

**Why artifact symlinks work:** Artifact symlinks use `../../collections/{name}` from `/artifacts/types/{type}/{collection}`, which resolves to `/artifacts/collections/{name}` - staying UNDER `/artifacts/`. Sweep symlinks need to go to `/runs/` at ROOT level, requiring one more `../`.

**Fix:** Changed `../../runs/%s` to `../../../runs/%s` in `wandbfs.go:523`

### Bug #2: Empty metadata.json on First Read

**Symptom:** First `cat runs/{run}/metadata.json` returns empty, second read returns data.

**Root Cause:** The `Stat()` function had special handling to calculate file size for artifact `NodeTypeMetadataJSON` but NOT for run `NodeTypeRunMetadataJSON`. On first stat, `FileSize` was 0, so NFS read 0 bytes.

**NFS Read Sequence:**
1. Client calls `stat()` to get file size
2. `Stat()` returns `FileInfo` with `FileSize: 0`
3. Client reads 0 bytes based on size
4. Empty result

On second read, `OpenFile()` had already populated `node.FileSize`, so stat returned correct size.

**Fix:** Added size calculation for `NodeTypeRunMetadataJSON` in `Stat()`, mirroring the artifact metadata handling.

## Lessons Learned

### 1. Relative Symlink Paths Require Careful Counting

When creating relative symlinks, count directory levels from the symlink's **parent** directory, not from the symlink itself. Use `tree` command with increased depth to visualize and verify symlink targets.

### 2. NFS Stat Before Read Pattern

NFS clients typically call `stat()` before `read()` to determine file size. For dynamically generated content (like metadata.json), the size must be calculated in `Stat()`, not just in `OpenFile()`.

### 3. GraphQL Pointer Types

The genqlient-generated GraphQL types use pointers for optional fields. When iterating over results:

```go
// Wrong - will fail to compile if node.State is *string
state := node.State

// Correct - handle nil pointers
state := ""
if node.State != nil {
    state = *node.State
}
```

### 4. State-Based Cache Invalidation

For resources with lifecycle states (runs, sweeps), using different TTLs based on state provides a good balance:
- Short TTL for active resources ensures fresh data
- Long TTL for terminal resources reduces API calls

### 5. Tree Command for Debugging

Running `tree -L 4` on the mounted filesystem is invaluable for:
- Verifying directory structure
- Seeing symlink targets (shown as `name -> target`)
- Confirming lazy loading works correctly

## Testing Commands

```bash
# Build
cd core && go build -o wandb-core ./cmd/wandb-core

# Start server
./wandb-core nfs serve entity/project

# Mount
sudo mount -t nfs -o vers=4,port=2049 localhost:/ /tmp/wandb-mount

# Verify structure
tree -L 4 /tmp/wandb-mount

# Test symlinks
readlink /tmp/wandb-mount/sweeps/{sweep}/runs/{run}
cd /tmp/wandb-mount/sweeps/{sweep}/runs/{run}

# Test metadata
cat /tmp/wandb-mount/runs/{run}/metadata.json

# Unmount
sudo umount /tmp/wandb-mount
```
