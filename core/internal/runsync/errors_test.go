package runsync_test

import (
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"

	. "github.com/wandb/wandb/core/internal/runsync"
)

func TestToUserText_SyncError(t *testing.T) {
	err := &SyncError{
		Message:  "internal text",
		UserText: "A problem happened.",
	}

	userText := ToUserText(err)

	assert.Equal(t, "A problem happened.", userText)
}

func TestToUserText_SyncErrorWithoutUserText(t *testing.T) {
	err := &SyncError{Message: "internal text"}

	userText := ToUserText(err)

	assert.Equal(t, "Internal error: internal text", userText)
}

func TestToUserText_UnknownError(t *testing.T) {
	err := fmt.Errorf("test error")

	userText := ToUserText(err)

	assert.Equal(t, "Internal error: test error", userText)
}
