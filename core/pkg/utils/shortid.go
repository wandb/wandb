package utils

import (
	"context"
	"crypto/rand"
	"fmt"
	"log/slog"
)

var chars = "abcdefghijklmnopqrstuvwxyz1234567890"

func ShortID(length int) string {

	charsLen := len(chars)
	b := make([]byte, length)
	_, err := rand.Read(b) // generates len(b) random bytes
	if err != nil {
		err = fmt.Errorf("rand error: %s", err.Error())
		slog.LogAttrs(context.Background(),
			slog.LevelError,
			"ShortID: error",
			slog.String("error", err.Error()))
		panic(err)
	}

	for i := 0; i < length; i++ {
		b[i] = chars[int(b[i])%charsLen]
	}
	return string(b)
}
