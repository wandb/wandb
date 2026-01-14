# Plan: Go CLI for Listing W&B Artifact Collections

## Goal
Add a `wandb-core nfs ls <entity/project>` command that lists artifact collections and their versions using pure Go (GraphQL API), without needing a run.

Example:
```
$ wandb-core nfs ls reg-team-2/pinglei-benchmark
long-text/
   v0
   v1
   v2
another-collection/
   v0
```

**Key insight:** Users work with collections directly (e.g., `api.artifact("entity/project/collection:v0")`), so we focus on collections first, not artifact types.

## Why New GraphQL Queries Are Needed

Existing Go GraphQL operations (`core/internal/gql/gql_gen.go`) require an artifact ID:
- `ArtifactManifest(artifactID)` - needs ID
- `ArtifactFileURLs(artifactID)` - needs ID

**No existing queries to discover/list artifacts** - the Go code assumes you already have artifact IDs (typically from Python SDK or a run context).

The Python SDK has these listing queries in `wandb/sdk/artifacts/_generated/operations.py`, but they haven't been ported to Go yet.

## Implementation Phases

### Phase 1: Add GraphQL Operations

**Create file:** `core/api/graphql/query_nfs_artifact_collections.graphql`

To list all collections, we need to go through artifact types (GraphQL schema requirement), but we'll flatten the output to just show collections:

```graphql
query NFSArtifactCollections($entity: String!, $project: String!, $typeName: String!, $cursor: String, $perPage: Int) {
  project(entityName: $entity, name: $project) {
    artifactType(name: $typeName) {
      artifactCollections(after: $cursor, first: $perPage) {
        edges {
          node {
            id
            name
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
}
```

**Create file:** `core/api/graphql/query_nfs_artifact_types.graphql` (internal use only)
```graphql
query NFSArtifactTypes($entity: String!, $project: String!, $cursor: String, $perPage: Int) {
  project(name: $project, entityName: $entity) {
    artifactTypes(after: $cursor, first: $perPage) {
      edges {
        node {
          name
        }
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
}
```

**Create file:** `core/api/graphql/query_nfs_artifacts.graphql` (for listing versions)
```graphql
query NFSArtifacts($entity: String!, $project: String!, $typeName: String!, $collectionName: String!, $cursor: String, $perPage: Int) {
  project(entityName: $entity, name: $project) {
    artifactType(name: $typeName) {
      artifactCollection(name: $collectionName) {
        artifacts(after: $cursor, first: $perPage) {
          edges {
            node {
              id
              versionIndex
            }
          }
          pageInfo {
            endCursor
            hasNextPage
          }
        }
      }
    }
  }
}
```

**Regenerate:** `cd core/api/graphql && go generate`

### Phase 2: Create NFS Package

**Create directory:** `core/internal/nfs/`

**Create file:** `core/internal/nfs/client.go`
- `Config` struct with APIKey, BaseURL
- `LoadConfig()` - reads `WANDB_API_KEY` env var, defaults BaseURL to `https://api.wandb.ai`
- `NewGraphQLClient(cfg)` - creates GraphQL client using:
  - `api.NewAPIKeyCredentialProvider(apiKey)`
  - `api.NewClient(opts)` with `api.ClientOptions`
  - `graphql.NewClient(endpoint, api.AsStandardClient(httpClient))`

**Create file:** `core/internal/nfs/list.go`
- `ProjectPath` struct with Entity, Project
- `ParseProjectPath(path)` - splits "entity/project"
- `Lister` struct with graphql.Client
- `ListCollections(ctx, path)` - main function that:
  1. Fetches all artifact types (internal step, not exposed)
  2. For each type, fetches collections
  3. For each collection, fetches artifact versions
  4. Returns flat list of collections with versions

**Create file:** `core/internal/nfs/output.go`
- `CollectionInfo` struct with Name, TypeName, Versions
- `VersionInfo` struct with Index, ID
- `PrintCollections(w io.Writer, collections []CollectionInfo)` - formats tree output

### Phase 3: Add CLI Subcommand

**Modify:** `core/cmd/wandb-core/main.go`

Add to `run(args)` function (around line 46):
```go
case "nfs":
    return nfsMain(args[1:])
```

Add `nfsMain(args)` function following the `leetMain` pattern:
- Parse flags with `flag.NewFlagSet("nfs", ...)`
- Handle `ls` subcommand
- Call `nfs.LoadConfig()`, `nfs.NewGraphQLClient()`, `nfs.ParseProjectPath()`
- Create `nfs.Lister`, call `ListCollections()`, print output

