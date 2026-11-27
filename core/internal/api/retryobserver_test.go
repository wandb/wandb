package api

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestRetryObserver(t *testing.T) {
	ctx := withRetryObserver(context.Background())

	setLastRetriedError(ctx, "some error")

	assert.Equal(t, "some error", lastRetriedError(ctx))
}

func TestNoRetryObserver(t *testing.T) {
	ctx := context.Background()

	assert.NotPanics(t, func() { setLastRetriedError(ctx, "some error") })
	assert.Empty(t, lastRetriedError(ctx))
}
