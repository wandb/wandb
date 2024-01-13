package artifacts

import (
	"os"

	"github.com/segmentio/encoding/json"
	"github.com/wandb/wandb/core/internal/lib/hashlib"
)

func WriteJsonToFileWithDigest(marshallable interface{}) (filename string, digest string, rerr error) {
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

	digest, rerr = hashlib.ComputeB64MD5(data)
	return
}
