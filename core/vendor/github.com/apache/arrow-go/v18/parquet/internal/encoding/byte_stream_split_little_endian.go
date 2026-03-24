// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//go:build 386 || amd64 || amd64p32 || alpha || arm || arm64 || loong64 || mipsle || mips64le || mips64p32le || nios2 || ppc64le || riscv || riscv64 || sh || wasm

package encoding

import (
	"fmt"

	"github.com/apache/arrow-go/v18/parquet/internal/debug"
)

// decodeByteStreamSplitBatchWidth4InByteOrder decodes the batch of nValues raw bytes representing a 4-byte datatype provided
// by 'data', into the output buffer 'out' using BYTE_STREAM_SPLIT encoding. The values are expected to be in little-endian
// byte order and are be decoded into the 'out' array in machine's native endianness.
// 'out' must have space for at least len(data) bytes.
func decodeByteStreamSplitBatchWidth4InByteOrder(data []byte, nValues, stride int, out []byte) {
	const width = 4
	debug.Assert(len(out) >= nValues*width, fmt.Sprintf("not enough space in output buffer for decoding, out: %d bytes, data: %d bytes", len(out), len(data)))
	for element := 0; element < nValues; element++ {
		// Little Endian: least significant byte first
		out[width*element+0] = data[element]
		out[width*element+1] = data[stride+element]
		out[width*element+2] = data[2*stride+element]
		out[width*element+3] = data[3*stride+element]
	}
}

// decodeByteStreamSplitBatchWidth8InByteOrder decodes the batch of nValues raw bytes representing a 8-byte datatype provided
// by 'data', into the output buffer 'out' using BYTE_STREAM_SPLIT encoding. The values are expected to be in little-endian
// byte order and are be decoded into the 'out' array in machine's native endianness.
// 'out' must have space for at least len(data) bytes.
func decodeByteStreamSplitBatchWidth8InByteOrder(data []byte, nValues, stride int, out []byte) {
	const width = 8
	debug.Assert(len(out) >= nValues*width, fmt.Sprintf("not enough space in output buffer for decoding, out: %d bytes, data: %d bytes", len(out), len(data)))
	for element := 0; element < nValues; element++ {
		// Little Endian: least significant byte first
		out[width*element+0] = data[element]
		out[width*element+1] = data[stride+element]
		out[width*element+2] = data[2*stride+element]
		out[width*element+3] = data[3*stride+element]
		out[width*element+4] = data[4*stride+element]
		out[width*element+5] = data[5*stride+element]
		out[width*element+6] = data[6*stride+element]
		out[width*element+7] = data[7*stride+element]
	}
}
