package hashencode

import (
	"crypto/md5"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"io"
	"os"
)

// ComputeB64MD5 computes the MD5 hash of the given data and returns it as a
// base64 encoded string.
func ComputeB64MD5(data []byte) string {
	hasher := md5.New()
	_, _ = hasher.Write(data) // hasher.Write can't fail; the returned values are just to implement io.Writer
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil))
}

// ComputeHexMD5 returns the MD5 hash of data as a hexadecimal string.
func ComputeHexMD5(data []byte) string {
	hasher := md5.New()
	_, _ = hasher.Write(data)
	return hex.EncodeToString(hasher.Sum(nil))
}

// ComputeFileB64MD5 computes the MD5 hash of the file at the given path and
// returns the result as a base64 encoded string.
//
// Returns an error if the file cannot be opened or read.
func ComputeFileB64MD5(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() {
		_ = f.Close()
	}()

	hasher := md5.New()
	if _, err = io.Copy(hasher, f); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil)), nil
}

// ComputeReaderHexMD5 computes the MD5 hash of the data from the given io.Reader
// and returns the result as a hexadecimal string.
//
// Returns an error if the reader cannot be read.
func ComputeReaderHexMD5(reader io.Reader) (string, error) {
	hasher := md5.New()
	if _, err := io.Copy(hasher, reader); err != nil {
		return "", err
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

// VerifyFileB64MD5 checks if the file at the given path matches the provided
// base64-encoded MD5 hash.
//
// Returns true if the file matches the hash or false if there is no match or
// if there is an error (e.g., file is missing, can't be read, or hash doesn't
// match).
func VerifyFileB64MD5(path string, b64md5 string) bool {
	actual, err := ComputeFileB64MD5(path)
	if err != nil {
		return false
	}
	return actual == b64md5
}

// ComputeSHA256 computes the SHA256 hash of the given data.
func ComputeSHA256(data []byte) []byte {
	hasher := sha256.New()
	hasher.Write(data)
	return hasher.Sum(nil)
}
