package main

import (
	"flag"
	"os"

	log "github.com/sirupsen/logrus"
	"github.com/wandb/wandb/nexus/pkg/server"
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

	log.WithFields(log.Fields{
		"fname":     *portFilename,
		"pid":       *pid,
		"debug":     *debug,
		"serveSock": *serveSock,
		"serveGrpc": *serveGrpc,
	}).Debug("Flags")

	server.WandbService(*portFilename)
}
