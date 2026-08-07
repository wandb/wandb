// Command fixturegen writes the committed corpus of .wandb fixture trees
// used as the shared input for differential frame testing between Go leet
// (the oracle) and the Rust port.
//
// Usage:
//
//	fixturegen -out <path-to-leet/fixtures> [-only <name>] [-verify]
//
// Output is deterministic: running the generator twice produces
// byte-identical trees. See the generated README.md for details.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
)

// fixtureNames lists every fixture this generator owns, in output order.
var fixtureNames = []string{
	"single-tiny",
	"workspace-multi",
	"system-stats",
	"media",
	"edge-nan-inf",
	"edge-empty",
	"edge-unicode",
	"wire-corrupt",
}

func main() {
	out := flag.String("out", "",
		"path to the leet/fixtures output root (required)")
	only := flag.String("only", "",
		"regenerate only the named fixture (one of: "+
			strings.Join(fixtureNames, ", ")+")")
	verify := flag.Bool("verify", false,
		"instead of generating, open every corpus .wandb file under -out "+
			"via transactionlog.OpenReader and report record counts")
	dump := flag.String("dump", "",
		"instead of generating, print a per-record digest of the given "+
			".wandb file (one \"REC <index> <case> <len> <crc32c>\" line per "+
			"record, then \"OK <count>\" or \"ERROR corrupt|eof\") and exit")
	chartdump := flag.Bool("chartdump", false,
		"instead of generating, print ANSI-stripped rune grids of a fixed "+
			"table of chart scenarios (the leet-charts canvas differential; "+
			"see chartdump.go) and exit")
	flag.Parse()

	if *dump != "" {
		os.Exit(dumpWandb(*dump))
	}

	if *chartdump {
		os.Exit(runChartDump(os.Stdout))
	}

	if *out == "" {
		fmt.Fprintln(os.Stderr,
			"usage: fixturegen -out <path-to-leet/fixtures> [-only <name>] [-verify]")
		os.Exit(2)
	}

	files, meta := buildCorpus()
	files = append(files, fileEntry{Path: "README.md", Data: renderREADME(meta)})
	// The manifest covers every file above (including README.md) but not
	// itself.
	files = append(files, fileEntry{Path: "manifest.json", Data: renderManifest(files)})

	if *verify {
		os.Exit(verifyCorpus(*out, files, meta))
	}

	selected := map[string]bool{}
	if *only != "" {
		ok := false
		for _, name := range fixtureNames {
			if name == *only {
				ok = true
			}
		}
		if !ok {
			fmt.Fprintf(os.Stderr,
				"fixturegen: unknown fixture %q (want one of: %s)\n",
				*only, strings.Join(fixtureNames, ", "))
			os.Exit(2)
		}
		selected[*only] = true
	} else {
		for _, name := range fixtureNames {
			selected[name] = true
		}
	}

	if err := writeCorpus(*out, files, selected, meta); err != nil {
		fmt.Fprintln(os.Stderr, "fixturegen:", err)
		os.Exit(1)
	}
}

// fixtureOfPath maps a corpus-relative path to the fixture that owns it.
// Meta files (README.md, manifest.json) return "" and are always written.
func fixtureOfPath(p string) string {
	if strings.HasPrefix(p, "wire/") {
		return "wire-corrupt"
	}
	if rest, ok := strings.CutPrefix(p, "wandb/"); ok {
		if i := strings.IndexByte(rest, '/'); i > 0 {
			return rest[:i]
		}
	}
	return ""
}

