//go:build tools

// This file prevents 'go mod tidy' from removing tool dependencies, so that
// 'go.sum' can be used to pin tool versions.
// https://github.com/golang/go/issues/25922#issuecomment-413898264

package core

import (
	_ "github.com/google/wire/cmd/wire"
)
