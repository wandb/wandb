package main

import (
	"flag"
	"fmt"
	"strings"

	"github.com/wandb/wandb/nexus/pkg/gowandb"
	"github.com/wandb/wandb/nexus/pkg/cli"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/runopts"
	"github.com/wandb/wandb/nexus/pkg/gowandb/opts/sessionopts"
	"github.com/wandb/wandb/nexus/pkg/gowandb/settings"
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

func (b *Bench) Run() {
	stream, err := b.wandb.NewStream(runopts.WithPath(*b.opts.streamTablePath))
	if err != nil {
		panic(err)
	}

	cli.ReadFromInput(stream)

	/*
	for i := 0; i < *b.opts.numHistory; i++ {
		stream.Log(data)
	}
	*/
	stream.Finish()
	paths := strings.SplitN(*b.opts.streamTablePath, "/", 3)
	paths = append(paths[:2], "table", paths[2])
	join := strings.Join(paths[:], "/")
	fmt.Printf("https://weave.wandb.ai/browse/wandb/%+v\n", join)
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
		streamTablePath:    flag.String("streamTablePath", "user/proj/table", "table to use"),
	}
	flag.Parse()

	b := NewBench(benchOpts)
	b.Setup()
	b.Run()
	b.Close()
}
