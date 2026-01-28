// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2018-2025)

#![cfg_attr(feature = "optimize", feature(optimize_attribute))]
#![cfg_attr(feature = "generic_simd", feature(portable_simd))]
#![cfg_attr(feature = "cold_path", feature(cold_path))]
#![allow(non_camel_case_types)]
#![allow(stable_features)] // MSRV
#![allow(static_mut_refs)]
#![allow(unknown_lints)] // internal_features
#![allow(unused_unsafe)]
#![warn(clippy::correctness)]
#![warn(clippy::suspicious)]
#![warn(clippy::complexity)]
#![warn(clippy::perf)]
#![warn(clippy::style)]
#![allow(clippy::absolute_paths)]
#![allow(clippy::allow_attributes)]
#![allow(clippy::allow_attributes_without_reason)]
#![allow(clippy::arbitrary_source_item_ordering)]
#![allow(clippy::arithmetic_side_effects)]
#![allow(clippy::decimal_literal_representation)]
#![allow(clippy::default_numeric_fallback)]
#![allow(clippy::doc_markdown)]
#![allow(clippy::enum_variant_names)]
#![allow(clippy::explicit_iter_loop)]
#![allow(clippy::host_endian_bytes)]
#![allow(clippy::if_not_else)]
#![allow(clippy::implicit_return)]
#![allow(clippy::incompatible_msrv)] // MSRV 1.89
#![allow(clippy::inline_always)]
#![allow(clippy::let_underscore_untyped)]
#![allow(clippy::missing_assert_message)]
#![allow(clippy::missing_docs_in_private_items)]
#![allow(clippy::missing_inline_in_public_items)]
#![allow(clippy::missing_panics_doc)]
#![allow(clippy::missing_safety_doc)]
#![allow(clippy::module_name_repetitions)]
#![allow(clippy::multiple_unsafe_ops_per_block)]
#![allow(clippy::needless_lifetimes)]
#![allow(clippy::question_mark_used)]
#![allow(clippy::redundant_else)]
#![allow(clippy::redundant_field_names)]
#![allow(clippy::renamed_function_params)]
#![allow(clippy::semicolon_outside_block)]
#![allow(clippy::single_call_fn)]
#![allow(clippy::undocumented_unsafe_blocks)]
#![allow(clippy::unreachable)]
#![allow(clippy::unreadable_literal)]
#![allow(clippy::unusual_byte_groupings)]
#![allow(clippy::unwrap_in_result)]
#![allow(clippy::unwrap_used)]
#![allow(clippy::upper_case_acronyms)]
#![allow(clippy::zero_prefixed_literal)]
#![warn(clippy::elidable_lifetime_names)]
#![warn(clippy::ptr_arg)]
#![warn(clippy::ptr_as_ptr)]
#![warn(clippy::ptr_cast_constness)]
#![warn(clippy::ptr_eq)]
#![warn(clippy::redundant_allocation)]
#![warn(clippy::redundant_clone)]
#![warn(clippy::redundant_locals)]
#![warn(clippy::redundant_slicing)]
#![warn(clippy::semicolon_inside_block)]
#![warn(clippy::size_of_ref)]
#![warn(clippy::std_instead_of_core)]
#![warn(clippy::trivially_copy_pass_by_ref)]
#![warn(clippy::unnecessary_semicolon)]
#![warn(clippy::unnecessary_wraps)]
#![warn(clippy::zero_ptr)]

#[cfg(feature = "unwind")]
extern crate unwinding;

#[macro_use]
mod util;

mod alloc;
mod deserialize;
mod exception;
mod ffi;
mod opt;
mod serialize;
mod str;
mod typeref;

use core::ffi::{c_char, c_int, c_void};
use core::ptr::{NonNull, null, null_mut};

