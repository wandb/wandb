package leet

import (
	"cmp"
	"errors"
	"io"
	"math"
	"os"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// runTailBytes is how far from the end of a large log a tail starts
	// reading. What came before only feeds the sparkline and the rate.
	runTailBytes = 4 << 20

	// runTailBlock is the LevelDB block size the log is written in; a read
	// can start at any block boundary.
	runTailBlock = 32 << 10

	// runTailBudget bounds the time one sampling pass spends reading one run.
	runTailBudget = 40 * time.Millisecond

	// runTailValues is how many latest metric values a run keeps for its
	// sparkline.
	runTailValues = 40

	// runTailRateWindow is the span of history rows the step rate covers.
	runTailRateWindow = time.Minute
)

// SymonRun is a live run together with what its transaction log says about
// it so far.
type SymonRun struct {
	monitor.LiveRun

	Name    string
	Project string

	// Step is the latest history step, or -1 before any history.
	Step int64

	// StepRate is the number of steps logged per second over the last
	// minute of history.
	StepRate float64

	// Metric is the charted metric and Values its latest values, oldest
	// first. A loss-like metric wins as soon as one is logged, else the
	// first metric by name.
	Metric string
	Values []float64

	Finished bool
}

type stepAt struct {
	at   time.Time
	step int64
}

// runTail follows one run's transaction log across sampling passes.
type runTail struct {
	store *LiveStore
	run   SymonRun
	steps []stepAt
}

// runTails keeps a tail per live run. The sampler updates it from a
// command goroutine while Cleanup may close it from the main one.
type runTails struct {
	mu     sync.Mutex
	tails  map[string]*runTail
	logger *observability.CoreLogger
}

func newRunTails(logger *observability.CoreLogger) *runTails {
	return &runTails{tails: make(map[string]*runTail), logger: logger}
}

// update tails the given runs and drops the tails of runs no longer live.
func (t *runTails) update(runs []monitor.LiveRun) []SymonRun {
	t.mu.Lock()
	defer t.mu.Unlock()

	seen := make(map[string]bool, len(runs))
	out := make([]SymonRun, 0, len(runs))
	for _, run := range runs {
		seen[run.Path] = true
		tail, ok := t.tails[run.Path]
		if !ok {
			tail = openRunTail(run.Path, t.logger)
			t.tails[run.Path] = tail
		}
		tail.read(runTailBudget)
		info := tail.run
		info.LiveRun = run
		out = append(out, info)
	}
	for path, tail := range t.tails {
		if !seen[path] {
			tail.close()
			delete(t.tails, path)
		}
	}
	return out
}

func (t *runTails) close() {
	t.mu.Lock()
	defer t.mu.Unlock()

	for path, tail := range t.tails {
		tail.close()
		delete(t.tails, path)
	}
}

// openRunTail opens a run's log, reads its head for the run record and,
// for a large log, skips to the last blocks so the tail catches up quickly.
func openRunTail(path string, logger *observability.CoreLogger) *runTail {
	tail := &runTail{run: SymonRun{Step: -1}}
	store, err := NewLiveStore(path, logger)
	if err != nil {
		return tail
	}
	tail.store = store

	for i := 0; i < 64 && tail.run.Name == ""; i++ {
		record, _, err := store.ReadWithOffset()
		if errors.Is(err, io.EOF) {
			return tail
		}
		if err == nil {
			tail.apply(record)
		}
	}

	if info, err := os.Stat(path); err == nil && info.Size() > runTailBytes {
		offset := (info.Size() - runTailBytes) &^ (runTailBlock - 1)
		if record, err := store.ReadAt(offset); err == nil {
			tail.apply(record)
		}
	}
	return tail
}

// read applies the records written since the last pass, for at most
// budget, skipping corrupt data.
func (t *runTail) read(budget time.Duration) {
	if t.store == nil {
		return
	}
	deadline := time.Now().Add(budget)
	for time.Now().Before(deadline) {
		record, _, err := t.store.ReadWithOffset()
		switch {
		case errors.Is(err, io.EOF), errors.Is(err, errLiveStoreClosed):
			// Caught up. A run that stopped logging a while ago has no rate.
			if n := len(t.steps); n > 0 && time.Since(t.steps[n-1].at) > runTailRateWindow {
				t.run.StepRate = 0
			}
			return
		case err != nil:
			continue
		}
		t.apply(record)
	}
}

func (t *runTail) close() {
	if t.store != nil {
		t.store.Close()
	}
}

func (t *runTail) apply(record *spb.Record) {
	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		t.run.Name = cmp.Or(rec.Run.GetDisplayName(), rec.Run.GetRunId())
		t.run.Project = rec.Run.GetProject()
	case *spb.Record_History:
		t.applyHistory(rec.History)
	case *spb.Record_Exit:
		t.run.Finished = true
	}
}

func (t *runTail) applyHistory(history *spb.HistoryRecord) {
	values := make(map[string]float64, len(history.GetItem()))
	for _, item := range history.GetItem() {
		v, err := strconv.ParseFloat(trimJSONString(item.GetValueJson()), 64)
		if err == nil && !math.IsInf(v, 0) && !math.IsNaN(v) {
			values[historyItemKey(item)] = v
		}
	}

	if step, ok := historyStep(history); ok {
		t.run.Step = max(t.run.Step, step)
		at := time.Now()
		if ts, ok := values["_timestamp"]; ok {
			at = time.Unix(0, int64(ts*float64(time.Second)))
		}
		t.steps = append(t.steps, stepAt{at: at, step: step})
		for len(t.steps) > 2 && at.Sub(t.steps[0].at) > runTailRateWindow {
			t.steps = t.steps[1:]
		}
		if first, last := t.steps[0], t.steps[len(t.steps)-1]; last.at.After(first.at) {
			t.run.StepRate = float64(last.step-first.step) / last.at.Sub(first.at).Seconds()
		}
	}

	if metric := pickRunMetric(t.run.Metric, values); metric != t.run.Metric {
		t.run.Metric, t.run.Values = metric, nil
	}
	if v, ok := values[t.run.Metric]; ok {
		t.run.Values = append(t.run.Values, v)
		if len(t.run.Values) > runTailValues {
			t.run.Values = t.run.Values[len(t.run.Values)-runTailValues:]
		}
	}
}

// pickRunMetric chooses the metric to follow: current once it is
// loss-like, else the first loss-like key in values, else current, else
// the first key by name. Internal keys are skipped.
func pickRunMetric(current string, values map[string]float64) string {
	if isLossLike(current) {
		return current
	}
	var keys []string
	for key := range values {
		if !strings.HasPrefix(key, "_") {
			keys = append(keys, key)
		}
	}
	slices.Sort(keys)
	for _, key := range keys {
		if isLossLike(key) {
			return key
		}
	}
	if current == "" && len(keys) > 0 {
		return keys[0]
	}
	return current
}

func isLossLike(key string) bool {
	return strings.Contains(strings.ToLower(key), "loss")
}
