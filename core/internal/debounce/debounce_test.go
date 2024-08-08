package debounce_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/debounce"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/time/rate"
)

func TestNewDebouncer(t *testing.T) {
	logger := observability.NewNoOpLogger()
	debouncer := debounce.NewDebouncer(rate.Every(time.Second), 1, logger)
	assert.NotNil(t, debouncer)
}

func TestDebouncer(t *testing.T) {
	logger := observability.NewNoOpLogger()
	debouncer := debounce.NewDebouncer(rate.Every(time.Millisecond*50), 1, logger)

	count := 0
	debouncer.SetNeedsDebounce()
	debouncer.Debounce(func() {
		count++
	})

	debouncer.Debounce(func() {
		count++
	})

	time.Sleep(time.Millisecond * 150)
	assert.Equal(t, 1, count)
}
