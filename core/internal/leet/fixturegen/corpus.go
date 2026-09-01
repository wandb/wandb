package main

// Fixture corpus definitions.
//
// buildCorpus is a pure function: it deterministically produces every
// fixture file (and its bytes) in memory. Nothing here reads the clock,
// the environment, or unseeded randomness; float values are rounded to six
// decimals before formatting so the emitted JSON strings are stable.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"math"
	"strconv"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// The fixed base timestamp for every record and derived name:
// 2026-01-02T03:04:05Z.
var baseUnix = time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC).Unix()

const (
	baseISO   = "2026-01-02T03:04:05Z"
	baseStamp = "20260102_030405"

	fixtureProject = "leet-fixtures"
	fixtureEntity  = "fixture-entity"
	fixtureHost    = "fixture-host"
)

// fileEntry is one output file, with Path relative to the fixtures root
// (forward slashes). If Link is non-empty the entry is a symlink to Link.
type fileEntry struct {
	Path string
	Data []byte
	Link string
}

type wireFileMeta struct {
	Name         string
	Records      int   // records in the pre-corruption stream
	Readable     int   // records a reader should decode successfully
	FullLen      int   // pre-corruption stream length in bytes
	FinalLen     int   // on-disk file length in bytes
	ChunkOffsets []int // chunk-header offset per record
	PayloadLens  []int // proto payload length per record
	CorruptNote  string
	FlipOffset   int // bad-crc: offset of the XORed byte (-1 otherwise)
	CutOffset    int // truncated-tail: truncation offset (-1 otherwise)
}

type corpusMeta struct {
	recordCounts map[string]int // .wandb path -> record count as written
	wire         []wireFileMeta
}

// --- deterministic value helpers -----------------------------------------

// round6 rounds to six decimals and normalizes negative zero.
func round6(v float64) float64 {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return v
	}
	r := math.Round(v*1e6) / 1e6
	if r == 0 {
		r = 0 // normalize -0
	}
	return r
}

func fmtF(v float64) string {
	return strconv.FormatFloat(round6(v), 'g', -1, 64)
}

func clamp(v, lo, hi float64) float64 { return math.Min(hi, math.Max(lo, v)) }

// prng is a xorshift64 generator; all-integer, hence bit-identical
// everywhere. Seeded from a name so each series gets independent noise.
type prng struct{ s uint64 }

func newPrng(name string) *prng {
	h := fnv.New64a()
	_, _ = h.Write([]byte(name))
	s := h.Sum64()
	if s == 0 {
		s = 1
	}
	return &prng{s: s}
}

func (p *prng) next() uint64 {
	p.s ^= p.s << 13
	p.s ^= p.s >> 7
	p.s ^= p.s << 17
	return p.s
}

// unit returns a value in [0, 1) with 1e-4 granularity (integer-derived).
func (p *prng) unit() float64 { return float64(p.next()%10000) / 10000 }

// --- shared record helpers ------------------------------------------------

func runRecord(
	id, displayName, notes string,
	tags []string,
	cfg *spb.ConfigRecord,
) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
		RunId:       id,
		DisplayName: displayName,
		Project:     fixtureProject,
		Entity:      fixtureEntity,
		Notes:       notes,
		Tags:        tags,
		Config:      cfg,
		Host:        fixtureHost,
		StartTime:   ts(baseUnix),
	}}}
}

func environmentRecord(gpuType string, gpuCount uint32) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Environment{
		Environment: &spb.EnvironmentRecord{
			Os:              "Linux-6.1.0-fixture-x86_64-with-glibc2.36",
			Python:          "3.11.9",
			StartedAt:       ts(baseUnix),
			Program:         "train.py",
			Host:            fixtureHost,
			Username:        "fixture-user",
			Executable:      "/usr/bin/python3",
			CpuCount:        8,
			CpuCountLogical: 16,
			GpuType:         gpuType,
			GpuCount:        gpuCount,
			WriterId:        "fixturegen",
		},
	}}
}

// wandbFilePath returns the path of a run's .wandb file relative to the
// fixtures root, matching the layout leet discovers
// (wandb/<fixture>/wandb/run-<stamp>-<id>/run-<id>.wandb).
func wandbFilePath(fixture, runDir, runID string) string {
	return "wandb/" + fixture + "/wandb/" + runDir + "/run-" + runID + ".wandb"
}

