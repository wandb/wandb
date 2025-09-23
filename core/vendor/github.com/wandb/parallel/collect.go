package parallel

import (
	"context"
	"runtime"
	"sync/atomic"
)

// Executor that runs until the first error encountered
type ErrGroupExecutor interface {
	// Go submits a task to the Executor, to be run at some point in the future.
	//
	// Panics if Wait() has already been called.
	// May panic if any submitted task has already panicked.
	Go(func(context.Context) error)
	// Wait waits until all submitted tasks have completed, then returns one
	// error if any errors were returned by submitted tasks (or nil).
	//
	// After waiting, panics if any submitted task panicked.
	Wait() error
}

// Executor that collects all the return values of the operations, then returns
// the resulting slice or an error if any occurred.
type CollectingExecutor[T any] interface {
	// Go submits a task to the Executor, to be run at some point in the future.
	//
	// Panics if Wait() has already been called.
	// May panic if any submitted task has already panicked.
	Go(func(context.Context) (T, error))
	// Wait waits until all submitted tasks have completed, then returns a slice
	// of the returned values from non-erring tasks or an error if any occurred.
	//
	// After waiting, panics if any submitted task panicked.
	Wait() ([]T, error)
}

// Executor that feeds all the return values of the operations to a user
// function.
type FeedingExecutor[T any] interface {
	// Go submits a task to the Executor, to be run at some point in the future.
	//
	// Panics if Wait() has already been called.
	// May panic if any submitted task has already panicked.
	Go(func(context.Context) (T, error))
	// Wait waits until all running tasks have completed and all returned values
	// from non-erring tasks have been processed by the receiver function, then
	// returns an error if any occurred.
	//
	// After waiting, panics if any submitted task panicked.
	Wait() error
}

// Executor that collects every error from the operations.
type AllErrsExecutor interface {
	// Go submits a task to the Executor, to be run at some point in the future.
	//
	// Panics if Wait() has already been called.
	// May panic if any submitted task has already panicked.
	Go(func(context.Context) error)
	// Wait waits until all submitted tasks have completed, then returns a
	// MultiError of any errors that were returned by submitted tasks (or nil).
	//
	// After waiting, panics if any submitted task panicked.
	Wait() MultiError
}

// Executor that collects the returned values and errors of the operations.
type CollectingAllErrsExecutor[T any] interface {
	// Go submits a task to the Executor, to be run at some point in the future.
	//
	// Panics if Wait() has already been called.
	// May panic if any submitted task has already panicked.
	Go(func(context.Context) (T, error))
	// Wait waits until all submitted tasks have completed, then returns a slice
	// of the returned values from non-erring tasks and a MultiError of any
	// errors returned (or nil).
	//
	// After waiting, panics if any submitted task panicked.
	Wait() ([]T, MultiError)
}

// Executor that feeds all the return values of the operations to a user
// function and collects returned errors.
type FeedingAllErrsExecutor[T any] interface {
	// Go submits a task to the Executor, to be run at some point in the future.
	//
	// Panics if Wait() has already been called.
	// May panic if any submitted task has already panicked.
	Go(func(context.Context) (T, error))
	// Wait waits until all submitted tasks have completed and all returned
	// values from non-erring tasks have been processed by the receiver
	// function, then returns a MultiError of any errors that were returned by
	// the tasks (or nil).
	//
	// After waiting, panics if any submitted task panicked.
	Wait() MultiError
}

// Returns an executor that halts if any submitted task returns an error, and
// returns one error from Wait() if any occurred.
func ErrGroup(executor Executor) ErrGroupExecutor {
	return &errGroup{executor}
}

// Returns an executor that collects all the return values from the functions
// provided, returning them (in no guaranteed order!) in a slice at the end.
//
// These executors are even best-effort safe against misuse: if the owner panics
// or otherwise forgets to call Wait(), the goroutines started by this executor
// should still be cleaned up.
func Collect[T any](executor Executor) CollectingExecutor[T] {
	making := collectingGroup[T]{makePipeGroup[T, *[]T](executor)}
	var outOfLineResults []T
	making.res = &outOfLineResults
	pipe := making.pipe // Don't capture a pointer to the executor
	making.pipeWorkers.Go(func(context.Context) {
		for item := range pipe {
			outOfLineResults = append(outOfLineResults, item)
		}
	})
	return making
}

