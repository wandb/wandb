package main

import (
	"bytes"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"os"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// castagnoliTable is the CRC-32C table used for payload digests in -dump
// output.
var castagnoliTable = crc32.MakeTable(crc32.Castagnoli)

// dumpWandb prints one line per record of the .wandb file at path:
//
//	REC <index> <record-oneof-case-name> <payload-len> <crc32c-hex>
//
// followed by a final "OK <count>" on clean EOF, or "ERROR corrupt|eof" on
// the first read failure ("eof" if the error may be resolved by waiting for
// more data, i.e. it wraps io.ErrUnexpectedEOF; "corrupt" otherwise).
//
// The digest is CRC-32C over the raw record payload bytes as read from the
// log (no proto re-marshal), so the Go and Rust dumps hash identical bytes.
//
// The read loop mirrors transactionlog.Reader.Read (leveldb reader with
// CRCAlgoIEEE, W&B header version 0, Recover deferred around every read)
// because transactionlog does not expose the raw payload bytes.
func dumpWandb(path string) int {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintln(os.Stderr, "fixturegen: -dump:", err)
		return 2
	}
	defer func() { _ = f.Close() }()

	reader := leveldb.NewReaderExt(f, leveldb.CRCAlgoIEEE)
	needsToVerifyHeader := true

	count := 0
	for {
		payload, err := dumpReadOne(reader, &needsToVerifyHeader)

		switch {
		case err == nil:
			// Handled below.
		case errors.Is(err, io.ErrUnexpectedEOF):
			fmt.Println("ERROR eof")
			return 0
		case errors.Is(err, io.EOF):
			// Clean end of the record stream.
			fmt.Printf("OK %d\n", count)
			return 0
		default:
			fmt.Println("ERROR corrupt")
			return 0
		}

		msg := &spb.Record{}
		if err := proto.Unmarshal(payload, msg); err != nil {
			// transactionlog.Reader.Read wraps unmarshal errors with %v
			// (opaque, not EOF-like), so they classify as corrupt.
			fmt.Println("ERROR corrupt")
			return 0
		}

		fmt.Printf("REC %d %s %d %08x\n",
			count, recordCaseName(msg), len(payload),
			crc32.Checksum(payload, castagnoliTable))
		count++
	}
}

// dumpReadOne reads the next raw record payload, mirroring
// transactionlog.Reader.Read.
func dumpReadOne(
	r *leveldb.Reader,
	needsToVerifyHeader *bool,
) ([]byte, error) {
	// Always recover after errors, skipping corrupt data.
	// No-op if there is no error.
	defer r.Recover()

	if *needsToVerifyHeader {
		// transactionlog: wandbStoreVersion = 0.
		if err := r.VerifyWandbHeader(0); err != nil {
			return nil, fmt.Errorf("bad header: %w", err)
		}
		*needsToVerifyHeader = false
	}

	recordReader, err := r.Next()
	if err != nil {
		return nil, err
	}

	var buf bytes.Buffer
	if _, err := io.Copy(&buf, recordReader); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// recordCaseName returns the proto field name of the record_type oneof case
// ("history", "run", "output_raw", ...), or "none" if no case is set.
func recordCaseName(msg *spb.Record) string {
	m := msg.ProtoReflect()
	od := m.Descriptor().Oneofs().ByName("record_type")
	if od == nil {
		return "none"
	}
	fd := m.WhichOneof(od)
	if fd == nil {
		return "none"
	}
	return string(fd.Name())
}
