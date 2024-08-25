package server_test

import (
	"fmt"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/server"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

	store := server.NewStore(tmpFile.Name())
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

	store := server.NewStore(tmpFile.Name())
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(tmpFile.Name())
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

	store := server.NewStore(tmpFile.Name())
	defer store.Close()

	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &spb.Record{Num: 1, Uuid: "test-uuid"}

	err = store.Write(record)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	store2 := server.NewStore(tmpFile.Name())
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

// AppendToFile appends the given data to the file specified by filename.
func AppendToFile(filename string, data []byte) error {
	// Open the file in append mode, create it if it doesn't exist
	file, err := os.OpenFile(filename, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("failed to open file: %w", err)
	}
	defer file.Close()

	// Write the data to the file
	_, err = file.Write(data)
	if err != nil {
		return fmt.Errorf("failed to write data to file: %w", err)
	}

	return nil
}

func TestCorruptFile(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(tmpFile.Name())
	defer store.Close()

	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &spb.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.NoError(t, err)
	err = store.Close()
	assert.NoError(t, err)

	err = AppendToFile(tmpFile.Name(), []byte("bad record"))
	assert.NoError(t, err)

	store2 := server.NewStore(tmpFile.Name())
	err = store2.Open(os.O_RDONLY)
	assert.NoError(t, err)
	defer store2.Close()

	// this record was fine (record num:1)
	_, err = store2.Read()
	assert.NoError(t, err)

	// this record is bad.. we appended a string to the file "bad record"
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

	store := server.NewStore(tmpFile.Name())

	// Intentionally writing bad header data
	err = os.WriteFile(tmpFile.Name(), []byte("Invalid"), 0644)
	assert.NoError(t, err)

	err = store.Open(os.O_RDONLY)
	assert.Error(t, err)
}

// TestStoreHeader_Write_Error is intended to test the error scenario when writing the header
func TestStoreHeader_Write_Error(t *testing.T) {
	store := server.NewStore("non_existent_dir/file")
	err := store.Open(os.O_WRONLY)
	assert.Error(t, err)
}

// TestInvalidFlag tests the scenario where an invalid flag is provided in the Open() method
func TestInvalidFlag(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(tmpFile.Name())
	err = store.Open(9999) // 9999 is an invalid flag
	assert.Errorf(t, err, "invalid flag %d", 9999)
}

// TestWriteToClosedStore tests the scenario where a record is written to a closed store.
func TestWriteToClosedStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(tmpFile.Name())
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	record := &spb.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.Error(t, err, "can't write header")
}

// TestReadFromClosedStore tests the scenario where a record is read from a closed store.
func TestReadFromClosedStore(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	store := server.NewStore(tmpFile.Name())
	err = store.Open(os.O_WRONLY)
	assert.NoError(t, err)

	record := &spb.Record{Num: 1, Uuid: "test-uuid"}
	err = store.Write(record)
	assert.NoError(t, err)

	err = store.Close()
	assert.NoError(t, err)

	_, err = store.Read()
	assert.Error(t, err, "can't read record")
}
