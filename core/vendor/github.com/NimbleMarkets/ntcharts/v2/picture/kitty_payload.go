package picture

import (
	"encoding/base64"
	"fmt"
	"io"

	"github.com/charmbracelet/x/ansi"
	"github.com/charmbracelet/x/ansi/kitty"
)

// encodeKittyGraphicsData frames already-encoded PNG bytes.
// It does not compress data. Keep this compatibility helper
// private until Charm's payload encoder is released, then use that API instead.
// Options and APC serialization remain owned by the upstream ANSI package.
// Will be replaced by https://github.com/charmbracelet/x/pull/982
func encodeKittyGraphicsData(w io.Writer, data []byte, o *kitty.Options) error {
	if o == nil {
		o = &kitty.Options{}
	}
	payload := base64.StdEncoding.AppendEncode(nil, data)
	if !o.Chunk {
		_, err := io.WriteString(w, ansi.KittyGraphics(payload, o.Options()...))
		return err
	}
	for first := true; ; first = false {
		// Match Charm's framing at exact boundaries: a full chunk is followed
		// by an empty m=0 terminator, including for a single full chunk.
		last := len(payload) < kitty.MaxChunkSize
		n := min(len(payload), kitty.MaxChunkSize)
		var opts []string
		if first {
			opts = o.Options()
		} else {
			quiet := o.Quiet
			if o.Quite > 0 {
				quiet = o.Quite
			}
			if quiet > 0 {
				opts = append(opts, fmt.Sprintf("q=%d", quiet))
			}
			if o.Action == kitty.Frame {
				opts = append(opts, "a=f")
			}
		}
		if !first || !last {
			more := "m=1"
			if last {
				more = "m=0"
			}
			opts = append(opts, more)
		}
		apc := ansi.KittyGraphics(payload[:n], opts...)
		if o.ChunkFormatter != nil {
			apc = o.ChunkFormatter(apc)
		}
		if _, err := io.WriteString(w, apc); err != nil {
			return err
		}
		if last {
			return nil
		}
		payload = payload[n:]
	}
}
