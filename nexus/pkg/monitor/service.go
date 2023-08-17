package monitor

import (
	"fmt"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
	"io"
	"log/slog"
	"net/http"
	"time"
)

type SystemMonitorService struct {
	SystemMonitor *SystemMonitor
	LatestSample  *service.Record
}

func NewSystemMonitorService() *SystemMonitorService {
	settings := &service.Settings{
		XDisableStats:           &wrapperspb.BoolValue{Value: false},
		XStatsSampleRateSeconds: &wrapperspb.DoubleValue{Value: 1},
		XStatsSamplesToAverage:  &wrapperspb.Int32Value{Value: 1},
	}

	logger := observability.NewNexusLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		nil,
	)

	return &SystemMonitorService{
		SystemMonitor: NewSystemMonitor(settings, logger),
		LatestSample:  &service.Record{},
	}
}

func (smm *SystemMonitorService) Start() {
	// Start the system monitor
	smm.SystemMonitor.Do()

	go func() {
		for sample := range smm.SystemMonitor.OutChan {
			fmt.Println(sample)
			smm.LatestSample = sample
		}
	}()

	// Register a function for the root path
	http.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		// Set the response header content type to be plain text
		w.Header().Set("Content-Type", "text/plain")

		// Write the response body
		fmt.Fprint(w, smm.LatestSample)
	})

	server := &http.Server{
		Addr:           ":1337",
		Handler:        nil, // Use default ServeMux
		ReadTimeout:    10 * time.Second,
		WriteTimeout:   10 * time.Second,
		MaxHeaderBytes: 1 << 20, // 1 MB
	}

	// Listen to the address and port using the custom configuration
	err := server.ListenAndServe()

	// If there is an error, log it and exit the application
	if err != nil {
		fmt.Println("Error starting server:", err)
		return
	}
}
