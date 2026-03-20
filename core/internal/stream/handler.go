package stream

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"golang.org/x/time/rate"
	"google.golang.org/protobuf/proto"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/fileutil"
	"github.com/wandb/wandb/core/internal/gitops"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runmetric"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/timer"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/wboperation"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	MetaFileName         = "wandb-metadata.json"
	SummaryFileName      = "wandb-summary.json"
	DiffFileName         = "diff.patch"
	RequirementsFileName = "requirements.txt"
	ConfigFileName       = "config.yaml"
)

var handlerProviders = wire.NewSet(
	wire.Struct(new(HandlerFactory), "*"),
)

type GitCommitHash string

type HandlerFactory struct {
	// Commit is the W&B Git commit hash
	Commit               GitCommitHash
	FileTransferStats    filetransfer.FileTransferStats
	Logger               *observability.CoreLogger
	Mailbox              *mailbox.Mailbox
	Operations           *wboperation.WandbOperations
	Settings             *settings.Settings
	SystemMonitorFactory *monitor.SystemMonitorFactory
	TerminalPrinter      *observability.Printer
}

// Handler performs non-blocking operations to preprocess incoming Work.
type Handler struct {
	// commit is the W&B Git commit hash
	commit GitCommitHash

	// fileTransferStats reports file upload/download statistics
	fileTransferStats filetransfer.FileTransferStats

	// fwdChan is the channel for forwarding messages to the next component
	fwdChan chan runwork.Work

	// logger is the logger for the handler
	logger *observability.CoreLogger

	mailbox *mailbox.Mailbox

	// metricHandler is the metric handler for the stream
	metricHandler *runmetric.MetricHandler

	// operations tracks the status of the run's uploads
	operations *wboperation.WandbOperations

	// partialHistory is a set of run metrics accumulated for the current step.
	partialHistory *runhistory.RunHistory

	// partialHistoryStep is the next history "step" to emit
	// when not running in shared mode.
	partialHistoryStep int64

	// pollExitLogRateLimit limits log messages when handling PollExit requests
	pollExitLogRateLimit *rate.Limiter

	// runHistorySampler tracks samples of all metrics in the run's history.
	//
	// This is used to display the sparkline in the terminal at the end of
	// the run.
	runHistorySampler *runhistory.RunHistorySampler

	// runRecord is the runRecord record received from the server
	runRecord *spb.RunRecord

	// runSummary contains summaries of the run's metrics.
	//
	// These summaries are up-to-date with respect to the current request being
	// handled which is crucial for serving the GetSummaryRequest. The Sender
	// also tracks summaries, but with respect to its own queue of requests,
	// which may be arbitrarily far behind the Handler.
	runSummary *runsummary.RunSummary

	// runTimer is used to track the run start and execution times
	runTimer *timer.Timer

	// settings is the settings for the handler
	settings *settings.Settings

	// systemMonitor is the system monitor for the stream
	systemMonitor *monitor.SystemMonitor

	// terminalPrinter gathers terminal messages to send back to the user process
	terminalPrinter *observability.Printer
}

// New returns a new Handler.
func (f *HandlerFactory) New(extraWork runwork.ExtraWork) *Handler {
	var systemMonitor *monitor.SystemMonitor
	if f.SystemMonitorFactory != nil { // nil in tests only
		systemMonitor = f.SystemMonitorFactory.New(extraWork)
	}

	return &Handler{
		commit:               f.Commit,
		fileTransferStats:    f.FileTransferStats,
		fwdChan:              make(chan runwork.Work, BufferSize),
		logger:               f.Logger,
		mailbox:              f.Mailbox,
		metricHandler:        runmetric.New(),
		operations:           f.Operations,
		pollExitLogRateLimit: rate.NewLimiter(rate.Every(time.Minute), 1),
		runHistorySampler:    runhistory.NewRunHistorySampler(),
		runSummary:           runsummary.New(),
		runTimer:             timer.New(0),
		settings:             f.Settings,
		systemMonitor:        systemMonitor,
		terminalPrinter:      f.TerminalPrinter,
	}
}

