package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log/slog"
	_ "net/http/pprof"
	"os"
	"path/filepath"
	"runtime"
	"runtime/trace"
	"time"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/server"
)

// this is set by the build script and used by the observability package
var commit string

func init() {
	runtime.SetBlockProfileRate(1)
}

func main() {
	portFilename := flag.String(
		"port-filename",
		"port_file.txt",
		"filename for port to communicate with client",
	)
	pid := flag.Int("pid", 0, "pid")
	debug := flag.Bool("debug", false, "debug mode")
	noAnalytics := flag.Bool("no-observability", false, "turn off observability")
	// todo: remove these flags, they are here for backward compatibility
	serveSock := flag.Bool("serve-sock", false, "use sockets")

	flag.Parse()

	var writers []io.Writer
	var loggerPath string

	var cacheDir string
	var err error
	if dir := os.Getenv("WANDB_CACHE_DIR"); dir != "" {
		cacheDir = dir
	} else {
		cacheDir, err = os.UserCacheDir()
	}
	if err != nil {
		// Create a unique file name using a timestamp
		timestamp := time.Now().Format("20060102_150405")
		loggerPath = filepath.Join(cacheDir, "wandb", fmt.Sprintf("core-debug-%s.log", timestamp))

		file, err := os.OpenFile(loggerPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
		if err == nil {
			writers = append(writers, file)
		}
	}

	if os.Getenv("WANDB_NEXUS_DEBUG") != "" {
		writers = append(writers, os.Stderr)
	}
	logger := server.SetupDefaultLogger(writers...)
	ctx := context.Background()

	// set up sentry reporting
	observability.InitSentry(*noAnalytics, commit)
	defer sentry.Flush(2)

	logger.LogAttrs(
		ctx,
		slog.LevelDebug,
		"Flags",
		slog.String("fname", *portFilename),
		slog.Int("pid", *pid),
		slog.Bool("debug", *debug),
		slog.Bool("noAnalytics", *noAnalytics),
		slog.Bool("serveSock", *serveSock),
	)

	if os.Getenv("_WANDB_TRACE") != "" {
		f, err := os.Create("trace.out")
		if err != nil {
			slog.Error("failed to create trace output file", "err", err)
			panic(err)
		}
		defer func() {
			if err = f.Close(); err != nil {
				slog.Error("failed to close trace file", "err", err)
				panic(err)
			}
		}()

		if err = trace.Start(f); err != nil {
			slog.Error("failed to start trace", "err", err)
			panic(err)
		}
		defer trace.Stop()
	}
	nexus := server.NewServer(ctx, "127.0.0.1:0", *portFilename)
	nexus.SetDefaultLoggerPath(loggerPath)
	nexus.Close()
}