### Phase 4 (Future): Add Files and Runs

Can be added later:
- `query_nfs_artifact_files.graphql` - list files per artifact version
- `query_nfs_runs.graphql` - list runs in project

## Key Files to Modify/Create

| File | Action |
|------|--------|
| `core/api/graphql/query_nfs_artifact_types.graphql` | Create |
| `core/api/graphql/query_nfs_artifact_collections.graphql` | Create |
| `core/api/graphql/query_nfs_artifacts.graphql` | Create |
| `core/internal/gql/gql_gen.go` | Auto-generated |
| `core/internal/nfs/client.go` | Create |
| `core/internal/nfs/list.go` | Create |
| `core/internal/nfs/output.go` | Create |
| `core/cmd/wandb-core/main.go` | Modify (add nfs subcommand) |

## Reference Files (Patterns to Follow)

- `core/cmd/wandb-core/main.go` - CLI structure, `leetMain` pattern at lines 164-259
- `core/internal/api/api.go` - `NewClient()` at line 129, `ClientOptions` at line 61
- `core/internal/api/credentials.go` - `NewAPIKeyCredentialProvider()` at line 50
- `core/internal/api/standardclient.go` - `AsStandardClient()` at line 22
- `wandb/sdk/artifacts/_generated/operations.py` - Python GraphQL queries to port

## Verification

1. **Build:** `cd core && go build ./cmd/wandb-core`
2. **Test collections listing:**
   ```bash
   export WANDB_API_KEY="your-key"
   ./wandb-core nfs ls your-entity/your-project
   ```
3. **Expected output:**
   ```
   collection-name/
      v0
      v1
   another-collection/
      v0
   ```
4. **Error cases to verify:**
   - Missing `WANDB_API_KEY` shows clear error
   - Invalid project path (not "entity/project") shows error
   - Non-existent project shows error from API

## Notes

- Collections are fetched by iterating through artifact types internally (GraphQL schema requirement)
- Output shows collections in flat list, hiding the type hierarchy from users
- Pagination uses Relay-style cursors (hasNextPage, endCursor)
- The `nfs` package design supports future NFS server and file/run listing extensions

---

## Implementation Log

### Status: COMPLETED

All phases (1-3) have been implemented successfully. The CLI builds and runs.

### Files Created

| File | Description |
|------|-------------|
| `core/api/graphql/query_nfs_artifact_types.graphql` | GraphQL query for listing artifact types |
| `core/api/graphql/query_nfs_artifact_collections.graphql` | GraphQL query for listing collections per type |
| `core/api/graphql/query_nfs_artifacts.graphql` | GraphQL query for listing artifact versions |
| `core/internal/nfs/client.go` | GraphQL client setup from API key |
| `core/internal/nfs/list.go` | Listing logic with pagination |
| `core/internal/nfs/output.go` | Tree-style output formatting |

### Files Modified

| File | Changes |
|------|---------|
| `core/cmd/wandb-core/main.go` | Added `nfs` subcommand dispatch, `nfsMain()`, and `nfsLs()` functions |
| `core/internal/gql/gql_gen.go` | Auto-generated - added `NFSArtifactTypes`, `NFSArtifactCollections`, `NFSArtifacts` functions |

### Problems Encountered and Resolutions

#### 1. GraphQL Schema Not Found

**Problem:** Running `go generate` failed because `schema-latest.graphql` was missing. The `generate-graphql.sh` script tries to clone `wandb/core` repo to get the schema.

**Resolution:** Downloaded schema manually using `gh` CLI:
```bash
gh api "repos/wandb/core/contents/services/gorilla/schema.graphql?ref=dd114cf9af2633d6d39de0adb068cb19b5dcd045" -q '.content' | base64 -d > core/api/graphql/schemas/schema-latest.graphql
```

Then ran genqlient directly:
```bash
cd core && go run ./cmd/generate_gql api/graphql/genqlient.yaml
```

#### 2. Interface Pointer Type Errors

**Problem:** Build failed with errors like:
```
edge.Node.GetName undefined (type *gql.NFSArtifact...ArtifactCollection is pointer to interface, not interface)
```

The genqlient library generates pointer-to-interface types for GraphQL union/interface types (like `ArtifactCollection` which can be `ArtifactPortfolio` or `ArtifactSequence`).

**Resolution:** Dereference the pointer before calling interface methods:
```go
// Wrong:
collName := edge.Node.GetName()

// Correct:
collName := (*edge.Node).GetName()
```

