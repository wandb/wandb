package server

import (
	"encoding/binary"
	"io"
)

type HeaderOptions struct {
	IDENT   [4]byte `binary:"ident"`
	Magic   uint16  `binary:"magic"`
	Version byte    `binary:"version"`
}

// NewHeader returns a new header
func NewHeader() *HeaderOptions {
	return &HeaderOptions{
		IDENT:   [4]byte{':', 'W', '&', 'B'},
		Magic:   0xBEE1,
		Version: 0,
	}
}

var h = NewHeader()

func (o *HeaderOptions) MarshalBinary(w io.Writer) error {
	if err := binary.Write(w, binary.LittleEndian, o); err != nil {
		return err
	}
	return nil
}

func (o *HeaderOptions) UnmarshalBinary(r io.Reader) error {
	if err := binary.Read(r, binary.LittleEndian, o); err != nil {
		return err
	}
	return nil
}

func (o *HeaderOptions) Valid() bool {

	if o.IDENT != h.IDENT || o.Magic != h.Magic || o.Version != h.Version {
		return false
	}
	return true

}
