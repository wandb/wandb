package leet_test

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TestNewLiveStore_ValidFile tests creating a LiveStore with a valid file
func TestNewLiveStore_ValidFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "valid.wandb")

	// Write a valid header to a tranaction log.
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	w.Close()

	// Now open with LiveStore
	ls, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer ls.Close()

	// Should be able to read (will get EOF since no records)
	_, err = ls.Read()
	require.ErrorIs(t, err, io.EOF)
}

// TestNewLiveStore_NonExistentFile tests error handling for missing files
func TestNewLiveStore_NonExistentFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nonexistent.wandb")
	_, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.Error(t, err)
}

// TestNewLiveStore_InvalidHeader tests handling of files with invalid headers
func TestNewLiveStore_InvalidHeader(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "invalid-header-*.wandb")
	require.NoError(t, err)
	defer os.Remove(tmpFile.Name())

	// Write invalid header data
	_, err = tmpFile.WriteString("INVALID_HEADER_DATA")
	require.NoError(t, err)
	tmpFile.Close()

	store, err := leet.NewLiveStore(tmpFile.Name(), observability.NewNoOpLogger())
	require.NoError(t, err)

	_, err = store.Read()
	require.ErrorContains(t, err, "bad header")
}

// TestLiveStore_ReadValidRecords tests reading valid records
func TestLiveStore_ReadValidRecords(t *testing.T) {
	path := filepath.Join(t.TempDir(), "records.wandb")

	// Write records using regular Store
	// Write a valid header to a tranaction log.
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	records := []*spb.Record{
		{Num: 1},
		{Num: 2},
		{Num: 3},
	}

	for _, rec := range records {
		err := w.Write(rec)
		require.NoError(t, err)
	}
	w.Close()

	// Read with LiveStore
	ls, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer ls.Close()

	// Read all records
	for _, expected := range records {
		rec, err := ls.Read()
		require.NoError(t, err)
		require.Equal(t, rec.Num, expected.Num)
	}

	// Next read should return EOF
	_, err = ls.Read()
	require.ErrorIs(t, err, io.EOF)
}

// TestLiveStore_ReadAfterClose tests that reading after close returns an error
func TestLiveStore_ReadAfterClose(t *testing.T) {
	path := filepath.Join(t.TempDir(), "read-after-close.wandb")

	// Create valid file with a record.
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	_ = w.Write(&spb.Record{Num: 1})
	w.Close()

	ls, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)

	// Close the LiveStore.
	ls.Close()

	// Try to read after close.
	_, err = ls.Read()
	require.Error(t, err)
	require.Equal(t, err.Error(), "livestore: reader is closed")
}

// TestLiveStore_LiveRead_ConcurrentWriterFlushes writes records in one goroutine
// using the low-level LevelDB writer (so we can Flush) and reads them from another.
// It ensures we see newly flushed records in order, and only get io.EOF between flushes.
func TestLiveStore_LiveRead_ConcurrentWriterFlushes(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "live-*.wandb")
	require.NoError(t, err)
	_ = tmp.Close()

	const total = 50

	// Writer goroutine.
	var wg sync.WaitGroup
	wg.Add(1)
	go func(path string) {
		defer wg.Done()

		f, err := os.OpenFile(path, os.O_WRONLY|os.O_TRUNC, 0o644)
		if err != nil {
			t.Errorf("open for write: %v", err)
			return
		}
		defer f.Close()

		// Match LiveStore (CRCAlgoIEEE, version 0).
		w := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, 0)

		for i := range total {
			rec := &spb.Record{Num: int64(i)}
			payload, err := proto.Marshal(rec)
			if err != nil {
				t.Errorf("marshal: %v", err)
				return
			}

			chunk, err := w.Next()
			if err != nil {
				t.Errorf("writer.Next: %v", err)
				return
			}
			if _, err := chunk.Write(payload); err != nil {
				t.Errorf("writer.Write: %v", err)
				return
			}
			if err := w.Flush(); err != nil {
				t.Errorf("writer.Flush: %v", err)
				return
			}

			// Small delay to exercise reader's EOF path between records.
			time.Sleep(2 * time.Millisecond)
		}
		// Finish cleanly.
		if err := w.Close(); err != nil {
			t.Errorf("writer.Close: %v", err)
		}
	}(tmp.Name())

	// Reader on the same file.
	ls, err := leet.NewLiveStore(tmp.Name(), observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	defer ls.Close()

	deadline := time.After(5 * time.Second)
	for i := 0; i < total; {
		select {
		case <-deadline:
			t.Fatalf("timeout waiting for record %d/%d", i, total)
		default:
			rec, err := ls.Read()
			if errors.Is(err, io.EOF) {
				// No complete record yet; try again shortly.
				time.Sleep(1 * time.Millisecond)
				continue
			}
			require.NoError(t, err)
			require.Equal(t, rec.Num, int64(i))
			i++
		}
	}
	wg.Wait()
}

