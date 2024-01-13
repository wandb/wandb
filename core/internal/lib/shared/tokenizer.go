package shared

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"log/slog"
)

type Header struct {
	Magic      uint8
	DataLength uint32
}

type Tokenizer struct {
	header       Header
	headerLength int
	headerValid  bool
}

func Write(writer io.Writer, bytes []byte) error {

	header := Header{Magic: byte('W'), DataLength: uint32(len(bytes))}
	if err := binary.Write(writer, binary.LittleEndian, &header); err != nil {
		return fmt.Errorf("can't write header: %w", err)
	}
	if _, err := writer.Write(bytes); err != nil {
		return fmt.Errorf("can't write msg: %w", err)
	}
	return nil
}

func (x *Tokenizer) Split(data []byte, _ bool) (advance int, token []byte, err error) {
	if x.headerLength == 0 {
		x.headerLength = binary.Size(x.header)
	}

	advance = 0

	if !x.headerValid {
		if len(data) < x.headerLength {
			return
		}
		buf := bytes.NewReader(data)
		err := binary.Read(buf, binary.LittleEndian, &x.header)
		if err != nil {
			slog.Error("can't read token", "err", err)
			return 0, nil, err
		}
		if x.header.Magic != uint8('W') {
			slog.Error("Invalid magic byte in header")
		}
		x.headerValid = true
		advance += x.headerLength
		data = data[advance:]
	}

	if len(data) < int(x.header.DataLength) {
		return
	}

	advance += int(x.header.DataLength)
	token = data[:x.header.DataLength]
	x.headerValid = false
	return
}
