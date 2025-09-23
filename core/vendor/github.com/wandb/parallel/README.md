# Parallel executors library
*The goroutine group library we wish we had*

## See also
[Contributing](/CONTRIBUTING.md)

[Security disclosures](/SECURITY.md)

[Code of Conduct](/CODE_OF_CONDUCT.md)

[License (Apache 2.0)](/LICENSE) & [copyright notice](/NOTICE)

[API quick-start 👇](#api)

## Motivation
Existing libraries and APIs for running code in parallel in golang are limited and laden with sharp edges.
* `WaitGroup` has a verbose and mistake-prone API. We must always remember to `.Add()` the correct number of times and must always `defer wg.Done()` in the associated goroutines.
* When performing work in parallel with a `WaitGroup`, there are no amenities for stopping early in the event of an error.
* It's also complicated to put limits on the number of goroutines that may be running in parallel.

There does exist a slightly friendlier library for such things: `x/sync/errgroup`. The `errgroup` library offers amenities for some of the aforementioned challenges:
* Goroutines are started in an `errgroup` with a simple `Go(func() error)` API, and completion is awaited via `Wait() error` on the same group object. 
* Stopping early is available via `WithContext(ctx)`
* Limiting concurrency is available via `SetLimit(n)`, which must be called before any work is submitted

It's pretty good, but it's not perfect. Managing the child context object dedicated to the group is particularly error prone: `WithContext()` returns both a `Group` and the `ctx` that it uses. Now we have two `Context` objects in scope, and we have to be super disciplined about always using the correct one, not just falling back on using `ctx` by habit.

Another challenge we have to contend with when using golang's parallelism is panic safety. In an ideologically pure world, panics only happen when something has gone severely sideways and the whole process should shut down. In reality, any sufficiently large codebase will have panics all over the place, especially since there is such a heavy reliance in the language upon pointers and fat-pointer types (interfaces) that we must always meticulously check. What's worse, panics that escape a non-main goroutine's main function in golang are *fundamentally unrecoverable.* We must strongly prefer to hoist panics out of isolated goroutines and into the controlling goroutine, where they are more likely to be handled by a framework or other dedicated recovery mechanism that can avoid crashing a large, long-running server process.

Even more complicated is the task of collecting or combining results from the work that happens inside the group. Synchronizing with the completion of the output requires a second wait group, because we must make sure that all the writers have completed before we tell the reader(s) to finish up. We can't really get around this: appending to a slice of results isn't thread-safe, and putting all the results into a channel to be read after writing has finished is also hazardous: channels have a fixed maximum size, and when they are full they block forever. A channel's buffer always consumes space, and it cannot reallocate to grow later like a slice will. Golang offers no real pre-built solution for a synchronized collection. It is inherently a little bit tricky, and yet another sort of thing we shouldn't have to trust ourselves to write exactly right every single time.

What's more, panics are relevant here too: if a panic occurs in (or is hoisted to) the controlling goroutine, open channels that are being used to pipe data for readers & writers can be left dangling open causing the goroutines waiting for them to leak, never continuing or terminating, taking up memory forever.

`errgroup` has an [effort](https://github.com/golang/go/issues/53757) to handle panics that has not ([at time of writing](https://go-review.googlesource.com/c/sync/+/416555)) borne any fruit. The authors are not aware of any effort to automate cleanups of discarded groups, simplify collection of results, or remove which-context-do-we-use style footguns.

We hope to solve all these problems here, in a single library. It should be:
1. an easy and obvious choice for every reasonable use case (several slightly different APIs provided for different use cases),
2. as hard to get wrong as possible (panic and leak safety, always providing contexts inside work functions; there are many subtle ways for such APIs to be error prone), and
3. easy to remember the available features for
   * even while referencing `errgroup` while writing this library, it was all too easy to forget that it even has features like `SetLimit(int)`
   * it's preferable that in places where more options exist the chosen behavior is explicit and configured up front in the first function call :)

## API
For simply running work to completion, we have some very simple executors:
* introducing `parallel.Unlimited(ctx)`
   ```go
   group := parallel.Unlimited(ctx)
   group.Go(func(ctx context.Context) {
       println("yes")
   })
   group.Wait()
   // at this point, it's guaranteed that all functions
   // that were sent to the group have completed!
   // this group can run an unbounded number of goroutines
   // simultaneously.
   ```
* introducing `parallel.Limited(ctx, n)`
   ```go
   // Works just like parallel.Unlimited(), but the functions sent to it
   // run with at most N parallelism
   group := parallel.Limited(ctx, 10)
   for i := 0; i < 100; i++ {
       // i := i -- We no longer support versions of golang that do not have
       // the loopvar semantic enabled by default; worrying about repeatedly
	   // capturing the same loop variable should be a thing of the past.
       group.Go(func(ctx context.Context) {
           <-time.After(time.Second)
           println("ok", i)
       })
   })
   group.Wait()
   // we didn't start 100 goroutines!
   ```

For the more complex chore of running work that produces results which are aggregated at the end, we have several more wrapper APIs that compose with the above executors:
* `parallel.ErrGroup(executor)`, for `func(context.Context) error`
   * This one is the most like a bare executor, but offers additional benefits and, like all the other tools in this library, always provides `ctx` to the functions so the user does not have to fight to remember which context variable to use.
   ```go
   group := parallel.ErrGroup(parallel.Unlimited(ctx))
   group.Go(func(ctx context.Context) error {
       println("this might not run if an error happens first!")
       return nil
   })
   group.Go(func(ctx context.Context) error {
       return errors.New("uh oh")
   })
   group.Go(func(ctx context.Context) error {
       return errors.New("bad foo")
   })
   err := group.Wait() // it's one of the errors returned!
   ```
* `parallel.Collect[T](executor)`, for `func(context.Context) (T, error)`
   * Collects returned values into a slice automatically, which is returned at the end
   ```go
   group := parallel.Collect[int](parallel.Unlimited(ctx))
   group.Go(func(ctx context.Context) (int, error) {
       return 1, nil
   })
   // we get all the results back in a slice from Wait(), or one error
   // if there were any.
   result, err := group.Wait() // []int{1}, nil
   ```
* `parallel.Feed(executor, receiver)`, for `func(context.Context) (T, error)`
   * Provides returned values to a function that is provided up front, which receives all of the values as they are returned from functions submitted to `Go()` but without any worries about thread safety
   ```go
   result := make(map[int]bool)
   group := parallel.Feed(parallel.Unlimited(ctx),
       // This can also be a function that doesn't return an error!
       func(ctx context.Context, n int) error {
           // values from the functions sent to the group end up here!
           result[n] = true // this runs safely in 1 thread!
           return nil       // an error here also stops execution
       })
   group.Go(func(ctx context.Context) (int, error) {
       return 1, nil
   })
   err := group.Wait() // nil
   // at this point, it's guaranteed that the receiver function above
   // has seen every return value of the functions sent to the group:
   result // map[int]bool{1: true}
   ```
* `parallel.GatherErrs(executor)`, for `func(context.Context) error`
   * Kind of like `ErrGroup`, but instead of halting the executor, all non-`nil` errors returned from the submitted functions are combined into a `MultiError` at the end.
   ```go
   group := parallel.GatherErrs(parallel.Unlimited(ctx))
   group.Go(func(ctx context.Context) error {
       println("okay (this definitely runs)")
       return nil
   })
   group.Go(func(ctx context.Context) error {
       return errors.New("uh oh")
   })
   group.Go(func(ctx context.Context) error {
       return NewMultiError(
           errors.New("bad foo"),
           errors.New("bad bar"),
       )
   })
   err := group.Wait() // it's a MultiError!
   // Because it's our own MultiError type, we get tools like:
   err.Error()         // "uh oh\nbad foo\nbad bar" - normal error behavior
   err.One()           // "uh oh" - one of the original errors!
   err.Unwrap()        // []error{ "uh oh", "bad foo", "bad bar" }
   // As shown, this even flattens other MultiErrors we return, if we need
   // to send multiple (see CombineErrors())
   ```
* `parallel.CollectWithErrs[T](executor)`, for `func(context.Context) (T, error)`
   * `MultiError`-returning version of `Collect[T]` which, like `GatherErrs`, does not halt when an error occurs
   ```go
   group := parallel.CollectWithErrs[int](parallel.Unlimited(ctx))
   group.Go(func(ctx context.Context) (int, error) {
       return 1, nil
   })
   group.Go(func(ctx context.Context) (int, error) {
       return 2, errors.New("oops")
   })
   group.Go(func(ctx context.Context) (int, error) {
       return 3, errors.New("bad foo")
   })
   // both concepts at once! note that we get back a slice of
   // values from successful invocations only, and the combined errors
   // from the failed invocations.
   result, err := group.Wait() // []int{1}, !MultiError with "oops", "bad foo"!
   ```
* `parallel.FeedWithErrs(executor, receiver)`, for `func(context.Context) (T, error)`
   * `MultiError`-returning version of `Feed`
   ```go
   result := make(map[int]bool)
   group := parallel.FeedWithErrs(parallel.Unlimited(ctx),
       func(ctx context.Context, n int) error {
           // values from the functions sent to the group end up here,
           // but only if there was no error!
           result[n] = true // this runs safely in 1 thread!
           return nil       // errors returned here will also be collected
       })
   group.Go(func(ctx context.Context) (int, error) {
       return 1, nil
   })
   group.Go(func(ctx context.Context) (int, error) {
       return 2, errors.New("oh no")
   })
   group.Go(func(ctx context.Context) (int, error) {
       return 3, errors.New("bad bar")
   })
   err := group.Wait() // !MultiError with "oh no", "bad bar"!
   result              // map[int]bool{1: true}
   ```

* All of the above tools will clean up after themselves even if `Wait()` is never called!
Unfortunately if we write functions that get stuck and block forever, that's still a hard problem and this library doesn't even attempt to solve. Fortunately, we find that in practice that isn't a hugely prevalent issue and is pretty easy to avoid outside of the kind of difficult code written here. 😔
* All of the above tools will propagate panics from their workers and collector functions to their owner (that is, the code that is using the executor/wrapper directly, calling `Go()` and `Wait()`).
* Cancelation of the context that is first provided to the executor leads to the executor stopping early if possible
* Errors also stop the execution and context of the groups that stop on error (the inner context provided to the functions, but not the outer context that was provided to create the executor)
* If stopping on errors is not desirable, use the wrappers which are designed to collect a `MultiErr`: `GatherErrs`, `FeedWithErrs` and `CollectWithErrs`

## Additional notes

### Conceptual organization

There are basically two different concepts here:
1. an underlying `Executor` that runs functions in goroutines, and
2. various kinds of wrappers for that that take functions with/without return values, with/without automatic halting on error, and either collecting results into a slice automatically or sending them to a function we provide up front.

### Context lifetime

**Possibly important:** ➡️ The *inner* context provided to the functions run by the executors *always* gets canceled, even if the executor completes successfully. If a worker function needs to capture or leak a context that must outlive the executor, it should *explicitly ignore* the `Context` parameter that it receives from the executor and capture a longer-lived one instead.

This avoids unbounded memory usage buildup inside the outer context. Cancelable child contexts of other cancelable child contexts can never be garbage collected until they are canceled, which is why linters often admonish us to `defer cancel()` after creating one. If the parent context is long lived this can lead to a very, very large amount of uncollectable memory built up.

If you are seeing context cancelation errors with the `ctx.Cause()` error string `"executor done"`, that means a worker function should probably be capturing a longer-lived context.

### Executor reuse

It's possible to use a single executor for none, one, or several wrappers at the same time; this works fine, but we must be careful:

⚠️ Never re-use an executor! Once we have called `Wait()` on an executor *or any wrapper around it*, we cannot send any more work to it.

This means recreating the group every time we need to await it. Don't worry, this is not expensive to do.
