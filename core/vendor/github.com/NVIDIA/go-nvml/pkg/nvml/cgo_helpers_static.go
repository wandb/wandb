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

package nvml

import (
	"unsafe"
)

import "C"

var cgoAllocsUnknown = new(struct{})

type stringHeader struct {
	Data unsafe.Pointer
	Len  int
}

func clen(n []byte) int {
	for i := 0; i < len(n); i++ {
		if n[i] == 0 {
			return i
		}
	}
	return len(n)
}

func uint32SliceToIntSlice(s []uint32) []int {
	ret := make([]int, len(s))
	for i := range s {
		ret[i] = int(s[i])
	}
	return ret
}

func convertSlice[T any, I any](input []T) []I {
	output := make([]I, len(input))
	for i, obj := range input {
		switch v := any(obj).(type) {
		case I:
			output[i] = v
		}
	}
	return output
}

// packPCharString creates a Go string backed by *C.char and avoids copying.
func packPCharString(p *C.char) (raw string) {
	if p != nil && *p != 0 {
		h := (*stringHeader)(unsafe.Pointer(&raw))
		h.Data = unsafe.Pointer(p)
		for *p != 0 {
			p = (*C.char)(unsafe.Pointer(uintptr(unsafe.Pointer(p)) + 1)) // p++
		}
		h.Len = int(uintptr(unsafe.Pointer(p)) - uintptr(h.Data))
	}
	return
}

// unpackPCharString represents the data from Go string as *C.char and avoids copying.
func unpackPCharString(str string) (*C.char, *struct{}) {
	h := (*stringHeader)(unsafe.Pointer(&str))
	return (*C.char)(h.Data), cgoAllocsUnknown
}
