# Changelog


## 3.11.5 - 2025-12-06

### Changed

- Show simple error message instead of traceback when attempting to
build on unsupported Python versions.


## 3.11.4 - 2025-10-24

### Changed

- ABI compatibility with CPython 3.15 alpha 1.
- Publish PyPI wheels for 3.14 and manylinux i686, manylinux arm7,
manylinux ppc64le, manylinux s390x.
- Build now requires a C compiler.


## 3.11.3 - 2025-08-26

### Fixed

- Fix PyPI project metadata when using maturin 1.9.2 or later.


## 3.11.2 - 2025-08-12

### Fixed

- Fix build using Rust 1.89 on amd64.

### Changed

- Build now depends on Rust 1.85 or later instead of 1.82.


## 3.11.1 - 2025-07-25

### Changed

- Publish PyPI wheels for CPython 3.14.

### Fixed

- Fix `str` on big-endian architectures. This was introduced in 3.11.0.


## 3.11.0 - 2025-07-15

### Changed

- Use a deserialization buffer allocated per request instead of a shared
buffer allocated on import.
- ABI compatibility with CPython 3.14 beta 4.


## 3.10.18 - 2025-04-29

### Fixed

- Fix incorrect escaping of the vertical tabulation character. This was
introduced in 3.10.17.


## 3.10.17 - 2025-04-29

### Changed

- Publish PyPI Windows aarch64/arm64 wheels.
- ABI compatibility with CPython 3.14 alpha 7.
- Fix incompatibility running on Python 3.13 using WASM.


## 3.10.16 - 2025-03-24

### Changed

- Improve performance of serialization on amd64 machines with AVX-512.
- ABI compatibility with CPython 3.14 alpha 6.
- Drop support for Python 3.8.
- Publish additional PyPI wheels for macOS that target only aarch64, macOS 15,
and recent Python.


## 3.10.15 - 2025-01-08

### Changed

- Publish PyPI manylinux aarch64 wheels built and tested on aarch64.
- Publish PyPI musllinux aarch64 and arm7l wheels built and tested on aarch64.
- Publish PyPI manylinux Python 3.13 wheels for i686, arm7l, ppc64le, and s390x.


## 3.10.14 - 2024-12-29

### Changed

- Specify build system dependency on `maturin>=1,<2` again.
- Allocate memory using `PyMem_Malloc()` and similar APIs for integration
with pymalloc, mimalloc, and tracemalloc.
- Source distribution does not ship compressed test documents and relevant
tests skip if fixtures are not present.
- Build now depends on Rust 1.82 or later instead of 1.72.


## 3.10.13 - 2024-12-29

### Changed

- Fix compatibility with maturin introducing a breaking change in 1.8.0 and
specify a fixed version of maturin. Projects relying on any previous version
being buildable from source by end users (via PEP 517) must upgrade to at
least this version.


## 3.10.12 - 2024-11-23

### Changed

- Publish PyPI manylinux i686 wheels.
- Publish PyPI musllinux i686 and arm7l wheels.
- Publish PyPI macOS wheels for Python 3.10 or later built on macOS 15.
- Publish PyPI Windows wheels using trusted publishing.


## 3.10.11 - 2024-11-01

### Changed

- Improve performance of UUIDs.
- Publish PyPI wheels with trusted publishing and PEP 740 attestations.
- Include text of licenses for vendored dependencies.


## 3.10.10 - 2024-10-22

### Fixed

- Fix `int` serialization on `s390x`. This was introduced in 3.10.8.

### Changed

- Publish aarch64 manylinux_2_17 wheel for 3.13 to PyPI.


## 3.10.9 - 2024-10-19

### Fixed

- Fix `int` serialization on 32-bit Python 3.8, 3.9, 3.10. This was
introduced in 3.10.8.


## 3.10.8 - 2024-10-19

### Changed

- `int` serialization no longer chains `OverflowError` to the
the `__cause__` attribute of `orjson.JSONEncodeError` when range exceeded.
- Compatibility with CPython 3.14 alpha 1.
- Improve performance.


## 3.10.7 - 2024-08-08

### Changed

