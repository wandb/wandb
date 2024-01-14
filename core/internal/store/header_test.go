package store_test

import (
	"io"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/store"
)

// Test to check the Valid scenario
func TestValidHeader(t *testing.T) {
	header := store.NewHeader()

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
	header := store.HeaderOptions{
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