Same pattern for `ArtifactCollection.GetArtifacts()`:
```go
// Wrong:
artifacts := resp.Project.ArtifactType.ArtifactCollection.Artifacts

// Correct:
artifacts := (*resp.Project.ArtifactType.ArtifactCollection).GetArtifacts()
```

### Test Results

```bash
# Help works
$ ./wandb-core nfs --help
wandb-core nfs - List artifacts in a W&B project
Usage:
  wandb-core nfs ls <entity>/<project>
...

# Missing project path error
$ ./wandb-core nfs ls
Error: missing project path (entity/project)

# Missing API key error
$ ./wandb-core nfs ls test/test
Error: WANDB_API_KEY environment variable not set

# Invalid project path error
$ WANDB_API_KEY=test ./wandb-core nfs ls "invalid"
Error: invalid project path: expected entity/project, got "invalid"
```

### Usage

```bash
export WANDB_API_KEY="your-api-key"
./wandb-core nfs ls your-entity/your-project
```

### Next Steps (Phase 4)

Future enhancements to consider:
1. Add `query_nfs_artifact_files.graphql` to list files in each artifact version
2. Add `query_nfs_runs.graphql` to list runs in a project
3. Convert the listing logic into an NFS server for filesystem access

---

## Phase 5: NFS Server Implementation

### Status: COMPLETED

Implemented `wandb-core nfs serve <entity/project>` command that starts an NFSv4 server for browsing W&B artifacts.

### Folder Layout

```
/
└── artifacts/
    ├── types/
    │   ├── model/
    │   │   └── foo -> ../../collections/foo  (symlink)
    │   └── dataset/
    │       └── bar -> ../../collections/bar  (symlink)
    └── collections/
        └── foo/
            └── v0/
                ├── metadata.json
                └── files/
                    └── a.parquet
```

Collections under `types/{type}/` are symlinks pointing to `collections/{name}` to avoid duplicating the tree structure.

### Files Created

| File | Purpose |
|------|---------|
| `core/internal/nfs/wandbfs.go` | Main `fs.FS` implementation for W&B |
| `core/internal/nfs/wandbfs_node.go` | Virtual node tree structure with symlink support |
| `core/internal/nfs/wandbfs_file.go` | `fs.File` implementation (read-only) |
| `core/internal/nfs/wandbfs_fileinfo.go` | `fs.FileInfo` implementation |
| `core/internal/nfs/wandbfs_cache.go` | Lazy loading cache with TTL |
| `core/internal/nfs/audit.go` | Audit logging for client access |
| `core/internal/nfs/serve.go` | Server startup and command logic |
| `core/api/graphql/query_nfs_artifact_metadata.graphql` | Query for artifact metadata (id, digest, size, etc.) |
| `core/api/graphql/query_nfs_artifact_files.graphql` | Query for artifact files with size |

### Files Modified

| File | Changes |
|------|---------|
| `core/cmd/wandb-core/main.go` | Added `serve` subcommand with `--listen` flag |
| `core/go.mod` | Added `github.com/smallfz/libnfs-go` dependency |
| `core/internal/gql/gql_gen.go` | Auto-generated - added `NFSArtifactMetadata`, `NFSArtifactFiles` functions |

### Key Design Decisions

#### Symlink Support
- Set `SymlinkSupport: true` in FS attributes
- Collections under `types/{type}/` are symlink nodes pointing to `../../collections/{name}`
- `Readlink()` returns the symlink target path
- `Symlink()` (create) returns `os.ErrPermission` (read-only)

#### Lazy Loading Strategy
1. **Startup**: Only create root `/artifacts` node
2. **On Readdir**: Fetch and cache children from API
3. **Cache TTL**: Types 5min, Collections 1min, Files 5min

#### Handle Management
- Each node gets unique uint64 ID (starting at 1000)
- Handle = 8-byte big-endian encoded ID
- `nodeByID` map for O(1) resolution

#### Read-Only Enforcement
All write operations (`Chmod`, `Chown`, `Rename`, `Remove`, `MkdirAll`, `Write`, `Truncate`, `Symlink`) return `os.ErrPermission`

#### metadata.json Content
Each artifact version has a `metadata.json` containing:
```json
{
  "id": "QXJ0aWZhY3Q6MTIzNDU2",
  "versionIndex": 0,
  "digest": "abc123...",
  "size": 12345,
  "fileCount": 3,
  "createdAt": "2024-01-15T10:30:00Z",
  "description": "Model checkpoint",
  "state": "COMMITTED"
}
```

#### Audit Logging
Log to stdout via `slog.Info()`:
- `SetCreds()` - log client connection
- `Stat()` - log path lookups
- `Open()` - log file opens
- `Readdir()` - log directory listings

