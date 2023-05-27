package main

import (
	"flag"
	// "fmt"
	log "github.com/sirupsen/logrus"
	"github.com/wandb/wandb/nexus/pkg/server"
)

func main() {
	portFilename := flag.String("port-filename", "portfile.txt", "filename")

	pid := flag.Int("pid", 0, "pid")
	debug := flag.Bool("debug", false, "debug")
	serveSock := flag.Bool("serve-sock", false, "debug")
	serveGrpc := flag.Bool("serve-grpc", false, "debug")

	// fmt.Println("Starting 0.0\n")
	flag.Parse()

	server.InitLogging()

	// log.Println("got", *portFilename, *pid, *debug, *serveSock, *serveGrpc)
	log.WithFields(log.Fields{
		"fname":     *portFilename,
		"pid":       *pid,
		"debug":     *debug,
		"serveSock": *serveSock,
		"serveGrpc": *serveGrpc,
	}).Debug("Flags")

	server.WandbService(*portFilename)
}