// Returns an executor that collects all the return values from the functions
// provided, passing them all (in no guaranteed order!) to the provided
// receiver, which runs in a single goroutine by itself. In the event of an
// error from either the work functions or the receiver function, execution
// halts and the first error is returned.
//
// These executors are even best-effort safe against misuse: if the owner panics
// or otherwise forgets to call Wait(), the goroutines started by this executor
// should still be cleaned up.
func Feed[T any](executor Executor, receiver func(context.Context, T) error) FeedingExecutor[T] {
	making := feedingGroup[T]{makePipeGroup[T, struct{}](executor)}
	pipe := making.pipe // Don't capture a pointer to the executor
	_, cancel := making.g.getContext()
	making.pipeWorkers.Go(func(ctx context.Context) {
		for val := range pipe {
			if err := receiver(ctx, val); err != nil {
				cancel(err)
				for range pipe {
					// Discard all future values
				}
				return
			}
		}
	})
	return making
}

// Returns an executor similar to parallel.ErrGroup, except instead of only
// returning the first error encountered it returns a MultiError of any & all
// errors encountered (or nil if none).
//
// These executors are even best-effort safe against misuse: if the owner panics
// or otherwise forgets to call Wait(), the goroutines started by this executor
// should still be cleaned up.
func GatherErrs(executor Executor) AllErrsExecutor {
	making := multiErrGroup{makePipeGroup[error, *[]error](executor)}
	var outOfLineErrs []error
	making.res = &outOfLineErrs
	pipe := making.pipe // Don't capture a pointer to the executor
	making.pipeWorkers.Go(func(context.Context) {
		for err := range pipe {
			outOfLineErrs = append(outOfLineErrs, err)
		}
	})
	return making
}

// Returns an executor that collects both values and a MultiError of any & all
// errors (or nil if none). Return values are not included in the results if
// that invocation returned an error. Execution does not stop if errors are
// encountered, only if there is a panic.
//
// These executors are even best-effort safe against misuse: if the owner panics
// or otherwise forgets to call Wait(), the goroutines started by this executor
// should still be cleaned up.
func CollectWithErrs[T any](executor Executor) CollectingAllErrsExecutor[T] {
	making := collectingMultiErrGroup[T]{
		makePipeGroup[withErr[T], *collectedResultWithErrs[T]](executor),
	}
	var outOfLineResults collectedResultWithErrs[T]
	making.res = &outOfLineResults
	pipe := making.pipe // Don't capture a pointer to the executor
	making.pipeWorkers.Go(func(context.Context) {
		for item := range pipe {
			if item.err != nil {
				outOfLineResults.errs = append(outOfLineResults.errs, item.err)
			} else {
				outOfLineResults.values = append(outOfLineResults.values, item.value)
			}
		}
	})
	return making
}

// Returns an executor that collects all the return values from the functions
// provided, passing them all (in no guaranteed order!) to the provided
// receiver, which runs in a single goroutine by itself. Execution does not stop
// if errors are encountered from either the work functions or the receiver
// function; those errors are all combined into the MultiError returned by
// Wait().
//
// These executors are even best-effort safe against misuse: if the owner panics
// or otherwise forgets to call Wait(), the goroutines started by this executor
// should still be cleaned up.
func FeedWithErrs[T any](executor Executor, receiver func(context.Context, T) error) FeedingAllErrsExecutor[T] {
	making := feedingMultiErrGroup[T]{makePipeGroup[withErr[T], *[]error](executor)}
	var outOfLineResults []error
	making.res = &outOfLineResults
	pipe := making.pipe // Don't capture a pointer to the executor
	making.pipeWorkers.Go(func(ctx context.Context) {
		for pair := range pipe {
			if pair.err != nil {
				outOfLineResults = append(outOfLineResults, pair.err)
			} else if processErr := receiver(ctx, pair.value); processErr != nil {
				outOfLineResults = append(outOfLineResults, processErr)
			}
		}
	})
	return making
}

