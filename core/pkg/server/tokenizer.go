package server

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
)

type Header struct {
	Magic      uint8
	DataLength uint32
}

var wbHeaderLength = binary.Size(Header{})

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

	if len(data) < wbHeaderLength+int(header.DataLength) {
		// 'data' does not yet contain the entire token.
		return 0, nil, nil
	}

	advance := wbHeaderLength + int(header.DataLength)
	token := data[wbHeaderLength:]
	return advance, token, nil
}