func latestRunLink(fixture, runDir string) fileEntry {
	return fileEntry{
		Path: "wandb/" + fixture + "/wandb/latest-run",
		Link: runDir,
	}
}

// --- corpus ---------------------------------------------------------------

func buildCorpus() ([]fileEntry, *corpusMeta) {
	meta := &corpusMeta{recordCounts: map[string]int{}}

	var files []fileEntry
	files = append(files, buildSingleTiny(meta)...)
	files = append(files, buildWorkspaceMulti(meta)...)
	files = append(files, buildSystemStats(meta)...)
	files = append(files, buildMedia(meta)...)
	files = append(files, buildEdgeNaNInf(meta)...)
	files = append(files, buildEdgeEmpty(meta)...)
	files = append(files, buildEdgeUnicode(meta)...)
	files = append(files, buildWireCorrupt(meta)...)
	return files, meta
}

// 1. single-tiny: one finished run, 3 metric shapes x 50 steps, config,
// summary, environment, ~20 console lines (with \r rewrites + ANSI), exit 0.
func buildSingleTiny(meta *corpusMeta) []fileEntry {
	const (
		fixture = "single-tiny"
		runID   = "tiny0001"
		runDir  = "run-" + baseStamp + "-" + runID
		steps   = 50
	)

	b := newWandbBuilder()
	b.write(runRecord(runID, "single-tiny-run", "", nil, configRecord([]kv{
		{"batch_size", "32"},
		{"epochs", "5"},
		{"lr", "0.001"},
		{"optimizer", `"adam"`},
		{"seed", "1234"},
	})))
	b.write(environmentRecord("NVIDIA FixtureRTX 4090", 1))

	b.write(outputRawRecord(
		"Starting training run tiny0001\n", false, baseUnix))
	b.write(outputRawRecord(
		"\x1b[32mINFO\x1b[0m config loaded: lr=0.001 batch_size=32\n",
		false, baseUnix+1))

	noise := newPrng("single-tiny/train/sine")
	for s := range steps {
		fs := float64(s)
		b.write(historyRecord(s, []kv{
			{"_timestamp", fmt.Sprintf("%d", baseUnix+2+int64(s))},
			{"eval/step_fn", fmtF(float64((s / 10) % 3))},
			{"train/loss", fmtF(2.0 - 0.035*fs)},
			{"train/sine", fmtF(0.5 + 0.4*math.Sin(fs/5) + 0.05*(noise.unit()-0.5))},
		}))
		// Progress-bar style \r rewrites every 5 steps (10 lines).
		if s%5 == 4 {
			pct := (s + 1) * 2
			bar := ""
			for range pct / 10 {
				bar += "#"
			}
			for range 10 - pct/10 {
				bar += "-"
			}
			b.write(outputRawRecord(
				fmt.Sprintf("training: %3d%%|%s| %d/%d\r", pct, bar, s+1, steps),
				false, baseUnix+2+int64(s)))
		}
	}
	b.write(outputRawRecord(
		fmt.Sprintf("training: 100%%|##########| %d/%d\n", steps, steps),
		false, baseUnix+2+steps))
	b.write(outputRawRecord(
		"warning: fixture warning emitted at step 25\n", true, baseUnix+3+steps))
	for e := range 5 {
		b.write(outputRawRecord(
			fmt.Sprintf("epoch %d complete, loss=%s\n",
				e+1, fmtF(2.0-0.35*float64(e+1))),
			false, baseUnix+4+steps+int64(e)))
	}
	b.write(outputRawRecord("Run finished successfully.\n", false, baseUnix+60))

	b.write(summaryRecord([]kv{
		{"best_step", "49"},
		{"eval/step_fn", "1"},
		{"note", `"fixture summary"`},
		{"train/loss", fmtF(2.0 - 0.035*49)},
		{"train/sine", fmtF(0.5 + 0.4*math.Sin(49.0/5))},
	}))
	b.write(exitRecord(0, 300))

	path := wandbFilePath(fixture, runDir, runID)
	data := b.bytes()
	meta.recordCounts[path] = b.recordCount()
	return []fileEntry{
		{Path: path, Data: data},
		latestRunLink(fixture, runDir),
	}
}

