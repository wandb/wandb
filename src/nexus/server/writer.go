package server

import (
	// "flag"
	"os"
	// "io"
	"bytes"
	"encoding/binary"
	"github.com/wandb/wandb/nexus/service"
	"google.golang.org/protobuf/proto"
	"sync"
	// "google.golang.org/protobuf/reflect/protoreflect"
	"github.com/golang/leveldb/record"
	log "github.com/sirupsen/logrus"
)

type Writer struct {
	writerChan chan service.Record
	wg         *sync.WaitGroup
}

func NewWriter(wg *sync.WaitGroup) *Writer {
	writer := Writer{}
	writer.writerChan = make(chan service.Record)
	writer.wg = wg

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

/*

func write(w io.Writer, ss []string) error {
    records := record.NewWriter(w)
    for _, s := range ss {
        rec, err := records.Next()
        if err != nil {
            return err
        }
        if _, err := rec.Write([]byte(s)), err != nil {
            return err
        }
    }
    return records.Close()
}


LEVELDBLOG_HEADER_IDENT = ":W&B"
LEVELDBLOG_HEADER_MAGIC = (
    0xBEE1  # zlib.crc32(bytes("Weights & Biases", 'iso8859-1')) & 0xffff
)
LEVELDBLOG_HEADER_VERSION = 0
        ident, magic, version = struct.unpack("<4sHB", header)

*/

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
	f, err := os.Create("run-data.wandb")
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
