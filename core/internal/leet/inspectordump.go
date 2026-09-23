package leet

import (
	"errors"
	"fmt"
	"io"

	"google.golang.org/protobuf/encoding/prototext"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// DumpRecords writes every record in a .wandb file to w as prototext,
// each preceded by a "# record N: <type>" line. An empty runFile resolves
// to the latest run in wandbDir, like starting LEET in single-run mode.
//
// Notes about skipped corrupt regions and an incomplete tail (a run that
// is still writing or did not finish cleanly) are emitted as "#" comment
// lines, so the output remains a sequence of valid prototext stanzas.
func DumpRecords(runFile, wandbDir string, w io.Writer) error {
	path, err := resolveWandbFile(runFile, wandbDir)
	if err != nil {
		return err
	}

	reader, err := transactionlog.OpenReader(path, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	defer reader.Close()

	marshal := prototext.MarshalOptions{Multiline: true, Indent: "  "}

	for num := 1; ; {
		record, err := readRecord(reader)

		switch {
		case errors.Is(err, io.EOF):
			return nil
		case errors.Is(err, io.ErrUnexpectedEOF):
			_, err = fmt.Fprintln(w,
				"# reached the end of an incomplete .wandb file"+
					" (the run may still be active or was interrupted)")
			return err
		case errors.Is(err, errCorruptSkipped):
			if _, err := fmt.Fprintf(w, "# %v\n", err); err != nil {
				return err
			}
			continue
		case err != nil:
			return err
		}

		_, err = fmt.Fprintf(w, "# record %d: %s\n%s\n",
			num, recordTypeName(record), marshal.Format(record))
		if err != nil {
			return err
		}
		num++
	}
}

// errCorruptSkipped wraps a read error after which reading continues past
// the corrupt data.
var errCorruptSkipped = errors.New("skipped corrupt data")

// readRecord reads the next record.
//
// An error wrapping errCorruptSkipped means corrupt data was skipped and
// reading can go on. Any other error besides EOF would repeat on every
// call, as for a file that is not a transaction log.
func readRecord(reader *transactionlog.Reader) (*spb.Record, error) {
	before := reader.NextRecordOffset()
	record, err := reader.Read()
	if err != nil &&
		!errors.Is(err, io.EOF) &&
		!errors.Is(err, io.ErrUnexpectedEOF) &&
		reader.NextRecordOffset() > before {
		return nil, fmt.Errorf("%w: %v", errCorruptSkipped, err)
	}
	return record, err
}
