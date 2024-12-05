package main

import (
	_ "embed"

	"github.com/wandb/wandb/experimental/client-go/pkg/gowandb"
)

// Generate the core SDK library.  This is useful if you want to create self-contained binaries.
//
//go:generate go build -C ../../.. -o cmd/examples/embed/embed-core.bin cmd/core/main.go
//go:embed embed-core.bin
var coreBinary []byte

func main() {
	wandb, err := gowandb.NewSession(gowandb.SessionParams{
		CoreBinary: coreBinary,
	})
	if err != nil {
		panic(err)
	}
	defer wandb.Close()

	run, err := wandb.NewRun(gowandb.RunParams{})
	if err != nil {
		panic(err)
	}
	run.Log(gowandb.History{"acc": 1.0}, true)
	run.Finish()
}