// OutChan contains work to pass to the next stream component.
func (h *Handler) OutChan() <-chan runwork.Work {
	return h.fwdChan
}

// Do processes all work on the input channel.
//
//gocyclo:ignore
func (h *Handler) Do(allWork <-chan runwork.Work) {
	defer h.logger.Reraise()
	h.logger.Info("handler: started")
	for work := range allWork {
		h.logger.Debug("handler: got work", "work", work)

		if work.Accept(h.handleRecord) {
			h.fwdWork(work)
		}
	}
	h.Close()
}

func (h *Handler) Close() {
	h.logger.Info("handler: closed")
	close(h.fwdChan)
}

// respond sends a response to the client.
func (h *Handler) respond(request *runwork.Request, response *spb.Response) {
	request.Respond(&spb.ServerResponse{
		ServerResponseType: &spb.ServerResponse_ResultCommunicate{
			ResultCommunicate: &spb.Result{
				ResultType: &spb.Result_Response{
					Response: response,
				},
			},
		},
	})
}

// fwdWork passes work to the Writer and Sender.
func (h *Handler) fwdWork(work runwork.Work) {
	h.fwdChan <- work
}

// fwdRecord forwards a record to the next component
func (h *Handler) fwdRecord(record *spb.Record, request *runwork.Request) {
	if record == nil {
		return
	}

	h.fwdWork(runwork.Work{
		WorkImpl: runwork.WorkFromRecord(record),
		Request:  request,
	})
}

//gocyclo:ignore
func (h *Handler) handleRecord(record *spb.Record, request *runwork.Request) {
	switch x := record.RecordType.(type) {
	case *spb.Record_Final:
	case *spb.Record_Footer:
	case *spb.Record_NoopLinkArtifact:
		// The above have been deleted but are kept here to avoid
		// the panic in the default case.

	case *spb.Record_Alert:
	case *spb.Record_Artifact:
	case *spb.Record_Config:
	case *spb.Record_Files:
	case *spb.Record_History:
	case *spb.Record_Output:
	case *spb.Record_OutputRaw:
	case *spb.Record_Preempting:
	case *spb.Record_Stats:
	case *spb.Record_Telemetry:
	case *spb.Record_UseArtifact:
	case *spb.Record_Environment:
	// The above are no-ops in the handler.

	case *spb.Record_Exit:
		h.handleExit(record, x.Exit, request)
	case *spb.Record_Header:
		h.handleHeader(record)
	case *spb.Record_Metric:
		h.handleMetric(record)
	case *spb.Record_Request:
		h.handleRequest(record, request)
	case *spb.Record_Summary:
		h.handleSummary(x.Summary)
	case nil:
		h.logger.CaptureFatalAndPanic(
			errors.New("handler: handleRecord: record type is nil"))
	default:
		h.logger.CaptureFatalAndPanic(
			fmt.Errorf("handler: handleRecord: unknown record type %T", x))
	}
}

