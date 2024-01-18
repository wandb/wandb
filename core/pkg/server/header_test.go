package server_test

import (
	"context"
	"io"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/store"
	"github.com/wandb/wandb/core/pkg/server"
)

// Test to check the Valid scenario
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

// Test to check the InvalidHeader scenario
func TestStoreInvalidHeader(t *testing.T) {
	db, err := os.CreateTemp("", "temp-invalid-header")
	assert.NoError(t, err)
	defer os.Remove(db.Name())
	db.Close()

	rd := store.New(context.Background(),
		store.StoreOptions{
			Name:   db.Name(),
			Flag:   os.O_RDONLY,
			Header: &server.HeaderOptions{},
		},
	)
	// Intentionally writing bad header data
	err = os.WriteFile(db.Name(), []byte("Invalid"), 0644)
	assert.NoError(t, err)

	err = rd.Open()
	assert.Error(t, err)
}
