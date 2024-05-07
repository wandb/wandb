package core

import (
	_ "embed"
)

// generate core binary and embed into this package
//
//go:generate go build -C ../.. -o lib/core/embed-core.bin cmd/core/main.go
//go:embed embed-core.bin
var coreBinary []byte
