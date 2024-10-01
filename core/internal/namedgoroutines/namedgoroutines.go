// Package namedgoroutines implements a concurrency pattern where
// operations for the same key happen in series.
package namedgoroutines

import (
	"sync"

	"golang.org/x/sync/errgroup"
)

// Operation runs a function in a new goroutine for each input
// except for those that share a key.
type Operation[T any] struct {
	// buffer is the buffer size of each channel in inputsByKey.
	buffer int

	// workerPool is used to limit concurrency.
	workerPool *errgroup.Group

	// processInput is the function to run on each input.
	processInput func(T)

	// inputsByKey maps keys to the input channel for the goroutine
	// for that key.
	//
	// There is an active goroutine for a key if and only if that key
	// is in this map.
	inputsByKey map[string]chan T

	// inputsByKeyCond is locked for modifying inputsByKey or any channels
	// stored in it, including sending or receiving on a channel.
	//
	// It is broadcast whenever space is made in a channel buffer.
	inputsByKeyCond *sync.Cond
}

func New[T any](
	buffer int,
	workerPool *errgroup.Group,
	fn func(T),
) *Operation[T] {
	return &Operation[T]{
		buffer:          buffer,
		workerPool:      workerPool,
		inputsByKey:     make(map[string]chan T),
		processInput:    fn,
		inputsByKeyCond: sync.NewCond(&sync.Mutex{}),
	}
}

// Go runs the operation for the input in the goroutine identified by the key.
//
// If two Go calls for the same key happen one after another, their inputs
// are guaranteed to be processed in the same order.
//
// This may block if buffers for the key are full. It is invalid for
// the underlying function to call Go.
func (o *Operation[T]) Go(key string, input T) {
	o.inputsByKeyCond.L.Lock()
	defer o.inputsByKeyCond.L.Unlock()

	// Loop trying to push the input to the channel for the key.
	//
	// If the channel buffer is full, we release the lock and try
	// again later.
	for {
		inputs := o.inputsByKey[key]

		if inputs == nil {
			o.scheduleGoroutine(key, input)
			return
		}

		select {
		case inputs <- input:
			return

		default:
			o.inputsByKeyCond.Wait()
		}
	}
}

// scheduleGoroutine creates a new goroutine for the key and immediately
// queues the given input.
//
// The mutex must be held. This temporarily releases the mutex.
func (o *Operation[T]) scheduleGoroutine(key string, input T) {
	inputs := make(chan T, max(o.buffer, 1))
	inputs <- input
	o.inputsByKey[key] = inputs

	// Don't hold the mutex while waiting to schedule the goroutine.
	o.inputsByKeyCond.L.Unlock()
	o.workerPool.Go(func() error {
		o.processInputsForKey(key, inputs)
		return nil
	})
	o.inputsByKeyCond.L.Lock()
}

// nextInputForKey returns a buffered value from the inputs channel,
// or removes the key from the map if the channel was empty.
//
// Returns true if there was a value and false otherwise.
func (o *Operation[T]) nextInputForKey(
	key string,
	inputs <-chan T,
) (T, bool) {
	o.inputsByKeyCond.L.Lock()
	defer o.inputsByKeyCond.L.Unlock()

	select {
	case input := <-inputs:
		o.inputsByKeyCond.Broadcast()
		return input, true

	default:
		delete(o.inputsByKey, key)
		return *new(T), false
	}
}

func (o *Operation[T]) processInputsForKey(
	key string,
	inputs <-chan T,
) {
	for {
		input, ok := o.nextInputForKey(key, inputs)
		if !ok {
			break
		}

		o.processInput(input)
	}
}
