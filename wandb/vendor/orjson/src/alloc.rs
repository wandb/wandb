// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2025)

use crate::ffi::{PyMem_Free, PyMem_Malloc, PyMem_Realloc};
use core::alloc::{GlobalAlloc, Layout};
use core::ffi::c_void;

struct PyMemAllocator {}

#[global_allocator]
static ALLOCATOR: PyMemAllocator = PyMemAllocator {};

unsafe impl Sync for PyMemAllocator {}

unsafe impl GlobalAlloc for PyMemAllocator {
    #[inline]
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        unsafe { PyMem_Malloc(layout.size()).cast::<u8>() }
    }

    #[inline]
    unsafe fn dealloc(&self, ptr: *mut u8, _layout: Layout) {
        unsafe { PyMem_Free(ptr.cast::<c_void>()) }
    }

    #[inline]
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        unsafe {
            let len = layout.size();
            let ptr = PyMem_Malloc(len).cast::<u8>();
            core::ptr::write_bytes(ptr, 0, len);
            ptr
        }
    }

    #[inline]
    unsafe fn realloc(&self, ptr: *mut u8, _layout: Layout, new_size: usize) -> *mut u8 {
        unsafe { PyMem_Realloc(ptr.cast::<c_void>(), new_size).cast::<u8>() }
    }
}
