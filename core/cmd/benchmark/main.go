package main

import (
	"flag"
	"fmt"
	"runtime"
	"sync"

	"github.com/wandb/wandb/core/pkg/gowandb"
	"github.com/wandb/wandb/core/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/core/pkg/gowandb/opts/sessionopts"
	"github.com/wandb/wandb/core/pkg/gowandb/settings"
)

type BenchOpts struct {
	host               *string
	port               *int
	numHistory         *int
	numHistoryElements *int
	teardown           *bool
	offline            *bool
	numCPUs            *int
	numWorkers         *int
	useStreamTable     *bool
	streamTablePath    *string
}

type Bench struct {
	opts  BenchOpts
	wandb *gowandb.Session
}

func NewBench(benchOpts BenchOpts) *Bench {
	return &Bench{opts: benchOpts}
}

func (b *Bench) Setup() {
	opts := []sessionopts.SessionOption{}
	if *b.opts.port != 0 {
		opts = append(opts, sessionopts.WithCoreAddress(fmt.Sprintf("%s:%d", *b.opts.host, *b.opts.port)))
	}
	if *b.opts.offline {
		baseSettings := settings.NewSettings()
		baseSettings.XOffline.Value = true
		opts = append(opts, sessionopts.WithSettings(baseSettings))
	}
	var err error
	b.wandb, err = gowandb.NewSession(opts...)
	if err != nil {
		panic(err)
	}
}

func (b *Bench) RunWorkers() {
	if *b.opts.numCPUs != 0 {
		runtime.GOMAXPROCS(*b.opts.numCPUs)
	}
	var wg sync.WaitGroup
	for i := 0; i < *b.opts.numWorkers; i++ {
		wg.Add(1)
		go func() {
			if *b.opts.useStreamTable {
				b.StreamWorker()
			} else {
				b.RunWorker()
			}
			wg.Done()
		}()
	}
	wg.Wait()
}

func (b *Bench) RunWorker() {
	run, err := b.wandb.NewRun()
	if err != nil {
		panic(err)
	}

	data := make(gowandb.History)
	for i := 0; i < *b.opts.numHistoryElements; i++ {
		data[fmt.Sprintf("loss_%d", i)] = float64(100 + i)
	}

	for i := 0; i < *b.opts.numHistory; i++ {
		run.Log(data)
	}
	run.Finish()
}

func (b *Bench) StreamWorker() {
	stream, err := b.wandb.NewStream(runopts.WithPath(*b.opts.streamTablePath))
	if err != nil {
		panic(err)
	}

	data := make(gowandb.History)
	for i := 0; i < *b.opts.numHistoryElements; i++ {
		data[fmt.Sprintf("loss_%d", i)] = float64(100 + i)
	}

	for i := 0; i < *b.opts.numHistory; i++ {
		stream.Log(data)
	}
	stream.Finish()
}

func (b *Bench) Close() {
	if *b.opts.teardown {
		b.wandb.Close()
	}
}

func main() {
	benchOpts := BenchOpts{
		host:               flag.String("host", "localhost", "host to connect to"),
		port:               flag.Int("port", 0, "port to connect to"),
		numHistory:         flag.Int("numHistory", 1000, "number of history records to log"),
		numHistoryElements: flag.Int("numHistoryElements", 5, "number of elements in a history record"),
		teardown:           flag.Bool("close", false, "flag to close the server"),
		offline:            flag.Bool("offline", false, "use offline mode"),
		numCPUs:            flag.Int("numCPUs", 0, "number of cpus"),
		numWorkers:         flag.Int("numWorkers", 1, "number of parallel workers"),
		useStreamTable:     flag.Bool("useStreamTable", false, "create stream table runs"),
		streamTablePath:    flag.String("streamTablePath", "user/proj/table", "table to use"),
	}
	flag.Parse()

	b := NewBench(benchOpts)
	b.Setup()
	b.RunWorkers()
	b.Close()
}