- Improve performance of stable Rust amd64 builds.


## 3.10.6 - 2024-07-02

### Changed

- Improve performance.


## 3.10.5 - 2024-06-13

### Changed

- Improve performance.


## 3.10.4 - 2024-06-10

### Changed

- Improve performance.


## 3.10.3 - 2024-05-03

### Changed

- `manylinux` amd64 builds include runtime-detected AVX-512 `str`
implementation.
- Tests now compatible with numpy v2.


## 3.10.2 - 2024-05-01

### Fixed

- Fix crash serializing `str` introduced in 3.10.1.

### Changed

- Improve performance.
- Drop support for arm7.


## 3.10.1 - 2024-04-15

### Fixed

- Serializing `numpy.ndarray` with non-native endianness raises
`orjson.JSONEncodeError`.

### Changed

- Improve performance of serializing.


## 3.10.0 - 2024-03-27

### Changed

- Support serializing `numpy.float16` (`numpy.half`).
- sdist uses metadata 2.3 instead of 2.1.
- Improve Windows PyPI builds.


## 3.9.15 - 2024-02-23

### Fixed

- Implement recursion limit of 1024 on `orjson.loads()`.
- Use byte-exact read on `str` formatting SIMD path to avoid crash.


## 3.9.14 - 2024-02-14

### Fixed

- Fix crash serializing `str` introduced in 3.9.11.

### Changed

- Build now depends on Rust 1.72 or later.


## 3.9.13 - 2024-02-03

### Fixed

- Serialization `str` escape uses only 128-bit SIMD.
- Fix compatibility with CPython 3.13 alpha 3.

### Changed

- Publish `musllinux_1_2` instead of `musllinux_1_1` wheels.
- Serialization uses small integer optimization in CPython 3.12 or later.


## 3.9.12 - 2024-01-18

### Changed

- Update benchmarks in README.

### Fixed

- Minimal `musllinux_1_1` build due to sporadic CI failure.


## 3.9.11 - 2024-01-18

### Changed

- Improve performance of serializing. `str` is significantly faster. Documents
using `dict`, `list`, and `tuple` are somewhat faster.


## 3.9.10 - 2023-10-26

### Fixed

- Fix debug assert failure on 3.12 `--profile=dev` build.


## 3.9.9 - 2023-10-12

### Changed

- `orjson` module metadata explicitly marks subinterpreters as not supported.


## 3.9.8 - 2023-10-10

### Changed

- Improve performance.
- Drop support for Python 3.7.


## 3.9.7 - 2023-09-08

### Fixed

- Fix crash in `orjson.loads()` due to non-reentrant handling of persistent
buffer. This was introduced in 3.9.3.
- Handle some FFI removals in CPython 3.13.


## 3.9.6 - 2023-09-07

### Fixed

- Fix numpy reference leak on unsupported array dtype.
- Fix numpy.datetime64 reference handling.

### Changed

- Minor performance improvements.


## 3.9.5 - 2023-08-16

### Fixed

- Remove futex from module import and initialization path.


## 3.9.4 - 2023-08-07

### Fixed

- Fix hash builder using default values.
- Fix non-release builds of orjson copying large deserialization buffer
from stack to heap. This was introduced in 3.9.3.


## 3.9.3 - 2023-08-06

### Fixed

- Fix compatibility with CPython 3.12.

### Changed

- Support i686/x86 32-bit Python installs on Windows.


## 3.9.2 - 2023-07-07

### Fixed

- Fix the `__cause__` exception on `orjson.JSONEncodeError` possibly being
denormalized, i.e., of type `str` instead of `Exception`.


## 3.9.1 - 2023-06-09

### Fixed

- Fix memory leak on chained tracebacks of exceptions raised in `default`. This
was introduced in 3.8.12.


## 3.9.0 - 2023-06-01

### Added

- `orjson.Fragment` includes already-serialized JSON in a document.


## 3.8.14 - 2023-05-25

### Changed

- PyPI `manylinux` wheels are compiled for `x86-64` instead of `x86-64-v2`.


## 3.8.13 - 2023-05-23

### Changed

