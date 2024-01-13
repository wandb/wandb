package store

import (
	"encoding/binary"
	"fmt"
	"io"
)

const (
	HeaderIdent   = ":W&B"
	HeaderMagic   = 0xBEE1
	HeaderVersion = 0
)

type SHeader struct {
	ident   [4]byte
	magic   uint16
	version byte
}

func (sh *SHeader) Write(w io.Writer) error {

	head := SHeader{
		ident:   IdentToByteSlice(),
		magic:   HeaderMagic,
		version: HeaderVersion,
	}
	if err := binary.Write(w, binary.LittleEndian, &head); err != nil {
		return err
	}
	return nil
}

func (sh *SHeader) Read(r io.Reader) error {
	buf := [7]byte{}
	if err := binary.Read(r, binary.LittleEndian, &buf); err != nil {
		return err
	}
	sh.ident = [4]byte{buf[0], buf[1], buf[2], buf[3]}
	sh.magic = binary.LittleEndian.Uint16(buf[4:6])
	sh.version = buf[6]

	if sh.ident != IdentToByteSlice() {
		err := fmt.Errorf("invalid header")
		return err
	}
	if sh.magic != HeaderMagic {
		err := fmt.Errorf("invalid header")
		return err
	}
	if sh.version != HeaderVersion {
		err := fmt.Errorf("invalid header")
		return err
	}
	return nil
}

func (sh *SHeader) GetIdent() [4]byte {
	return sh.ident
}

func (sh *SHeader) GetMagic() uint16 {
	return sh.magic
}

func (sh *SHeader) GetVersion() byte {
	return sh.version
}
