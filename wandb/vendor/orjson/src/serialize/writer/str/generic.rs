// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

use core::simd::cmp::{SimdPartialEq, SimdPartialOrd};
use core::simd::u8x16;

#[inline(never)]
#[cfg_attr(target_arch = "aarch64", target_feature(enable = "neon"))]
pub(crate) unsafe fn format_escaped_str_impl_generic_128(
    odst: *mut u8,
    value_ptr: *const u8,
    value_len: usize,
) -> usize {
    unsafe {
        const STRIDE: usize = 16;

        let mut dst = odst;
        let mut src = value_ptr;

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        if value_len < STRIDE {
            impl_format_scalar!(dst, src, value_len);
        } else {
            let blash = u8x16::splat(b'\\');
            let quote = u8x16::splat(b'"');
            let x20 = u8x16::splat(32);

            let last_stride_src = src.add(value_len).sub(STRIDE);
            let mut nb: usize = value_len;

            {
                while nb >= STRIDE {
                    let v = u8x16::from_slice(core::slice::from_raw_parts(src, STRIDE));
                    let mask =
                        (v.simd_eq(blash) | v.simd_eq(quote) | v.simd_lt(x20)).to_bitmask() as u32;
                    v.copy_to_slice(core::slice::from_raw_parts_mut(dst, STRIDE));

                    if mask != 0 {
                        let cn = mask.trailing_zeros() as usize;
                        nb -= cn;
                        dst = dst.add(cn);
                        src = src.add(cn);
                        nb -= 1;
                        write_escape!(*(src), dst);
                        src = src.add(1);
                    } else {
                        nb -= STRIDE;
                        dst = dst.add(STRIDE);
                        src = src.add(STRIDE);
                    }
                }
            }

            let mut scratch: [u8; 32] = [b'a'; 32];
            let mut v = u8x16::from_slice(core::slice::from_raw_parts(last_stride_src, STRIDE));
            v.copy_to_slice(core::slice::from_raw_parts_mut(
                scratch.as_mut_ptr(),
                STRIDE,
            ));

            let mut scratch_ptr = scratch.as_mut_ptr().add(16 - nb);
            v = u8x16::from_slice(core::slice::from_raw_parts(scratch_ptr, STRIDE));
            let mut mask =
                (v.simd_eq(blash) | v.simd_eq(quote) | v.simd_lt(x20)).to_bitmask() as u32;

            loop {
                v.copy_to_slice(core::slice::from_raw_parts_mut(dst, STRIDE));
                if mask != 0 {
                    let cn = mask.trailing_zeros() as usize;
                    nb -= cn;
                    dst = dst.add(cn);
                    scratch_ptr = scratch_ptr.add(cn);
                    nb -= 1;
                    mask >>= cn + 1;
                    write_escape!(*(scratch_ptr), dst);
                    scratch_ptr = scratch_ptr.add(1);
                    v = u8x16::from_slice(core::slice::from_raw_parts(scratch_ptr, STRIDE));
                } else {
                    dst = dst.add(nb);
                    break;
                }
            }
        }

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        dst as usize - odst as usize
    }
}