// writeCorpus wipes and rewrites the directories owned by the selected
// fixtures, then writes their files plus README.md and manifest.json.
func writeCorpus(
	root string,
	files []fileEntry,
	selected map[string]bool,
	meta *corpusMeta,
) error {
	// Wipe only the trees we own and that are selected.
	for name := range selected {
		dir := filepath.Join(root, "wandb", name)
		if name == "wire-corrupt" {
			dir = filepath.Join(root, "wire")
		}
		if err := os.RemoveAll(dir); err != nil {
			return fmt.Errorf("wiping %s: %w", dir, err)
		}
	}

	written, skipped := 0, 0
	var totalBytes int64
	for _, f := range files {
		if fx := fixtureOfPath(f.Path); fx != "" && !selected[fx] {
			skipped++
			continue
		}
		abs := filepath.Join(root, filepath.FromSlash(f.Path))
		if err := os.MkdirAll(filepath.Dir(abs), 0o755); err != nil {
			return err
		}
		if f.Link != "" {
			// Symlinks have no rewrite; remove any stale one first.
			if err := os.Remove(abs); err != nil && !os.IsNotExist(err) {
				return err
			}
			if err := os.Symlink(f.Link, abs); err != nil {
				return fmt.Errorf("symlink %s -> %s: %w", abs, f.Link, err)
			}
		} else {
			if err := os.WriteFile(abs, f.Data, 0o644); err != nil {
				return err
			}
			totalBytes += int64(len(f.Data))
		}
		written++
	}

	fmt.Printf("fixturegen: wrote %d files (%d bytes) under %s",
		written, totalBytes, root)
	if skipped > 0 {
		fmt.Printf(" (skipped %d files of unselected fixtures)", skipped)
	}
	fmt.Println()

	// Per-file record counts, sorted for stable output.
	paths := make([]string, 0, len(meta.recordCounts))
	for p := range meta.recordCounts {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	for _, p := range paths {
		if fx := fixtureOfPath(p); fx != "" && !selected[fx] {
			continue
		}
		fmt.Printf("  %-72s %3d records\n", p, meta.recordCounts[p])
	}
	return nil
}

// --- manifest --------------------------------------------------------------

type manifestFile struct {
	Path    string `json:"path"`
	Symlink string `json:"symlink,omitempty"`
	Size    int    `json:"size,omitempty"`
	SHA256  string `json:"sha256,omitempty"`
}

type manifestDoc struct {
	Generator     string         `json:"generator"`
	BaseTimestamp string         `json:"baseTimestamp"`
	Files         []manifestFile `json:"files"`
}

func renderManifest(files []fileEntry) []byte {
	entries := make([]manifestFile, 0, len(files))
	for _, f := range files {
		if f.Link != "" {
			entries = append(entries, manifestFile{Path: f.Path, Symlink: f.Link})
			continue
		}
		sum := sha256.Sum256(f.Data)
		entries = append(entries, manifestFile{
			Path:   f.Path,
			Size:   len(f.Data),
			SHA256: hex.EncodeToString(sum[:]),
		})
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Path < entries[j].Path
	})

	doc := manifestDoc{
		Generator:     "core/internal/leet/fixturegen",
		BaseTimestamp: baseISO,
		Files:         entries,
	}
	data, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		panic(err)
	}
	return append(data, '\n')
}

// --- README ----------------------------------------------------------------