// groupError returns the error associated with a group's context; if the error
// was errGroupDone, that doesn't count as an error and nil is returned instead.
func groupError(ctx context.Context) error {
	err := context.Cause(ctx)
	// We are explicitly using == here to check for the exact value of our
	// sentinel error, not using errors.Is(), because we don't actually want to
	// find it if it's in wrapped errors. We *only* want to know whether the
	// cancelation error is *exactly* errGroupDone.
	if err == errGroupDone {
		return nil
	}
	return err
}

var _ ErrGroupExecutor = &errGroup{}

type errGroup struct {
	g Executor
}

func (eg *errGroup) Go(op func(context.Context) error) {
	_, cancel := eg.g.getContext() // Don't capture a pointer to the group
	eg.g.Go(func(ctx context.Context) {
		err := op(ctx)
		if err != nil {
			cancel(err)
		}
	})
}

func (eg *errGroup) Wait() error {
	eg.g.Wait()
	ctx, _ := eg.g.getContext()
	return groupError(ctx)
}

func makePipeGroup[T any, R any](executor Executor) *pipeGroup[T, R] {
	making := &pipeGroup[T, R]{
		g:           executor,
		pipeWorkers: makeGroup(executor.getContext()), // use the same context for the pipe group
		pipe:        make(chan T, bufferSize),
	}
	runtime.SetFinalizer(making, func(doomed *pipeGroup[T, R]) {
		close(doomed.pipe)
	})
	return making
}

// Underlying implementation for executors that handle results.
//
// T is the type that goes through the pipe, and R is the return value field we
// are collecting into
type pipeGroup[T any, R any] struct {
	// All the constituent parts of this struct are out-of-line so that none of
	// the goroutines doing work for it need to hold a reference to any of this
	// memory. Thus, if the user forgets to call Wait(), we can hook the GC
	// finalizer and ensure that the channels are closed and the goroutines we
	// were running get cleaned up.
	g           Executor
	pipeWorkers *group
	pipe        chan T
	awaited     atomic.Bool
	res         R
}

func sendToPipe[T any](pipe chan T, val T) {
	defer func() {
		if recover() != nil {
			panic("parallel executor pipe error: a collector using this " +
				"same executor was probably not awaited")
		}
	}()
	pipe <- val
}

func (pg *pipeGroup[T, R]) doWait() {
	// This function sucks to look at because go has no concept of scoped
	// lifetime other than function-scope. You can only ensure something happens
	// even in case of a panic by deferring it, and that always only happens at
	// the end of the function... so, we just put an inner function here to make
	// it happen "early."

	// Runs last: We must make completely certain that we cancel the context
	// owned by the pipeGroup. This context is shared between the executor and
	// the pipeWorkers; we take charge of making sure this cancelation happens
	// as soon as possible here, and we want it to happen at the very end after
	// everything else in case something else wanted to set the cancel cause of
	// the context to an actual error instead of our "no error" sentinel value.
	defer pg.pipeWorkers.cancel(errGroupDone)
	func() {
		// Runs second: Close the results chan and unblock the pipe worker.
		// Because we're deferring this, it will happen even if there is a panic
		defer func() {
			if !pg.awaited.Swap(true) {
				close(pg.pipe)
				// Don't try to close this chan again :)
				runtime.SetFinalizer(pg, nil)
			}
		}()
		// Runs first: Wait for inputs. Wait "quietly", not canceling the
		// context yet so if there is an error later we can still see it
		pg.g.waitWithoutCanceling()
	}()
	// Runs third: Wait for outputs to be done
	pg.pipeWorkers.waitWithoutCanceling()
}

var _ CollectingExecutor[int] = collectingGroup[int]{}

