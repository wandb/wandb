// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

use core::arch::x86_64::{
    __m128i, _mm_cmpeq_epi8, _mm_loadu_si128, _mm_movemask_epi8, _mm_or_si128, _mm_set1_epi8,
    _mm_setzero_si128, _mm_storeu_si128, _mm_subs_epu8,
};

#[allow(dead_code)]
#[expect(clippy::cast_ptr_alignment)]
#[inline(never)]
pub(crate) unsafe fn format_escaped_str_impl_sse2_128(
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
            let blash = _mm_set1_epi8(0b01011100i8);
            let quote = _mm_set1_epi8(0b00100010i8);
            let x20 = _mm_set1_epi8(0b00011111i8);
            let v0 = _mm_setzero_si128();

            let last_stride_src = src.add(value_len).sub(STRIDE);
            let mut nb: usize = value_len;

            unsafe {
                while nb >= STRIDE {
                    let str_vec = _mm_loadu_si128(src.cast::<__m128i>());

                    let mask = _mm_movemask_epi8(_mm_or_si128(
                        _mm_or_si128(
                            _mm_cmpeq_epi8(str_vec, blash),
                            _mm_cmpeq_epi8(str_vec, quote),
                        ),
                        _mm_cmpeq_epi8(_mm_subs_epu8(str_vec, x20), v0),
                    ));

                    _mm_storeu_si128(dst.cast::<__m128i>(), str_vec);

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

                let mut scratch: [u8; 32] = [b'a'; 32];
                let mut str_vec = _mm_loadu_si128(last_stride_src.cast::<__m128i>());
                _mm_storeu_si128(scratch.as_mut_ptr().cast::<__m128i>(), str_vec);

                let mut scratch_ptr = scratch.as_mut_ptr().add(16 - nb);
                str_vec = _mm_loadu_si128(scratch_ptr as *const __m128i);

                let mut mask = _mm_movemask_epi8(_mm_or_si128(
                    _mm_or_si128(
                        _mm_cmpeq_epi8(str_vec, blash),
                        _mm_cmpeq_epi8(str_vec, quote),
                    ),
                    _mm_cmpeq_epi8(_mm_subs_epu8(str_vec, x20), v0),
                ));

                loop {
                    _mm_storeu_si128(dst.cast::<__m128i>(), str_vec);

                    if mask != 0 {
                        let cn = mask.trailing_zeros() as usize;
                        nb -= cn;
                        dst = dst.add(cn);
                        scratch_ptr = scratch_ptr.add(cn);
                        nb -= 1;
                        mask >>= cn + 1;
                        write_escape!(*(scratch_ptr), dst);
                        scratch_ptr = scratch_ptr.add(1);
                        str_vec = _mm_loadu_si128(scratch_ptr as *const __m128i);
                    } else {
                        dst = dst.add(nb);
                        break;
                    }
                }
            }
        }

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        dst as usize - odst as usize
    }
}