- Source distribution contains all source code required for an offline build.
- PyPI macOS wheels use a `MACOSX_DEPLOYMENT_TARGET` of 10.15 instead of 11.
- Build uses maturin v1.


## 3.8.12 - 2023-05-07

### Changed

- Exceptions raised in `default` are now chained as the `__cause__` attribute
on `orjson.JSONEncodeError`.


## 3.8.11 - 2023-04-27

### Changed

- `orjson.loads()` on an empty document has a specific error message.
- PyPI `manylinux_2_28_x86_64` wheels are compiled for `x86-64-v2`.
- PyPI macOS wheels are only `universal2` and compiled for
`x86-64-v2` and `apple-m1`.


## 3.8.10 - 2023-04-09

### Fixed

- Fix compatibility with CPython 3.12.0a7.
- Fix compatibility with big-endian architectures.
- Fix crash in serialization.

### Changed

- Publish musllinux 3.11 wheels.
- Publish s390x wheels.


## 3.8.9 - 2023-03-28

### Fixed

- Fix parallel initialization of orjson.


## 3.8.8 - 2023-03-20

### Changed

- Publish ppc64le wheels.


## 3.8.7 - 2023-02-28

### Fixed

- Use serialization backend introduced in 3.8.4 only on well-tested
platforms such as glibc, macOS by default.


## 3.8.6 - 2023-02-09

### Fixed

- Fix crash serializing when using musl libc.

### Changed

- Make `python-dateutil` optional in tests.
- Handle failure to load system timezones in tests.


## 3.8.5 - 2023-01-10

### Fixed

- Fix `orjson.dumps()` invalid output on Windows.


## 3.8.4 - 2023-01-04

### Changed

- Improve performance.


## 3.8.3 - 2022-12-02

### Fixed

- `orjson.dumps()` accepts `option=None` per `Optional[int]` type.


## 3.8.2 - 2022-11-20

### Fixed

- Fix tests on 32-bit for `numpy.intp` and `numpy.uintp`.

### Changed

- Build now depends on rustc 1.60 or later.
- Support building with maturin 0.13 or 0.14.


## 3.8.1 - 2022-10-25

### Changed

- Build maintenance for Python 3.11.


## 3.8.0 - 2022-08-27

### Changed

- Support serializing `numpy.int16` and `numpy.uint16`.


## 3.7.12 - 2022-08-14

### Fixed

- Fix datetime regression tests for tzinfo 2022b.

### Changed

- Improve performance.


## 3.7.11 - 2022-07-31

### Fixed

- Revert `dict` iterator implementation introduced in 3.7.9.


## 3.7.10 - 2022-07-30

### Fixed

- Fix serializing `dict` with deleted final item. This was introduced in 3.7.9.


## 3.7.9 - 2022-07-29

### Changed

- Improve performance of serializing.
- Improve performance of serializing pretty-printed (`orjson.OPT_INDENT_2`)
to be much nearer to compact.
- Improve performance of deserializing `str` input.
- orjson now requires Rust 1.57 instead of 1.54 to build.


## 3.7.8 - 2022-07-19

### Changed

- Build makes best effort instead of requiring "--features".
- Build using maturin 0.13.


## 3.7.7 - 2022-07-06

### Changed

- Support Python 3.11.


## 3.7.6 - 2022-07-03

### Changed

- Handle unicode changes in CPython 3.12.
- Build PyPI macOS wheels on 10.15 instead of 12 for compatibility.


## 3.7.5 - 2022-06-28

### Fixed

- Fix issue serializing dicts that had keys popped and replaced. This was
introduced in 3.7.4.


## 3.7.4 - 2022-06-28

### Changed

- Improve performance.

### Fixed

- Fix deallocation of `orjson.JSONDecodeError`.


## 3.7.3 - 2022-06-23


## Changed

- Improve build.
- Publish aarch64 musllinux wheels.


## 3.7.2 - 2022-06-07


## Changed

- Improve deserialization performance.


## 3.7.1 - 2022-06-03

### Fixed

