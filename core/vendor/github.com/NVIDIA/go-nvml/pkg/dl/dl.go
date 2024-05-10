// Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package dl

import (
	"errors"
	"fmt"
	"runtime"
	"unsafe"
)

// #cgo LDFLAGS: -ldl
// #include <dlfcn.h>
// #include <stdlib.h>
import "C"

const (
	RTLD_LAZY     = C.RTLD_LAZY
	RTLD_NOW      = C.RTLD_NOW
	RTLD_GLOBAL   = C.RTLD_GLOBAL
	RTLD_LOCAL    = C.RTLD_LOCAL
	RTLD_NODELETE = C.RTLD_NODELETE
	RTLD_NOLOAD   = C.RTLD_NOLOAD
)

type DynamicLibrary struct {
	Name   string
	Flags  int
	handle unsafe.Pointer
}

func New(name string, flags int) *DynamicLibrary {
	return &DynamicLibrary{
		Name:   name,
		Flags:  flags,
		handle: nil,
	}
}

func withOSLock(action func() error) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	return action()
}

func dlError() error {
	lastErr := C.dlerror()
	if lastErr == nil {
		return nil
	}
	return errors.New(C.GoString(lastErr))
}

func (dl *DynamicLibrary) Open() error {
	name := C.CString(dl.Name)
	defer C.free(unsafe.Pointer(name))

	if err := withOSLock(func() error {
		handle := C.dlopen(name, C.int(dl.Flags))
		if handle == nil {
			return dlError()
		}
		dl.handle = handle
		return nil
	}); err != nil {
		return err
	}
	return nil
}

func (dl *DynamicLibrary) Close() error {
	if dl.handle == nil {
		return nil
	}
	if err := withOSLock(func() error {
		if C.dlclose(dl.handle) != 0 {
			return dlError()
		}
		dl.handle = nil
		return nil
	}); err != nil {
		return err
	}
	return nil
}

func (dl *DynamicLibrary) Lookup(symbol string) error {
	sym := C.CString(symbol)
	defer C.free(unsafe.Pointer(sym))

	var pointer unsafe.Pointer
	if err := withOSLock(func() error {
		// Call dlError() to clear out any previous errors.
		_ = dlError()
		pointer = C.dlsym(dl.handle, sym)
		if pointer == nil {
			return fmt.Errorf("symbol %q not found: %w", symbol, dlError())
		}
		return nil
	}); err != nil {
		return err
	}
	return nil
}
