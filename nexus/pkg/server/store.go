package server

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"cloud.google.com/go/storage"
	"github.com/wandb/wandb/nexus/pkg/leveldb"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

func NewGCSWriter() (*storage.Writer, error) {
	ctx := context.Background()
	client, err := storage.NewClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("storage.NewClient: %w", err)
	}
	defer func(client *storage.Client) {
		err := client.Close()
		if err != nil {
			panic(err)
		}
	}(client)

	// ctx, cancel := context.WithTimeout(ctx, time.Second*50)
	// defer cancel()

	// Upload an object with storage.Writer.
	bucket := "dotwandb"
	object := "loltest"
	wc := client.Bucket(bucket).Object(object).NewWriter(ctx)
	wc.ChunkSize = 0 // note retries are not supported for chunk size 0.

	return wc, nil
}

// Store is the persistent store for a stream
type Store struct {
	// ctx is the context for the store
	ctx context.Context

	// writer is the underlying writer
	writer *leveldb.Writer

	// db is the underlying database
	db *os.File

	gcsWriter *storage.Writer

	// logger is the logger for the store
	logger *observability.NexusLogger
}

// NewStore creates a new store
func NewStore(ctx context.Context, fileName string, logger *observability.NexusLogger) (*Store, error) {
	f, err := os.Create(fileName)
	if err != nil {
		logger.CaptureError("can't write header", err)
		return nil, err
	}
	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
	gcsWriter, _ := NewGCSWriter()
	sr := &Store{ctx: ctx,
		writer:    writer,
		db:        f,
		gcsWriter: gcsWriter,
		logger:    logger,
	}
	if err = sr.addHeader(); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return nil, err
	}
	return sr, nil
}

func (sr *Store) addHeader() error {
	type Header struct {
		ident   [4]byte
		magic   uint16
		version byte
	}
	buf := new(bytes.Buffer)
	ident := [4]byte{byte(':'), byte('W'), byte('&'), byte('B')}
	head := Header{ident: ident, magic: 0xBEE1, version: 0}
	if err := binary.Write(buf, binary.LittleEndian, &head); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	// write to gcs
	if _, err := io.Copy(sr.gcsWriter, buf); err != nil {
		fmt.Println("can't write header to GCS", err)
		sr.logger.CaptureError("can't write header to GCS", err)
	}
	if _, err := sr.db.Write(buf.Bytes()); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	return nil
}

func (sr *Store) Close() error {
	err := sr.gcsWriter.Close()
	err = sr.writer.Close()
	return err
}

func (sr *Store) storeRecord(msg *service.Record) error {
	writer, err := sr.writer.Next()
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}

	if _, err = writer.Write(out); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	return nil
}
