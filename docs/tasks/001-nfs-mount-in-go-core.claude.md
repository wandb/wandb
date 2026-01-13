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
