package debounce

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"golang.org/x/time/rate"
)

func TestNewDebouncer(t *testing.T) {
	logger := observability.NewNoOpLogger()
	debouncer := NewDebouncer(rate.Every(time.Second), 1, logger)
	assert.NotNil(t, debouncer)
}

func TestDebouncer_Start(t *testing.T) {
	logger := observability.NewNoOpLogger()
	debouncer := NewDebouncer(rate.Every(time.Millisecond*50), 1, logger)

	count := 0
	debouncer.Start(func() {
		count++
	})

	time.Sleep(time.Millisecond * 300)
	debouncer.Close()
	// the function gets called once
	assert.Equal(t, 1, count)
}

func TestDebouncer_Trigger(t *testing.T) {
	logger := observability.NewNoOpLogger()
	debouncer := NewDebouncer(rate.Every(time.Millisecond*50), 1, logger)

	count := 0
	debouncer.Start(func() {
		count++
	})

	debouncer.Trigger()

	time.Sleep(time.Millisecond * 150)
	debouncer.Close()
	assert.Equal(t, 2, count)
}

func TestDebouncer_Close(t *testing.T) {
	logger := observability.NewNoOpLogger()
	debouncer := NewDebouncer(rate.Every(time.Second), 1, logger)

	closed := false
	debouncer.Start(func() {
		closed = true
	})

	debouncer.Close()
	assert.True(t, closed)
}
