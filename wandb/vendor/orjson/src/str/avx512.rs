// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

use crate::str::pyunicode_new::*;

use core::arch::x86_64::{
    _mm512_and_si512, _mm512_cmpgt_epu8_mask, _mm512_cmpneq_epi8_mask, _mm512_loadu_epi8,
    _mm512_mask_cmpneq_epi8_mask, _mm512_maskz_loadu_epi8, _mm512_max_epu8, _mm512_set1_epi8,
};

#[inline(never)]
#[target_feature(enable = "avx512f,avx512bw,avx512vl,bmi2")]
pub(crate) unsafe fn create_str_impl_avx512vl(buf: &str) -> *mut crate::ffi::PyObject {
    unsafe {
        const STRIDE: usize = 64;

        let buf_ptr = buf.as_bytes().as_ptr().cast::<i8>();
        let buf_len = buf.len();

        assume!(buf_len > 0);

        let num_loops = buf_len / STRIDE;
        let remainder = buf_len % STRIDE;

        let remainder_mask: u64 = !(u64::MAX << remainder);
        let mut str_vec = _mm512_maskz_loadu_epi8(remainder_mask, buf_ptr);
        let sptr = buf_ptr.add(remainder);

        for i in 0..num_loops {
            str_vec = _mm512_max_epu8(
                str_vec,
                _mm512_loadu_epi8(sptr.add(STRIDE * i).cast::<i8>()),
            );
        }

        #[allow(overflowing_literals)]
        let vec_128 = _mm512_set1_epi8(0b10000000i8);
        if _mm512_cmpgt_epu8_mask(str_vec, vec_128) == 0 {
            pyunicode_ascii(buf.as_bytes().as_ptr(), buf_len)
        } else {
            #[allow(overflowing_literals)]
            let is_four = _mm512_cmpgt_epu8_mask(str_vec, _mm512_set1_epi8(239i8)) != 0;
            #[allow(overflowing_literals)]
            let is_not_latin = _mm512_cmpgt_epu8_mask(str_vec, _mm512_set1_epi8(195i8)) != 0;
            #[allow(overflowing_literals)]
            let multibyte = _mm512_set1_epi8(0b11000000i8);

            let mut num_chars = _mm512_mask_cmpneq_epi8_mask(
                remainder_mask,
                _mm512_and_si512(_mm512_maskz_loadu_epi8(remainder_mask, buf_ptr), multibyte),
                vec_128,
            )
            .count_ones() as usize;

            for i in 0..num_loops {
                num_chars += _mm512_cmpneq_epi8_mask(
                    _mm512_and_si512(
                        _mm512_loadu_epi8(sptr.add(STRIDE * i).cast::<i8>()),
                        multibyte,
                    ),
                    vec_128,
                )
                .count_ones() as usize;
            }

            if is_four {
                pyunicode_fourbyte(buf, num_chars)
            } else if is_not_latin {
                pyunicode_twobyte(buf, num_chars)
            } else {
                pyunicode_onebyte(buf, num_chars)
            }
        }
    }
}
