package hashencode

import (
	"encoding/base64"
	"encoding/hex"
)

// B64ToHex converts a base64 encoded string to a hexadecimal string.
//
// Returns an error if the provided string is not a valid base64 string.
func B64ToHex(data string) (string, error) {
	buf, err := base64.StdEncoding.DecodeString(data)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

// HexToB64 converts a hexadecimal string to a base64 encoded string.
//
// Returns an error if the provided string is not valid hexadecimal.
func HexToB64(data string) (string, error) {
	buf, err := hex.DecodeString(data)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(buf), nil
}
