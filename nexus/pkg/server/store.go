package server

import (
	"bytes"
	"encoding/binary"
	"os"

	"github.com/wandb/wandb/nexus/pkg/leveldb"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

type Store struct {
	writer *leveldb.Writer
	db     *os.File
}

func NewStore(fileName string) *Store {
	f, err := os.Create(fileName)
	if err != nil {
		LogError("cant create store", err)
	}
	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
	s := &Store{writer: writer, db: f}
	s.addHeader()
	return s
}

func (s *Store) addHeader() {
	type Header struct {
		ident   [4]byte
		magic   uint16
		version byte
	}
	buf := new(bytes.Buffer)
	ident := [4]byte{byte(':'), byte('W'), byte('&'), byte('B')}
	head := Header{ident: ident, magic: 0xBEE1, version: 0}
	if err := binary.Write(buf, binary.LittleEndian, &head); err != nil {
		LogError("cant write header", err)
	}
	if _, err := s.db.Write(buf.Bytes()); err != nil {
		LogError("cant write data", err)
	}
}

func (s *Store) Close() error {
	err := s.writer.Close()
	return err
}

func (s *Store) storeRecord(msg *service.Record) {
	writer, err := s.writer.Next()
	if err != nil {
		LogError("cant get next record", err)
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		LogError("cant marshal", err)
	}

	if _, err = writer.Write(out); err != nil {
		LogError("cant write rec", err)
	}
}
