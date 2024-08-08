package utils

import (
	"crypto/md5"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"io"
	"os"
)

// ComputeB64MD5 computes the MD5 hash of the given data and returns the result as a
// base64 encoded string.
func ComputeB64MD5(data []byte) string {
	hasher := md5.New()
	// hasher.Write can't fail; the returned values are just to implement io.Writer
	_, _ = hasher.Write(data)
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil))
}

// ComputeHexMD5 returns the MD5 hash of data as a hexadecimal string.
func ComputeHexMD5(data []byte) string {
	hasher := md5.New()
	_, _ = hasher.Write(data)
	return hex.EncodeToString(hasher.Sum(nil))
}

// ComputeFileB64MD5 computes the MD5 hash of the file at the given path and returns the
// result as a base64 encoded string.
// It returns an error if the file cannot be opened or read.
func ComputeFileB64MD5(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	hasher := md5.New()
	_, err = io.Copy(hasher, f)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil)), nil
}

// VerifyFileHash checks if file at the given path matches the MD5 hash provided as a
// base64 encoded string. It returns true if the file is present and matches the hash,
// false otherwise -- including if the file is missing, a directory, or can't be read.
func VerifyFileHash(path string, b64md5 string) bool {
	actual, err := ComputeFileB64MD5(path)
	if err != nil {
		return false
	}
	return actual == b64md5
}

// B64ToHex converts a base64 encoded string to a hexadecimal string.
// It returns an error if the string provided is not a valid base64 string.
func B64ToHex(data string) (string, error) {
	buf, err := base64.StdEncoding.DecodeString(data)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

// HexToB64 converts a hexadecimal string to a base64 encoded string.
// It returns an error if the string provided is not valid hexadecimal.
func HexToB64(data string) (string, error) {
	buf, err := hex.DecodeString(data)
	if err != nil {
		return "", err
	}
	b64Str := base64.StdEncoding.EncodeToString(buf)
	return b64Str, nil
}

// ComputeSHA256 computes the SHA256 hash of the given data.
func ComputeSHA256(data []byte) []byte {
	hasher := sha256.New()
	hasher.Write(data)
	return hasher.Sum(nil)
}
