package main

import (
	"context"
	"flag"

	"github.com/wandb/wandb/nexus/pkg/client"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:8080", "address to connect to")
	samples := flag.Int("smpl", 1000000, "number of samples to log")
	teardown := flag.Bool("td", false, "flag to close the server")
	flag.Parse()

	ctx := context.Background()
	settings := client.NewSettings()
	manager := client.NewManager(ctx, settings, *addr)
	run := manager.NewRun()

	run.Setup()
	run.Init()
	run.Start()

	data := map[string]float64{
		"loss": float64(100),
	}
	for i := 0; i < *samples; i++ {
		run.Log(data)
	}
	run.Finish()

	if *teardown {
		manager.Close()
	}
}