### Usage

```bash
# Build
cd core && go build -o wandb-core ./cmd/wandb-core

# Start NFS server
export WANDB_API_KEY=...
./wandb-core nfs serve entity/project 2>&1 | tee nfs-server.log

# With custom port
./wandb-core nfs serve --listen :3049 entity/project

# Mount (macOS)
mkdir -p /tmp/wandb-mount
sudo mount -t nfs -o vers=4,port=2049 localhost:/ /tmp/wandb-mount

# Browse
ls /tmp/wandb-mount/artifacts/
ls /tmp/wandb-mount/artifacts/types/
ls /tmp/wandb-mount/artifacts/collections/

# Unmount
sudo umount /tmp/wandb-mount
```

### Test Results

```bash
# Help works
$ ./wandb-core nfs --help
wandb-core nfs - NFS server for W&B artifacts

Usage:
  wandb-core nfs ls <entity>/<project>
  wandb-core nfs serve [--listen :2049] <entity>/<project>

Commands:
  ls      List artifacts in a project
  serve   Start NFS server to browse artifacts
...

# Serve help
$ ./wandb-core nfs serve --help
wandb-core nfs serve - Start NFS server for W&B artifacts

Usage:
  wandb-core nfs serve [--listen :2049] <entity>/<project>

Flags:
  --listen   Listen address (default: :2049)
...
```

### Future Enhancements

1. **Run files**: Add `/runs/` directory to browse run files
2. **Caching improvements**: Add cache invalidation on demand
3. **Authentication**: Support more auth methods beyond Unix credentials

---

## Phase 6: File Content Reading

### Status: COMPLETED

Implemented file content reading for the NFS server. Files are downloaded to a local cache on first access and served from disk on subsequent reads.

### Design Approach: Download-to-Cache

Uses the same cache directory structure as Python SDK for cache sharing:
- Location: `~/.cache/wandb/artifacts/obj/md5/{first2chars}/{rest}`
- Index by MD5 hash (from artifact file metadata)
- Download full file on first access, serve from cache afterward

### Files Modified

| File | Changes |
|------|---------|
| `core/api/graphql/query_nfs_artifact_files.graphql` | Added `directUrl` and `md5` fields |
| `core/internal/nfs/wandbfs_cache.go` | Added `FileContentCache` for disk-based caching, updated `ArtifactFileInfo` with URL/MD5 |
| `core/internal/nfs/wandbfs_file.go` | Implemented `Read()` with cache support, added `localFile` field |
| `core/internal/nfs/wandbfs.go` | Added `contentCache` field, pass DirectURL/MD5 to file nodes |
| `core/internal/nfs/wandbfs_node.go` | Added `DirectURL` and `MD5` fields |
| `core/internal/gql/gql_gen.go` | Auto-generated - added DirectUrl and Md5 fields |

### Key Implementation Details

#### FileContentCache
```go
type FileContentCache struct {
    cacheDir string  // ~/.cache/wandb/artifacts
    client   *http.Client
}

// GetOrDownload checks cache, downloads if needed
func (c *FileContentCache) GetOrDownload(ctx context.Context, md5B64, directURL string, size int64) (string, error)
```

#### WandBFile.Read() Flow
1. Check if `localFile` is already open
2. If not, call `ensureCached()` which:
   - Calls `contentCache.GetOrDownload()` with MD5, URL, size
   - Opens the cached file as `localFile`
3. Read from `localFile` at current position using `ReadAt()`

#### Cache Structure (Matches Python SDK)
```
~/.cache/wandb/artifacts/
├── obj/
│   └── md5/
│       ├── ab/
│       │   └── cdef1234...  (file content)
│       └── 12/
│           └── 3456789a...  (file content)
└── tmp/
    └── .download-*  (temp files during download)
```

### Usage

```bash
# Start server
./wandb-core nfs serve entity/project

# Mount
sudo mount -t nfs -o vers=4,port=2049 localhost:/ /tmp/wandb-mount

# Read file content (downloads on first access)
cat /tmp/wandb-mount/artifacts/collections/my-artifact/v0/files/model.pt

# Verify cache was populated
ls -la ~/.cache/wandb/artifacts/obj/md5/
```

### Cache Sharing with Python SDK

Files cached via NFS are usable by Python SDK and vice versa:
```python
import wandb
artifact = wandb.use_artifact('entity/project/my-artifact:v0')
path = artifact.get_path('model.pt').download()
# Instant if already cached via NFS
```

