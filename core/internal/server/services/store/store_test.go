package store_test

import (
	"context"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/server/services/store"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func TestStoreHeaderReadWrite(t *testing.T) {
	header := store.SHeader{}

	r, w := io.Pipe()

	go func() {
		defer w.Close()
		err := header.Write(w)
		assert.NoError(t, err)
	}()

	err := header.Read(r)
	assert.NoError(t, err)
	headerString := header.GetIdent()
	assert.Equal(t, store.HeaderIdent, string(headerString[:]))
	assert.Equal(t, uint16(store.HeaderMagic), header.GetMagic())
	assert.Equal(t, byte(store.HeaderVersion), header.GetVersion())
	_ = r.Close()
}

func TestOpenCreateStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store := store.New(context.Background(), tmpFile.Name(), logger)
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)
}

func TestOpenReadStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store1.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store1.Close()
	assert.NoError(t, err)

	store2 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)

	err = store2.Close()
	assert.NoError(t, err)
}

func TestReadWriteRecord(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)
	defer store1.Close()

	err = store1.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &pb.Record{Num: 1, Uuid: "test-uuid"}

	err = store1.Write(record)
	assert.NoError(t, err)

	err = store1.Close()
	assert.NoError(t, err)

	store2 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)
	defer store2.Close()

	readRecord, err := store2.Read()
	assert.NoError(t, err)

	assert.Equal(t, record.Control, readRecord.Control)
	assert.Equal(t, record.Num, readRecord.Num)
	assert.Equal(t, record.Uuid, readRecord.Uuid)
	err = store2.Close()
	assert.NoError(t, err)
}

func TestCorruptFile(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)
	defer store1.Close()

	err = store1.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &pb.Record{Num: 1, Uuid: "test-uuid"}
	err = store1.Write(record)
	assert.NoError(t, err)

	_, err = store1.WriteDirectlyToDB([]byte("bad record"))
	assert.NoError(t, err)

	err = store1.Close()
	assert.NoError(t, err)

	store2 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)
	defer store2.Close()

	_, err = store2.Read()
	assert.Error(t, err)

	err = store2.Close()
	assert.NoError(t, err)
}

// Test to check the InvalidHeader scenario
func TestInvalidHeader(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-invalid-header")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)

	// Intentionally writing bad header data
	err = os.WriteFile(tmpFile.Name(), []byte("Invalid"), 0644)
	assert.NoError(t, err)

	err = store1.Open(os.O_RDONLY)
	assert.Error(t, err)
}

// TestStoreHeader_Write_Error is intended to test the error scenario when writing the header
func TestStoreHeader_Write_Error(t *testing.T) {
	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), "non_existent_dir/file", logger)
	err := store1.Open(os.O_WRONLY)
	assert.Error(t, err)
}

// TestInvalidFlag tests the scenario where an invalid flag is provided in the Open() method
func TestInvalidFlag(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store1.Open(9999) // 9999 is an invalid flag
	assert.Errorf(t, err, "invalid flag %d", 9999)
}

// TestWriteToClosedStore tests the scenario where a record is written to a closed store.
func TestWriteToClosedStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store1.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store1.Close()
	assert.NoError(t, err)

	record := &pb.Record{Num: 1, Uuid: "test-uuid"}
	err = store1.Write(record)
	assert.Error(t, err, "can't write header")
}

// TestReadFromClosedStore tests the scenario where a record is read from a closed store.
func TestReadFromClosedStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	logger := observability.NewNoOpLogger()
	store1 := store.New(context.Background(), tmpFile.Name(), logger)
	err = store1.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &pb.Record{Num: 1, Uuid: "test-uuid"}
	err = store1.Write(record)
	assert.NoError(t, err)

	err = store1.Close()
	assert.NoError(t, err)

	_, err = store1.Read()
	assert.Error(t, err, "can't read record")
}