//gocyclo:ignore
func (h *Handler) handleRequest(
	record *spb.Record,
	request *runwork.Request,
) {
	requestRecord := record.GetRequest()
	switch x := requestRecord.RequestType.(type) {

	case *spb.Request_SummaryRecord:
	case *spb.Request_TelemetryRecord:
		// TODO: Do we need to implement the above?

	case *spb.Request_Keepalive:
	case *spb.Request_TestInject:
	case *spb.Request_JobInfo:
		// not implemented in the old handler

	case *spb.Request_ServerInfo:
	case *spb.Request_CheckVersion:
	case *spb.Request_Defer:
		// The above been removed from the client but are kept here for now.
		// Should be removed in the future.

	case *spb.Request_RunStatus:
		h.handleRequestRunStatus(record, request)
	case *spb.Request_Status:
		h.handleRequestStatus(record, request)
	case *spb.Request_SenderMark:
		h.handleRequestSenderMark(record)
	case *spb.Request_StatusReport:
		h.handleRequestStatusReport(record)
	case *spb.Request_Shutdown:
		h.handleRequestShutdown(record, request)
	case *spb.Request_GetSummary:
		h.handleRequestGetSummary(record, request)
	case *spb.Request_NetworkStatus:
		h.handleRequestNetworkStatus(record, request)
	case *spb.Request_PartialHistory:
		h.handleRequestPartialHistory(record, x.PartialHistory)
	case *spb.Request_PollExit:
		h.handleRequestPollExit(record, request)
	case *spb.Request_RunStart:
		h.handleRequestRunStart(record, x.RunStart, request)
	case *spb.Request_SampledHistory:
		h.handleRequestSampledHistory(record, request)
	case *spb.Request_PythonPackages:
		h.handleRequestPythonPackages(record, x.PythonPackages)
	case *spb.Request_StopStatus:
		h.handleRequestStopStatus(record, request)
	case *spb.Request_LogArtifact:
		h.handleRequestLogArtifact(record, request)
	case *spb.Request_LinkArtifact:
		h.handleRequestLinkArtifact(record, request)
	case *spb.Request_DownloadArtifact:
		h.handleRequestDownloadArtifact(record, request)
	case *spb.Request_Attach:
		h.handleRequestAttach(record, request)
	case *spb.Request_Pause:
		h.handleRequestPause()
	case *spb.Request_Resume:
		h.handleRequestResume()
	case *spb.Request_Cancel:
		h.handleRequestCancel(x.Cancel)
	case *spb.Request_GetSystemMetrics:
		h.handleRequestGetSystemMetrics(record, request)
	case *spb.Request_InternalMessages:
		h.handleRequestInternalMessages(record, request)
	case *spb.Request_SyncFinish:
		h.handleRequestSyncFinish(record, request)
	case *spb.Request_SenderRead:
		// TODO: implement this
	case *spb.Request_JobInput:
		h.handleRequestJobInput(record, request)
	case *spb.Request_RunFinishWithoutExit:
		h.handleRequestRunFinishWithoutExit(record, request)
	case *spb.Request_Operations:
		h.handleRequestOperations(record, request)
	case *spb.Request_ProbeSystemInfo:
		h.handleRequestProbeSystemInfo(record)
	case nil:
		h.logger.CaptureFatalAndPanic(
			errors.New("handler: handleRequest: request type is nil"))
	default:
		h.logger.CaptureFatalAndPanic(
			fmt.Errorf("handler: handleRequest: unknown request type %T", x))
	}
}

// TODO: remove
func (h *Handler) handleRequestRunStatus(
	record *spb.Record,
	request *runwork.Request,
) {
	h.respond(request, &spb.Response{})
}

// TODO: remove
func (h *Handler) handleRequestStatus(
	record *spb.Record,
	request *runwork.Request,
) {
	h.respond(request, &spb.Response{})
}

// TODO: remove
func (h *Handler) handleRequestSenderMark(_ *spb.Record) {
	// TODO(flow-control): implement sender mark
}

// TODO: remove
func (h *Handler) handleRequestStatusReport(_ *spb.Record) {
	// TODO(flow-control): implement status report
}

// TODO: remove
func (h *Handler) handleRequestShutdown(
	record *spb.Record,
	request *runwork.Request,
) {
	h.respond(request, &spb.Response{})
}

func (h *Handler) handleMetric(record *spb.Record) {
	metric := record.GetMetric()
	if metric == nil {
		h.logger.CaptureError(
			errors.New("handler: bad record type for handleMetric"))
		return
	}

	if err := h.metricHandler.ProcessRecord(metric); err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: cannot add metric: %v", err),
			"metric", metric)
		return
	}

	if metric.Name != "" {
		// TODO: Add !h.settings.IsEnableServerSideDerivedSummary() to the condition
		// once we support server-side derived summary aggregation (min, max, mean, etc.)
		h.metricHandler.UpdateSummary(metric.Name, h.runSummary)
	}
}

