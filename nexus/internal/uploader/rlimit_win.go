//go:build windows

package uploader

func getRlimit(defaultValue int32) int32 {
	if defaultValue > 0 {
		return defaultValue
	}
	return defaultConcurrencyLimit
}
