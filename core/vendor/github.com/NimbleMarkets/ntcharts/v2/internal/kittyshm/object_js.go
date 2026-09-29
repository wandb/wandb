//go:build js && wasm

package kittyshm

import (
	"fmt"
	"syscall/js"
)

func registry() js.Value {
	return js.Global().Get("ghosttyKittySharedMemory")
}

func validRegistry(r js.Value) bool {
	return r.Type() == js.TypeObject && !r.IsNull() &&
		r.Get("set").Type() == js.TypeFunction && r.Get("delete").Type() == js.TypeFunction
}

// Supported reports whether the terminal has installed its browser registry.
func Supported() bool { return validRegistry(registry()) }

// Create publishes a tightly packed buffer under a unique name. fill runs before
// publication, so a failed fill leaves no registry entry.
func Create(size int, fill func([]byte) error) (obj *Object, err error) {
	r := registry()
	if !validRegistry(r) {
		return nil, ErrUnsupported
	}
	if size <= 0 || fill == nil {
		return nil, fmt.Errorf("invalid shared-memory buffer")
	}
	name := newName()
	// Treat JS allocation/registry errors as failures so the caller can fall back.
	defer func() {
		if p := recover(); p != nil {
			if e, ok := p.(js.Error); ok {
				obj, err = nil, fmt.Errorf("create shared memory: %w", e)
			} else {
				panic(p)
			}
		}
	}()
	data := make([]byte, size)
	if err := fill(data); err != nil {
		return nil, err
	}
	array := js.Global().Get("Uint8Array").New(size)
	js.CopyBytesToJS(array, data)
	r.Call("set", name, array)
	return &Object{Name: name, Size: size, unlink: func() (err error) {
		defer func() {
			if p := recover(); p != nil {
				if e, ok := p.(js.Error); ok {
					err = fmt.Errorf("unlink shared memory: %w", e)
				} else {
					panic(p)
				}
			}
		}()
		r.Call("delete", name)
		return nil
	}}, nil
}
