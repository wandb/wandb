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
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/server"
)

// this is set by the build script and used by the observability package
var commit string

func init() {
	runtime.SetBlockProfileRate(1)
}

// LoggerPath function with FileSystem parameter
func cacheLoggerPath() (*os.File, error) {
	// TODO: replace with a setting during client rewrite
	dir := os.Getenv("WANDB_CACHE_DIR")
	if dir == "" {
		dir, _ = os.UserCacheDir()
	}

	if dir == "" {
		return nil, fmt.Errorf("failed to get logger path")
	}

	dir, err := filepath.Abs(dir)
	if err != nil {
		return nil, fmt.Errorf("failed to get logger path: %s", err)
	}

	timestamp := time.Now().Format("20060102_150405")
	path := filepath.Join(dir, ".wandb", fmt.Sprintf("core-debug-%s.log", timestamp))

	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return nil, fmt.Errorf("error creating log directory: %s", err)
	}

	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		return nil, fmt.Errorf("error opening log file: %s", err)
	}

	return file, nil
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
	profile := flag.String("profile", "", "path to write trace")
	// todo: remove these flags, they are here for backward compatibility
	serveSock := flag.Bool("serve-sock", false, "use sockets")

	flag.Parse()

	var writers []io.Writer

	var loggerPath string
	file, err := cacheLoggerPath()
	if err == nil {
		writers = append(writers, file)
		loggerPath = file.Name()
	}
	if file != nil {
		defer file.Close()
	}
	level := slog.LevelInfo
	if *debug {
		writers = append(writers, os.Stderr)
		level = slog.LevelDebug
	}
	opts := &slog.HandlerOptions{
		Level: level,
	}
	writer := io.MultiWriter(writers...)
	logger := slog.New(slog.NewJSONHandler(writer, opts))
	slog.SetDefault(logger)
	slog.Info("started logging")

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
		slog.String("tracePath", *profile),
	)

	if *profile != "" {
		f, err := os.Create(*profile)
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
	serve := server.NewServer(ctx, "127.0.0.1:0", *portFilename)
	observability.SetDefaultLoggerPath(loggerPath)
	serve.Close()
}
