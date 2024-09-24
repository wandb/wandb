package randomid_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/randomid"
)

func TestShortID(t *testing.T) {
	t.Run("shortid", func(t *testing.T) {
		item := randomid.GenerateUniqueID(8)
		assert.Equal(t, len(item), 8)
	})
}