func renderREADME(meta *corpusMeta) []byte {
	var b strings.Builder

	b.WriteString(`# leet fixture corpus

Deterministic ` + "`.wandb`" + ` fixture trees shared by Go leet (the oracle) and the
Rust port for differential frame testing. Generated by
` + "`core/internal/leet/fixturegen`" + `; do not edit by hand.

Regenerate (from the repo root):

    cd core && go run ./internal/leet/fixturegen -out ../leet/fixtures

Verify readability of the committed corpus:

    cd core && go run ./internal/leet/fixturegen -out ../leet/fixtures -verify

## Determinism

Byte-identical output across runs and machines:

- Every record timestamp derives from the fixed base ` + baseISO + `
  (unix ` + fmt.Sprint(baseUnix) + `); no ` + "`time.Now`" + `.
- Records are marshaled with ` + "`proto.MarshalOptions{Deterministic: true}`" + `
  and all key/value collections are emitted from ordered slices.
- Metric values come from closed-form formulas rounded to six decimals; the
  only "noise" is an integer xorshift64 PRNG seeded per series.
- PNGs are written by a hand-rolled encoder using zlib stored (uncompressed)
  deflate blocks, so their bytes do not depend on the Go toolchain version.

## Layout

Each fixture is a self-contained tree ` + "`wandb/<name>/wandb/`" + ` holding run dirs
(` + "`run-YYYYMMDD_HHMMSS-<id>/run-<id>.wandb`" + `) plus a ` + "`latest-run`" + ` symlink to
the newest run dir. Symlinks are committed as git symlink objects (precedent:
` + "`core/LICENSE`" + `); on filesystems without symlink support they check out as
plain files containing the target name.

## Fixtures

| Fixture | Contents |
| --- | --- |
| single-tiny | One finished run: 3 metric shapes (linear, noisy sine, step fn) x 50 steps, config, summary, EnvironmentRecord, ~20 console lines incl. CR progress-bar rewrites and one ANSI-colored line, exit 0. |
| workspace-multi | 5 runs: distinct display names, tags on 2 runs, notes on 1, overlapping + unique metrics, one crashed (exit 1), one with no exit record (appears live/stale). |
| system-stats | One run with 60 StatsRecords: cpu %, per-core cpu, memory %, disk usage + cumulative I/O, network, nvidia-style gpu.0.{gpu,memoryAllocated,temp,powerWatts}, and /l:trainer labeled variants. |
| media | One run, 5 steps: an ` + "`image-file`" + ` series ("samples", with captions + sha256) and an ` + "`images/separated`" + ` series ("gallery", 2 images/step with captions); 15 real PNGs under ` + "`files/media/images/`" + `. |
| edge-nan-inf | Metrics with NaN / Infinity / -Infinity value_json, a single-point metric, and an all-identical (flat-range) metric. |
| edge-empty | Valid header + RunRecord only; no history, no exit. |
| edge-unicode | CJK + emoji + ZWJ sequences in display name, tags, notes, config, and metric keys. |
| wire/ | Wire-level corruption fixtures for reader tests only (never loaded by the TUI). |

## Record counts

`)

	paths := make([]string, 0, len(meta.recordCounts))
	for p := range meta.recordCounts {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	b.WriteString("| File | Records |\n| --- | --- |\n")
	for _, p := range paths {
		fmt.Fprintf(&b, "| %s | %d |\n", p, meta.recordCounts[p])
	}

	b.WriteString(`
## Wire corruption details

The .wandb wire format is a 7-byte W&B header (":W&B", magic 0xBEE1 LE,
version 0) followed by LevelDB chunks; each chunk has a 7-byte header
(CRC32-IEEE over type+payload, 4 bytes LE; payload length, 2 bytes LE;
chunk type, 1 byte). Both wire files fit in a single 32KiB block, one chunk
per record, so all offsets below are exact.

`)
	for _, w := range meta.wire {
		fmt.Fprintf(&b, "### %s\n\n", w.Name)
		fmt.Fprintf(&b, "%s.\n\n", w.CorruptNote)
		fmt.Fprintf(&b,
			"- records in stream: %d; expected readable: %d\n", w.Records, w.Readable)
		fmt.Fprintf(&b, "- file size: %d bytes", w.FinalLen)
		if w.CutOffset >= 0 {
			fmt.Fprintf(&b, " (truncated from %d at offset %d)",
				w.FullLen, w.CutOffset)
		}
		b.WriteString("\n")
		if w.FlipOffset >= 0 {
			fmt.Fprintf(&b, "- flipped byte offset: %d\n", w.FlipOffset)
		}
		b.WriteString("- chunk offsets (payload lengths): ")
		for i, off := range w.ChunkOffsets {
			if i > 0 {
				b.WriteString(", ")
			}
			fmt.Fprintf(&b, "%d (%d)", off, w.PayloadLens[i])
		}
		b.WriteString("\n\n")
	}

	b.WriteString(`## manifest.json

Machine-readable listing of every generated file with size and sha256
(symlinks list their target instead). Rebuilt on every generator run.
`)

	return []byte(b.String())
}

// --- verify ----------------------------------------------------------------

// verifyCorpus opens every corpus .wandb file under root with
// transactionlog.OpenReader and reads to EOF, counting records. Wire
// fixtures are expected to produce read errors; everything else must
// decode its full record count cleanly.
func verifyCorpus(root string, files []fileEntry, meta *corpusMeta) int {
	logger := observability.NewNoOpLogger()
	failures := 0

	for _, f := range files {
		if !strings.HasSuffix(f.Path, ".wandb") {
			continue
		}
		expectCorrupt := strings.HasPrefix(f.Path, "wire/")
		abs := filepath.Join(root, filepath.FromSlash(f.Path))

		reader, err := transactionlog.OpenReader(abs, logger)
		if err != nil {
			fmt.Printf("FAIL  %-70s open: %v\n", f.Path, err)
			failures++
			continue
		}

		count := 0
		var readErrs []string
		for range 1_000_000 {
			_, err := reader.Read()
			if err == nil {
				count++
				continue
			}
			if errors.Is(err, io.EOF) && !errors.Is(err, io.ErrUnexpectedEOF) {
				break
			}
			readErrs = append(readErrs, err.Error())
			if len(readErrs) >= 8 {
				break
			}
		}
		reader.Close()

		status := "ok  "
		switch {
		case expectCorrupt && len(readErrs) == 0:
			status = "FAIL"
			failures++
		case !expectCorrupt && len(readErrs) > 0:
			status = "FAIL"
			failures++
		case !expectCorrupt && count != meta.recordCounts[f.Path]:
			status = "FAIL"
			failures++
		}

		fmt.Printf("%s  %-70s %3d/%d records", status, f.Path,
			count, meta.recordCounts[f.Path])
		if len(readErrs) > 0 {
			fmt.Printf(", %d read error(s): %s", len(readErrs), readErrs[0])
		}
		fmt.Println()
	}

	if failures > 0 {
		fmt.Printf("fixturegen -verify: %d failure(s)\n", failures)
		return 1
	}
	fmt.Println("fixturegen -verify: all files readable as expected")
	return 0
}
