package core

import (
	_ "embed"
)

// generate core binary and embed into this package
//
//go:generate ./../../scripts/build_embed.sh bindings/core/embed-core.bin
//go:embed embed-core.bin
var coreBinary []byte