func (h *Handler) handleRequestStopStatus(
	record *spb.Record,
	request *runwork.Request,
) {
	if h.settings.IsOffline() {
		// Send an empty response if we're offline.
		h.respond(request, &spb.Response{})
	} else {
		h.fwdRecord(record, request)
	}
}

func (h *Handler) handleRequestLogArtifact(
	record *spb.Record,
	request *runwork.Request,
) {
	h.fwdRecord(record, request)
}

func (h *Handler) handleRequestDownloadArtifact(
	record *spb.Record,
	request *runwork.Request,
) {
	h.fwdRecord(record, request)
}

func (h *Handler) handleRequestLinkArtifact(
	record *spb.Record,
	request *runwork.Request,
) {
	h.fwdRecord(record, request)
}

func (h *Handler) handleRequestOperations(
	record *spb.Record,
	request *runwork.Request,
) {
	h.respond(request, &spb.Response{
		ResponseType: &spb.Response_OperationsResponse{
			OperationsResponse: &spb.OperationStatsResponse{
				OperationStats: h.operations.ToProto(),
			},
		},
	})
}

func (h *Handler) handleRequestPollExit(
	record *spb.Record,
	request *runwork.Request,
) {
	pollExitResponse := &spb.PollExitResponse{
		OperationStats: h.operations.ToProto(),
	}

	if h.pollExitLogRateLimit.Allow() {
		// Log these for now while we don't display them.
		h.logger.Info(
			"handler: operation stats",
			"stats", pollExitResponse.OperationStats,
		)
	}

	if h.fileTransferStats != nil {
		pollExitResponse.PusherStats = h.fileTransferStats.GetFilesStats()
		pollExitResponse.FileCounts = h.fileTransferStats.GetFileCounts()
		pollExitResponse.Done = h.fileTransferStats.IsDone()
	} else {
		pollExitResponse.Done = true
	}

	h.respond(request, &spb.Response{
		ResponseType: &spb.Response_PollExitResponse{
			PollExitResponse: pollExitResponse,
		},
	})
}

func (h *Handler) handleHeader(record *spb.Record) {
	// populate with version info
	versionString := fmt.Sprintf("%s+%s", version.Version, h.commit)
	record.GetHeader().VersionInfo = &spb.VersionInfo{
		Producer:    versionString,
		MinConsumer: version.MinServerVersion,
	}
	h.fwdRecord(record, nil)
}

func (h *Handler) handleRequestRunStart(
	record *spb.Record,
	req *spb.RunStartRequest,
	request *runwork.Request,
) {
	var ok bool
	run := req.Run

	// Add on to the previous run time for branched runs.
	offset := time.Duration(run.Runtime) * time.Second
	h.runTimer = timer.New(offset)

	// start the timer
	h.runTimer.Start()

	if h.runRecord, ok = proto.Clone(run).(*spb.RunRecord); !ok {
		h.logger.CaptureFatalAndPanic(
			errors.New("handleRunStart: failed to clone run"))
	}
	h.fwdRecord(record, request)

	// TODO: Move computation of git state to wandb-core.
	var git *spb.GitRepoRecord
	if run.GetGit().GetRemoteUrl() != "" || run.GetGit().GetCommit() != "" {
		git = &spb.GitRepoRecord{
			RemoteUrl: run.GetGit().GetRemoteUrl(),
			Commit:    run.GetGit().GetCommit(),
		}
	}

	// start the system monitor
	h.systemMonitor.Start(git)

	// save code and patch
	if h.settings.IsSaveCode() && !h.settings.IsDisableMachineInfo() {
		h.handleCodeSave()
		h.handlePatchSave()
	}

	h.respond(request, &spb.Response{})
}

func (h *Handler) handleRequestProbeSystemInfo(record *spb.Record) {
	h.systemMonitor.Probe()
}

