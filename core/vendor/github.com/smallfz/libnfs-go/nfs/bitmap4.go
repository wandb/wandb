package nfs

func Bitmap4Encode(x map[int]bool) []uint32 {
	max := 0
	for v := range x {
		if v > max {
			max = v
		}
	}

	size := int(max / 32)
	if max%32 > 0 {
		size += 1
	}

	rs := make([]uint32, size)

	for v, on := range x {
		if !on {
			continue
		}
		i := v / 32
		j := v % 32
		s := uint32(1) << j
		rs[i] |= s
	}

	return rs
}

func Bitmap4Decode(nums []uint32) map[int]bool {
	x := map[int]bool{}
	for i, v := range nums {
		for j := 31; j >= 0; j-- {
			s := uint32(1) << j
			n := 32*i + j
			x[n] = s&v == s
		}
	}
	return x
}
