package namedgoroutines_test

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/namedgoroutines"
	"golang.org/x/sync/errgroup"
)

func TestDifferentKeys_Concurrent(t *testing.T) {
	blockers := []chan struct{}{
		make(chan struct{}),
		make(chan struct{}),
		make(chan struct{}),
	}
	results := make(chan int)
	op := namedgoroutines.New(1, &errgroup.Group{}, func(blockerID int) {
		<-blockers[blockerID]
		results <- blockerID
	})

	op.Go("zero", 0)
	op.Go("one", 1)
	op.Go("two", 2)
	blockers[1] <- struct{}{}
	result1 := <-results
	blockers[0] <- struct{}{}
	result2 := <-results
	blockers[2] <- struct{}{}
	result3 := <-results

	assert.Equal(t, 1, result1)
	assert.Equal(t, 0, result2)
	assert.Equal(t, 2, result3)
}

func TestSameKey_Serialized(t *testing.T) {
	results := make(chan int, 100)
	op := namedgoroutines.New(1, &errgroup.Group{}, func(x int) {
		results <- x
	})

	for i := range 100 {
		op.Go("key", i)
	}

	for i := range 100 {
		assert.Equal(t, i, <-results)
	}
}

func TestLimitsConcurrency(t *testing.T) {
	results := make(chan int, 100)
	pool := &errgroup.Group{}
	pool.SetLimit(1)
	op := namedgoroutines.New(1, pool, func(x int) {
		results <- x
	})

	for i := range 100 {
		// All keys are different, so the concurrency is limited by
		// the errgroup.
		op.Go(fmt.Sprintf("key %d", i), i)
	}

	for i := range 100 {
		assert.Equal(t, i, <-results)
	}
}

func TestSameKey_BufferedChannel(t *testing.T) {
	// Run several times to increase likelihood of detecting failure.
	for range 10 {
		results := make(chan int)
		finalGo := make(chan struct{})
		op := namedgoroutines.New(10, &errgroup.Group{}, func(x int) {
			results <- x
		})

		// 11 operations should be non-blocking:
		// - 1 is picked up by a goroutine
		// - 10 fill up a channel buffer
		for i := range 11 {
			op.Go("key", i)
		}
		// The 12th blocks until one of the previous completes.
		go func() {
			op.Go("key", 12)
			close(finalGo)
		}()

		select {
		case <-results:
		case <-finalGo:
			t.Fatal("12th call to Go didn't block")
		}
		select {
		case <-finalGo:
		case <-time.After(time.Second):
			t.Fatal("12th call to Go didn't get unblocked")
		}
	}
}