func (h *Handler) handleRequestPythonPackages(
	_ *spb.Record,
	request *spb.PythonPackagesRequest,
) {
	if !h.settings.IsPrimary() {
		return
	}
	// write all requirements to a file
	// send the file as a Files record
	filename := filepath.Join(h.settings.GetFilesDir(), RequirementsFileName)
	file, err := os.Create(filename)
	if err != nil {
		h.logger.Error("error creating requirements file", "error", err)
		return
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			h.logger.Error("error closing requirements file", "error", err)
		}
	}(file)

	for _, pkg := range request.Package {
		line := fmt.Sprintf("%s==%s\n", pkg.Name, pkg.Version)
		_, err := file.WriteString(line)
		if err != nil {
			h.logger.Error("error writing requirements file", "error", err)
			return
		}
	}
	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: []*spb.FilesItem{
					{
						Path: RequirementsFileName,
						Type: spb.FilesItem_WANDB,
					},
				},
			},
		},
	}
	h.fwdRecord(record, nil)
}

func (h *Handler) handleCodeSave() {
	if !h.settings.IsPrimary() {
		return
	}

	programRelative := h.settings.GetProgramRelativePath()
	if programRelative == "" {
		h.logger.Warn("handleCodeSave: program relative path is empty")
		return
	}

	programAbsolute := h.settings.GetProgramAbsolutePath()
	if _, err := os.Stat(programAbsolute); err != nil {
		h.logger.Warn(
			"handleCodeSave: program absolute path does not exist",
			"path", programAbsolute,
		)
		return
	}

	codeDir := filepath.Join(h.settings.GetFilesDir(), "code")
	programPath := filepath.Join(codeDir, filepath.Dir(programRelative))
	if err := os.MkdirAll(programPath, os.ModePerm); err != nil {
		return
	}
	savedProgram := filepath.Join(codeDir, programRelative)
	if _, err := os.Stat(savedProgram); err != nil {
		if err = fileutil.CopyFile(programAbsolute, savedProgram); err != nil {
			return
		}
	}
	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: []*spb.FilesItem{
					{
						Path: filepath.Join("code", programRelative),
						Type: spb.FilesItem_WANDB,
					},
				},
			},
		},
	}
	h.fwdRecord(record, nil)
}

func (h *Handler) handlePatchSave() {
	// capture git state
	if h.settings.IsDisableGit() || h.settings.IsDisableMachineInfo() || !h.settings.IsPrimary() {
		return
	}

	git := gitops.New(h.settings.GetRootDir(), h.logger)
	if !git.IsAvailable() {
		return
	}

	var files []*spb.FilesItem

	filesDirPath := h.settings.GetFilesDir()
	file := filepath.Join(filesDirPath, DiffFileName)
	if err := git.SavePatch("HEAD", file); err != nil {
		h.logger.Error("error generating diff", "error", err)
	} else {
		files = append(files, &spb.FilesItem{Path: DiffFileName, Type: spb.FilesItem_WANDB})
	}

	if output, err := git.LatestCommit("@{u}"); err != nil {
		h.logger.Error("error getting latest commit", "error", err)
	} else {
		diffFileName := fmt.Sprintf("diff_%s.patch", output)
		file = filepath.Join(filesDirPath, diffFileName)
		if err := git.SavePatch("@{u}", file); err != nil {
			h.logger.Error("error generating diff", "error", err)
		} else {
			files = append(files, &spb.FilesItem{Path: diffFileName, Type: spb.FilesItem_WANDB})
		}
	}

	if len(files) == 0 {
		return
	}

	record := &spb.Record{
		RecordType: &spb.Record_Files{
			Files: &spb.FilesRecord{
				Files: files,
			},
		},
	}
	h.fwdRecord(record, nil)
}

func (h *Handler) handleRequestAttach(
	record *spb.Record,
	request *runwork.Request,
) {
	h.respond(request, &spb.Response{
		ResponseType: &spb.Response_AttachResponse{
			AttachResponse: &spb.AttachResponse{
				Run: h.runRecord,
			},
		},
	})
}