// 2. workspace-multi: 5 runs with distinct names, tags on 2, notes on 1,
// overlapping + unique metrics, one crashed (exit 1), one without exit.
func buildWorkspaceMulti(meta *corpusMeta) []fileEntry {
	const fixture = "workspace-multi"

	type runSpec struct {
		id, stamp, name, notes string
		tags                   []string
		steps                  int
		exit                   int32 // -1: no exit record
		extras                 []string
	}
	specs := []runSpec{
		{id: "wm1plain", stamp: "20260102_030005", name: "plain-hill-1",
			steps: 30, exit: 0},
		{id: "wm2notes", stamp: "20260102_030105", name: "noted-morning-2",
			notes: "Fixture run with notes: baseline comparison for leet.",
			steps: 30, exit: 0, extras: []string{"eval/bleu"}},
		{id: "wm3live", stamp: "20260102_030205", name: "live-salad-3",
			steps: 30, exit: -1,
			extras: []string{"train/accuracy", "train/kl"}},
		{id: "wm4crash", stamp: "20260102_030305", name: "crashed-flame-4",
			tags:  []string{"crash-test"},
			steps: 18, exit: 1, extras: []string{"sys/throughput"}},
		{id: "wm5best", stamp: "20260102_030405", name: "sunny-lion-5",
			tags:  []string{"baseline", "best"},
			steps: 30, exit: 0, extras: []string{"train/accuracy"}},
	}

	var files []fileEntry
	for r, sp := range specs {
		runDir := "run-" + sp.stamp + "-" + sp.id
		b := newWandbBuilder()
		b.write(runRecord(sp.id, sp.name, sp.notes, sp.tags, configRecord([]kv{
			{"lr", fmtF(0.001 * float64(r+1))},
			{"run_index", strconv.Itoa(r + 1)},
		})))

		for s := range sp.steps {
			fs := float64(s)
			fr := float64(r + 1)
			items := []kv{
				{"train/loss",
					fmtF((1.0+0.2*fr)*(1.0-fs/40) + 0.05*math.Sin(fs/3+fr))},
			}
			for _, extra := range sp.extras {
				switch extra {
				case "train/accuracy":
					items = append(items, kv{extra,
						fmtF(clamp(0.5+0.015*fs+0.01*fr, 0, 0.99))})
				case "train/kl":
					items = append(items, kv{extra, fmtF(0.1 / (1.0 + fs))})
				case "sys/throughput":
					items = append(items, kv{extra,
						fmtF(1000 + 50*math.Sin(fs/4))})
				case "eval/bleu":
					items = append(items, kv{extra, fmtF(20 + 0.3*fs)})
				}
			}
			b.write(historyRecord(s, items))
		}

		if sp.exit == 1 {
			b.write(outputRawRecord(
				"Traceback (most recent call last):\n", true,
				baseUnix+int64(sp.steps)))
			b.write(outputRawRecord(
				"RuntimeError: fixture crash at step 17\n", true,
				baseUnix+int64(sp.steps)+1))
		}
		if sp.exit >= 0 {
			b.write(exitRecord(sp.exit, int32(sp.steps)))
		}

		path := wandbFilePath(fixture, runDir, sp.id)
		data := b.bytes()
		meta.recordCounts[path] = b.recordCount()
		files = append(files, fileEntry{Path: path, Data: data})
	}

	// latest-run points at the newest run dir (wm5best).
	files = append(files, latestRunLink(fixture, "run-20260102_030405-wm5best"))
	return files
}

