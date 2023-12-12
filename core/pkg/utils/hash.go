package utils

import (
	"crypto/md5"
	"encoding/base64"
	"encoding/hex"
)

func ComputeB64MD5(data []byte) (string, error) {
	hasher := md5.New()
	_, err := hasher.Write(data)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(hasher.Sum(nil)), nil
}

func B64ToHex(data string) (string, error) {
	buf, err := base64.StdEncoding.DecodeString(data)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

func EncodeBytesAsHex(contents []byte) string {
	return hex.EncodeToString(contents)
}

func HexToB64(data string) (string, error) {
	buf, err := hex.DecodeString(data)
	if err != nil {
		return "", err
	}
	b64Str := base64.StdEncoding.EncodeToString(buf)
	return b64Str, nil
}