func (h *Handler) handleRequestCancel(request *spb.CancelRequest) {
	// TODO(flow-control): implement cancel
	cancelSlot := request.GetCancelSlot()
	if cancelSlot != "" {
		h.mailbox.Cancel(cancelSlot)
	}
}

func (h *Handler) handleRequestPause() {
	h.runTimer.Stop()
	h.systemMonitor.Pause()
}

func (h *Handler) handleRequestResume() {
	h.runTimer.Start()
	h.systemMonitor.Resume()
}

func (h *Handler) handleRequestRunFinishWithoutExit(
	record *spb.Record,
	request *runwork.Request,
) {
	h.runTimer.Stop()
	h.updateRunTiming()
	h.systemMonitor.Finish()
	h.flushPartialHistory(true, h.partialHistoryStep+1)
	h.fwdRecord(record, request)
}

func (h *Handler) handleExit(
	record *spb.Record,
	exit *spb.RunExitRecord,
	request *runwork.Request,
) {
	// stop the run timer and set the runtime
	h.runTimer.Stop()
	exit.Runtime = int32(h.runTimer.Elapsed().Seconds())

	if !h.settings.IsEnableServerSideDerivedSummary() {
		h.updateRunTiming()
	}

	// Stop generating system statistics events.
	h.systemMonitor.Finish()

	// Flush any history data---any further history records must
	// be configured to flush.
	if h.settings.IsSharedMode() {
		h.flushPartialHistory(false, 0)
	} else {
		h.flushPartialHistory(true, h.partialHistoryStep+1)
	}

	if record.Control == nil {
		record.Control = &spb.Control{}
	}
	record.Control.AlwaysSend = true

	h.fwdRecord(record, request)
}

func (h *Handler) handleRequestGetSummary(
	record *spb.Record,
	request *runwork.Request,
) {
	response := &spb.Response{}

	items, err := h.runSummary.ToRecords()

	// If there's an error, we still respond with the records we were
	// able to produce.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error flattening run summary: %v", err))
	}

	response.ResponseType = &spb.Response_GetSummaryResponse{
		GetSummaryResponse: &spb.GetSummaryResponse{
			Item: items,
		},
	}
	h.respond(request, response)
}

func (h *Handler) handleRequestGetSystemMetrics(
	record *spb.Record,
	request *runwork.Request,
) {
	sm := h.systemMonitor.GetBuffer()

	response := &spb.Response{}

	response.ResponseType = &spb.Response_GetSystemMetricsResponse{
		GetSystemMetricsResponse: &spb.GetSystemMetricsResponse{
			SystemMetrics: make(map[string]*spb.SystemMetricsBuffer),
		},
	}

	for key, samples := range sm {
		buffer := make([]*spb.SystemMetricSample, 0, len(samples))

		// convert samples to buffer:
		for _, sample := range samples {
			buffer = append(buffer, &spb.SystemMetricSample{
				Timestamp: sample.Timestamp,
				Value:     float32(sample.Value),
			})
		}
		// add to response as map key: buffer
		response.GetGetSystemMetricsResponse().SystemMetrics[key] = &spb.SystemMetricsBuffer{
			Record: buffer,
		}
	}

	h.respond(request, response)
}

func (h *Handler) handleRequestInternalMessages(
	record *spb.Record,
	request *runwork.Request,
) {
	messages := h.terminalPrinter.Read()

	// TODO: Respect message severity in the InternalMessages request.
	messageContents := make([]string, 0, len(messages))
	for _, message := range messages {
		messageContents = append(messageContents, message.Content)
	}

	response := &spb.Response{
		ResponseType: &spb.Response_InternalMessagesResponse{
			InternalMessagesResponse: &spb.InternalMessagesResponse{
				Messages: &spb.InternalMessages{
					Warning: messageContents,
				},
			},
		},
	}
	h.respond(request, response)
}

// TODO: remove
func (h *Handler) handleRequestSyncFinish(
	record *spb.Record,
	request *runwork.Request,
) {
	h.fwdRecord(record, request)
}

func (h *Handler) handleRequestJobInput(
	record *spb.Record,
	request *runwork.Request,
) {
	h.fwdRecord(record, request)
}

