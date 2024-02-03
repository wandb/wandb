package utils

import (
	"math/rand"
)

const alphanumericChars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

func NilIfZero[T comparable](x T) *T {
	var zero T
	if x == zero {
		return nil
	}
	return &x
}

func GenerateAlphanumericSequence(length int) string {
	var result string
	for i := 0; i < length; i++ {
		index := rand.Intn(len(alphanumericChars))
		result += string(alphanumericChars[index])
	}

	return result
}
