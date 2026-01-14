# 001 NFS mount in go-core

Support a read only NFS mount using go core for artifact and run files.

## Status

- [x] nfs server for artifact, can list artifacts, files and read file content
  - [ ] does not support run, metrics and run files
- [x] go cli that list artifacts only, `wandb-core nfs ls <entity/project>`
  - [ ] does not support `~/.netrc` have to `export WANDB_API_KEY=...`

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

## NFS v4 using libnfs-go

I have cloned the repo locally at `~/go/src/github.com/smallfz/libnfs-go/examples/server`

- It ships with exampme memfs and disk fs implementation, which can be good reference
- You need to update go mod to use the library, it should be published

I want to have `wandb-core nfs serve <entity/project>` command that starts the NFS server similar to the example.
For beginning, we can just support listing artifact collections and their versions.
I want the folder layout to look following

```text
artifacts/
   types/
      model/
        foo/
          v0
      dataset/
   collections/
      foo/
         v0/
           metadata.json
           files/
              a.parquet
```

Now need to actually list files within in the artifacts.
For simplicity we do NOT allow

- Any write operation
- Read file content (we will implement that later)

I want to implement a audit log logic to know which nfs client has accessed what file/folder.

For test

- You can run the go server in background with tee to show the log in both stdout and a file.
- You should be able to mount the nfs in folder you created, remember to create a folder before mounting on it.

Trial run

```bash
# Start the NFS server
./wandb-core nfs serve reg-team-2/pinglei-benchmark

# With custom port
./wandb-core nfs serve --listen :3049 entity/project

# Mount (macOS)
mkdir -p /tmp/wandb-mount
# NOTE: You do NOT need sudo
mount -t nfs -o vers=4,port=2049 localhost:/ /tmp/wandb-mount

# Browse
ls /tmp/wandb-mount/artifacts/types/
ls /tmp/wandb-mount/artifacts/collections/
# Open entire folder in your favorite editor!
cursor /tmp/wandb-mount

# Unmount
umount /tmp/wandb-mount
```

## Read file in NFS

Now we can list but cannot read file content.
Implement read file logic.

First read the nfs library and protocol to see what we need to implement.
A naive approach is simply download entire file content to local disk
and read from local disk.

For caching file on local disk, existing wandb sdk already has a standard
file cache location and checksum logic, we can consider reuse that so that
files cached on nfs server can be used by python sdk and vice versa.

A better approach can be reading file by range using http range header.
Which is supported by object storage and used for parallel file download.
NOTE: the download in go core is still in serial for now (unlike python),
we can stay with it for now.

```bash
cd ~/go/src/github.com/wandb/wandb-nfs/core && go build -o wandb-core ./cmd/wandb-core
```

Seems it cached at `~/.cache/wandb/artifacts/obj/md5/{hex}/` need to verify that.