// handleSummary processes an update to the run summary.
//
// These records come from one of three sources:
//   - Explicit updates made by using `run.summary[...] = ...`
//   - Records from the transaction log when syncing
//   - `updateRunTiming`
func (h *Handler) handleSummary(summary *spb.SummaryRecord) {
	if err := runsummary.FromProto(summary).Apply(h.runSummary); err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error processing summary: %v", err))
	}
}

// updateRunTiming updates the `_wandb.runtime` summary metric which
// tracks the total duration of the run.
//
// This emits a summary record that is written to the transaction log.
func (h *Handler) updateRunTiming() {
	runtime := int(h.runTimer.Elapsed().Seconds())
	record := &spb.Record{
		RecordType: &spb.Record_Summary{
			Summary: &spb.SummaryRecord{
				Update: []*spb.SummaryItem{
					{
						NestedKey: []string{"_wandb", "runtime"},
						ValueJson: strconv.Itoa(runtime),
					},
					{
						Key:       "_runtime",
						ValueJson: strconv.Itoa(runtime),
					},
				},
			},
		},
	}

	h.handleSummary(record.GetSummary())
	h.fwdRecord(record, nil)
}

func (h *Handler) handleRequestNetworkStatus(
	record *spb.Record,
	request *runwork.Request,
) {
	h.fwdRecord(record, request)
}

// handleRequestPartialHistory updates the run history, flushing data for
// completed steps.
func (h *Handler) handleRequestPartialHistory(
	_ *spb.Record,
	request *spb.PartialHistoryRequest,
) {
	if h.settings.IsSharedMode() {
		h.handlePartialHistoryAsync(request)
	} else {
		h.handlePartialHistorySync(request)
	}
}

// handlePartialHistoryAsync updates the run history in shared mode.
//
// In "shared" mode, multiple processes (possibly running on different
// machines) write to the same run and the backend infers step numbers.
func (h *Handler) handlePartialHistoryAsync(request *spb.PartialHistoryRequest) {
	if h.partialHistory == nil {
		// NOTE: We ignore the step in shared mode.
		h.partialHistory = runhistory.New()
	}

	// Append the history items from the request to the current history record.
	//
	// We do this on a best-effort basis: errors are logged and problematic
	// metrics are ignored.
	for _, item := range request.GetItem() {
		err := h.partialHistory.SetFromRecord(item)

		if err != nil {
			h.logger.CaptureError(
				fmt.Errorf("handler: failed to set history metric: %v", err),
				"item", item)
		}
	}

	if request.GetAction() == nil || request.Action.GetFlush() {
		h.flushPartialHistory(false, 0)
	}
}

// handlePartialHistorySync updates the run history in non-shared mode.
//
// In this mode, we are the only process writing to this run.
// The main difference from shared mode is that we're responsible
// for setting step numbers.
func (h *Handler) handlePartialHistorySync(request *spb.PartialHistoryRequest) {
	if h.partialHistory == nil {
		h.partialHistory = runhistory.New()
		h.partialHistoryStep = h.runRecord.GetStartingStep()
	}

	if request.GetStep() != nil {
		step := request.Step.GetNum()
		current := h.partialHistoryStep
		if step > current {
			h.flushPartialHistory(true, step)
		} else if step < current {
			h.logger.Warn(
				"handler: ignoring partial history record",
				"step", step,
				"current", current,
			)

			h.terminalPrinter.Warnf(
				"Tried to log to step %d that is less than the current step %d."+
					" Steps must be monotonically increasing, so this data"+
					" will be ignored. See https://wandb.me/define-metric"+
					" to log data out of order.",
				step,
				current,
			)
			return
		}
	}

	for _, item := range request.GetItem() {
		err := h.partialHistory.SetFromRecord(item)
		if err != nil {
			h.logger.CaptureError(
				fmt.Errorf("handler: failed to set history metric: %v", err),
				"item", item)
		}
	}

	var shouldFlush bool
	if request.GetAction() != nil {
		shouldFlush = request.GetAction().GetFlush()
	} else {
		// Default to flushing if the step is not provided.
		shouldFlush = request.GetStep() == nil
	}
	if !shouldFlush {
		return
	}

	h.flushPartialHistory(true, h.partialHistoryStep+1)
}

