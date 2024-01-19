package store_test

import (
	"context"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/store"
)

func TestOpenCreateStore(t *testing.T) {
	db, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_WRONLY,
		},
	)
	err = wr.Open()
	assert.NoError(t, err)

	err = wr.Close()
	assert.NoError(t, err)
}

func TestOpenReadStore(t *testing.T) {
	db, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_WRONLY,
		},
	)
	err = wr.Open()
	assert.NoError(t, err)

	err = wr.Close()
	assert.NoError(t, err)

	rd := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_RDONLY,
		},
	)
	err = rd.Open()
	assert.NoError(t, err)

	err = rd.Close()
	assert.NoError(t, err)
}

func TestReadWriteRecord(t *testing.T) {
	db, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_WRONLY,
		},
	)
	defer wr.Close()

	err = wr.Open()
	assert.NoError(t, err)

	bufwr := []byte("test")
	assert.NoError(t, err)

	err = wr.Write(bufwr)
	assert.NoError(t, err)

	err = wr.Close()
	assert.NoError(t, err)

	rd := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_RDONLY,
		},
	)
	err = rd.Open()
	assert.NoError(t, err)
	defer rd.Close()

	bufrd, err := rd.Read()
	assert.NoError(t, err)

	assert.Equal(t, bufwr, bufrd)
	err = rd.Close()
	assert.NoError(t, err)
}

func TestCorruptFile(t *testing.T) {
	db, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_WRONLY,
		},
	)
	defer wr.Close()

	err = wr.Open()
	assert.NoError(t, err)

	bufwr := []byte("test")
	err = wr.Write(bufwr)
	assert.NoError(t, err)

	_, err = wr.WriteDirectly([]byte("currupt"))
	assert.NoError(t, err)

	err = wr.Close()
	assert.NoError(t, err)

	rd := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_RDONLY,
		},
	)
	err = rd.Open()
	assert.NoError(t, err)
	defer rd.Close()

	_, err = rd.Read()
	assert.Error(t, err)

	err = rd.Close()
	assert.NoError(t, err)
}

// TestHeaderWriteError tests the scenario where an error occurs while writing the header
func TestHeaderWriteError(t *testing.T) {
	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: "non_existent_dir/file",
			Flag: os.O_WRONLY,
		},
	)
	err := wr.Open()
	assert.Error(t, err)
}

// TestInvalidFlag tests the scenario where an invalid flag is provided in the Open() method
func TestInvalidFlag(t *testing.T) {
	tmpFile, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(tmpFile.Name())
	tmpFile.Close()

	flag := 9999
	invalid := store.New(context.Background(),
		store.StoreOptions{
			Name: tmpFile.Name(),
			Flag: flag, // invalid flag
		},
	)
	err = invalid.Open()
	assert.ErrorIs(t, err, store.ErrInvalidFlag)
}

// TestWriteToClosedStore tests the scenario where a record is written to a closed store.
func TestWriteToClosedStore(t *testing.T) {
	db, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_WRONLY,
		},
	)
	err = wr.Open()
	assert.NoError(t, err)

	err = wr.Close()
	assert.NoError(t, err)

	bufwr := []byte("test")
	err = wr.Write(bufwr)
	assert.Error(t, err, "can't write to closed store")
}

// TestReadFromClosedStore tests the scenario where a record is read from a closed store.
func TestReadFromClosedStore(t *testing.T) {
	db, err := os.CreateTemp("", "temp-db")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	wr := store.New(context.Background(),
		store.StoreOptions{
			Name: db.Name(),
			Flag: os.O_WRONLY,
		},
	)
	err = wr.Open()
	assert.NoError(t, err)

	bufwr := []byte("test")
	err = wr.Write(bufwr)
	assert.NoError(t, err)

	err = wr.Close()
	assert.NoError(t, err)

	_, err = wr.Read()
	assert.Error(t, err, "can't read from closed store")
}
