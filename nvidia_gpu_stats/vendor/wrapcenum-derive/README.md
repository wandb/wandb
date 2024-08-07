# wrapcenum-derive

Internal macro used in [nvml-wrapper](https://github.com/Cldfire/nvml-wrapper).

This macro is tied to the crate and is not meant for use by the general public.

Its purpose is to auto-generate both a `TryFrom` implementation converting an `i32`
into a Rust enum (specifically for converting a C enum represented as an integer that
has come over FFI) and an `as_c` method for converting the Rust enum back into an `i32`.

It wouldn't take much effort to turn this into something usable by others; if you're
interested feel free to contribute or file an issue asking me to put some work into it.

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