// flushPartialHistory finalizes and resets the accumulated run history.
//
// If useStep is true, then the emitted history record has an explicit
// step, and partialHistoryStep is updated to nextStep. Otherwise,
// nextStep is ignored.
func (h *Handler) flushPartialHistory(useStep bool, nextStep int64) {
	// Don't log anything if there are no metrics.
	if h.partialHistory == nil || h.partialHistory.IsEmpty() {
		if useStep {
			h.partialHistoryStep = nextStep
		}

		return
	}

	h.partialHistory.SetFloat(
		pathtree.PathOf("_runtime"),
		h.runTimer.Elapsed().Seconds(),
	)

	if !h.settings.IsSharedMode() && useStep {
		h.partialHistory.SetInt(
			pathtree.PathOf("_step"),
			h.partialHistoryStep,
		)
	}

	newMetricDefs := h.metricHandler.UpdateMetrics(h.partialHistory)
	for _, newMetric := range newMetricDefs {
		// We don't mark the record 'Local' because partial history updates
		// are not already written to the transaction log.
		newMetric.ExpandedFromGlob = true
		rec := &spb.Record{
			RecordType: &spb.Record_Metric{Metric: newMetric},
		}
		h.handleMetric(rec)
		h.fwdRecord(rec, nil)
	}
	h.metricHandler.InsertStepMetrics(h.partialHistory)

	h.runHistorySampler.SampleNext(h.partialHistory)

	// Update the summary if server-side derived summaries are disabled.
	if !h.settings.IsEnableServerSideDerivedSummary() {
		h.updateRunTiming()
		h.updateSummary()
	}

	items, err := h.partialHistory.ToRecords()
	currentStep := h.partialHistoryStep

	h.partialHistory = runhistory.New()
	if useStep {
		h.partialHistoryStep = nextStep
	}

	// Report errors, but continue anyway to drop as little data as possible.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error flattening run history: %v", err))
		h.terminalPrinter.Warnf(
			"There was an issue processing run metrics in step %d;"+
				" some data may be missing.",
			currentStep,
		)
	}

	historyRecord := &spb.HistoryRecord{Item: items}
	if useStep {
		historyRecord.Step = &spb.HistoryStep{Num: currentStep}
	}
	h.fwdRecord(&spb.Record{
		RecordType: &spb.Record_History{
			History: historyRecord,
		},
	}, nil)
}

// updateSummary updates the summary based on the current history step.
//
// This emits a summary record that is written to the transaction log.
func (h *Handler) updateSummary() {
	updates, err := h.runSummary.UpdateSummaries(h.partialHistory)

	// We continue despite errors to update as much of the summary as we can.
	if err != nil {
		h.logger.CaptureError(
			fmt.Errorf("handler: error updating summary: %v", err))
	}

	if len(updates) == 0 {
		return
	}

	// We must forward these changes to the Sender which uses them to build
	// its own summary.
	h.fwdRecord(&spb.Record{
		RecordType: &spb.Record_Summary{
			Summary: &spb.SummaryRecord{
				Update: updates,
			},
		},
	}, nil)
}

// samples history items and updates the history record with the sampled values
//
// This function samples history items and updates the history record with the
// sampled values. It is used to display a subset of the history items in the
// terminal. The sampling is done using a reservoir sampling algorithm.
func (h *Handler) handleRequestSampledHistory(
	record *spb.Record,
	request *runwork.Request,
) {
	h.respond(request, &spb.Response{
		ResponseType: &spb.Response_SampledHistoryResponse{
			SampledHistoryResponse: &spb.SampledHistoryResponse{
				Item: h.runHistorySampler.Get(),
			},
		},
	})
}