- Type stubs for `orjson.JSONDecodeError` now inherit from
`json.JSONDecodeError` instead of `ValueError`
- Null-terminate the internal buffer of `orjson.dumps()` output.


## 3.7.0 - 2022-06-03

### Changed

- Improve deserialization performance significantly through the use of a new
backend. PyPI wheels for manylinux_2_28 and macOS have it enabled. Packagers
are advised to see the README.


## 3.6.9 - 2022-06-01

### Changed

- Improve serialization and deserialization performance.


## 3.6.8 - 2022-04-15

### Fixed

- Fix serialization of `numpy.datetime64("NaT")` to raise on an
unsupported type.


## 3.6.7 - 2022-02-14

### Changed

- Improve performance of deserializing almost-empty documents.
- Publish arm7l `manylinux_2_17` wheels to PyPI.
- Publish amd4 `musllinux_1_1` wheels to PyPI.

### Fixed

- Fix build requiring `python` on `PATH`.


## 3.6.6 - 2022-01-21

### Changed

- Improve performance of serializing `datetime.datetime` using `tzinfo` that
are `zoneinfo.ZoneInfo`.

### Fixed

- Fix invalid indexing in line and column number reporting in
`JSONDecodeError`.
- Fix `orjson.OPT_STRICT_INTEGER` not raising an error on
values exceeding a 64-bit integer maximum.


## 3.6.5 - 2021-12-05

### Fixed

- Fix build on macOS aarch64 CPython 3.10.
- Fix build issue on 32-bit.


## 3.6.4 - 2021-10-01

### Fixed

- Fix serialization of `dataclass` inheriting from `abc.ABC` and
using `__slots__`.
- Decrement refcount for numpy `PyArrayInterface`.
- Fix build on recent versions of Rust nightly.


## 3.6.3 - 2021-08-20

### Fixed

- Fix build on aarch64 using the Rust stable channel.


## 3.6.2 - 2021-08-17

### Changed

- `orjson` now compiles on Rust stable 1.54.0 or above. Use of some SIMD
usage is now disabled by default and packagers are advised to add
`--cargo-extra-args="--features=unstable-simd"` to the `maturin build` command
 if they continue to use nightly.
- `orjson` built with `--features=unstable-simd` adds UTF-8 validation
implementations that use AVX2 or SSE4.2.
- Drop support for Python 3.6.


## 3.6.1 - 2021-08-04

### Changed

- `orjson` now includes a `pyi` type stubs file.
- Publish manylinux_2_24 wheels instead of manylinux2014.

### Fixed

- Fix compilation on latest Rust nightly.


## 3.6.0 - 2021-07-08

### Added

- `orjson.dumps()` serializes `numpy.datetime64` instances as RFC 3339
strings.


## 3.5.4 - 2021-06-30

### Fixed

- Fix memory leak serializing `datetime.datetime` with `tzinfo`.
- Fix wrong error message when serializing an unsupported numpy type
without default specified.

### Changed

- Publish python3.10 and python3.9 manylinux_2_24 wheels.


## 3.5.3 - 2021-06-01

### Fixed

- `orjson.JSONDecodeError` now has `pos`, `lineno`, and `colno`.
- Fix build on recent versions of Rust nightly.


## 3.5.2 - 2021-04-15

### Changed

- Improve serialization and deserialization performance.
- `orjson.dumps()` serializes individual `numpy.bool_` objects.


## 3.5.1 - 2021-03-06

### Changed

- Publish `universal2` wheels for macOS supporting Apple Silicon (aarch64).


## 3.5.0 - 2021-02-24

### Added

- `orjson.loads()` supports reading from `memoryview` objects.

### Fixed

- `datetime.datetime` and `datetime.date` zero pad years less than 1000 to
four digits.
- sdist pins maturin 0.9.0 to avoid breaks in later 0.9.x.

### Changed

- `orjson.dumps()` when given a non-C contiguous `numpy.ndarray` has
an error message suggesting to use `default`.


## 3.4.8 - 2021-02-04

### Fixed

- aarch64 manylinux2014 wheels are now compatible with glibc 2.17.

### Changed

- Fix build warnings on ppcle64.


## 3.4.7 - 2021-01-19