// 3. system-stats: one run with 60 StatsRecords covering cpu, memory %,
// disk, network, nvidia-style gpu.0.* keys, and /l:<label> variants.
func buildSystemStats(meta *corpusMeta) []fileEntry {
	const (
		fixture = "system-stats"
		runID   = "sysstats1"
		runDir  = "run-" + baseStamp + "-" + runID
		samples = 60
	)

	b := newWandbBuilder()
	b.write(runRecord(runID, "system-stats-run", "", nil, nil))
	b.write(environmentRecord("NVIDIA H100 80GB HBM3", 1))
	b.write(historyRecord(0, []kv{{"train/loss", "1"}}))

	noise := newPrng("system-stats")
	for i := range samples {
		fi := float64(i)
		n := noise.unit() - 0.5
		items := []kv{
			{"cpu", fmtF(clamp(30+20*math.Sin(fi/6)+4*n, 0, 100))},
			{"cpu.0.cpu_percent", fmtF(clamp(40+30*math.Sin(fi/5), 0, 100))},
			{"cpu.1.cpu_percent", fmtF(clamp(35+25*math.Sin(fi/5+1), 0, 100))},
			{"cpu/l:trainer", fmtF(clamp(25+10*math.Sin(fi/6+1), 0, 100))},
			{"disk./.usagePercent", fmtF(clamp(60+0.05*fi, 0, 100))},
			{"disk.in", fmtF(12.5 * fi)},
			{"disk.out", fmtF(30 * fi)},
			{"gpu.0.gpu", fmtF(clamp(80+15*math.Sin(fi/4), 0, 100))},
			{"gpu.0.gpu/l:trainer",
				fmtF(clamp(70+15*math.Sin(fi/4+0.5), 0, 100))},
			{"gpu.0.memoryAllocated",
				fmtF(clamp(65+10*math.Sin(fi/7), 0, 100))},
			{"gpu.0.powerWatts", fmtF(250 + 60*math.Sin(fi/5))},
			{"gpu.0.temp", fmtF(55 + 8*math.Sin(fi/9))},
			{"memory_percent", fmtF(clamp(50+0.3*fi, 0, 100))},
			{"network.recv", fmtF(1.0e6 + 5.0e4*fi)},
			{"network.sent", fmtF(8.0e5 + 3.0e4*fi)},
		}
		b.write(statsRecord(baseUnix+int64(2*i), items))
	}
	b.write(exitRecord(0, 2*samples))

	path := wandbFilePath(fixture, runDir, runID)
	data := b.bytes()
	meta.recordCounts[path] = b.recordCount()
	return []fileEntry{
		{Path: path, Data: data},
		latestRunLink(fixture, runDir),
	}
}

// 4. media: one run with an "image-file" series and an "images/separated"
// series (with captions), 5 steps each, plus real PNGs under
// files/media/images/ where leet's resolveMediaPath looks for them.
func buildMedia(meta *corpusMeta) []fileEntry {
	const (
		fixture = "media"
		runID   = "media001"
		runDir  = "run-" + baseStamp + "-" + runID
		steps   = 5
		imgW    = 32
		imgH    = 24
	)
	runBase := "wandb/" + fixture + "/wandb/" + runDir

	var files []fileEntry
	b := newWandbBuilder()
	b.write(runRecord(runID, "media-run", "", nil, nil))

	// addPNG encodes a deterministic gradient, names the file after its
	// content hash (mirroring wandb's media naming), and records it.
	addPNG := func(prefix string, s, variant int) (relPath, sum string, size int) {
		png := encodePNG(imgW, imgH, func(x, y int) [3]byte {
			return [3]byte{
				byte(x * 255 / (imgW - 1)),
				byte(y * 255 / (imgH - 1)),
				byte((s*40 + variant*80 + (x+y)*4) % 256),
			}
		})
		digest := sha256.Sum256(png)
		hexSum := hex.EncodeToString(digest[:])
		var name string
		if variant < 0 {
			name = fmt.Sprintf("%s_%d_%s.png", prefix, s, hexSum[:8])
		} else {
			name = fmt.Sprintf("%s_%d_%d_%s.png", prefix, s, variant, hexSum[:8])
		}
		rel := "media/images/" + name
		files = append(files, fileEntry{
			Path: runBase + "/files/" + rel,
			Data: png,
		})
		return rel, hexSum, len(png)
	}

	for s := range steps {
		var items []*spb.HistoryItem

		// Series "samples": _type image-file.
		rel, sum, size := addPNG("samples", s, -1)
		items = append(items,
			nestedItem([]string{"samples", "_type"}, `"image-file"`),
			nestedItem([]string{"samples", "caption"},
				strconv.Quote(fmt.Sprintf("sample at step %d", s))),
			nestedItem([]string{"samples", "format"}, `"png"`),
			nestedItem([]string{"samples", "height"}, strconv.Itoa(imgH)),
			nestedItem([]string{"samples", "path"}, strconv.Quote(rel)),
			nestedItem([]string{"samples", "sha256"}, strconv.Quote(sum)),
			nestedItem([]string{"samples", "size"}, strconv.Itoa(size)),
			nestedItem([]string{"samples", "width"}, strconv.Itoa(imgW)),
		)

		// Series "gallery": _type images/separated with captions.
		var names, captions []string
		for v := range 2 {
			rel, _, _ := addPNG("gallery", s, v)
			names = append(names, rel)
			captions = append(captions,
				fmt.Sprintf("gallery %d/%d at step %d", v+1, 2, s))
		}
		namesJSON, _ := json.Marshal(names)
		captionsJSON, _ := json.Marshal(captions)
		items = append(items,
			nestedItem([]string{"gallery", "_type"}, `"images/separated"`),
			nestedItem([]string{"gallery", "captions"}, string(captionsJSON)),
			nestedItem([]string{"gallery", "count"}, "2"),
			nestedItem([]string{"gallery", "filenames"}, string(namesJSON)),
			nestedItem([]string{"gallery", "format"}, `"png"`),
			nestedItem([]string{"gallery", "height"}, strconv.Itoa(imgH)),
			nestedItem([]string{"gallery", "width"}, strconv.Itoa(imgW)),
		)

		// A scalar metric so the metrics grid renders too.
		items = append(items,
			nestedItem([]string{"train/loss"}, fmtF(0.9-0.12*float64(s))))

		b.write(historyRecordNested(s, items))
	}
	b.write(exitRecord(0, 42))

	path := wandbFilePath(fixture, runDir, runID)
	data := b.bytes()
	meta.recordCounts[path] = b.recordCount()
	files = append(files,
		fileEntry{Path: path, Data: data},
		latestRunLink(fixture, runDir),
	)
	return files
}

