package xdr

func Pad(size int) int {
	if size%4 != 0 {
		return 4 - size%4
	}
	return 0
}