### Changed

- Use vectorcall APIs for method calls on python3.9 and above.
- Publish python3.10 wheels for Linux on amd64 and aarch64.


## 3.4.6 - 2020-12-07

### Fixed

- Fix compatibility with debug builds of CPython.


## 3.4.5 - 2020-12-02

### Fixed

- Fix deserializing long strings on processors without AVX2.


## 3.4.4 - 2020-11-25

### Changed

- `orjson.dumps()` serializes integers up to a 64-bit unsigned integer's
maximum. It was previously the maximum of a 64-bit signed integer.


## 3.4.3 - 2020-10-30

### Fixed

- Fix regression in parsing similar `dict` keys.


## 3.4.2 - 2020-10-29

### Changed

- Improve deserialization performance.
- Publish Windows python3.9 wheel.
- Disable unsupported SIMD features on non-x86, non-ARM targets


## 3.4.1 - 2020-10-20

### Fixed

- Fix `orjson.dumps.__module__` and `orjson.loads.__module__` not being the
`str` "orjson".

### Changed

- Publish macos python3.9 wheel.
- More packaging documentation.


## 3.4.0 - 2020-09-25

### Added

- Serialize `numpy.uint8` and `numpy.int8` instances.

### Fixed

- Fix serializing `numpy.empty()` instances.

### Changed

- No longer publish `manylinux1` wheels due to tooling dropping support.


## 3.3.1 - 2020-08-17

### Fixed

- Fix failure to deserialize some latin1 strings on some platforms. This
was introduced in 3.2.0.
- Fix annotation of optional parameters on `orjson.dumps()` for `help()`.

### Changed

- Publish `manylinux2014` wheels for amd64 in addition to `manylinux1`.


## 3.3.0 - 2020-07-24

### Added

- `orjson.dumps()` now serializes individual numpy floats and integers, e.g.,
`numpy.float64(1.0)`.
- `orjson.OPT_PASSTHROUGH_DATACLASS` causes `orjson.dumps()` to pass
`dataclasses.dataclass` instances to `default`.


## 3.2.2 - 2020-07-13

### Fixed

- Fix serializing `dataclasses.dataclass` that have no attributes.

### Changed

- Improve deserialization performance of `str`.


## 3.2.1 - 2020-07-03

### Fixed

- Fix `orjson.dumps(..., **{})` raising `TypeError` on python3.6.


## 3.2.0 - 2020-06-30

### Added

- `orjson.OPT_APPEND_NEWLINE` appends a newline to output.

### Changed

- Improve deserialization performance of `str`.


## 3.1.2 - 2020-06-23

### Fixed

- Fix serializing zero-dimension `numpy.ndarray`.


## 3.1.1 - 2020-06-20

### Fixed

- Fix repeated serialization of `str` that are ASCII-only and have a legacy
(non-compact) layout.


## 3.1.0 - 2020-06-08

### Added

- `orjson.OPT_PASSTHROUGH_SUBCLASS` causes `orjson.dumps()` to pass
subclasses of builtin types to `default` so the caller can customize the
output.
- `orjson.OPT_PASSTHROUGH_DATETIME` causes `orjson.dumps()` to pass
`datetime` objects to `default` so the caller can customize the
output.


## 3.0.2 - 2020-05-27

### Changed

- `orjson.dumps()` does not serialize `dataclasses.dataclass` attributes
that begin with a leading underscore, e.g., `_attr`. This is because of the
Python idiom that a leading underscores marks an attribute as "private."
- `orjson.dumps()` does not serialize `dataclasses.dataclass` attributes that
are `InitVar` or `ClassVar` whether using `__slots__` or not.


## 3.0.1 - 2020-05-19

### Fixed

- `orjson.dumps()` raises an exception if the object to be serialized
is not given as a positional argument. `orjson.dumps({})` is intended and ok
while `orjson.dumps(obj={})` is an error. This makes it consistent with the
documentation, `help()` annotation, and type annotation.
- Fix orphan reference in exception creation that leaks memory until the
garbage collector runs.

### Changed

