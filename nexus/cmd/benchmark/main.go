package main

import (
	"flag"

	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/session"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:8080", "address to connect to")
	samples := flag.Int("smpl", 1000000, "number of samples to log")
	teardown := flag.Bool("td", false, "flag to close the server")
	flag.Parse()

	wandb, err := gowandb.NewSession(
		session.WithCoreAddress(*addr),
	)
	if err != nil {
		panic(err)
	}

	run, err := wandb.NewRun()
	if err != nil {
		panic(err)
	}

	data := map[string]float64{
		"loss": float64(100),
	}
	for i := 0; i < *samples; i++ {
		run.Log(data)
	}
	run.Finish()

	if *teardown {
		wandb.Close()
	}
}
