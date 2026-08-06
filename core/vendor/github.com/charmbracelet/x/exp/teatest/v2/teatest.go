// Package teatest provides helper functions to test tea.Model's.
package teatest

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/exp/golden"
)

// Program defines the subset of the tea.Program API we need for testing.
type Program interface {
	Send(tea.Msg)
}

// TestModelOptions defines all options available to the test function.
type TestModelOptions struct {
	size        tea.WindowSizeMsg
	programOpts []tea.ProgramOption
}

// TestOption is a functional option.
type TestOption func(opts *TestModelOptions)

// WithInitialTermSize ...
func WithInitialTermSize(x, y int) TestOption {
	return func(opts *TestModelOptions) {
		opts.size = tea.WindowSizeMsg{
			Width:  x,
			Height: y,
		}
	}
}

// WithProgramOptions adds tea.ProgramOptions to the test model during initialization
// of the program.
func WithProgramOptions(options ...tea.ProgramOption) TestOption {
	return func(opts *TestModelOptions) {
		opts.programOpts = options
	}
}

// WaitingForContext is the context for a WaitFor.
type WaitingForContext struct {
	Duration      time.Duration
	CheckInterval time.Duration
}

// WaitForOption changes how a WaitFor will behave.
type WaitForOption func(*WaitingForContext)

// WithCheckInterval sets how much time a WaitFor should sleep between every
// check.
func WithCheckInterval(d time.Duration) WaitForOption {
	return func(wf *WaitingForContext) {
		wf.CheckInterval = d
	}
}

// WithDuration sets how much time a WaitFor will wait for the condition.
func WithDuration(d time.Duration) WaitForOption {
	return func(wf *WaitingForContext) {
		wf.Duration = d
	}
}

// WaitFor keeps reading from r until the condition matches.
// Default duration is 1s, default check interval is 50ms.
// These defaults can be changed with WithDuration and WithCheckInterval.
func WaitFor(
	tb testing.TB,
	r io.Reader,
	condition func(bts []byte) bool,
	options ...WaitForOption,
) {
	tb.Helper()
	if err := doWaitFor(r, condition, options...); err != nil {
		tb.Fatal(err)
	}
}

func doWaitFor(r io.Reader, condition func(bts []byte) bool, options ...WaitForOption) error {
	wf := WaitingForContext{
		Duration:      time.Second,
		CheckInterval: 50 * time.Millisecond, //nolint: gomnd
	}

	for _, opt := range options {
		opt(&wf)
	}

	var b bytes.Buffer
	start := time.Now()
	for time.Since(start) <= wf.Duration {
		if _, err := io.ReadAll(io.TeeReader(r, &b)); err != nil {
			return fmt.Errorf("WaitFor: %w", err)
		}
		if condition(b.Bytes()) {
			return nil
		}
		time.Sleep(wf.CheckInterval)
	}
	return fmt.Errorf("WaitFor: condition not met after %s. Last output:\n%s", wf.Duration, b.String())
}

// TestModel is a model that is being tested.
type TestModel struct {
	program *tea.Program

	in  *bytes.Buffer
	out io.ReadWriter

	modelCh chan tea.Model
	model   tea.Model

	done   sync.Once
	doneCh chan bool
}

// NewTestModel makes a new TestModel which can be used for tests.
func NewTestModel(tb testing.TB, m tea.Model, options ...TestOption) *TestModel {
	tm := &TestModel{
		in:      bytes.NewBuffer(nil),
		out:     safe(bytes.NewBuffer(nil)),
		modelCh: make(chan tea.Model, 1),
		doneCh:  make(chan bool, 1),
	}

	// We always have an initial size.
	options = append([]TestOption{
		WithInitialTermSize(80, 24),
	}, options...)

	var opts TestModelOptions
	for _, opt := range options {
		opt(&opts)
	}
	programOpts := append(
		opts.programOpts,
		// Append our options to ensure they always override.
		tea.WithInput(tm.in),
		tea.WithOutput(tm.out),
		tea.WithoutSignals(),
		tea.WithWindowSize(opts.size.Width, opts.size.Height),
	)

	tm.program = tea.NewProgram(m, programOpts...)

	interruptions := make(chan os.Signal, 1)
	signal.Notify(interruptions, syscall.SIGINT)
	go func() {
		m, err := tm.program.Run()
		if err != nil {
			tb.Fatalf("app failed: %s", err)
		}
		tm.modelCh <- m
		tm.doneCh <- true
	}()
	go func() {
		<-interruptions
		signal.Stop(interruptions)
		tb.Log("interrupted")
		tm.program.Kill()
	}()

	if opts.size.Width != 0 {
		tm.program.Send(opts.size)
	}
	return tm
}

