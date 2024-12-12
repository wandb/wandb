package main

import (
	_ "embed"

	"github.com/wandb/wandb/experimental/client-go/pkg/wandb"
)

// Generate the core SDK library.  This is useful if you want to create self-contained binaries.
//
//go:generate go build -C ../../.. -o cmd/examples/embed/embed-core.bin cmd/core/main.go
//go:embed embed-core.bin
var coreBinary []byte

func main() {
	session, err := wandb.Setup(&wandb.SessionParams{CoreBinary: coreBinary})
	if err != nil {
		panic(err)
	}
	defer session.Close()

	run, err := session.Init(&wandb.RunParams{})
	if err != nil {
		panic(err)
	}
	data := wandb.History{"acc": 1.0}
	run.Log(data, true)
	run.Finish()
}