// 5. edge-nan-inf: NaN, +Inf, -Inf values; a single-point metric; and an
// all-identical-values (flat-range) metric.
func buildEdgeNaNInf(meta *corpusMeta) []fileEntry {
	const (
		fixture = "edge-nan-inf"
		runID   = "nanedge1"
		runDir  = "run-" + baseStamp + "-" + runID
		steps   = 20
	)

	b := newWandbBuilder()
	b.write(runRecord(runID, "edge-nan-inf-run", "", nil, nil))
	for s := range steps {
		var v string
		switch s % 5 {
		case 1:
			v = "NaN"
		case 2:
			v = "Infinity"
		case 3:
			v = "-Infinity"
		default:
			v = fmtF(math.Sin(float64(s) / 3))
		}
		items := []kv{
			{"edge/flat", "1.5"},
			{"edge/nan_inf", v},
		}
		if s == 0 {
			items = append(items, kv{"edge/single_point", "42"})
		}
		b.write(historyRecord(s, items))
	}
	b.write(exitRecord(0, steps))

	path := wandbFilePath(fixture, runDir, runID)
	data := b.bytes()
	meta.recordCounts[path] = b.recordCount()
	return []fileEntry{
		{Path: path, Data: data},
		latestRunLink(fixture, runDir),
	}
}

// 6. edge-empty: valid header + RunRecord only; no history, no exit.
func buildEdgeEmpty(meta *corpusMeta) []fileEntry {
	const (
		fixture = "edge-empty"
		runID   = "empty001"
		runDir  = "run-" + baseStamp + "-" + runID
	)

	b := newWandbBuilder()
	b.write(runRecord(runID, "edge-empty-run", "", nil, nil))

	path := wandbFilePath(fixture, runDir, runID)
	data := b.bytes()
	meta.recordCounts[path] = b.recordCount()
	return []fileEntry{
		{Path: path, Data: data},
		latestRunLink(fixture, runDir),
	}
}

// 7. edge-unicode: CJK + emoji + ZWJ sequences in display name, tags, notes,
// and metric keys (unicode-hostile fixture for structural-only diffing).
func buildEdgeUnicode(meta *corpusMeta) []fileEntry {
	const (
		fixture = "edge-unicode"
		runID   = "uni00001"
		runDir  = "run-" + baseStamp + "-" + runID
		steps   = 10
	)

	b := newWandbBuilder()
	b.write(runRecord(
		runID,
		"日本語ラン 🚀 家族👨‍👩‍👧‍👦", // CJK + emoji + ZWJ family sequence
		"多言語ノート: emoji 🎉, ZWJ 👩‍🚀, combining café, 中文注释。",
		[]string{"标签", "🏷️tag", "ラベル", "café"},
		configRecord([]kv{
			{"描述", `"值"`},
			{"模型/名字", `"变形金刚🤖"`},
		}),
	))
	b.write(outputRawRecord("训练开始 🚀 ログ出力 👨‍👩‍👧‍👦\n", false, baseUnix))
	for s := range steps {
		fs := float64(s)
		b.write(historyRecord(s, []kv{
			{"emoji/🚀speed", fmtF(100 + 5*fs)},
			{"损失/loss", fmtF(1.0 - 0.08*fs)},
		}))
	}
	b.write(exitRecord(0, steps))

	path := wandbFilePath(fixture, runDir, runID)
	data := b.bytes()
	meta.recordCounts[path] = b.recordCount()
	return []fileEntry{
		{Path: path, Data: data},
		latestRunLink(fixture, runDir),
	}
}

