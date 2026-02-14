// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

use core::arch::x86_64::{
    _mm256_cmpeq_epu8_mask, _mm256_cmplt_epu8_mask, _mm256_loadu_epi8, _mm256_maskz_loadu_epi8,
    _mm256_set1_epi8, _mm256_storeu_epi8,
};

#[inline(never)]
#[target_feature(enable = "avx512f,avx512bw,avx512vl,bmi2")]
pub(crate) unsafe fn format_escaped_str_impl_512vl(
    odst: *mut u8,
    value_ptr: *const u8,
    value_len: usize,
) -> usize {
    unsafe {
        const STRIDE: usize = 32;

        let mut dst = odst;
        let mut src = value_ptr;
        let mut nb: usize = value_len;

        let blash = _mm256_set1_epi8(0b01011100i8);
        let quote = _mm256_set1_epi8(0b00100010i8);
        let x20 = _mm256_set1_epi8(0b00100000i8);

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        while nb >= STRIDE {
            let str_vec = _mm256_loadu_epi8(src.cast::<i8>());

            _mm256_storeu_epi8(dst.cast::<i8>(), str_vec);

            let mask = _mm256_cmpeq_epu8_mask(str_vec, blash)
                | _mm256_cmpeq_epu8_mask(str_vec, quote)
                | _mm256_cmplt_epu8_mask(str_vec, x20);

            if mask != 0 {
                let cn = mask.trailing_zeros() as usize;
                src = src.add(cn);
                dst = dst.add(cn);
                nb -= cn;
                nb -= 1;

                write_escape!(*(src), dst);
                src = src.add(1);
            } else {
                nb -= STRIDE;
                dst = dst.add(STRIDE);
                src = src.add(STRIDE);
            }
        }

        loop {
            let remainder_mask = !(u32::MAX << nb);
            let str_vec = _mm256_maskz_loadu_epi8(remainder_mask, src.cast::<i8>());

            _mm256_storeu_epi8(dst.cast::<i8>(), str_vec);

            let mask = (_mm256_cmpeq_epu8_mask(str_vec, blash)
                | _mm256_cmpeq_epu8_mask(str_vec, quote)
                | _mm256_cmplt_epu8_mask(str_vec, x20))
                & remainder_mask;

            if mask != 0 {
                let cn = mask.trailing_zeros() as usize;
                src = src.add(cn);
                dst = dst.add(cn);
                nb -= cn;
                nb -= 1;

                write_escape!(*(src), dst);
                src = src.add(1);
            } else {
                dst = dst.add(nb);
                break;
            }
        }

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        dst as usize - odst as usize
    }
}