use crate::deserialize::deserialize;
use crate::exception::{
    raise_dumps_exception_dynamic, raise_dumps_exception_fixed, raise_loads_exception,
};
use crate::ffi::{
    METH_KEYWORDS, METH_O, Py_SIZE, Py_ssize_t, PyCFunction_NewEx, PyLong_AsLong, PyMethodDef,
    PyMethodDefPointer, PyModuleDef, PyModuleDef_HEAD_INIT, PyModuleDef_Slot, PyObject,
    PyUnicode_FromStringAndSize, PyUnicode_InternFromString, PyVectorcall_NARGS,
};
use crate::serialize::serialize;
use crate::util::{isize_to_usize, usize_to_isize};

#[cfg(Py_3_13)]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        crate::ffi::PyModule_Add($mptr, $name.as_ptr(), $obj);
    };
}

#[cfg(all(Py_3_10, not(Py_3_13)))]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        crate::ffi::PyModule_AddObjectRef($mptr, $name.as_ptr(), $obj);
    };
}

#[cfg(not(Py_3_10))]
macro_rules! add {
    ($mptr:expr, $name:expr, $obj:expr) => {
        crate::ffi::PyModule_AddObject($mptr, $name.as_ptr(), $obj);
    };
}

macro_rules! opt {
    ($mptr:expr, $name:expr, $opt:expr) => {
        #[cfg(all(not(target_os = "windows"), target_pointer_width = "64"))]
        crate::ffi::PyModule_AddIntConstant($mptr, $name.as_ptr(), i64::from($opt));
        #[cfg(all(not(target_os = "windows"), target_pointer_width = "32"))]
        crate::ffi::PyModule_AddIntConstant($mptr, $name.as_ptr(), $opt as i32);
        #[cfg(target_os = "windows")]
        crate::ffi::PyModule_AddIntConstant($mptr, $name.as_ptr(), $opt as i32);
    };
}

#[allow(non_snake_case)]
#[unsafe(no_mangle)]
#[cold]
#[cfg_attr(not(Py_3_10), allow(deprecated))] // _PyCFunctionFastWithKeywords
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) unsafe extern "C" fn orjson_init_exec(mptr: *mut PyObject) -> c_int {
    unsafe {
        typeref::init_typerefs();

        {
            let version = env!("CARGO_PKG_VERSION");
            let pyversion = PyUnicode_FromStringAndSize(
                version.as_ptr().cast::<c_char>(),
                usize_to_isize(version.len()),
            );
            add!(mptr, c"__version__", pyversion);
        }

        {
            let dumps_doc = c"dumps(obj, /, default=None, option=None)\n--\n\nSerialize Python objects to JSON.";

            let wrapped_dumps = Box::new(PyMethodDef {
                ml_name: c"dumps".as_ptr(),
                ml_meth: PyMethodDefPointer {
                    #[cfg(Py_3_10)]
                    PyCFunctionFastWithKeywords: dumps,
                    #[cfg(not(Py_3_10))]
                    _PyCFunctionFastWithKeywords: dumps,
                },
                ml_flags: crate::ffi::METH_FASTCALL | METH_KEYWORDS,
                ml_doc: dumps_doc.as_ptr(),
            });

            let func = PyCFunction_NewEx(
                Box::into_raw(wrapped_dumps),
                null_mut(),
                PyUnicode_InternFromString(c"orjson".as_ptr()),
            );
            add!(mptr, c"dumps", func);
        }

        {
            let loads_doc = c"loads(obj, /)\n--\n\nDeserialize JSON to Python objects.";

            let wrapped_loads = Box::new(PyMethodDef {
                ml_name: c"loads".as_ptr(),
                ml_meth: PyMethodDefPointer { PyCFunction: loads },
                ml_flags: METH_O,
                ml_doc: loads_doc.as_ptr(),
            });
            let func = PyCFunction_NewEx(
                Box::into_raw(wrapped_loads),
                null_mut(),
                PyUnicode_InternFromString(c"orjson".as_ptr()),
            );
            add!(mptr, c"loads", func);
        }

        add!(mptr, c"Fragment", typeref::FRAGMENT_TYPE.cast::<PyObject>());

        opt!(mptr, c"OPT_APPEND_NEWLINE", opt::APPEND_NEWLINE);
        opt!(mptr, c"OPT_FAIL_ON_INVALID_FLOAT", opt::FAIL_ON_INVALID_FLOAT);
        opt!(mptr, c"OPT_INDENT_2", opt::INDENT_2);
        opt!(mptr, c"OPT_NAIVE_UTC", opt::NAIVE_UTC);
        opt!(mptr, c"OPT_NON_STR_KEYS", opt::NON_STR_KEYS);
        opt!(mptr, c"OPT_OMIT_MICROSECONDS", opt::OMIT_MICROSECONDS);
        opt!(
            mptr,
            c"OPT_PASSTHROUGH_DATACLASS",
            opt::PASSTHROUGH_DATACLASS
        );
        opt!(mptr, c"OPT_PASSTHROUGH_DATETIME", opt::PASSTHROUGH_DATETIME);
        opt!(mptr, c"OPT_PASSTHROUGH_SUBCLASS", opt::PASSTHROUGH_SUBCLASS);
        opt!(mptr, c"OPT_SERIALIZE_DATACLASS", opt::SERIALIZE_DATACLASS);
        opt!(mptr, c"OPT_SERIALIZE_NUMPY", opt::SERIALIZE_NUMPY);
        opt!(mptr, c"OPT_SERIALIZE_UUID", opt::SERIALIZE_UUID);
        opt!(mptr, c"OPT_SORT_KEYS", opt::SORT_KEYS);
        opt!(mptr, c"OPT_STRICT_INTEGER", opt::STRICT_INTEGER);
        opt!(mptr, c"OPT_UTC_Z", opt::UTC_Z);

        add!(mptr, c"JSONDecodeError", typeref::JsonDecodeError);
        add!(mptr, c"JSONEncodeError", typeref::JsonEncodeError);

        0
    }
}