- Improve serialization performance marginally by using the fastcall/vectorcall
calling convention on python3.7 and above.
- Reduce build time.


## 3.0.0 - 2020-05-01

### Added

- `orjson.dumps()` serializes subclasses of `str`, `int`, `list`, and `dict`.

### Changed

- `orjson.dumps()` serializes `dataclasses.dataclass` and `uuid.UUID`
instances by default. The options `OPT_SERIALIZE_DATACLASS` and
`OPT_SERIALIZE_UUID` can still be specified but have no effect.


## 2.6.8 - 2020-04-30

### Changed

- The source distribution vendors a forked dependency.


## 2.6.7 - 2020-04-30

### Fixed

- Fix integer overflows in debug builds.

### Changed

- The source distribution sets the recommended RUSTFLAGS in `.cargo/config`.


## 2.6.6 - 2020-04-24

### Fixed

- Import `numpy` only on first use of `OPT_SERIALIZE_NUMPY` to reduce
interpreter start time when not used.
- Reduce build time by half.


## 2.6.5 - 2020-04-08

### Fixed

- Fix deserialization raising `JSONDecodeError` on some valid negative
floats with large exponents.


## 2.6.4 - 2020-04-08

### Changed

- Improve deserialization performance of floats by about 40%.


## 2.6.3 - 2020-04-01

### Changed

- Serialize `enum.Enum` objects.
- Minor performance improvements.


## 2.6.2 - 2020-03-27

### Changed

- Publish python3.9 `manylinux2014` wheel instead of `manylinux1` for `x86_64`.
- Publish python3.9 `manylinux2014` wheel for `aarch64`.

### Fixed

- Fix compilation failure on 32-bit.


## 2.6.1 - 2020-03-19

### Changed

- Serialization is 10-20% faster and uses about 50% less memory by writing
directly to the returned `bytes` object.


## 2.6.0 - 2020-03-10

### Added

- `orjson.dumps()` pretty prints with an indentation of two spaces if
`option=orjson.OPT_INDENT_2` is specified.


## 2.5.2 - 2020-03-07

### Changed

- Publish `manylinux2014` wheels for `aarch64`.
- numpy support now includes `numpy.uint32` and `numpy.uint64`.


## 2.5.1 - 2020-02-24

### Changed

- `manylinux1` wheels for 3.6, 3.7, and 3.8 are now compliant with the spec by
not depending on glibc 2.18.


## 2.5.0 - 2020-02-19

### Added

- `orjson.dumps()` serializes `dict` keys of type other than `str` if
`option=orjson.OPT_NON_STR_KEYS` is specified.


## 2.4.0 - 2020-02-14

### Added

- `orjson.dumps()` serializes `numpy.ndarray` instances if
`option=orjson.OPT_SERIALIZE_NUMPY` is specified.

### Fixed

- Fix `dataclasses.dataclass` attributes that are `dict` to be effected by
`orjson.OPT_SORT_KEYS`.


## 2.3.0 - 2020-02-12

### Added

- `orjson.dumps()` serializes `dict` instances sorted by keys, equivalent to
`sort_keys` in other implementations, if `option=orjson.OPT_SORT_KEYS` is
specified.

### Changed

- `dataclasses.dataclass` instances without `__slots__` now serialize faster.

### Fixed

- Fix documentation on `default`, in particular documenting the need to raise
an exception if the type cannot be handled.


## 2.2.2 - 2020-02-10

### Changed

- Performance improvements to serializing a list containing elements of the
same type.


## 2.2.1 - 2020-02-04

### Fixed

- `orjson.loads()` rejects floats that do not have a digit following
the decimal, e.g., `-2.`, `2.e-3`.

### Changed

- Build Linux, macOS, and Windows wheels on more recent distributions.


## 2.2.0 - 2020-01-22

### Added

- `orjson.dumps()` serializes `uuid.UUID` instances if
`option=orjson.OPT_SERIALIZE_UUID` is specified.

### Changed

- Minor performance improvements.
- Publish Python 3.9 wheel for Linux.


## 2.1.4 - 2020-01-08

### Fixed

- Specify a text signature for `orjson.loads()`.

