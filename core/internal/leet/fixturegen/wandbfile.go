package main

// In-memory .wandb (W&B transaction log) construction.
//
// The byte layout matches what transactionlog.OpenWriter produces:
// a 7-byte W&B header (":W&B" + magic 0xBEE1 LE + version 0) written by
// leveldb.NewWriterExt, followed by LevelDB-style chunks (7-byte chunk
// header: CRC32-IEEE (4B LE), length (2B LE), chunk type (1B)).
//
// Records are marshaled with proto.MarshalOptions{Deterministic: true} so
// map fields (if any) serialize in sorted-key order, keeping the output
// byte-identical across runs and machines.

import (
	"bytes"
	"fmt"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// wandbHeaderLen is the size of the W&B file header.
	wandbHeaderLen = 7
	// chunkHeaderLen is the size of a LevelDB chunk header.
	chunkHeaderLen = 7
	// wandbStoreVersion mirrors core/internal/transactionlog.
	wandbStoreVersion = 0
	// leveldbBlockSize is the LevelDB block size; files smaller than this
	// consist of a single block, making chunk offsets analytic.
	leveldbBlockSize = 32 * 1024
)

// wandbBuilder accumulates records into an in-memory .wandb byte stream.
type wandbBuilder struct {
	buf         bytes.Buffer
	w           *leveldb.Writer
	payloadLens []int
}

func newWandbBuilder() *wandbBuilder {
	b := &wandbBuilder{}
	b.w = leveldb.NewWriterExt(&b.buf, leveldb.CRCAlgoIEEE, wandbStoreVersion)
	return b
}

func (b *wandbBuilder) write(rec *spb.Record) {
	data, err := proto.MarshalOptions{Deterministic: true}.Marshal(rec)
	if err != nil {
		panic(fmt.Sprintf("fixturegen: marshal record: %v", err))
	}
	dst, err := b.w.Next()
	if err != nil {
		panic(fmt.Sprintf("fixturegen: writer.Next: %v", err))
	}
	if _, err := dst.Write(data); err != nil {
		panic(fmt.Sprintf("fixturegen: write record: %v", err))
	}
	b.payloadLens = append(b.payloadLens, len(data))
}

// bytes closes the builder and returns the complete file contents.
func (b *wandbBuilder) bytes() []byte {
	if err := b.w.Close(); err != nil {
		panic(fmt.Sprintf("fixturegen: writer.Close: %v", err))
	}
	return b.buf.Bytes()
}

func (b *wandbBuilder) recordCount() int { return len(b.payloadLens) }

// chunkOffset returns the file offset of record i's chunk header. Valid only
// for single-block files (verified by assertSingleBlock).
func (b *wandbBuilder) chunkOffset(i int) int {
	off := wandbHeaderLen
	for j := range i {
		off += chunkHeaderLen + b.payloadLens[j]
	}
	return off
}

// assertSingleBlock panics unless the finished stream fits in one LevelDB
// block with one chunk per record, which is what makes chunkOffset exact.
func (b *wandbBuilder) assertSingleBlock(data []byte) {
	want := b.chunkOffset(len(b.payloadLens))
	if len(data) != want || len(data) > leveldbBlockSize {
		panic(fmt.Sprintf(
			"fixturegen: expected single-block file of %d bytes, got %d",
			want, len(data)))
	}
}

// --- record helpers ------------------------------------------------------

func ts(unixSec int64) *timestamppb.Timestamp {
	return &timestamppb.Timestamp{Seconds: unixSec}
}

// kv is an ordered key/value_json pair; slices of kv avoid map-iteration
// nondeterminism at the source.
type kv struct {
	key   string
	value string
}

func historyRecord(step int, items []kv) *spb.Record {
	h := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: int64(step)}}
	h.Item = append(h.Item, &spb.HistoryItem{
		NestedKey: []string{"_step"},
		ValueJson: fmt.Sprintf("%d", step),
	})
	for _, it := range items {
		h.Item = append(h.Item, &spb.HistoryItem{
			NestedKey: []string{it.key},
			ValueJson: it.value,
		})
	}
	return &spb.Record{RecordType: &spb.Record_History{History: h}}
}

// historyRecordNested is like historyRecord but items carry full nested key
// paths (used for media values such as ["samples", "path"]).
func historyRecordNested(step int, items []*spb.HistoryItem) *spb.Record {
	h := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: int64(step)}}
	h.Item = append(h.Item, &spb.HistoryItem{
		NestedKey: []string{"_step"},
		ValueJson: fmt.Sprintf("%d", step),
	})
	h.Item = append(h.Item, items...)
	return &spb.Record{RecordType: &spb.Record_History{History: h}}
}

func nestedItem(path []string, valueJSON string) *spb.HistoryItem {
	return &spb.HistoryItem{NestedKey: path, ValueJson: valueJSON}
}

func statsRecord(unixSec int64, items []kv) *spb.Record {
	s := &spb.StatsRecord{Timestamp: ts(unixSec)}
	for _, it := range items {
		s.Item = append(s.Item, &spb.StatsItem{Key: it.key, ValueJson: it.value})
	}
	return &spb.Record{RecordType: &spb.Record_Stats{Stats: s}}
}

func outputRawRecord(line string, stderr bool, unixSec int64) *spb.Record {
	typ := spb.OutputRawRecord_STDOUT
	if stderr {
		typ = spb.OutputRawRecord_STDERR
	}
	return &spb.Record{RecordType: &spb.Record_OutputRaw{
		OutputRaw: &spb.OutputRawRecord{
			Line:       line,
			OutputType: typ,
			Timestamp:  ts(unixSec),
		},
	}}
}

func summaryRecord(items []kv) *spb.Record {
	s := &spb.SummaryRecord{}
	for _, it := range items {
		s.Update = append(s.Update, &spb.SummaryItem{
			Key:       it.key,
			ValueJson: it.value,
		})
	}
	return &spb.Record{RecordType: &spb.Record_Summary{Summary: s}}
}

func exitRecord(code int32, runtimeSec int32) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Exit{
		Exit: &spb.RunExitRecord{ExitCode: code, Runtime: runtimeSec},
	}}
}

func configRecord(items []kv) *spb.ConfigRecord {
	c := &spb.ConfigRecord{}
	for _, it := range items {
		c.Update = append(c.Update, &spb.ConfigItem{
			Key:       it.key,
			ValueJson: it.value,
		})
	}
	return c
}
