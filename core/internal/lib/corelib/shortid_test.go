package corelib_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/lib/corelib"
)

func TestShortID(t *testing.T) {
	t.Run("shortid", func(t *testing.T) {
		item := corelib.ShortID(8)
		assert.Equal(t, len(item), 8)
	})
}