// 8. wire-corrupt: wire-level corruption fixtures (not loaded by the TUI):
// a stream truncated mid-payload and a stream with one flipped CRC byte.
func buildWireCorrupt(meta *corpusMeta) []fileEntry {
	var files []fileEntry

	// (a) truncated-tail.wandb: valid stream whose last record is cut
	// mid-payload.
	{
		b := newWandbBuilder()
		b.write(runRecord("wiretrnc", "wire-truncated-run", "", nil, nil))
		for s := range 3 {
			b.write(historyRecord(s, []kv{
				{"wire/metric", fmtF(1.0 + float64(s))},
			}))
		}
		// A final record with a fatter payload so the cut lands cleanly
		// inside it.
		b.write(historyRecord(3, []kv{
			{"wire/metric", "4"},
			{"wire/note", `"this record is deliberately cut mid-payload"`},
		}))
		full := b.bytes()
		b.assertSingleBlock(full)

		n := b.recordCount()
		lastOff := b.chunkOffset(n - 1)
		lastLen := b.payloadLens[n-1]
		cut := lastOff + chunkHeaderLen + lastLen/2
		data := full[:cut]

		offsets := make([]int, n)
		for i := range n {
			offsets[i] = b.chunkOffset(i)
		}
		meta.wire = append(meta.wire, wireFileMeta{
			Name:         "wire/truncated-tail.wandb",
			Records:      n,
			Readable:     n - 1,
			FullLen:      len(full),
			FinalLen:     len(data),
			ChunkOffsets: offsets,
			PayloadLens:  append([]int(nil), b.payloadLens...),
			FlipOffset:   -1,
			CutOffset:    cut,
			CorruptNote: fmt.Sprintf(
				"valid %d-byte stream truncated to %d bytes: record #%d's "+
					"chunk starts at offset %d with a %d-byte payload, and the "+
					"file ends %d bytes into that payload",
				len(full), cut, n-1, lastOff, lastLen,
				cut-lastOff-chunkHeaderLen),
		})
		meta.recordCounts["wire/truncated-tail.wandb"] = n
		files = append(files, fileEntry{
			Path: "wire/truncated-tail.wandb",
			Data: data,
		})
	}

	// (b) bad-crc.wandb: one record's checksum byte-flipped.
	{
		const corruptIdx = 2 // 0-based record index whose CRC is flipped

		b := newWandbBuilder()
		b.write(runRecord("wirebcrc", "wire-bad-crc-run", "", nil, nil))
		for s := range 4 {
			b.write(historyRecord(s, []kv{
				{"wire/metric", fmtF(10.0 + float64(s))},
			}))
		}
		b.write(exitRecord(0, 4))
		data := b.bytes()
		b.assertSingleBlock(data)

		n := b.recordCount()
		flip := b.chunkOffset(corruptIdx) // first byte of the 4-byte CRC (LE)
		data = append([]byte(nil), data...)
		data[flip] ^= 0xFF

		offsets := make([]int, n)
		for i := range n {
			offsets[i] = b.chunkOffset(i)
		}
		meta.wire = append(meta.wire, wireFileMeta{
			Name:         "wire/bad-crc.wandb",
			Records:      n,
			Readable:     corruptIdx,
			FullLen:      len(data),
			FinalLen:     len(data),
			ChunkOffsets: offsets,
			PayloadLens:  append([]int(nil), b.payloadLens...),
			FlipOffset:   flip,
			CutOffset:    -1,
			CorruptNote: fmt.Sprintf(
				"byte at offset %d (first CRC byte of record #%d's chunk) "+
					"XORed with 0xFF; records #0-#%d read fine, record #%d "+
					"fails its checksum, and LevelDB recovery skips to the "+
					"next 32KiB block, so the remaining %d records in this "+
					"single-block file are unrecoverable",
				flip, corruptIdx, corruptIdx-1, corruptIdx, n-corruptIdx-1),
		})
		meta.recordCounts["wire/bad-crc.wandb"] = n
		files = append(files, fileEntry{
			Path: "wire/bad-crc.wandb",
			Data: data,
		})
	}

	return files
}
