package sender

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/segmentio/encoding/json"
	"gopkg.in/yaml.v3"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/artifacts"
	"github.com/wandb/wandb/core/internal/debounce"
	fs "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/lib/corelib"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/retryableclient"
	"github.com/wandb/wandb/core/internal/server/consts"
	"github.com/wandb/wandb/core/internal/server/services/store"
	sync "github.com/wandb/wandb/core/internal/server/services/sync"
	"github.com/wandb/wandb/core/internal/server/stream/handler"
	"github.com/wandb/wandb/core/internal/version"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

const (
	// RFC3339Micro Modified from time.RFC3339Nano
	RFC3339Micro             = "2006-01-02T15:04:05.000000Z07:00"
	configDebouncerRateLimit = 1 / 30.0 // todo: audit rate limit
	configDebouncerBurstSize = 1        // todo: audit burst size
)

type SenderOption func(*Sender)

func WithSenderFwdChannel(fwd chan *pb.Record) SenderOption {
	return func(s *Sender) {
		s.fwdChan = fwd
	}
}

func WithSenderOutChannel(out chan *pb.Result) SenderOption {
	return func(s *Sender) {
		s.OutChan = out
	}
}

// Sender is the sender for a stream it handles the incoming messages and sends to the server
// or/and to the dispatcher/handler
type Sender struct {
	// ctx is the context for the handler
	ctx context.Context

	// cancel is the cancel function for the handler
	cancel context.CancelFunc

	// logger is the logger for the sender
	logger *observability.CoreLogger

	// settings is the settings for the sender
	settings *pb.Settings

	// fwdChan is the channel for loopback messages (messages from the sender to the handler)
	fwdChan chan *pb.Record

	// OutChan is the channel for dispatcher messages
	OutChan chan *pb.Result

	// graphqlClient is the graphql client
	graphqlClient graphql.Client

	// fileStream is the file stream
	fileStream *fs.FileStream

	// filetransfer is the file uploader/downloader
	fileTransfer *filetransfer.Manager

	// RunRecord is the run record
	RunRecord *pb.RunRecord

	// resumeState is the resume state
	resumeState *ResumeState

	telemetry *pb.TelemetryRecord

	metricSender *MetricSender

	configDebouncer *debounce.Debouncer

	// Keep track of summary which is being updated incrementally
	summaryMap map[string]*pb.SummaryItem

	// Keep track of config which is being updated incrementally
	configMap map[string]interface{}

	// Info about the (local) server we are talking to
	serverInfo *gql.ServerInfoServerInfo

	// Keep track of exit record to pass to file stream when the time comes
	exitRecord *pb.Record

	syncService *sync.SyncService

	store *store.Store
}

