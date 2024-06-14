package server_test

import (
	"context"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestValidHeader(t *testing.T) {
	header := server.NewHeader()

	r, w := io.Pipe()

	go func() {
		defer w.Close()
		err := header.MarshalBinary(w)
		assert.NoError(t, err)
	}()

	err := header.UnmarshalBinary(r)
	assert.NoError(t, err)
	assert.True(t, header.Valid())
	_ = r.Close()
}

// Test to check the Invalid scenario
func TestInvalidHeader(t *testing.T) {
	header := server.HeaderOptions{
		IDENT:   [4]byte{'a', 'b', 'c', 'd'},
		Magic:   0xABCD,
		Version: 1,
	}

	r, w := io.Pipe()

	go func() {
		defer w.Close()
		err := header.MarshalBinary(w)
		assert.NoError(t, err)
	}()

	err := header.UnmarshalBinary(r)
	assert.NoError(t, err)
	assert.False(t, header.Valid())
	_ = r.Close()
}

func TestOpenCreateStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(context.Background(), tmpFile.Name())
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

	store := server.NewStore(context.Background(), tmpFile.Name())
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(context.Background(), tmpFile.Name())
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

	store := server.NewStore(context.Background(), tmpFile.Name())
	defer store.Close()

	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &service.Record{Num: 1, Uuid: "test-uuid"}

	err = store.Write(record)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(context.Background(), tmpFile.Name())
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

	store := server.NewStore(context.Background(), tmpFile.Name())
	defer store.Close()

	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &service.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.NoError(t, err)

	_, err = store.WriteDirectlyToDB([]byte("bad record"))
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(context.Background(), tmpFile.Name())
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)
	defer store2.Close()

	_, err = store2.Read()
	assert.Error(t, err)

	err = store2.Close()
	assert.NoError(t, err)
}

// Test to check the InvalidHeader scenario
func TestStoreInvalidHeader(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-invalid-header")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(context.Background(), tmpFile.Name())

	// Intentionally writing bad header data
	err = os.WriteFile(tmpFile.Name(), []byte("Invalid"), 0644)
	assert.NoError(t, err)

	err = store.Open(os.O_RDONLY)
	assert.Error(t, err)
}

// TestStoreHeader_Write_Error is intended to test the error scenario when writing the header
func TestStoreHeader_Write_Error(t *testing.T) {
	store := server.NewStore(context.Background(), "non_existent_dir/file")
	err := store.Open(os.O_WRONLY)
	assert.Error(t, err)
}

// TestInvalidFlag tests the scenario where an invalid flag is provided in the Open() method
func TestInvalidFlag(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(context.Background(), tmpFile.Name())
	err = store.Open(9999) // 9999 is an invalid flag
	assert.Errorf(t, err, "invalid flag %d", 9999)
}

// TestWriteToClosedStore tests the scenario where a record is written to a closed store.
func TestWriteToClosedStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(context.Background(), tmpFile.Name())
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	record := &service.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.Error(t, err, "can't write header")
}

// TestReadFromClosedStore tests the scenario where a record is read from a closed store.
func TestReadFromClosedStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(context.Background(), tmpFile.Name())
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &service.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	_, err = store.Read()
	assert.Error(t, err, "can't read record")
}