type collectingGroup[T any] struct {
	*pipeGroup[T, *[]T]
}

func (cg collectingGroup[T]) Go(op func(context.Context) (T, error)) {
	pipe := cg.pipe // Don't capture a pointer to the group
	_, cancel := cg.g.getContext()
	cg.g.Go(func(ctx context.Context) {
		val, err := op(ctx)
		if err != nil {
			cancel(err)
			return
		}
		sendToPipe(pipe, val)
	})
}

func (cg collectingGroup[T]) Wait() ([]T, error) {
	cg.doWait()
	ctx, _ := cg.g.getContext()
	if err := groupError(ctx); err != nil {
		// We have an error; return it
		return nil, err
	}
	return *cg.res, nil
}

var _ FeedingExecutor[int] = feedingGroup[int]{}

type feedingGroup[T any] struct {
	*pipeGroup[T, struct{}]
}

func (fg feedingGroup[T]) Go(op func(context.Context) (T, error)) {
	pipe := fg.pipe // Don't capture a pointer to the group
	_, cancel := fg.g.getContext()
	fg.g.Go(func(ctx context.Context) {
		val, err := op(ctx)
		if err != nil {
			cancel(err)
			return
		}
		sendToPipe(pipe, val)
	})
}

func (fg feedingGroup[T]) Wait() error {
	fg.doWait()
	ctx, _ := fg.g.getContext()
	return groupError(ctx)
}

var _ AllErrsExecutor = multiErrGroup{}

type multiErrGroup struct {
	*pipeGroup[error, *[]error]
}

func (meg multiErrGroup) Go(op func(context.Context) error) {
	pipe := meg.pipe // Don't capture a pointer to the group
	meg.g.Go(func(ctx context.Context) {
		// Only send non-nil errors to the results pipe
		if err := op(ctx); err != nil {
			sendToPipe(pipe, err)
		}
	})
}

func (meg multiErrGroup) Wait() MultiError {
	meg.doWait()
	err := CombineErrors(*meg.res...)
	ctx, _ := meg.g.getContext()
	if cause := groupError(ctx); cause != nil {
		return CombineErrors(cause, err)
	}
	return err
}

var _ CollectingAllErrsExecutor[int] = collectingMultiErrGroup[int]{}

type withErr[T any] struct {
	value T
	err   error
}

type collectedResultWithErrs[T any] struct {
	values []T
	errs   []error
}

type collectingMultiErrGroup[T any] struct {
	*pipeGroup[withErr[T], *collectedResultWithErrs[T]]
}

func (ceg collectingMultiErrGroup[T]) Go(op func(context.Context) (T, error)) {
	pipe := ceg.pipe // Don't capture a pointer to the group
	ceg.g.Go(func(ctx context.Context) {
		value, err := op(ctx)
		sendToPipe(pipe, withErr[T]{value, err})
	})
}

func (ceg collectingMultiErrGroup[T]) Wait() ([]T, MultiError) {
	ceg.doWait()
	res, err := ceg.res.values, CombineErrors(ceg.res.errs...)
	ctx, _ := ceg.g.getContext()
	if cause := groupError(ctx); cause != nil {
		return res, CombineErrors(cause, err)
	}
	return res, err
}

var _ FeedingAllErrsExecutor[int] = feedingMultiErrGroup[int]{}

type feedingMultiErrGroup[T any] struct {
	*pipeGroup[withErr[T], *[]error]
}

func (feg feedingMultiErrGroup[T]) Go(op func(context.Context) (T, error)) {
	pipe := feg.pipe // Don't capture a pointer to the group
	feg.g.Go(func(ctx context.Context) {
		value, err := op(ctx)
		sendToPipe(pipe, withErr[T]{value, err})
	})
}

func (feg feedingMultiErrGroup[T]) Wait() MultiError {
	feg.doWait()
	err := CombineErrors(*feg.res...)
	ctx, _ := feg.g.getContext()
	if cause := groupError(ctx); cause != nil {
		return CombineErrors(cause, err)
	}
	return err
}
