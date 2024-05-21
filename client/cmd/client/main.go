package main

import (
	"C"
	"os"
	"strings"

	"log/slog"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/core/pkg/observability"

	"github.com/wandb/wandb/client/internal/launcher"
	"github.com/wandb/wandb/client/pkg/session"
)

var (
	defaultLauncher *launcher.Launcher
	defaultLogger   *observability.CoreLogger
)

const (
	sentryDsn = "https://2fbeaa43dbe0ed35e536adc7f019ba17@o151352.ingest.us.sentry.io/4507273364242432"
)

// Setup initializes the session and starts wandb-core process
//
//export Setup
func Setup(corePath *C.char) *C.char {
	if defaultLogger == nil {
		defaultLogger = initLogger()
	}

	if defaultLauncher != nil {
		return C.CString(defaultLauncher.Address())
	}

	corePathStr := C.GoString(corePath)
	defaultLauncher = launcher.New()
	if err := defaultLauncher.Launch(corePathStr); err != nil {
		defaultLogger.CaptureError("failed to launch wandb-core", err)
		return C.CString("")
	}
	return C.CString(defaultLauncher.Address())
}

// Teardown closes the session and stops wandb-core process
//
//export Teardown
func Teardown(code C.int) {
	if defaultLauncher == nil {
		return
	}
	s := session.New(
		session.Params{
			Address: defaultLauncher.Address(),
		},
	)

	if err := s.Teardown(int32(code)); err != nil {
		defaultLogger.CaptureError("failed to teardown session", err)
	}

	if err := defaultLauncher.Close(); err != nil {
		defaultLogger.CaptureError("failed to close launcher", err)
	}
	defaultLauncher = nil
}

// initLogger initializes the logger for the session
func initLogger() *observability.CoreLogger {
	file, _ := observability.GetLoggerPath("client")
	if file == nil {
		return observability.NewCoreLogger(
			slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{})),
			observability.WithTags(observability.Tags{}),
			observability.WithCaptureMessage(observability.CaptureMessage),
			observability.WithCaptureException(observability.CaptureException),
		)
	}

	level := slog.LevelInfo
	if os.Getenv("WANDB_DEBUG") != "" {
		level = slog.LevelDebug
	}
	opts := &slog.HandlerOptions{
		Level:     level,
		AddSource: false,
	}
	logger := slog.New(slog.NewJSONHandler(file, opts))
	slog.SetDefault(logger)

	return observability.NewCoreLogger(
		logger,
		observability.WithTags(observability.Tags{}),
		observability.WithCaptureMessage(observability.CaptureMessage),
		observability.WithCaptureException(observability.CaptureException),
	)
}

// InitSentry initializes Sentry for error reporting.
//
//export InitSentry
func InitSentry() {
	disableSentry := false
	if strings.ToLower(os.Getenv("WANDB_ERROR_REPORTING")) == "false" {
		disableSentry = true
	}
	// TODO: get commit hash from build script
	commit := ""

	observability.InitSentry(sentryDsn, disableSentry, commit)
	defer sentry.Flush(2)
}

func main() {}
