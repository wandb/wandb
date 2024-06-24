package server

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"math"
)

const wbHeaderLength = 5 // (8 + 32) / 8

type Header struct {
	Magic      uint8
	DataLength uint32
}

// ScanWBRecords is a split function for a [bufio.Scanner] that returns
// the bytes corresponding to incoming Record protos.
func ScanWBRecords(data []byte, _ bool) (int, []byte, error) {
	if len(data) < wbHeaderLength {
		return 0, nil, nil
	}

	var header Header
	if err := binary.Read(
		bytes.NewReader(data),
		binary.LittleEndian,
		&header,
	); err != nil {
		return 0, nil, fmt.Errorf("failed to read header: %v", err)
	}

	if header.Magic != uint8('W') {
		return 0, nil, errors.New("invalid magic byte in header")
	}

	tokenEnd64 := uint64(header.DataLength) + wbHeaderLength

	// Ensure tokenEnd64 fits into an int.
	//
	// On 64-bit systems, it always fits. On 32-bit systems, there will
	// sometimes be overflow.
	//
	// If Go ever introduces integers with >=66 bits, then this code will
	// fail to compile on those systems because Go can tell at compile time
	// that MaxInt doesn't fit into uint64.
	if tokenEnd64 > uint64(math.MaxInt) {
		return 0, nil, errors.New("data too long, got integer overflow")
	}
	tokenEnd := int(tokenEnd64)

	if len(data) < tokenEnd {
		// 'data' does not yet contain the entire token.
		return 0, nil, nil
	}

	token := data[wbHeaderLength:tokenEnd]
	return tokenEnd, token, nil
}
