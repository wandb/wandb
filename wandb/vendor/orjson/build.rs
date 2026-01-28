// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2021-2025)

fn main() {
    let python_config = pyo3_build_config::get();

    if python_config.is_free_threaded() && std::env::var("ORJSON_BUILD_FREETHREADED").is_err() {
        not_supported("free-threaded Python")
    }

    for cfg in python_config.build_script_outputs() {
        println!("{cfg}");
    }

    #[allow(unused_variables)]
    let is_64_bit_python = matches!(python_config.pointer_width, Some(64));

    match python_config.implementation {
        pyo3_build_config::PythonImplementation::CPython => {
            println!("cargo:rustc-cfg=CPython");
            #[cfg(any(target_arch = "x86_64", target_arch = "aarch64"))]
            if is_64_bit_python {
                println!("cargo:rustc-cfg=feature=\"inline_int\"");
            }
        }
        pyo3_build_config::PythonImplementation::GraalPy => not_supported("GraalPy"),
        pyo3_build_config::PythonImplementation::PyPy => not_supported("PyPy"),
    }

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=include/yyjson/*");
    println!("cargo:rerun-if-env-changed=CC");
    println!("cargo:rerun-if-env-changed=CFLAGS");
    println!("cargo:rerun-if-env-changed=LDFLAGS");
    println!("cargo:rerun-if-env-changed=ORJSON_BUILD_FREETHREADED");
    println!("cargo:rerun-if-env-changed=RUSTFLAGS");
    println!("cargo:rustc-check-cfg=cfg(cold_path)");
    println!("cargo:rustc-check-cfg=cfg(CPython)");
    println!("cargo:rustc-check-cfg=cfg(GraalPy)");
    println!("cargo:rustc-check-cfg=cfg(optimize)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_10)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_11)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_12)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_13)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_14)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_15)");
    println!("cargo:rustc-check-cfg=cfg(Py_3_9)");
    println!("cargo:rustc-check-cfg=cfg(Py_GIL_DISABLED)");
    println!("cargo:rustc-check-cfg=cfg(PyPy)");

    #[cfg(all(target_arch = "x86_64", not(target_os = "macos")))]
    if version_check::is_min_version("1.89.0").unwrap_or(false) && is_64_bit_python {
        println!("cargo:rustc-cfg=feature=\"avx512\"");
    }

    #[cfg(target_arch = "aarch64")]
    if version_check::supports_feature("portable_simd").unwrap_or(false) {
        println!("cargo:rustc-cfg=feature=\"generic_simd\"");
    }

    if version_check::supports_feature("cold_path").unwrap_or(false) {
        println!("cargo:rustc-cfg=feature=\"cold_path\"");
    }

    if version_check::supports_feature("optimize_attribute").unwrap_or(false) {
        println!("cargo:rustc-cfg=feature=\"optimize\"");
    }

    cc::Build::new()
        .file("include/yyjson/yyjson.c")
        .include("include/yyjson")
        .define("YYJSON_DISABLE_NON_STANDARD", "1")
        .define("YYJSON_DISABLE_UTF8_VALIDATION", "1")
        .define("YYJSON_DISABLE_UTILS", "1")
        .define("YYJSON_DISABLE_WRITER", "1")
        .compile("yyjson")
}

fn not_supported(flavor: &str) {
    let version = env!("CARGO_PKG_VERSION");
    eprintln!("\n\n\norjson v{version} does not support {flavor}\n\n\n");
    std::process::exit(1);
}
