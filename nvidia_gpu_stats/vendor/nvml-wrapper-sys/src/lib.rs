/*!
Rust bindings for the [NVIDIA Management Library][nvml] (NVML), a C-based programmatic
interface for monitoring and managing various states within NVIDIA GPUs.

It is intended to be a platform for building 3rd-party applications, and is also the
underlying library for NVIDIA's nvidia-smi tool.

See [`nvml-wrapper`][nvml-wrapper] for a safe wrapper over top of these bindings.

## Type of Bindings

These bindings were created using [bindgen]'s feature to generate wrappers over top
of the functionality that the [`libloading`][libloading] crate provides. This means
that they're designed for loading the NVML library at runtime; they are not suitable
for linking to NVML (statically or dynamically) at buildtime.

This choice was made because NVML is the type of library that you'd realistically
always want to load at runtime, for the following reasons:

* NVIDIA doesn't distribute static versions of NVML, so it isn't possible to statically
  link it anyway
* Linking to NVML at buildtime means the resulting binary can only be run on systems
  that have NVIDIA GPUs and well-formed NVIDIA driver installs

Loading NVML at runtime means it's possible to drop NVIDIA-related features at runtime
on systems that don't have relevant hardware.

I would be willing to consider maintaining both types of bindings in this crate if
there's a convincing reason to do so; please file an issue.

## NVML Support

These bindings were generated for NVML version 11. Each new version of NVML is
guaranteed to be backwards-compatible according to NVIDIA, so these bindings
should be useful regardless of NVML version bumps.

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

By default these bindings only include the newest versions of the functions.
Enable the `legacy-functions` feature if you require the ability to call older
functions.

[nvml]: https://developer.nvidia.com/nvidia-management-library-nvml
[nvml-wrapper]: https://github.com/Cldfire/nvml-wrapper
[bindgen]: https://github.com/rust-lang/rust-bindgen
[libloading]: https://github.com/nagisa/rust_libloading
*/

// bindgen generates code that triggers these lints
#![allow(clippy::missing_safety_doc)]
#![allow(clippy::redundant_static_lifetimes)]

// Generate bindings: ./gen_bindings.sh
//
// We avoid generating layout tests because they cause a large number of
// warnings and according to commentary are not useful. See
// https://github.com/rust-lang/rust-bindgen/issues/1651 for more.
pub mod bindings;
