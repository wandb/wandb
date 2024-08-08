# nvml-wrapper-sys Changelog

This file describes the changes / additions / fixes between bindings releases.

## Unreleased

## 0.8.0 (released 2024-02-10)

Bindings have been regenerated using the NVML 12.2 header and bindgen 0.68.1.

### Internal

* Bumped crate edition to `2021`

### Rust Version Support

The MSRV of this release is 1.60.0 (to match the wrapper crate).

## 0.7.0 (released 2023-01-20)

Bindings have been regenerated using the NVML 11.8 header and bindgen 0.63.0.

### Added

* The `legacy-functions` feature can now be enabled to access older function versions in the bindings.

### Rust Version Support

The MSRV of this release continues to be 1.51.0.

## 0.6.0 (released 2022-05-26)

### Release Summary

Bindings have been regenerated using the NVML 11.6 update 2 header and bindgen 0.59.2.

### Internal

* The generated layout tests have been removed from the bindings (see https://github.com/rust-lang/rust-bindgen/issues/1651 for rationale)

## 0.5.0 (released 2020-12-06)

### Release Summary

The NVML bindings have been regenerated using the [new dynamic loading bindgen feature](https://github.com/rust-lang/rust-bindgen/pull/1846) and for NVML 11. This means that this crate no longer needs to link to the NVML library at buildtime.

These bindings form a thin wrapper over [the `libloading` crate](https://github.com/nagisa/rust_libloading).

### Removed

* The `nvml.lib` import library has been removed from the crate as it is no longer needed now that NVML is loaded dynamically at runtime on Windows

### Dependencies

* `libloading`: new dependency on `0.6.6`

## 0.4.2 (released 2020-06-15)

### Release Summary

The crate was updated to Rust 2018 edition.

## 0.4.1 (released 2019-09-11)

### Release Summary

The Windows import library has been regenerated for NVML 10.1.

## 0.4.0 (released 2019-09-10)

### Release Summary

Bindings have been regenerated using the NVML 10.1 header and bindgen 0.50.0.

## 0.3.1 (released 2019-04-08)

### Release Summary

Improvements were made to the build script:

* An attempt will be made to locate the directory containing `libnvidia-ml.so` and it will be automatically added to the locations that the library is being searched for in. Thanks @SunDoge!
* The script will now display a helpful error message if compilation is attempted on macOS.

## 0.3.0 (released 2017-07-20)

### Release Summary

The `nightly` feature flag has been removed as unions are now available on stable Rust.

### Rust Version Support

This release **requires** and supports **Rust 1.19.0** or higher.

## 0.2.0 (released 2017-06-08)

### Release Summary

Rust `enum`s were removed in favor of numerical constants for C enums. This was done for safety reasons; see [rust-lang/rust#36927](https://github.com/rust-lang/rust/issues/36927) for more information.

### Changes

* Rust `enum`s replaced with numerical constants
* Replaced `::std::os::raw::x` paths with `raw::x` paths for readability
* Removed `Copy` and `Clone` from structs where they did not make sense
  * Forgot about this before

## 0.1.0 (released 2017-05-17)

### Release Summary

Initial release providing bindings for the entirety of the NVML API as well as nightly-only feature usage behind a feature flag.
