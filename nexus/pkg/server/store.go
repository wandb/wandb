package server

import (
	"bytes"
	"encoding/binary"
	"os"

	"github.com/wandb/wandb/nexus/pkg/leveldb"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
	"google.golang.org/protobuf/proto"
)

type Store struct {
	writer *leveldb.Writer
	db     *os.File
	logger *slog.Logger
}

func NewStore(fileName string, logger *slog.Logger) *Store {
	f, err := os.Create(fileName)
	if err != nil {
		LogError(logger, "cant create store", err)
	}
	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
	s := &Store{writer: writer, db: f, logger: logger}
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
		LogError(s.logger, "cant write header", err)
	}
	if _, err := s.db.Write(buf.Bytes()); err != nil {
		LogError(s.logger, "cant write data", err)
	}
}

func (s *Store) Close() error {
	err := s.writer.Close()
	return err
}

func (s *Store) storeRecord(msg *service.Record) {
	writer, err := s.writer.Next()
	if err != nil {
		LogError(s.logger, "cant get next record", err)
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		LogError(s.logger, "cant marshal", err)
	}

	if _, err = writer.Write(out); err != nil {
		LogError(s.logger, "cant write rec", err)
	}
}
