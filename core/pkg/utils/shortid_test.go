package utils_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/utils"
)

func TestShortID(t *testing.T) {
	t.Run("shortid", func(t *testing.T) {
		item := utils.ShortID(8)
		assert.Equal(t, len(item), 8)
	})
}
