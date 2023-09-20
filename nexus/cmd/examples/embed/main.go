package main

import (
	_ "embed"

	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/sessionopts"
)

// Generate the core SDK library.  This is useful if you want to create self-contained binaries.
//
//go:generate go build -C ../../.. -o cmd/examples/embed/embed-nexus.bin cmd/nexus/main.go
//go:embed embed-nexus.bin
var coreBinary []byte

func main() {
	wandb, err := gowandb.NewSession(
		sessionopts.WithCoreBinary(coreBinary),
	)
	if err != nil {
		panic(err)
	}
	defer wandb.Close()

	run, err := wandb.NewRun()
	if err != nil {
		panic(err)
	}
	run.Log(gowandb.History{"acc": 1.0})
	run.Finish()
}