func (tm *TestModel) waitDone(tb testing.TB, opts []FinalOpt) {
	tm.done.Do(func() {
		fopts := FinalOpts{}
		for _, opt := range opts {
			opt(&fopts)
		}
		if fopts.timeout > 0 {
			select {
			case <-time.After(fopts.timeout):
				if fopts.onTimeout == nil {
					tb.Fatalf("timeout after %s", fopts.timeout)
				}
				fopts.onTimeout(tb)
			case <-tm.doneCh:
			}
		} else {
			<-tm.doneCh
		}
	})
}

// FinalOpts represents the options for FinalModel and FinalOutput.
type FinalOpts struct {
	timeout   time.Duration
	onTimeout func(tb testing.TB)
}

// FinalOpt changes FinalOpts.
type FinalOpt func(opts *FinalOpts)

// WithTimeoutFn allows to define what happens when WaitFinished times out.
func WithTimeoutFn(fn func(tb testing.TB)) FinalOpt {
	return func(opts *FinalOpts) {
		opts.onTimeout = fn
	}
}

// WithFinalTimeout allows to set a timeout for how long FinalModel and
// FinalOuput should wait for the program to complete.
func WithFinalTimeout(d time.Duration) FinalOpt {
	return func(opts *FinalOpts) {
		opts.timeout = d
	}
}

// WaitFinished waits for the app to finish.
// This method only returns once the program has finished running or when it
// times out.
func (tm *TestModel) WaitFinished(tb testing.TB, opts ...FinalOpt) {
	tm.waitDone(tb, opts)
}

// FinalModel returns the resulting model, resulting from program.Run().
// This method only returns once the program has finished running or when it
// times out.
func (tm *TestModel) FinalModel(tb testing.TB, opts ...FinalOpt) tea.Model {
	tm.waitDone(tb, opts)
	select {
	case m := <-tm.modelCh:
		tm.model = m
		return tm.model
	default:
		return tm.model
	}
}

// FinalOutput returns the program's final output io.Reader.
// This method only returns once the program has finished running or when it
// times out.
func (tm *TestModel) FinalOutput(tb testing.TB, opts ...FinalOpt) io.Reader {
	tm.waitDone(tb, opts)
	return tm.Output()
}

// Output returns the program's current output io.Reader.
func (tm *TestModel) Output() io.Reader {
	return tm.out
}

// Send sends messages to the underlying program.
func (tm *TestModel) Send(m tea.Msg) {
	tm.program.Send(m)
}

// Quit quits the program and releases the terminal.
func (tm *TestModel) Quit() error {
	tm.program.Quit()
	return nil
}

// Type types the given text into the given program.
func (tm *TestModel) Type(s string) {
	for _, c := range s {
		tm.Send(tea.KeyPressMsg{
			Code: c,
			Text: string(c),
		})
	}
}

// GetProgram gets the TestModel's program.
func (tm *TestModel) GetProgram() *tea.Program {
	return tm.program
}

// RequireEqualOutput is a helper function to assert the given output is
// the expected from the golden files, printing its diff in case it is not.
//
// Important: this uses the system `diff` tool.
//
// You can update the golden files by running your tests with the -update flag.
func RequireEqualOutput(tb testing.TB, out []byte) {
	tb.Helper()
	golden.RequireEqualEscape(tb, out, true) //nolint:staticcheck
}

func safe(rw io.ReadWriter) io.ReadWriter {
	return &safeReadWriter{rw: rw}
}

// safeReadWriter implements io.ReadWriter, but locks reads and writes.
type safeReadWriter struct {
	rw io.ReadWriter
	m  sync.RWMutex
}

// Read implements io.ReadWriter.
func (s *safeReadWriter) Read(p []byte) (n int, err error) {
	s.m.RLock()
	defer s.m.RUnlock()
	return s.rw.Read(p) //nolint: wrapcheck
}

// Write implements io.ReadWriter.
func (s *safeReadWriter) Write(p []byte) (int, error) {
	s.m.Lock()
	defer s.m.Unlock()
	return s.rw.Write(p) //nolint: wrapcheck
}