#[allow(non_snake_case)]
#[unsafe(no_mangle)]
#[cold]
#[cfg_attr(feature = "optimize", optimize(size))]
pub(crate) unsafe extern "C" fn PyInit_orjson() -> *mut PyModuleDef {
    #[cfg(not(Py_3_12))]
    const PYMODULEDEF_LEN: usize = 2;
    #[cfg(all(Py_3_12, not(Py_3_13)))]
    const PYMODULEDEF_LEN: usize = 3;
    #[cfg(Py_3_13)]
    const PYMODULEDEF_LEN: usize = 4;
    unsafe {
        let mod_slots: Box<[PyModuleDef_Slot; PYMODULEDEF_LEN]> = Box::new([
            PyModuleDef_Slot {
                slot: crate::ffi::Py_mod_exec,
                #[allow(clippy::fn_to_numeric_cast_any, clippy::as_conversions)]
                value: orjson_init_exec as *mut c_void,
            },
            #[cfg(Py_3_12)]
            PyModuleDef_Slot {
                slot: crate::ffi::Py_mod_multiple_interpreters,
                value: crate::ffi::Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED,
            },
            #[cfg(Py_3_13)]
            PyModuleDef_Slot {
                slot: crate::ffi::Py_mod_gil,
                value: crate::ffi::Py_MOD_GIL_USED,
            },
            PyModuleDef_Slot {
                slot: 0,
                value: null_mut(),
            },
        ]);

        let init = Box::new(PyModuleDef {
            m_base: PyModuleDef_HEAD_INIT,
            m_name: c"orjson".as_ptr(),
            m_doc: null(),
            m_size: 0,
            m_methods: null_mut(),
            m_slots: Box::into_raw(mod_slots).cast::<PyModuleDef_Slot>(),
            m_traverse: None,
            m_clear: None,
            m_free: None,
        });
        let init_ptr = Box::into_raw(init);
        ffi!(PyModuleDef_Init(init_ptr));
        init_ptr
    }
}