### Problems Encountered and Resolutions

#### "Operation not permitted" on File Read

**Problem:** After implementing file reading, `cat <file>` returned "Operation not permitted" for all files, including `metadata.json` which doesn't use signed URLs.

**Root Cause:** The libnfs-go library uses `os.O_RDWR` by default when opening files (see `vendor/github.com/smallfz/libnfs-go/nfs/implv4/open.go:265`):

```go
// libnfs-go open.go:265-272
flag := os.O_RDWR  // <-- Default is O_RDWR, not O_RDONLY!
if trunc {
    flag = flag | os.O_TRUNC
}
if f, err := vfs.OpenFile(pathName, flag, fi.Mode()); err != nil {
    log.Warnf("vfs.OpenFile(%s): %v", pathName, err)
    return resFailPerm, nil  // Returns NFS4ERR_PERM on ANY error
}
```

Our `OpenFile()` was rejecting `O_RDWR` as a write flag:

```go
// wandbfs.go - BUGGY CODE
if flag&(os.O_WRONLY|os.O_RDWR|os.O_CREATE|os.O_APPEND|os.O_TRUNC) != 0 {
    return nil, os.ErrPermission
}
```

**Resolution:** Remove `os.O_RDWR` from the rejection check since it includes read access:

```go
// wandbfs.go - FIXED
// Check for write-only flags (O_RDWR is allowed since it includes read)
if flag&(os.O_WRONLY|os.O_CREATE|os.O_APPEND|os.O_TRUNC) != 0 {
    return nil, os.ErrPermission
}
```

---

## libnfs-go Library Internals

Understanding the libnfs-go library internals was critical for debugging. Key findings:

### NFSv4 READ Operation Flow

```
Client: READ(stateId, offset, count)
    ↓
implv4/read.go:read()
    ↓
x.Stat().GetOpenedFile(seqId)  → Get file handle from state
    ↓
f.Seek(offset, io.SeekStart)   → Seek to requested position
    ↓
io.CopyN(buff, f, count)       → Read requested bytes
    ↓
Return READ4res{Data, Eof}
```

### NFSv4 OPEN Operation Flow

```
Client: OPEN(fileName, ...)
    ↓
implv4/open.go:open()
    ↓
flag := os.O_RDWR             → Default flag (not O_RDONLY!)
    ↓
vfs.OpenFile(path, flag, mode)
    ↓
If err != nil → return NFS4ERR_PERM (hides actual error)
```

### Key Files in libnfs-go

| File | Purpose |
|------|---------|
| `nfs/implv4/open.go` | NFSv4 OPEN implementation |
| `nfs/implv4/read.go` | NFSv4 READ implementation |
| `nfs/implv4/readdir.go` | NFSv4 READDIR implementation |
| `fs/api.go` | `fs.FS` and `fs.File` interfaces |
| `nfs/const.go` | NFS error codes (`NFS4ERR_PERM`, etc.) |

### fs.File Interface Requirements

```go
type File interface {
    Name() string
    Stat() (FileInfo, error)
    Read(p []byte) (int, error)
    Write(p []byte) (int, error)
    Seek(offset int64, whence int) (int64, error)
    Close() error
    Truncate() error
    Sync() error
    Readdir(n int) ([]FileInfo, error)
}
```

### Error Handling Quirks

**Important:** libnfs-go converts ANY error from `OpenFile()`, `Read()`, or `Seek()` to `NFS4ERR_PERM`:

```go
// open.go:271 - All errors become permission denied
if f, err := vfs.OpenFile(pathName, flag, fi.Mode()); err != nil {
    log.Warnf("vfs.OpenFile(%s): %v", pathName, err)
    return resFailPerm, nil  // NFS4ERR_PERM
}

// read.go:33-34 - Seek errors become permission denied
if _, err := f.Seek(int64(args.Offset), io.SeekStart); err != nil {
    return &nfs.READ4res{Status: nfs.NFS4ERR_PERM}, nil
}

// read.go:46-47 - Read errors (except EOF) become permission denied
if _, err := io.CopyN(buff, f, cnt); err != nil {
    if err != io.EOF {
        return &nfs.READ4res{Status: nfs.NFS4ERR_PERM}, nil
    }
}
```

This means server-side logging is essential for debugging - the NFS client only sees "permission denied".

### MaxRead Configuration

```go
// fs.Attributes controls read size
attributes: fs.Attributes{
    MaxRead:  1048576,  // 1MB per READ request
    MaxWrite: 1048576,
}
```

NFS clients will chunk large file reads into MaxRead-sized requests.
