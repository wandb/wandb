package server_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/nexus/pkg/server"
)

func TestShortID(t *testing.T) {
	t.Run("shortid", func(t *testing.T) {
		item := server.ShortID(8)
		assert.Equal(t, len(item), 8)
	})
}
