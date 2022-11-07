package server

import (
	"bytes"
	"encoding/binary"
	"github.com/golang/leveldb/record"
	log "github.com/sirupsen/logrus"
	"github.com/wandb/wandb/nexus/service"
	"google.golang.org/protobuf/proto"
	"os"
	"sync"
)

type Writer struct {
	writerChan chan service.Record
	wg         *sync.WaitGroup
	settings   *Settings
}

func NewWriter(wg *sync.WaitGroup, settings *Settings) *Writer {
	writer := Writer{
		wg:         wg,
		settings:   settings,
		writerChan: make(chan service.Record),
	}

	wg.Add(1)
	go writer.writerGo()
	return &writer
}

func (writer *Writer) Stop() {
	close(writer.writerChan)
}

func (writer *Writer) WriteRecord(rec *service.Record) {
	writer.writerChan <- *rec
}

func logHeader(f *os.File) {
	type logHeader struct {
		ident   [4]byte
		magic   uint16
		version byte
	}
	buf := new(bytes.Buffer)
	ident := [4]byte{byte(':'), byte('W'), byte('&'), byte('B')}
	head := logHeader{ident: ident, magic: 0xBEE1, version: 1}
	err := binary.Write(buf, binary.LittleEndian, &head)
	check(err)
	f.Write(buf.Bytes())
}

func (w *Writer) writerGo() {
	f, err := os.Create(w.settings.SyncFile)
	check(err)
	defer w.wg.Done()
	defer f.Close()

	logHeader(f)

	records := record.NewWriter(f)

	log.Debug("WRITER: OPEN")
	for done := false; !done; {
		select {
		case msg, ok := <-w.writerChan:
			if !ok {
				log.Debug("NOMORE")
				done = true
				break
			}
			log.Debug("WRITE *******")
			// handleLogWriter(w, msg)

			rec, err := records.Next()
			check(err)

			out, err := proto.Marshal(&msg)
			check(err)

			_, err = rec.Write(out)
			check(err)
		}
	}
	log.Debug("WRITER: CLOSE")
	records.Close()
	log.Debug("WRITER: FIN")
}
