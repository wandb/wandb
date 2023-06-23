package server

import (
	"context"
	"fmt"
	"net"
	"os"
	"sync"

	log "github.com/sirupsen/logrus"
)

func writePortFile(portFile string, port int) {
	tempFile := fmt.Sprintf("%s.tmp", portFile)
	f, err := os.Create(tempFile)
	if err != nil {
		log.Error(err)
	}
	defer func(f *os.File) {
		_ = f.Close()
	}(f)

	if _, err = f.WriteString(fmt.Sprintf("sock=%d\n", port)); err != nil {
		log.Error(err)
	}

	if _, err = f.WriteString("EOF"); err != nil {
		log.Error(err)
	}

	if err = f.Sync(); err != nil {
		log.Error(err)
	}

	if err = os.Rename(tempFile, portFile); err != nil {
		log.Error(err)
	}
}

type NexusServer struct {
	shutdownChan chan bool
	shutdown     bool
	listen       net.Listener
}

func tcpServer(portFile string) {
	addr := "127.0.0.1:0"
	listen, err := net.Listen("tcp", addr)
	if err != nil {
		log.Error(err)
	}

	server := NexusServer{shutdownChan: make(chan bool), listen: listen}

	defer func() {
		err := listen.Close()
		if err != nil {
			log.Error("Error closing listener:", err)
		}
		close(server.shutdownChan)
	}()

	log.Println("Server is running on:", addr)
	port := listen.Addr().(*net.TCPAddr).Port
	log.Println("PORT", port)

	writePortFile(portFile, port)

	wg := sync.WaitGroup{}

	// Run a separate goroutine to handle incoming connections
	go func() {
		for {
			conn, err := listen.Accept()
			if err != nil {
				if server.shutdown {
					break // Break when shutdown has been requested
				}
				log.Println("Failed to accept conn.", err)
				continue
			}

			ctx, cancel := context.WithCancel(context.Background())

			wg.Add(1)
			go handleConnection(ctx, cancel, &wg, conn, server.shutdownChan)
		}
	}()

	// Wait for a shutdown signal
	<-server.shutdownChan
	server.shutdown = true
	log.Println("shutting down...")

	log.Println("What goes on here in my mind...")
	wg.Wait()
	log.Println("I think that I am falling down...")
}

func WandbService(portFilename string) {
	tcpServer(portFilename)
}
