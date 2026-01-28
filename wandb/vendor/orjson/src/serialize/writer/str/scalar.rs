// SPDX-License-Identifier: (Apache-2.0 OR MIT)
// Copyright ijl (2024-2025)

macro_rules! impl_format_scalar {
    ($dst:expr, $src:expr, $value_len:expr) => {
        unsafe {
            for _ in 0..$value_len {
                core::ptr::write($dst, *($src));
                $src = $src.add(1);
                $dst = $dst.add(1);
                if *super::escape::NEED_ESCAPED.get_unchecked(*($src.sub(1)) as usize) != 0 {
                    $dst = $dst.sub(1);
                    write_escape!(*($src.sub(1)), $dst);
                }
            }
        }
    };
}

#[inline(never)]
#[cfg(all(not(target_arch = "x86_64"), not(feature = "generic_simd")))]
pub(crate) unsafe fn format_escaped_str_scalar(
    odst: *mut u8,
    value_ptr: *const u8,
    value_len: usize,
) -> usize {
    unsafe {
        let mut dst = odst;
        let mut src = value_ptr;

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        impl_format_scalar!(dst, src, value_len);

        core::ptr::write(dst, b'"');
        dst = dst.add(1);

        dst as usize - odst as usize
    }
}
