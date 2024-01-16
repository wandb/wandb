package utils

import (
	"errors"
	"os"

	"github.com/segmentio/encoding/json"
)

func FileExists(path string) (bool, error) {
	_, err := os.Stat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func WriteJsonToFileWithDigest(marshallable interface{}) (filename string, digest string, size int64, rerr error) {
	data, rerr := json.Marshal(marshallable)
	if rerr != nil {
		return
	}

	f, rerr := os.CreateTemp("", "tmpfile-")
	if rerr != nil {
		return
	}
	defer f.Close()
	_, rerr = f.Write(data)
	if rerr != nil {
		return
	}
	filename = f.Name()

	if stat, err := f.Stat(); err == nil { // if NO error
		size = stat.Size()
	}

	digest, rerr = ComputeB64MD5(data)
	return
}
