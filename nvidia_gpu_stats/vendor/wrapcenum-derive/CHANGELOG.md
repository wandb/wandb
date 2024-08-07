# wrapcenum-derive Changelog

This file describes the changes / additions / fixes between macro releases.

## 0.4.1 (released 2024-02-10)

### Release Summary

Bumped dependency versions to the latest. ([#2](https://github.com/Cldfire/wrapcenum-derive/pull/2) - @KYovchevski)

### Dependencies

* `syn`: `1.0` -> `2.0`
* `darling`: `0.10` -> `0.20`

## 0.4.0 (released 2020-06-15)

### Release Summary

Re-wrote the macro to use `darling` and the `1.0` versions of `syn` and `quote`.

### Changes

The error type that is expected to be in scope is now `NvmlError`.

### Removals

* Support for the `default` attribute has been removed

## 0.3.0 (released 2017-07-20)

### Changes

The `UnexpectedVariant` error kind is now expected to hold the value that caused the error.

## 0.2.0 (released 2017-06-08)

### Release Summary

The macro is now meant to be used with numerical constants instead of Rust enums. This was done for safety reasons; see [rust-lang/rust#36927](https://github.com/rust-lang/rust/issues/36927) for more information.

### Changes

* `has_count` attribute removed and replaced with `default`

## 0.1.0 (released 2017-05-17)

### Release Summary

Initial release providing the functionality necessary to wrap Rust `enum`-based C enum bindings.

```text
derive on Rust enum `Foo`
`Foo` wraps Rust enum `Bar`
`Bar` was auto-generated within bindings for C enum `Bar`
```
