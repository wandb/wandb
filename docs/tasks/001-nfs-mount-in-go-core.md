# 001 NFS mount in go-core

Support a read only NFS mount using go core for artifact and run files.

## Status

- [x] go cli that list artifacts only, `wandb-core nfs ls <entity/project>`
 - [ ] does not support `~/.netrc`

## Background

Right now we can only download artifact and run files using python sdk.
This is a waste of resource if we just want to poke around to see the files.
Providing a actual file system makes it easier for both human and agent
to interact with the files (model, dataset, log, metrics etc.) easier.

Performance is not our main concern, we accept the fact that using a 
file system interface is not the fastest way to interactive with object storage,
which backs all the wandb aritifact, run files, metrics export in parquet.

Current status

- You can run go core directly without wandb run spawning it as background process, e.g. `wandb beta leet`
- Go core has upload artifact run file logic, download logic is there but might requires a run to use

## go cli to list artifacts and runs of a project

Before starting with NFS, I want to make sure we can actually, given a project (entity/project), do
the following in Go (i.e. without using python sdk):

- list artifacts in a project
- list files in an artifact
- list runs in a project

For example given a command like, we can get output like:

```
wandb nfs ls reg-team-2/pinglei-benchmark
```

```text
artifacts/
   long-text
     v0
       a.parquet
runs/
   run-abc
```

Once we have that, we can convert that logic into a NFS server.

Instructions for claude

- Go through existing codebase carefully
- Use the graphql API, most graphql API should have generated go and python code already
- Focus on a small part first, e.g. you can only focus on listing artifacts, there should be many useful example in our system tests (though mostly in python ...)
- Write down the plan doc in `docs/tasks/001-nfs-mount-in-go-core.claude.md`

Trial run

```bash
export WANDB_API_KEY=...

./core/wandb-core nfs ls reg-team-2/pinglei-benchmark        
2026/01/13 13:58:36 [DEBUG] POST https://api.wandb.ai/graphql
2026/01/13 13:58:36 [DEBUG] POST https://api.wandb.ai/graphql
2026/01/13 13:58:37 [DEBUG] POST https://api.wandb.ai/graphql
2026/01/13 13:58:37 [DEBUG] POST https://api.wandb.ai/graphql
2026/01/13 13:58:37 [DEBUG] POST https://api.wandb.ai/graphql
2026/01/13 13:58:37 [DEBUG] POST https://api.wandb.ai/graphql
Qwen-Qwen3-VL-2B-Instruct-20260113-2137/
   v0
run-jhidltab-history/
   v0
run-unmgo349-history/
   v0
```