// NewSender creates a new Sender with the given settings
func NewSender(
	ctx context.Context,
	cancel context.CancelFunc,
	logger *observability.CoreLogger,
	settings *pb.Settings,
	opts ...SenderOption,
) *Sender {

	sender := &Sender{
		ctx:        ctx,
		cancel:     cancel,
		settings:   settings,
		logger:     logger,
		summaryMap: make(map[string]*pb.SummaryItem),
		configMap:  make(map[string]interface{}),
		telemetry:  &pb.TelemetryRecord{CoreVersion: version.Version},
	}
	if !settings.GetXOffline().GetValue() {
		baseHeaders := map[string]string{
			"X-WANDB-USERNAME":   settings.GetUsername().GetValue(),
			"X-WANDB-USER-EMAIL": settings.GetEmail().GetValue(),
		}
		graphqlRetryClient := retryableclient.NewRetryClient(
			retryableclient.WithRetryClientLogger(logger),
			retryableclient.WithRetryClientHttpAuthTransport(
				settings.GetApiKey().GetValue(),
				baseHeaders,
				settings.GetXExtraHttpHeaders().GetValue(),
			),
			retryableclient.WithRetryClientRetryPolicy(retryableclient.CheckRetry),
			retryableclient.WithRetryClientResponseLogger(logger.Logger, func(resp *http.Response) bool {
				return resp.StatusCode >= 400
			}),
			retryableclient.WithRetryClientRetryMax(int(settings.GetXGraphqlRetryMax().GetValue())),
			retryableclient.WithRetryClientRetryWaitMin(time.Duration(settings.GetXGraphqlRetryWaitMinSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientRetryWaitMax(time.Duration(settings.GetXGraphqlRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientHttpTimeout(time.Duration(settings.GetXGraphqlTimeoutSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientBackoff(retryableclient.ExponentialBackoffWithJitter),
		)
		url := fmt.Sprintf("%s/graphql", settings.GetBaseUrl().GetValue())
		sender.graphqlClient = graphql.NewClient(url, graphqlRetryClient.StandardClient())

		fileStreamRetryClient := retryableclient.NewRetryClient(
			retryableclient.WithRetryClientLogger(logger),
			retryableclient.WithRetryClientResponseLogger(logger.Logger, func(resp *http.Response) bool {
				return resp.StatusCode >= 400
			}),
			retryableclient.WithRetryClientRetryMax(int(settings.GetXFileStreamRetryMax().GetValue())),
			retryableclient.WithRetryClientRetryWaitMin(time.Duration(settings.GetXFileStreamRetryWaitMinSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientRetryWaitMax(time.Duration(settings.GetXFileStreamRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientHttpTimeout(time.Duration(settings.GetXFileStreamTimeoutSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientHttpAuthTransport(sender.settings.GetApiKey().GetValue()),
			retryableclient.WithRetryClientBackoff(retryableclient.ExponentialBackoffWithJitter),
			// TODO(core:beta): add custom retry function
			// retryClient.CheckRetry = fs.GetCheckRetryFunc()
		)
		sender.fileStream = fs.NewFileStream(
			fs.WithSettings(settings),
			fs.WithLogger(logger),
			fs.WithHttpClient(fileStreamRetryClient),
		)
		fileTransferRetryClient := retryableclient.NewRetryClient(
			retryableclient.WithRetryClientLogger(logger),
			retryableclient.WithRetryClientRetryPolicy(retryableclient.CheckRetry),
			retryableclient.WithRetryClientRetryMax(int(settings.GetXFileTransferRetryMax().GetValue())),
			retryableclient.WithRetryClientRetryWaitMin(time.Duration(settings.GetXFileTransferRetryWaitMinSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientRetryWaitMax(time.Duration(settings.GetXFileTransferRetryWaitMaxSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientHttpTimeout(time.Duration(settings.GetXFileTransferTimeoutSeconds().GetValue()*int32(time.Second))),
			retryableclient.WithRetryClientBackoff(retryableclient.ExponentialBackoffWithJitter),
		)
		defaultFileTransfer := filetransfer.NewDefaultTransferer(
			logger,
			fileTransferRetryClient,
		)
		sender.fileTransfer = filetransfer.New(
			filetransfer.WithLogger(logger),
			filetransfer.WithFileTransfer(defaultFileTransfer),
			filetransfer.WithFSCChan(sender.fileStream.GetInputChan()),
		)

		sender.getServerInfo()
	}
	sender.configDebouncer = debounce.New(
		configDebouncerRateLimit,
		configDebouncerBurstSize,
		logger,
	)

	for _, opt := range opts {
		opt(sender)
	}

	return sender
}

// do sending of messages to the server
func (s *Sender) Do(inChan <-chan *pb.Record) {
	defer s.logger.Reraise()
	s.logger.Info("sender: started", "stream_id", s.settings.RunId)

	for record := range inChan {
		s.sendRecord(record)
		// TODO: reevaluate the logic here
		s.configDebouncer.Debounce(s.upsertConfig)
	}
	s.Close()
	s.logger.Info("sender: closed", "stream_id", s.settings.RunId)
}

func (s *Sender) Close() {
	// sender is done processing data, close our dispatch channel
	close(s.OutChan)
}

func (s *Sender) GetOutboundChannel() chan *pb.Result {
	return s.OutChan
}

func (s *Sender) SetGraphqlClient(client graphql.Client) {
	s.graphqlClient = client
}

func (s *Sender) SendRecord(record *pb.Record) {
	// this is for testing purposes only yet
	s.sendRecord(record)
}

// sendRecord sends a record
func (s *Sender) sendRecord(record *pb.Record) {
	s.logger.Debug("sender: sendRecord", "record", record, "stream_id", s.settings.RunId)
	switch x := record.RecordType.(type) {
	case *pb.Record_Run:
		s.sendRun(record, x.Run)
	case *pb.Record_Footer:
	case *pb.Record_Header:
	case *pb.Record_Final:
	case *pb.Record_Exit:
		s.sendExit(record, x.Exit)
	case *pb.Record_Alert:
		s.sendAlert(record, x.Alert)
	case *pb.Record_Metric:
		s.sendMetric(record, x.Metric)
	case *pb.Record_Files:
		s.sendFiles(record, x.Files)
	case *pb.Record_History:
		s.sendHistory(record, x.History)
	case *pb.Record_Summary:
		s.sendSummary(record, x.Summary)
	case *pb.Record_Config:
		s.sendConfig(record, x.Config)
	case *pb.Record_Stats:
		s.sendSystemMetrics(record, x.Stats)
	case *pb.Record_OutputRaw:
		s.sendOutputRaw(record, x.OutputRaw)
	case *pb.Record_Telemetry:
		s.sendTelemetry(record, x.Telemetry)
	case *pb.Record_Preempting:
		s.sendPreempting(record)
	case *pb.Record_Request:
		s.sendRequest(record, x.Request)
	case *pb.Record_LinkArtifact:
		s.sendLinkArtifact(record)
	case *pb.Record_UseArtifact:
	case *pb.Record_Artifact:
	case nil:
		err := fmt.Errorf("sender: sendRecord: nil RecordType")
		s.logger.CaptureFatalAndPanic("sender: sendRecord: nil RecordType", err)
	default:
		err := fmt.Errorf("sender: sendRecord: unexpected type %T", x)
		s.logger.CaptureFatalAndPanic("sender: sendRecord: unexpected type", err)
	}
}

// sendRequest sends a request
func (s *Sender) sendRequest(record *pb.Record, request *pb.Request) {

	switch x := request.RequestType.(type) {
	case *pb.Request_RunStart:
		s.sendRunStart(x.RunStart)
	case *pb.Request_NetworkStatus:
		s.sendNetworkStatusRequest(x.NetworkStatus)
	case *pb.Request_Defer:
		s.sendDefer(x.Defer)
	case *pb.Request_LogArtifact:
		s.sendLogArtifact(record, x.LogArtifact)
	case *pb.Request_PollExit:
	case *pb.Request_ServerInfo:
		s.sendServerInfo(record, x.ServerInfo)
	case *pb.Request_DownloadArtifact:
		s.sendDownloadArtifact(record, x.DownloadArtifact)
	case *pb.Request_Sync:
		s.sendSync(record, x.Sync)
	case *pb.Request_SenderRead:
		s.sendSenderRead(record, x.SenderRead)
	case *pb.Request_Cancel:
		// TODO: audit this
	case nil:
		err := fmt.Errorf("sender: sendRequest: nil RequestType")
		s.logger.CaptureFatalAndPanic("sender: sendRequest: nil RequestType", err)
	default:
		err := fmt.Errorf("sender: sendRequest: unexpected type %T", x)
		s.logger.CaptureFatalAndPanic("sender: sendRequest: unexpected type", err)
	}
}

// updateSettingsStartTime sets run start time in the settings if it is not set
func (s *Sender) updateSettingsStartTime() {
	// TODO: rewrite in a cleaner way
	if s.settings == nil || s.settings.XStartTime != nil {
		return
	}
	if s.RunRecord == nil || s.RunRecord.StartTime == nil {
		return
	}
	startTime := float64(s.RunRecord.StartTime.Seconds) + float64(s.RunRecord.StartTime.Nanos)/1e9
	s.settings.XStartTime = &wrapperspb.DoubleValue{Value: startTime}
}

// sendRun starts up all the resources for a run
func (s *Sender) sendRunStart(_ *pb.RunStartRequest) {
	fsPath := fmt.Sprintf("%s/files/%s/%s/%s/file_stream",
		s.settings.GetBaseUrl().GetValue(), s.RunRecord.Entity, s.RunRecord.Project, s.RunRecord.RunId)

	fs.WithPath(fsPath)(s.fileStream)
	fs.WithOffsets(s.resumeState.GetFileStreamOffset())(s.fileStream)

	s.updateSettingsStartTime()
	s.fileStream.Start()
	s.fileTransfer.Start()
}

func (s *Sender) sendNetworkStatusRequest(_ *pb.NetworkStatusRequest) {
}

func (s *Sender) sendDefer(request *pb.DeferRequest) {
	switch request.State {
	case pb.DeferRequest_BEGIN:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_RUN:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_STATS:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_PARTIAL_HISTORY:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_TB:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_SUM:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_DEBOUNCER:
		s.configDebouncer.Flush(s.upsertConfig)
		s.writeAndSendConfigFile()
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_OUTPUT:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_JOB:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_DIR:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_FP:
		s.fileTransfer.Close()
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_JOIN_FP:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_FS:
		s.fileStream.Close()
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_FLUSH_FINAL:
		request.State++
		s.sendRequestDefer(request)
	case pb.DeferRequest_END:
		request.State++
		s.syncService.Flush()
		s.respondExit(s.exitRecord)
		// cancel tells the stream to close the loopback channel
		s.cancel()
	default:
		err := fmt.Errorf("sender: sendDefer: unexpected state %v", request.State)
		s.logger.CaptureFatalAndPanic("sender: sendDefer: unexpected state", err)
	}
}

func (s *Sender) sendRequestDefer(request *pb.DeferRequest) {
	rec := &pb.Record{
		RecordType: &pb.Record_Request{Request: &pb.Request{
			RequestType: &pb.Request_Defer{Defer: request},
		}},
		Control: &pb.Control{AlwaysSend: true},
	}
	s.fwdChan <- rec
}

func (s *Sender) sendTelemetry(_ *pb.Record, telemetry *pb.TelemetryRecord) {
	proto.Merge(s.telemetry, telemetry)
	s.updateConfigPrivate(s.telemetry)
	// TODO(perf): improve when debounce config is added, for now this sends all the time
	s.sendConfig(nil, nil /*configRecord*/)
}

func (s *Sender) sendPreempting(record *pb.Record) {
	s.fileStream.StreamRecord(record)
}

func (s *Sender) sendLinkArtifact(record *pb.Record) {
	linker := artifacts.ArtifactLinker{
		Ctx:           s.ctx,
		Logger:        s.logger,
		LinkArtifact:  record.GetLinkArtifact(),
		GraphqlClient: s.graphqlClient,
	}
	err := linker.Link()
	if err != nil {
		s.logger.CaptureFatalAndPanic("sender: sendLinkArtifact: link failure", err)
	}

	result := &pb.Result{
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.OutChan <- result
}

// updateConfig updates the config map with the config record
func (s *Sender) updateConfig(configRecord *pb.ConfigRecord) {
	// TODO: handle nested key updates and deletes
	for _, d := range configRecord.GetUpdate() {
		var value interface{}
		if err := json.Unmarshal([]byte(d.GetValueJson()), &value); err != nil {
			s.logger.CaptureError("unmarshal problem", err)
			continue
		}
		keyList := d.GetNestedKey()
		if keyList == nil {
			keyList = []string{d.GetKey()}
		}
		target := s.configMap
		for _, k := range keyList[:len(keyList)-1] {
			val, ok := target[k].(map[string]interface{})
			if !ok {
				val = make(map[string]interface{})
				target[k] = val
			}
			target = val
		}
		target[keyList[len(keyList)-1]] = value
	}
	for _, d := range configRecord.GetRemove() {
		delete(s.configMap, d.GetKey())
	}
}

// updateConfigPrivate updates the private part of the config map
func (s *Sender) updateConfigPrivate(telemetry *pb.TelemetryRecord) {
	if _, ok := s.configMap["_wandb"]; !ok {
		s.configMap["_wandb"] = make(map[string]interface{})
	}

	switch v := s.configMap["_wandb"].(type) {
	case map[string]interface{}:
		if telemetry.GetCliVersion() != "" {
			v["cli_version"] = telemetry.CliVersion
		}
		if telemetry.GetPythonVersion() != "" {
			v["python_version"] = telemetry.PythonVersion
		}
		v["t"] = corelib.ProtoEncodeToDict(s.telemetry)
		if s.metricSender != nil {
			v["m"] = s.metricSender.configMetrics
		}
		// todo: add the rest of the telemetry from telemetry
	default:
		err := fmt.Errorf("can not parse config _wandb, saw: %v", v)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}
}

// serializeConfig serializes the config map to a json string
// that can be sent to the server
func (s *Sender) serializeConfig(format string) string {
	valueConfig := make(map[string]map[string]interface{})
	for key, elem := range s.configMap {
		valueConfig[key] = make(map[string]interface{})
		valueConfig[key]["value"] = elem
	}
	var serializedConfig []byte
	var err error
	if format == "yaml" {
		serializedConfig, err = yaml.Marshal(valueConfig)
	} else {
		// json
		serializedConfig, err = json.Marshal(valueConfig)
	}

	if err != nil {
		err = fmt.Errorf("failed to marshal config: %s", err)
		s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
	}
	return string(serializedConfig)
}

func (s *Sender) sendRunResult(record *pb.Record, runResult *pb.RunUpdateResult) {
	result := &pb.Result{
		ResultType: &pb.Result_RunResult{
			RunResult: runResult,
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.OutChan <- result

}

func (s *Sender) checkAndUpdateResumeState(record *pb.Record) error {
	if s.graphqlClient == nil {
		return nil
	}
	// There was no resume status set, so we don't need to do anything
	if s.settings.GetResume().GetValue() == "" {
		return nil
	}

	// init resume state if it doesn't exist
	s.resumeState = NewResumeState(s.logger, s.settings.GetResume().GetValue())
	run := s.RunRecord
	// If we couldn't get the resume status, we should fail if resume is set
	data, err := gql.RunResumeStatus(s.ctx, s.graphqlClient, &run.Project, corelib.NilIfZero(run.Entity), run.RunId)
	if err != nil {
		err = fmt.Errorf("failed to get run resume status: %s", err)
		s.logger.Error("sender:", "error", err)
		result := &pb.RunUpdateResult{
			Error: &pb.ErrorInfo{
				Message: err.Error(),
				Code:    pb.ErrorInfo_COMMUNICATION,
			}}
		s.sendRunResult(record, result)
		return err
	}

	if result, err := s.resumeState.Update(data, s.RunRecord, s.configMap); err != nil {
		s.sendRunResult(record, result)
		return err
	}

	return nil
}

func (s *Sender) sendRun(record *pb.Record, run *pb.RunRecord) {

	if s.RunRecord == nil && s.graphqlClient != nil {
		var ok bool
		s.RunRecord, ok = proto.Clone(run).(*pb.RunRecord)
		if !ok {
			err := fmt.Errorf("failed to clone RunRecord")
			s.logger.CaptureFatalAndPanic("sender: sendRun: ", err)
		}

		if err := s.checkAndUpdateResumeState(record); err != nil {
			s.logger.Error("sender: sendRun: failed to checkAndUpdateResumeState", "error", err)
			return
		}
	}

	if s.graphqlClient != nil {

		s.updateConfig(run.Config)
		proto.Merge(s.telemetry, run.Telemetry)
		s.updateConfigPrivate(run.Telemetry)
		config := s.serializeConfig("json")

		var tags []string
		tags = append(tags, run.Tags...)

		var commit, repo string
		git := run.GetGit()
		if git != nil {
			commit = git.GetCommit()
			repo = git.GetRemoteUrl()
		}

		program := s.settings.GetProgram().GetValue()
		// start a new context with an additional argument from the parent context
		// this is used to pass the retry function to the graphql client
		ctx := context.WithValue(s.ctx, retryableclient.CtxRetryPolicyKey, retryableclient.UpsertBucketRetryPolicy)
		data, err := gql.UpsertBucket(
			ctx,                                // ctx
			s.graphqlClient,                    // client
			nil,                                // id
			&run.RunId,                         // name
			corelib.NilIfZero(run.Project),     // project
			corelib.NilIfZero(run.Entity),      // entity
			corelib.NilIfZero(run.RunGroup),    // groupName
			nil,                                // description
			corelib.NilIfZero(run.DisplayName), // displayName
			corelib.NilIfZero(run.Notes),       // notes
			corelib.NilIfZero(commit),          // commit
			&config,                            // config
			corelib.NilIfZero(run.Host),        // host
			nil,                                // debug
			corelib.NilIfZero(program),         // program
			corelib.NilIfZero(repo),            // repo
			corelib.NilIfZero(run.JobType),     // jobType
			nil,                                // state
			nil,                                // sweep
			tags,                               // tags []string,
			nil,                                // summaryMetrics
		)
		if err != nil {
			err = fmt.Errorf("failed to upsert bucket: %s", err)
			s.logger.Error("sender: sendRun:", "error", err)
			// TODO(sync): make this more robust in case of a failed UpsertBucket request.
			//  Need to inform the sync service that this ops failed.
			if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
				result := &pb.Result{
					ResultType: &pb.Result_RunResult{
						RunResult: &pb.RunUpdateResult{
							Error: &pb.ErrorInfo{
								Message: err.Error(),
								Code:    pb.ErrorInfo_COMMUNICATION,
							},
						},
					},
					Control: record.Control,
					Uuid:    record.Uuid,
				}
				s.OutChan <- result
			}
			return
		}

		s.RunRecord.DisplayName = *data.UpsertBucket.Bucket.DisplayName
		s.RunRecord.Project = data.UpsertBucket.Bucket.Project.Name
		s.RunRecord.Entity = data.UpsertBucket.Bucket.Project.Entity.Name
	}

	if record.GetControl().GetReqResp() || record.GetControl().GetMailboxSlot() != "" {
		runResult := s.RunRecord
		if runResult == nil {
			runResult = run
		}
		result := &pb.Result{
			ResultType: &pb.Result_RunResult{
				RunResult: &pb.RunUpdateResult{Run: runResult},
			},
			Control: record.Control,
			Uuid:    record.Uuid,
		}
		s.OutChan <- result
	}
}

// sendHistory sends a history record to the file stream,
// which will then send it to the server
func (s *Sender) sendHistory(record *pb.Record, _ *pb.HistoryRecord) {
	s.fileStream.StreamRecord(record)
}

func (s *Sender) sendSummary(_ *pb.Record, summary *pb.SummaryRecord) {
	// TODO(network): buffer summary sending for network efficiency until we can send only updates
	// TODO(compat): handle deletes, nested keys
	// TODO(compat): write summary file

	// track each key in the in memory summary store
	// TODO(memory): avoid keeping summary for all distinct keys
	for _, item := range summary.Update {
		s.summaryMap[item.Key] = item
	}

	// build list of summary items from the map
	var summaryItems []*pb.SummaryItem
	for _, v := range s.summaryMap {
		summaryItems = append(summaryItems, v)
	}

	// build a full summary record to send
	record := &pb.Record{
		RecordType: &pb.Record_Summary{
			Summary: &pb.SummaryRecord{
				Update: summaryItems,
			},
		},
	}

	s.fileStream.StreamRecord(record)
}

func (s *Sender) upsertConfig() {
	if s.graphqlClient == nil {
		return
	}
	config := s.serializeConfig("json")

	ctx := context.WithValue(s.ctx, retryableclient.CtxRetryPolicyKey, retryableclient.UpsertBucketRetryPolicy)
	_, err := gql.UpsertBucket(
		ctx,                                    // ctx
		s.graphqlClient,                        // client
		nil,                                    // id
		&s.RunRecord.RunId,                     // name
		corelib.NilIfZero(s.RunRecord.Project), // project
		corelib.NilIfZero(s.RunRecord.Entity),  // entity
		nil,                                    // groupName
		nil,                                    // description
		nil,                                    // displayName
		nil,                                    // notes
		nil,                                    // commit
		&config,                                // config
		nil,                                    // host
		nil,                                    // debug
		nil,                                    // program
		nil,                                    // repo
		nil,                                    // jobType
		nil,                                    // state
		nil,                                    // sweep
		nil,                                    // tags []string,
		nil,                                    // summaryMetrics
	)
	if err != nil {
		s.logger.Error("sender: sendConfig:", "error", err)
	}
}

func (s *Sender) writeAndSendConfigFile() {
	if s.settings.GetXSync().GetValue() {
		// if sync is enabled, we don't need to do all this
		return
	}

	config := s.serializeConfig("yaml")
	configFile := filepath.Join(s.settings.GetFilesDir().GetValue(), consts.ConfigFileName)
	if err := os.WriteFile(configFile, []byte(config), 0644); err != nil {
		s.logger.Error("sender: writeAndSendConfigFile: failed to write config file", "error", err)
	}

	record := &pb.Record{
		RecordType: &pb.Record_Files{
			Files: &pb.FilesRecord{
				Files: []*pb.FilesItem{
					{
						Path: consts.ConfigFileName,
						Type: pb.FilesItem_WANDB,
					},
				},
			},
		},
	}
	s.fwdChan <- record
}

// sendConfig sends a config record to the server via an upsertBucket mutation
// and updates the in memory config
func (s *Sender) sendConfig(_ *pb.Record, configRecord *pb.ConfigRecord) {
	if configRecord != nil {
		s.updateConfig(configRecord)
	}
	s.configDebouncer.Set()
}

// sendSystemMetrics sends a system metrics record via the file stream
func (s *Sender) sendSystemMetrics(record *pb.Record, _ *pb.StatsRecord) {
	s.fileStream.StreamRecord(record)
}

func (s *Sender) sendOutputRaw(record *pb.Record, _ *pb.OutputRawRecord) {
	// TODO: match logic handling of lines to the one in the python version
	// - handle carriage returns (for tqdm-like progress bars)
	// - handle caching multiple (non-new lines) and sending them in one chunk
	// - handle lines longer than ~60_000 characters

	// copy the record to avoid mutating the original
	recordCopy := proto.Clone(record).(*pb.Record)
	outputRaw := recordCopy.GetOutputRaw()

	// ignore empty "new lines"
	if outputRaw.Line == "\n" {
		return
	}

	outputFile := filepath.Join(s.settings.GetFilesDir().GetValue(), consts.OutputFileName)
	// append line to file
	f, err := os.OpenFile(outputFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		s.logger.Error("sender: sendOutputRaw: failed to open output file", "error", err)
	}
	if _, err := f.WriteString(outputRaw.Line + "\n"); err != nil {
		s.logger.Error("sender: sendOutputRaw: failed to write to output file", "error", err)
	}
	defer func() {
		if err := f.Close(); err != nil {
			s.logger.Error("sender: sendOutputRaw: failed to close output file", "error", err)
		}
	}()

	// generate compatible timestamp to python iso-format (microseconds without Z)
	t := strings.TrimSuffix(time.Now().UTC().Format(RFC3339Micro), "Z")
	outputRaw.Line = fmt.Sprintf("%s %s", t, outputRaw.Line)
	if outputRaw.OutputType == pb.OutputRawRecord_STDERR {
		outputRaw.Line = fmt.Sprintf("ERROR %s", outputRaw.Line)
	}
	s.fileStream.StreamRecord(recordCopy)
}

func (s *Sender) sendAlert(_ *pb.Record, alert *pb.AlertRecord) {
	if s.graphqlClient == nil {
		return
	}

	if s.RunRecord == nil {
		err := fmt.Errorf("sender: sendAlert: RunRecord not set")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}
	// TODO: handle invalid alert levels
	severity := gql.AlertSeverity(alert.Level)

	data, err := gql.NotifyScriptableRunAlert(
		s.ctx,
		s.graphqlClient,
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
		alert.Title,
		alert.Text,
		&severity,
		&alert.WaitDuration,
	)
	if err != nil {
		err = fmt.Errorf("sender: sendAlert: failed to notify scriptable run alert: %s", err)
		s.logger.CaptureError("sender received error", err)
	} else {
		s.logger.Info("sender: sendAlert: notified scriptable run alert", "data", data)
	}

}

// respondExit called from the end of the defer state machine
func (s *Sender) respondExit(record *pb.Record) {
	if record == nil || s.settings.GetXSync().GetValue() {
		return
	}
	if record.Control.ReqResp || record.Control.MailboxSlot != "" {
		result := &pb.Result{
			ResultType: &pb.Result_ExitResult{ExitResult: &pb.RunExitResult{}},
			Control:    record.Control,
			Uuid:       record.Uuid,
		}
		s.OutChan <- result
	}
}

// sendExit sends an exit record to the server and triggers the shutdown of the stream
func (s *Sender) sendExit(record *pb.Record, _ *pb.RunExitRecord) {
	// response is done by respondExit() and called when defer state machine is complete
	s.exitRecord = record

	s.fileStream.StreamRecord(record)

	// send a defer request to the handler to indicate that the user requested to finish the stream
	// and the defer state machine can kick in triggering the shutdown process
	request := &pb.Request{RequestType: &pb.Request_Defer{
		Defer: &pb.DeferRequest{State: pb.DeferRequest_BEGIN}},
	}
	if record.Control == nil {
		record.Control = &pb.Control{AlwaysSend: true}
	}

	rec := &pb.Record{
		RecordType: &pb.Record_Request{Request: request},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	s.fwdChan <- rec
}

// sendMetric sends a metrics record to the file stream,
// which will then send it to the server
func (s *Sender) sendMetric(record *pb.Record, metric *pb.MetricRecord) {
	if s.metricSender == nil {
		s.metricSender = NewMetricSender()
	}

	if metric.GetGlobName() != "" {
		s.logger.Warn("sender: sendMetric: glob name is not supported in the backend", "globName", metric.GetGlobName())
		return
	}

	s.encodeMetricHints(record, metric)
	s.updateConfigPrivate(nil /*telemetry*/)
	s.sendConfig(nil, nil /*configRecord*/)
}

// sendFiles iterates over the files in the FilesRecord and sends them to
func (s *Sender) sendFiles(_ *pb.Record, filesRecord *pb.FilesRecord) {
	files := filesRecord.GetFiles()
	for _, file := range files {
		if strings.HasPrefix(file.GetPath(), "media") {
			file.Type = pb.FilesItem_MEDIA
		}
		s.sendFile(file)
	}
}

// sendFile sends a file to the server
// TODO: improve this to handle multiple files and send them in one request
func (s *Sender) sendFile(file *pb.FilesItem) {
	if s.graphqlClient == nil || s.fileTransfer == nil {
		return
	}

	if s.RunRecord == nil {
		err := fmt.Errorf("sender: sendFile: RunRecord not set")
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), file.GetPath())
	if _, err := os.Stat(fullPath); os.IsNotExist(err) {
		s.logger.Warn("sender: sendFile: file does not exist", "path", fullPath)
		return
	}

	data, err := gql.CreateRunFiles(
		s.ctx,
		s.graphqlClient,
		s.RunRecord.Entity,
		s.RunRecord.Project,
		s.RunRecord.RunId,
		[]string{file.GetPath()},
	)
	if err != nil {
		err = fmt.Errorf("sender: sendFile: failed to get upload urls: %s", err)
		s.logger.CaptureFatalAndPanic("sender received error", err)
	}

	for _, f := range data.GetCreateRunFiles().GetFiles() {
		fullPath := filepath.Join(s.settings.GetFilesDir().GetValue(), f.Name)
		task := &filetransfer.Task{
			Type: filetransfer.UploadTask,
			Path: fullPath,
			Name: f.Name,
			Url:  *f.UploadUrl,
		}

		task.SetProgressCallback(
			func(processed, total int) {
				if processed == 0 {
					return
				}
				record := &pb.Record{
					RecordType: &pb.Record_Request{
						Request: &pb.Request{
							RequestType: &pb.Request_FileTransferInfo{
								FileTransferInfo: &pb.FileTransferInfoRequest{
									Type:      pb.FileTransferInfoRequest_Upload,
									Path:      fullPath,
									Size:      int64(total),
									Processed: int64(processed),
								},
							},
						},
					},
				}
				s.fwdChan <- record
			},
		)
		task.AddCompletionCallback(s.fileTransfer.FSCallback())
		task.AddCompletionCallback(
			func(*filetransfer.Task) {
				fileCounts := &pb.FileCounts{}
				switch file.GetType() {
				case pb.FilesItem_MEDIA:
					fileCounts.MediaCount = 1
				case pb.FilesItem_OTHER:
					fileCounts.OtherCount = 1
				case pb.FilesItem_WANDB:
					fileCounts.WandbCount = 1
				}

				record := &pb.Record{
					RecordType: &pb.Record_Request{
						Request: &pb.Request{
							RequestType: &pb.Request_FileTransferInfo{
								FileTransferInfo: &pb.FileTransferInfoRequest{
									Type:       pb.FileTransferInfoRequest_Upload,
									Path:       fullPath,
									Size:       task.Size,
									Processed:  task.Size,
									FileCounts: fileCounts,
								},
							},
						},
					},
				}
				s.fwdChan <- record
			},
		)

		s.fileTransfer.AddTask(task)
	}
}

func (s *Sender) sendLogArtifact(record *pb.Record, msg *pb.LogArtifactRequest) {
	var response pb.LogArtifactResponse
	saver := artifacts.NewArtifactSaver(
		s.ctx, s.graphqlClient, s.fileTransfer, msg.Artifact, msg.HistoryStep, msg.StagingDir,
	)
	artifactID, err := saver.Save(s.fwdChan)
	if err != nil {
		response.ErrorMessage = err.Error()
	} else {
		response.ArtifactId = artifactID
	}

	result := &pb.Result{
		ResultType: &pb.Result_Response{
			Response: &pb.Response{
				ResponseType: &pb.Response_LogArtifactResponse{
					LogArtifactResponse: &response,
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.OutChan <- result
}

func (s *Sender) sendDownloadArtifact(record *pb.Record, msg *pb.DownloadArtifactRequest) {
	// TODO: this should be handled by a separate service starup mechanism
	s.fileTransfer.Start()

	var response pb.DownloadArtifactResponse
	downloader := artifacts.NewArtifactDownloader(s.ctx, s.graphqlClient, s.fileTransfer, msg.ArtifactId, msg.DownloadRoot, &msg.AllowMissingReferences)
	err := downloader.Download()
	if err != nil {
		s.logger.CaptureError("senderError: downloadArtifact: failed to download artifact: %v", err)
		response.ErrorMessage = err.Error()
	}

	result := &pb.Result{
		ResultType: &pb.Result_Response{
			Response: &pb.Response{
				ResponseType: &pb.Response_DownloadArtifactResponse{
					DownloadArtifactResponse: &response,
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.OutChan <- result
}

func (s *Sender) sendSync(record *pb.Record, request *pb.SyncRequest) {

	s.syncService = sync.NewSyncService(s.ctx,
		sync.WithSyncServiceLogger(s.logger),
		sync.WithSyncServiceSenderFunc(s.sendRecord),
		sync.WithSyncServiceOverwrite(request.GetOverwrite()),
		sync.WithSyncServiceSkip(request.GetSkip()),
		sync.WithSyncServiceFlushCallback(func(err error) {
			var errorInfo *pb.ErrorInfo
			if err != nil {
				errorInfo = &pb.ErrorInfo{
					Message: err.Error(),
					Code:    pb.ErrorInfo_UNKNOWN,
				}
			}

			var url string
			if s.RunRecord != nil {
				baseUrl := s.settings.GetBaseUrl().GetValue()
				baseUrl = strings.Replace(baseUrl, "api.", "", 1)
				url = fmt.Sprintf("%s/%s/%s/runs/%s", baseUrl, s.RunRecord.Entity, s.RunRecord.Project, s.RunRecord.RunId)
			}
			result := &pb.Result{
				ResultType: &pb.Result_Response{
					Response: &pb.Response{
						ResponseType: &pb.Response_SyncResponse{
							SyncResponse: &pb.SyncResponse{
								Url:   url,
								Error: errorInfo,
							},
						},
					},
				},
				Control: record.Control,
				Uuid:    record.Uuid,
			}
			s.OutChan <- result
		}),
	)
	s.syncService.Start()

	rec := &pb.Record{
		RecordType: &pb.Record_Request{
			Request: &pb.Request{
				RequestType: &pb.Request_SenderRead{
					SenderRead: &pb.SenderReadRequest{
						StartOffset: request.GetStartOffset(),
						FinalOffset: request.GetFinalOffset(),
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.fwdChan <- rec
}

func (s *Sender) sendSenderRead(record *pb.Record, request *pb.SenderReadRequest) {
	if s.store == nil {
		store := store.New(s.ctx, s.settings.GetSyncFile().GetValue(), s.logger)
		err := store.Open(os.O_RDONLY)
		if err != nil {
			s.logger.CaptureError("sender: sendSenderRead: failed to create store", err)
			return
		}
		s.store = store
	}
	// TODO:
	// 1. seek to startOffset
	//
	// if err := s.store.reader.SeekRecord(request.GetStartOffset()); err != nil {
	// 	s.logger.CaptureError("sender: sendSenderRead: failed to seek record", err)
	// 	return
	// }
	// 2. read records until finalOffset
	//
	for {
		record, err := s.store.Read()
		if s.settings.GetXSync().GetValue() {
			s.syncService.SyncRecord(record, err)
		} else if record != nil {
			s.sendRecord(record)
		}
		if err == io.EOF {
			return
		}
		if err != nil {
			s.logger.CaptureError("sender: sendSenderRead: failed to read record", err)
			return
		}
	}
}

func (s *Sender) getServerInfo() {
	if s.graphqlClient == nil {
		return
	}

	data, err := gql.ServerInfo(s.ctx, s.graphqlClient)
	if err != nil {
		err = fmt.Errorf("sender: getServerInfo: failed to get server info: %s", err)
		s.logger.CaptureError("sender received error", err)
		return
	}
	s.serverInfo = data.GetServerInfo()

	s.logger.Info("sender: getServerInfo: got server info", "serverInfo", s.serverInfo)
}

// TODO: this function is for deciding which GraphQL query/mutation versions to use
// func (s *Sender) getServerVersion() string {
// 	if s.serverInfo == nil {
// 		return ""
// 	}
// 	return s.serverInfo.GetLatestLocalVersionInfo().GetVersionOnThisInstanceString()
// }

// encodeMetricHints encodes the metric hints for the given metric record. The metric hints
// are used to configure the plots in the UI.
func (s *Sender) encodeMetricHints(_ *pb.Record, metric *pb.MetricRecord) {

	_, err := handler.AddMetric(metric, metric.GetName(), &s.metricSender.definedMetrics)
	if err != nil {
		return
	}

	if metric.GetStepMetric() != "" {
		index, ok := s.metricSender.metricIndex[metric.GetStepMetric()]
		if ok {
			metric = proto.Clone(metric).(*pb.MetricRecord)
			metric.StepMetric = ""
			metric.StepMetricIndex = index + 1
		}
	}

	encodeMetric := corelib.ProtoEncodeToDict(metric)
	if index, ok := s.metricSender.metricIndex[metric.GetName()]; ok {
		s.metricSender.configMetrics[index] = encodeMetric
	} else {
		nextIndex := len(s.metricSender.configMetrics)
		s.metricSender.configMetrics = append(s.metricSender.configMetrics, encodeMetric)
		s.metricSender.metricIndex[metric.GetName()] = int32(nextIndex)
	}
}

func (s *Sender) sendServerInfo(record *pb.Record, _ *pb.ServerInfoRequest) {

	localInfo := &pb.LocalInfo{}
	if s.serverInfo != nil && s.serverInfo.GetLatestLocalVersionInfo() != nil {
		localInfo = &pb.LocalInfo{
			Version:   s.serverInfo.GetLatestLocalVersionInfo().GetLatestVersionString(),
			OutOfDate: s.serverInfo.GetLatestLocalVersionInfo().GetOutOfDate(),
		}
	}

	result := &pb.Result{
		ResultType: &pb.Result_Response{
			Response: &pb.Response{
				ResponseType: &pb.Response_ServerInfoResponse{
					ServerInfoResponse: &pb.ServerInfoResponse{
						LocalInfo: localInfo,
					},
				},
			},
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.OutChan <- result
}
