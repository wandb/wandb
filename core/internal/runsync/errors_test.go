package runsync_test

import (
	"errors"
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observabilitytest"
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

func TestFirstSyncError_NoSyncError(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	err1 := fmt.Errorf("test error 1")
	var err2Nil error
	err3 := fmt.Errorf("test error 3")

	result := FirstSyncError(logger, err1, err2Nil, err3)

	assert.EqualError(t, result, errors.Join(err1, err3).Error())
	assert.Empty(t, logs.String())
}

func TestFirstSyncError_FindsSyncError(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	err1 := fmt.Errorf("test error 1")
	syncErr := &SyncError{Message: "test sync error"}
	var err2Nil error
	err3 := fmt.Errorf("test error 3")

	result := FirstSyncError(logger, err1, syncErr, err2Nil, err3)

	assert.Equal(t, syncErr, result)
	assert.Contains(t, logs.String(), err1.Error())
	assert.Contains(t, logs.String(), err3.Error())
}
