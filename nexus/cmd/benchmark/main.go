package main

import (
	"flag"
	"fmt"

	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/session"
)

func main() {
	host := flag.String("host", "localhost", "host to connect to")
	port := flag.Int("port", 0, "port to connect to")
	numHistory := flag.Int("numHistory", 1000, "number of history records to log")
	numHistoryElements := flag.Int("numHistoryElements", 5, "number of elements in a history record")
	teardown := flag.Bool("close", false, "flag to close the server")
	offline := flag.Bool("offline", false, "use offline mode")
	flag.Parse()

	opts := []gowandb.SessionOption{}
	if *port != 0 {
		opts = append(opts, session.WithCoreAddress(fmt.Sprintf("%s:%d", *host, *port)))
	}
	if *offline {
		settings := gowandb.NewSettings()
		settings.XOffline.Value = true
		opts = append(opts, session.WithSettings(settings))
	}
	wandb, err := gowandb.NewSession(opts...)
	if err != nil {
		panic(err)
	}

	run, err := wandb.NewRun()
	if err != nil {
		panic(err)
	}

	data := map[string]float64{}
	for i := 0; i < *numHistoryElements; i++ {
		data[fmt.Sprintf("loss_%d", i)] = float64(100+i)
	}

	for i := 0; i < *numHistory; i++ {
		run.Log(data)
	}
	run.Finish()

	if *teardown {
		wandb.Close()
	}
}
