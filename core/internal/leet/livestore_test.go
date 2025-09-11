package leet_test

import (
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

// TestNewLiveStore_ValidFile tests creating a LiveStore with a valid file
func TestNewLiveStore_ValidFile(t *testing.T) {
	// Create a valid .wandb file using the regular Store
	tmpFile, err := os.CreateTemp(t.TempDir(), "valid-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	tmpFile.Close()

	// Write a valid header using regular Store
	store := stream.NewStore(tmpFile.Name())
	if err := store.Open(os.O_WRONLY); err != nil {
		t.Fatalf("Failed to open store for writing: %v", err)
	}
	store.Close()

	// Now open with LiveStore
	ls, err := leet.NewLiveStore(tmpFile.Name())
	if err != nil {
		t.Fatalf("NewLiveStore failed: %v", err)
	}
	defer ls.Close()

	// Should be able to read (will get EOF since no records)
	_, err = ls.Read()
	if !errors.Is(err, io.EOF) {
		t.Fatalf("Expected EOF, got: %v", err)
	}
}

// TestNewLiveStore_NonExistentFile tests error handling for missing files
func TestNewLiveStore_NonExistentFile(t *testing.T) {
	_, err := leet.NewLiveStore("/nonexistent/path/file.wandb")
	if err == nil {
		t.Fatal("Expected error for non-existent file")
	}
}

// TestNewLiveStore_InvalidHeader tests handling of files with invalid headers
func TestNewLiveStore_InvalidHeader(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "invalid-header-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer os.Remove(tmpFile.Name())

	// Write invalid header data
	if _, err := tmpFile.Write([]byte("INVALID_HEADER_DATA")); err != nil {
		t.Fatalf("Failed to write invalid header: %v", err)
	}
	tmpFile.Close()

	_, err = leet.NewLiveStore(tmpFile.Name())
	if err == nil {
		t.Fatal("Expected error for invalid header")
	}
}

// TestLiveStore_ReadValidRecords tests reading valid records
func TestLiveStore_ReadValidRecords(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "records-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	// Write records using regular Store
	store := stream.NewStore(tmpFile.Name())
	if err := store.Open(os.O_WRONLY); err != nil {
		t.Fatalf("Failed to open store: %v", err)
	}

	records := []*spb.Record{
		{Num: 1, Uuid: "uuid-1"},
		{Num: 2, Uuid: "uuid-2"},
		{Num: 3, Uuid: "uuid-3"},
	}

	for _, rec := range records {
		if err := store.Write(rec); err != nil {
			t.Fatalf("Failed to write record: %v", err)
		}
	}
	store.Close()

	// Read with LiveStore
	ls, err := leet.NewLiveStore(tmpFile.Name())
	if err != nil {
		t.Fatalf("NewLiveStore failed: %v", err)
	}
	defer ls.Close()

	// Read all records
	for i, expected := range records {
		rec, err := ls.Read()
		if err != nil {
			t.Fatalf("Failed to read record %d: %v", i, err)
		}
		if rec.Num != expected.Num || rec.Uuid != expected.Uuid {
			t.Errorf("Record %d mismatch: got {Num:%d, Uuid:%s}, want {Num:%d, Uuid:%s}",
				i, rec.Num, rec.Uuid, expected.Num, expected.Uuid)
		}
	}

	// Next read should return EOF
	_, err = ls.Read()
	if !errors.Is(err, io.EOF) {
		t.Fatalf("Expected EOF, got: %v", err)
	}
}

// TestLiveStore_CloseIdempotent tests that Close can be called multiple times
func TestLiveStore_CloseIdempotent(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "close-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	// Create valid file
	store := stream.NewStore(tmpFile.Name())
	_ = store.Open(os.O_WRONLY)
	store.Close()

	ls, err := leet.NewLiveStore(tmpFile.Name())
	if err != nil {
		t.Fatalf("NewLiveStore failed: %v", err)
	}

	// Close multiple times
	if err := ls.Close(); err != nil {
		t.Fatalf("First Close() failed: %v", err)
	}
	if err := ls.Close(); err != nil {
		t.Fatalf("Second Close() failed: %v", err)
	}
	if err := ls.Close(); err != nil {
		t.Fatalf("Third Close() failed: %v", err)
	}
}

// TestLiveStore_ReadAfterClose tests that reading after close returns an error
func TestLiveStore_ReadAfterClose(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "read-after-close-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	// Create valid file with a record
	store := stream.NewStore(tmpFile.Name())
	_ = store.Open(os.O_WRONLY)
	_ = store.Write(&spb.Record{Num: 1, Uuid: "test"})
	store.Close()

	ls, err := leet.NewLiveStore(tmpFile.Name())
	if err != nil {
		t.Fatalf("NewLiveStore failed: %v", err)
	}

	// Close the LiveStore
	ls.Close()

	// Try to read after close
	_, err = ls.Read()
	if err == nil {
		t.Fatal("Expected error when reading from closed LiveStore")
	}
	if !errors.Is(err, os.ErrClosed) && err.Error() != "livestore: db is closed" {
		t.Fatalf("Unexpected error: %v", err)
	}
}

// TestLiveStore_LiveRead_ConcurrentWriterFlushes writes records in one goroutine
// using the low-level LevelDB writer (so we can Flush) and reads them from another.
// It ensures we see newly flushed records in order, and only get io.EOF between flushes.
func TestLiveStore_LiveRead_ConcurrentWriterFlushes(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "live-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
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
			rec := &spb.Record{
				Num:  int64(i),
				Uuid: fmt.Sprintf("uuid-%d", i),
			}
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
	ls, err := leet.NewLiveStore(tmp.Name())
	if err != nil {
		t.Fatalf("NewLiveStore: %v", err)
	}
	defer ls.Close()

	deadline := time.After(5 * time.Second)
	for i := 0; i < total; {
		select {
		case <-deadline:
			t.Fatalf("timeout waiting for record %d/%d", i, total)
		default:
			rec, err := ls.Read()
			if err == io.EOF {
				// No complete record yet; try again shortly.
				time.Sleep(1 * time.Millisecond)
				continue
			}
			if err != nil {
				t.Fatalf("Read: %v", err)
			}
			if rec.Num != int64(i) || rec.Uuid != fmt.Sprintf("uuid-%d", i) {
				t.Fatalf("out of order: got Num=%d Uuid=%q; want Num=%d Uuid=%q", rec.Num, rec.Uuid, i, fmt.Sprintf("uuid-%d", i))
			}
			i++
		}
	}
	wg.Wait()
}

func TestLiveStore_LiveRead_OpenedBeforeWriter(t *testing.T) {
	tmp, err := os.CreateTemp(t.TempDir(), "live-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	_ = tmp.Close()

	// Start reader first: header may not exist yet; allowed by NewLiveStore.
	ls, err := leet.NewLiveStore(tmp.Name())
	if err != nil {
		t.Fatalf("NewLiveStore: %v", err)
	}
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

		rec := &spb.Record{Num: 1, Uuid: "first"}
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
			if err == io.EOF {
				time.Sleep(1 * time.Millisecond)
				continue
			}
			if err != nil {
				t.Fatalf("Read: %v", err)
			}
			if rec.Num != 1 || rec.Uuid != "first" {
				t.Fatalf("unexpected record: %+v", rec)
			}
			wg.Wait()
			return
		}
	}
}

// TestLiveStore_LargeRecord tests handling of large records
func TestLiveStore_LargeRecord(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "large-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := stream.NewStore(tmpFile.Name())
	if err := store.Open(os.O_WRONLY); err != nil {
		t.Fatalf("Failed to open store: %v", err)
	}

	// Create a large record
	largeData := make([]byte, 1024*1024) // 1MB
	for i := range largeData {
		largeData[i] = byte(i % 256)
	}

	largeRecord := &spb.Record{
		Num:  1,
		Uuid: hex.EncodeToString(largeData[:16]), // Use first 16 bytes as UUID
	}

	if err := store.Write(largeRecord); err != nil {
		t.Fatalf("Failed to write large record: %v", err)
	}
	store.Close()

	// Read with LiveStore
	ls, err := leet.NewLiveStore(tmpFile.Name())
	if err != nil {
		t.Fatalf("NewLiveStore failed: %v", err)
	}
	defer ls.Close()

	rec, err := ls.Read()
	if err != nil {
		t.Fatalf("Failed to read large record: %v", err)
	}
	if rec.Num != largeRecord.Num || rec.Uuid != largeRecord.Uuid {
		t.Errorf("Large record mismatch")
	}
}

// TestLiveStore_PartialWrite tests handling of partial writes
func TestLiveStore_PartialWrite(t *testing.T) {
	tmpFile, err := os.CreateTemp(t.TempDir(), "partial-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer os.Remove(tmpFile.Name())

	// Write header
	store := stream.NewStore(tmpFile.Name())
	if err := store.Open(os.O_WRONLY); err != nil {
		t.Fatalf("Failed to open store: %v", err)
	}

	// Write one complete record
	if err := store.Write(&spb.Record{Num: 1, Uuid: "complete"}); err != nil {
		t.Fatalf("Failed to write record: %v", err)
	}
	store.Close()

	// Append partial record data (simulate interrupted write)
	f, err := os.OpenFile(tmpFile.Name(), os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		t.Fatalf("Failed to open for append: %v", err)
	}
	// Write incomplete record header
	_, _ = f.Write([]byte{0x00, 0x00}) // Partial record that will cause read error
	f.Close()

	// Try to read
	ls, err := leet.NewLiveStore(tmpFile.Name())
	if err != nil {
		t.Fatalf("NewLiveStore failed: %v", err)
	}
	defer ls.Close()

	// First record should be readable
	rec, err := ls.Read()
	if err != nil {
		t.Fatalf("Failed to read complete record: %v", err)
	}
	if rec.Num != 1 {
		t.Errorf("Expected Num=1, got %d", rec.Num)
	}

	// Second read should fail or return EOF
	_, err = ls.Read()
	if err == nil {
		t.Fatal("Expected error for partial record")
	}
}
