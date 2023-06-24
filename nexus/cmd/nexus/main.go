package main

import (
	"context"
	"flag"
	"os"

	"github.com/wandb/wandb/nexus/pkg/server"
	"golang.org/x/exp/slog"
)

func main() {
	portFilename := flag.String("port-filename", "portfile.txt", "filename")

	pid := flag.Int("pid", 0, "pid")
	debug := flag.Bool("debug", false, "debug")
	serveSock := flag.Bool("serve-sock", false, "debug")
	serveGrpc := flag.Bool("serve-grpc", false, "debug")

	flag.Parse()

	logStdErr := os.Getenv("WANDB_NEXUS_DEBUG") != ""
	server.SetupLogger(logStdErr)

	slog.LogAttrs(
		context.Background(),
		slog.LevelDebug,
		"Flags",
		slog.String("fname", *portFilename),
		slog.Int("pid", *pid),
		slog.Bool("debug", *debug),
		slog.Bool("serveSock", *serveSock),
		slog.Bool("serveGrpc", *serveGrpc))

	server.WandbService(*portFilename)
}