### Changed

- Improve documentation.


## 2.1.3 - 2019-11-12

### Changed

- Publish Python 3.8 wheels for macOS and Windows.


## 2.1.2 - 2019-11-07

### Changed

- The recursion limit of `default` on `orjson.dumps()` has been increased from
5 to 254.


## 2.1.1 - 2019-10-29

### Changed

- Publish `manylinux1` wheels instead of `manylinux2010`.


## 2.1.0 - 2019-10-24

### Added

- `orjson.dumps()` serializes `dataclasses.dataclass` instances if
`option=orjson.OPT_SERIALIZE_DATACLASS` is specified.
- `orjson.dumps()` accepts `orjson.OPT_UTC_Z` to serialize UTC as "Z" instead
of "+00:00".
- `orjson.dumps()` accepts `orjson.OPT_OMIT_MICROSECONDS` to not serialize
the `microseconds` attribute of `datetime.datetime` and `datetime.time`
instances.
- `orjson.loads()` accepts `bytearray`.

### Changed

- Drop support for Python 3.5.
- Publish `manylinux2010` wheels instead of `manylinux1`.


## 2.0.11 - 2019-10-01

### Changed

- Publish Python 3.8 wheel for Linux.


## 2.0.10 - 2019-09-25

### Changed

- Performance improvements and lower memory usage in deserialization
by creating only one `str` object for repeated map keys.


## 2.0.9 - 2019-09-22

### Changed

- Minor performance improvements.

### Fixed

- Fix inaccurate zero padding in serialization of microseconds on
`datetime.time` objects.


## 2.0.8 - 2019-09-18

### Fixed

- Fix inaccurate zero padding in serialization of microseconds on
`datetime.datetime` objects.


## 2.0.7 - 2019-08-29

### Changed

- Publish PEP 517 source distribution.

### Fixed

- `orjson.dumps()` raises `JSONEncodeError` on circular references.


## 2.0.6 - 2019-05-11

### Changed

- Performance improvements.


## 2.0.5 - 2019-04-19

### Fixed

- Fix inaccuracy in deserializing some `float` values, e.g.,
31.245270191439438 was parsed to 31.24527019143944. Serialization was
unaffected.


## 2.0.4 - 2019-04-02

### Changed

- `orjson.dumps()` now serializes `datetime.datetime` objects without a
`tzinfo` rather than raising `JSONEncodeError`.


## 2.0.3 - 2019-03-23

### Changed

- `orjson.loads()` uses SSE2 to validate `bytes` input.


## 2.0.2 - 2019-03-12

### Changed

- Support Python 3.5.


## 2.0.1 - 2019-02-05

### Changed

- Publish Windows wheel.


## 2.0.0 - 2019-01-28

### Added

- `orjson.dumps()` accepts a `default` callable to serialize arbitrary
types.
- `orjson.dumps()` accepts `datetime.datetime`, `datetime.date`,
and `datetime.time`. Each is serialized to an RFC 3339 string.
- `orjson.dumps(..., option=orjson.OPT_NAIVE_UTC)` allows serializing
`datetime.datetime` objects that do not have a timezone set as UTC.
- `orjson.dumps(..., option=orjson.OPT_STRICT_INTEGER)` available to
raise an error on integer values outside the 53-bit range of all JSON
implementations.

### Changed

- `orjson.dumps()` no longer accepts `bytes`.


## 1.3.1 - 2019-01-03

### Fixed

- Handle invalid UTF-8 in str.


## 1.3.0 - 2019-01-02

### Changed

- Performance improvements of 15-25% on serialization, 10% on deserialization.


## 1.2.1 - 2018-12-31

### Fixed

- Fix memory leak in deserializing dict.


## 1.2.0 - 2018-12-16

### Changed

- Performance improvements.


## 1.1.0 - 2018-12-04

### Changed

- Performance improvements.

### Fixed

- Dict key can only be str.


## 1.0.1 - 2018-11-26

### Fixed

- pyo3 bugfix update.


## 1.0.0 - 2018-11-23

### Added

- `orjson.dumps()` function.
- `orjson.loads()` function.
