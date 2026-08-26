package leet

import (
	"errors"
	"fmt"
	"io"

	"google.golang.org/protobuf/encoding/prototext"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
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
		record, err := reader.Read()

		switch {
		case errors.Is(err, io.EOF):
			return nil
		case errors.Is(err, io.ErrUnexpectedEOF):
			_, err = fmt.Fprintln(w,
				"# reached the end of an incomplete .wandb file"+
					" (the run may still be active or was interrupted)")
			return err
		case err != nil:
			if _, err := fmt.Fprintf(w,
				"# skipped corrupt data: %v\n", err); err != nil {
				return err
			}
			continue
		}

		_, err = fmt.Fprintf(w, "# record %d: %s\n%s\n",
			num, recordTypeName(record), marshal.Format(record))
		if err != nil {
			return err
		}
		num++
	}
}
