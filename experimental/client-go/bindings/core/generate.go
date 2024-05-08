package main

import (
	_ "embed"
)

// generate core binary and embed into this package
//
//go:generate go build -C ../../../core -o lib/core/embed-core.bin cmd/wandb-core/main.go
//go:embed embed-core.bin
var coreBinary []byte
