# Kitty shared-memory frames

Set `Config.KittyMedium` to `KittyMediumSharedMemory`, or call
`Model.SetKittyMedium(picture.KittyMediumSharedMemory)` and run its returned
command. Direct transmission remains the default.

```go
pic := picture.NewWithConfig(picture.Config{
    Fit:         picture.FitFill,
    KittyMedium: picture.KittyMediumSharedMemory,
    KittyFormat: picture.KittyFormatPNG, // direct fallback format
})
defer pic.SetImage(nil) // release outstanding objects when disposing the model
```

Use the normal `Init`, `Update`, and `SetImage` command flow. Shared-memory frames
always contain straight-alpha RGBA. `KittyFrameMsg.Medium` and `.Format` report
what was actually used. Unsupported builds and creation failures fall back to
the selected direct format.

| Environment | Implementation |
| --- | --- |
| Browser (`js/wasm`) | `globalThis.ghosttyKittySharedMemory` installed by the terminal |
| macOS with CGO | POSIX `shm_open` / `mmap` / `shm_unlink` |
| Linux, with or without CGO | POSIX shared-memory objects under `/dev/shm` |
| macOS without CGO; other platforms | Direct fallback |

Native support requires a local terminal that implements Kitty `t=s` and can
access the same shared-memory namespace. `QueryKittySupport` (batched by `Init`)
checks this with a `t=s` query naming a one-pixel object; frames are sent direct
unless the terminal answers `OK`, so remote hosts, container namespaces, and
terminals without `t=s` fall back automatically. `KittySharedMemorySupported()` checks
producer support only.

Native objects use random `/ntc-` names, exclusive creation, and mode 0600.
Descriptors and mappings are closed after filling. The terminal reads and
unlinks each object. Submitted frames remain available while the terminal drains
its input; abandoned retired frames are removed after five seconds. Pending
objects are capped at 64 MiB per process, with direct fallback when that limit is
reached. Frames discarded before submission are unlinked immediately.
`SetImage(nil)` releases the model's current and retired objects.

Native tests include a separate reader process and delayed-consumption cleanup:

```sh
go test -race ./internal/kittyshm ./picture/...
CGO_ENABLED=0 go test ./internal/kittyshm ./picture
```

For an opt-in real-terminal check, run inside a local Kitty-capable terminal:

```sh
go test -c -o /tmp/kittyshm.test ./internal/kittyshm
NTCHARTS_SHM_TERMINAL_TEST=1 /tmp/kittyshm.test \
  -test.run='^TestNativeTerminalConsumesObject$' -test.v
```

On macOS, the normal CGO-enabled tests and the real-terminal check passed with
Ghostty 1.3.1. Linux ARM64 lifecycle tests also pass with the race detector on
dwarfspark, including the separate reader process and delayed-consumption cases.
This validates Linux object handling; it does not test a local Linux terminal's
shared-memory support. Browser tests pass under Node with the Bubble Tea WASM fork.
