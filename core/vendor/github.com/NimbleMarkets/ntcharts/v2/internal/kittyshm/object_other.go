//go:build (!js || !wasm) && !linux && (!darwin || !cgo)

package kittyshm

// Supported reports whether this process can publish shared-memory pixels.
func Supported() bool { return false }

// Create is unavailable on this platform/build.
func Create(size int, fill func([]byte) error) (*Object, error) {
	return nil, ErrUnsupported
}