func TestLiveStore_LiveRead_OpenedBeforeWriter(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "live-*.wandb")
	require.NoError(t, err)
	_ = tmp.Close()

	// Start reader first: header may not exist yet; allowed by NewLiveStore.
	ls, err := leet.NewLiveStore(tmp.Name(), observabilitytest.NewTestLogger(t))
	require.NoError(t, err)
	defer ls.Close()

	// Now start the writer.
	var wg sync.WaitGroup
	wg.Add(1)
	go func(path string) {
		defer wg.Done()
		f, err := os.OpenFile(path, os.O_WRONLY|os.O_TRUNC, 0o644)
		if err != nil {
			t.Errorf("open for write: %v", err)
			return
		}
		defer f.Close()
		w := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, 0)

		rec := &spb.Record{Num: 1}
		payload, err := proto.Marshal(rec)
		if err != nil {
			t.Errorf("marshal: %v", err)
			return
		}
		chunk, err := w.Next()
		if err != nil {
			t.Errorf("writer.Next: %v", err)
			return
		}
		if _, err := chunk.Write(payload); err != nil {
			t.Errorf("writer.Write: %v", err)
			return
		}
		if err := w.Flush(); err != nil {
			t.Errorf("writer.Flush: %v", err)
			return
		}
		_ = w.Close()
	}(tmp.Name())

	deadline := time.After(3 * time.Second)
	for {
		select {
		case <-deadline:
			t.Fatal("timeout waiting for first record")
		default:
			rec, err := ls.Read()
			if errors.Is(err, io.EOF) {
				time.Sleep(1 * time.Millisecond)
				continue
			}
			require.NoError(t, err)
			require.Equal(t, rec.Num, int64(1))
			wg.Wait()
			return
		}
	}
}

// TestLiveStore_LargeRecord tests handling of large records
func TestLiveStore_LargeRecord(t *testing.T) {
	path := filepath.Join(t.TempDir(), "large.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	// Create a large record
	largeData := make([]byte, 1024*1024) // 1MB
	for i := range largeData {
		largeData[i] = byte(i % 256)
	}

	largeRecord := &spb.Record{Num: 1}

	err = w.Write(largeRecord)
	require.NoError(t, err)
	w.Close()

	// Read with LiveStore
	ls, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer ls.Close()

	rec, err := ls.Read()
	require.NoError(t, err)
	require.Equal(t, rec.Num, largeRecord.Num)
}

// TestLiveStore_PartialWrite tests handling of partial writes
func TestLiveStore_PartialWrite(t *testing.T) {
	path := filepath.Join(t.TempDir(), "partial.wandb")

	// Write header
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	// Write one complete record
	err = w.Write(&spb.Record{Num: 1})
	require.NoError(t, err)
	w.Close()

	// Append partial record data (simulate interrupted write)
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o644)
	require.NoError(t, err)
	// Write incomplete record header
	_, _ = f.Write([]byte{0x00, 0x00}) // Partial record that will cause read error
	f.Close()

	// Try to read
	ls, err := leet.NewLiveStore(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer ls.Close()

	// First record should be readable
	rec, err := ls.Read()
	require.NoError(t, err)
	require.Equal(t, rec.Num, int64(1))

	// Second read should fail or return EOF
	_, err = ls.Read()
	require.Error(t, err)
}
