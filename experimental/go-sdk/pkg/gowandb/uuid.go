package gowandb

import (
	"context"
	"crypto/rand"
	"fmt"
	"log/slog"
)

// GenerateUniqueID generates a random string of the given length using only lowercase alphanumeric characters.
func GenerateUniqueID(length int) string {

	charsLen := len(lowercaseAlphanumericChars)
	b := make([]byte, length)
	_, err := rand.Read(b) // generates len(b) random bytes
	if err != nil {
		err = fmt.Errorf("rand error: %s", err.Error())
		slog.LogAttrs(context.Background(),
			slog.LevelError,
			"GenerateUniqueID: error",
			slog.String("error", err.Error()))
		panic(err)
	}

	for i := 0; i < length; i++ {
		b[i] = lowercaseAlphanumericChars[int(b[i])%charsLen]
	}
	return string(b)
}
