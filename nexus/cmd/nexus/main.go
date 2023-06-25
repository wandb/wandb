package main

import (
	"context"
	"flag"

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

	server.SetupDefaultLogger()

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