#[unsafe(no_mangle)]
pub(crate) unsafe extern "C" fn loads(_self: *mut PyObject, obj: *mut PyObject) -> *mut PyObject {
    deserialize(obj).map_or_else(raise_loads_exception, NonNull::as_ptr)
}

#[cfg(CPython)]
macro_rules! matches_kwarg {
    ($val:expr, $ref:expr) => {
        unsafe { core::ptr::eq($val, $ref) }
    };
}

#[cfg(not(CPython))]
macro_rules! matches_kwarg {
    ($val:expr, $ref:expr) => {
        unsafe { crate::ffi::PyObject_Hash($val) == crate::ffi::PyObject_Hash($ref) }
    };
}

#[unsafe(no_mangle)]
pub(crate) unsafe extern "C" fn dumps(
    _self: *mut PyObject,
    args: *const *mut PyObject,
    nargs: Py_ssize_t,
    kwnames: *mut PyObject,
) -> *mut PyObject {
    unsafe {
        let mut default: Option<NonNull<PyObject>> = None;
        let mut optsptr: Option<NonNull<PyObject>> = None;

        let num_args = PyVectorcall_NARGS(isize_to_usize(nargs));
        if num_args == 0 {
            cold_path!();
            return raise_dumps_exception_fixed(
                "dumps() missing 1 required positional argument: 'obj'",
            );
        }
        if num_args & 2 == 2 {
            default = Some(NonNull::new_unchecked(*args.offset(1)));
        }
        if num_args & 3 == 3 {
            optsptr = Some(NonNull::new_unchecked(*args.offset(2)));
        }
        if !kwnames.is_null() {
            cold_path!();
            for i in 0..=Py_SIZE(kwnames).saturating_sub(1) {
                let arg = crate::ffi::PyTuple_GET_ITEM(kwnames, i as Py_ssize_t);
                if matches_kwarg!(arg, typeref::OPTION) {
                    if num_args & 3 == 3 {
                        cold_path!();
                        return raise_dumps_exception_fixed(
                            "dumps() got multiple values for argument: 'option'",
                        );
                    }
                    optsptr = Some(NonNull::new_unchecked(*args.offset(num_args + i)));
                } else if matches_kwarg!(arg, typeref::DEFAULT) {
                    if num_args & 2 == 2 {
                        cold_path!();
                        return raise_dumps_exception_fixed(
                            "dumps() got multiple values for argument: 'default'",
                        );
                    }
                    default = Some(NonNull::new_unchecked(*args.offset(num_args + i)));
                } else {
                    return raise_dumps_exception_fixed(
                        "dumps() got an unexpected keyword argument",
                    );
                }
            }
        }

        let mut optsbits: i32 = 0;
        if let Some(opts) = optsptr {
            cold_path!();
            if core::ptr::eq((*opts.as_ptr()).ob_type, typeref::INT_TYPE) {
                #[allow(clippy::cast_possible_truncation)]
                let tmp = PyLong_AsLong(optsptr.unwrap().as_ptr()) as i32; // stmt_expr_attributes
                optsbits = tmp;
                if !(0..=opt::MAX_OPT).contains(&optsbits) {
                    cold_path!();
                    return raise_dumps_exception_fixed("Invalid opts");
                }
            } else if !core::ptr::eq(opts.as_ptr(), typeref::NONE) {
                cold_path!();
                return raise_dumps_exception_fixed("Invalid opts");
            }
        }

        #[allow(clippy::cast_sign_loss)]
        let opts = optsbits as opt::Opt;

        serialize(*args, default, opts).map_or_else(
            |err| raise_dumps_exception_dynamic(err.as_str()),
            NonNull::as_ptr,
        )
    }
}
