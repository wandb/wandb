// Modified from upstream sources
// https://github.com/golang/leveldb/blob/master/crc/crc.go
// Justification for more bespoke crc
// https://www.rfc-editor.org/rfc/rfc3385

// Copyright 2011 The LevelDB-Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

// Package crc implements the checksum algorithm used throughout leveldb.
//
// The algorithm is CRC-32 with Castagnoli's polynomial, followed by a bit
// rotation and an additional delta. The additional processing is to lessen the
// probability of arbitrary key/value data coincidentally containing bytes that
// look like a checksum.
//
// To calculate the uint32 checksum of some data:
//
//	var u uint32 = crc.New(data).Value()
//
// In leveldb, the uint32 value is then stored in little-endian format.
package leveldb

import (
	"hash/crc32"
)

var tableCRC32ieee = crc32.MakeTable(crc32.IEEE)
var tableCRC32c = crc32.MakeTable(crc32.Castagnoli)

type CRCAlgo uint8

const (
	CRCAlgoCustom CRCAlgo = iota
	CRCAlgoIEEE
)

type CRC32c uint32

func NewCRC32c(b []byte) CRC32c {
	return CRC32c(0).Update(b)
}

func (c CRC32c) Update(b []byte) CRC32c {
	return CRC32c(crc32.Update(uint32(c), tableCRC32c, b))
}

func (c CRC32c) Value() uint32 {
	return uint32(c>>15|c<<17) + 0xa282ead8
}

func CRCStandard(b []byte) uint32 {
	return crc32.Checksum(b, tableCRC32ieee)
}

func CRCCustom(b []byte) uint32 {
	return NewCRC32c(b).Value()
}
