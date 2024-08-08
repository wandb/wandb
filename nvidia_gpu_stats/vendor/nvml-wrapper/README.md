# nvml-wrapper

[![Docs.rs docs](https://docs.rs/nvml-wrapper/badge.svg)](https://docs.rs/nvml-wrapper)
[![Crates.io version](https://img.shields.io/crates/v/nvml-wrapper.svg?style=flat-square)](https://crates.io/crates/nvml-wrapper)
[![Crates.io downloads](https://img.shields.io/crates/d/nvml-wrapper.svg?style=flat-square)](https://crates.io/crates/nvml-wrapper)
![CI](https://github.com/Cldfire/nvml-wrapper/workflows/CI/badge.svg)
[![dependency status](https://deps.rs/repo/github/cldfire/nvml-wrapper/status.svg)](https://deps.rs/repo/github/cldfire/nvml-wrapper)

A safe and ergonomic Rust wrapper for the [NVIDIA Management Library][nvml] (NVML),
a C-based programmatic interface for monitoring and managing various states within
NVIDIA GPUs.

```rust
use nvml_wrapper::Nvml;

let nvml = Nvml::init()?;
// Get the first `Device` (GPU) in the system
let device = nvml.device_by_index(0)?;

let brand = device.brand()?; // GeForce on my system
let fan_speed = device.fan_speed(0)?; // Currently 17% on my system
let power_limit = device.enforced_power_limit()?; // 275k milliwatts on my system
let encoder_util = device.encoder_utilization()?; // Currently 0 on my system; Not encoding anything
let memory_info = device.memory_info()?; // Currently 1.63/6.37 GB used on my system

// ... and there's a whole lot more you can do. Most everything in NVML is wrapped and ready to go
```

_try the [`basic_usage`](nvml-wrapper/examples/basic_usage.rs) example on your system_

NVML is intended to be a platform for building 3rd-party applications, and is
also the underlying library for NVIDIA's nvidia-smi tool.

## Usage

`nvml-wrapper` builds on top of generated bindings for NVML that make use of the
[`libloading`][libloading] crate. This means the NVML library gets loaded upon
calling `Nvml::init` and can return an error if NVML isn't present, making it
possible to drop NVIDIA-related features in your code at runtime on systems that
don't have relevant hardware.

Successful execution of `Nvml::init` means:

* The NVML library was present on the system and able to be opened
* The function symbol to initialize NVML was loaded and called successfully
* An attempt has been made to load all other NVML function symbols

Every function you call thereafter will individually return an error if it couldn't
be loaded from the NVML library during the `Nvml::init` call.

Note that it's not advised to repeatedly call `Nvml::init` as the constructor
has to perform all the work of loading the function symbols from the library
each time it gets called. Instead, call `Nvml::init` once and store the resulting
`Nvml` instance somewhere to be accessed throughout the lifetime of your program
(perhaps in a [`once_cell`][once_cell]).

## NVML Support

This wrapper is being developed against and currently supports NVML version
11. Each new version of NVML is guaranteed to be backwards-compatible according
to NVIDIA, so this wrapper should continue to work without issue regardless of
NVML version bumps.

### Legacy Functions

Sometimes there will be function-level API version bumps in new NVML releases.
For example:

```text
nvmlDeviceGetComputeRunningProcesses
nvmlDeviceGetComputeRunningProcesses_v2
nvmlDeviceGetComputeRunningProcesses_v3
```

The older versions of the functions will generally continue to work with the
newer NVML releases; however, the newer function versions will not work with
older NVML installs.

By default this wrapper only provides access to the newest function versions.
Enable the `legacy-functions` feature if you require the ability to call older
functions.

## MSRV

The Minimum Supported Rust Version is currently 1.60.0. I will not go out of my
way to avoid bumping this.

## Cargo Features

The `serde` feature can be toggled on in order to `#[derive(Serialize, Deserialize)]`
for every NVML data structure.

#### License

<sup>
Licensed under either of <a href="LICENSE-APACHE">Apache License, Version
2.0</a> or <a href="LICENSE-MIT">MIT license</a> at your option.
</sup>

<br>

<sub>
Unless you explicitly state otherwise, any contribution intentionally submitted
for inclusion in this crate by you, as defined in the Apache-2.0 license, shall
be dual licensed as above, without any additional terms or conditions.
</sub>

[nvml]: https://developer.nvidia.com/nvidia-management-library-nvml
[libloading]: https://github.com/nagisa/rust_libloading
[once_cell]: https://docs.rs/once_cell/latest/once_cell/sync/struct.Lazy.html
