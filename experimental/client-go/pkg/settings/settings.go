package settings

import (
	"os"
	"path/filepath"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

type SettingsWrap struct {
	*service.Settings
}

func (s *SettingsWrap) Copy() *SettingsWrap {
	protoSettings := proto.Clone(s.Settings).(*service.Settings)
	newSettings := &SettingsWrap{protoSettings}
	return newSettings
}

func NewSettings(args ...any) *SettingsWrap {
	rootDir, err := os.Getwd()
	if err != nil {
		panic(err)
	}
	// Default to ".wandb" if "wandb" dir doesnt exist (swapped logic from python wandb)
	wandbDir := filepath.Join(rootDir, "wandb")
	if _, err := os.Stat(wandbDir); os.IsNotExist(err) {
		wandbDir = filepath.Join(rootDir, ".wandb")
	}

	timeStamp := time.Now().Format("20060102_150405")

	// TODO: parse more settings env variables
	mode := "online"
	envMode := os.Getenv("WANDB_MODE")
	if envMode != "" {
		mode = envMode
	}

	runMode := "run"
	if mode == "offline" {
		runMode = "offline-run"
	}

	baseURL := os.Getenv("WANDB_BASE_URL")
	if baseURL == "" {
		baseURL = "https://api.wandb.ai"
	}

	settings := &service.Settings{
		BaseUrl: &wrapperspb.StringValue{
			Value: baseURL,
		},
		RootDir: &wrapperspb.StringValue{
			Value: rootDir,
		},
		WandbDir: &wrapperspb.StringValue{
			Value: wandbDir,
		},
		RunMode: &wrapperspb.StringValue{
			Value: runMode,
		},
		XStartDatetime: &wrapperspb.StringValue{
			Value: timeStamp,
		},
		Timespec: &wrapperspb.StringValue{
			Value: timeStamp,
		},
		XDisableStats: &wrapperspb.BoolValue{
			Value: false,
		},
		XOffline: &wrapperspb.BoolValue{
			Value: (mode == "offline"),
		},
		XFileStreamTimeoutSeconds: &wrapperspb.DoubleValue{
			Value: 60,
		},
		XStatsSamplesToAverage: &wrapperspb.Int32Value{
			Value: 15,
		},
		XStatsSampleRateSeconds: &wrapperspb.DoubleValue{
			Value: 2,
		},
		XStatsJoinAssets: &wrapperspb.BoolValue{
			Value: true,
		},
	}

	apiKey := os.Getenv("WANDB_API_KEY")
	if apiKey != "" {
		settings.ApiKey = &wrapperspb.StringValue{Value: apiKey}
	}

	return &SettingsWrap{settings}
}

func (s *SettingsWrap) SetRunID(runID string) {
	wandbDir := s.Settings.WandbDir.Value
	timeStamp := s.Settings.Timespec.Value
	runMode := s.Settings.RunMode.Value
	syncDir := filepath.Join(wandbDir, runMode+"-"+timeStamp+"-"+runID)
	logDir := filepath.Join(syncDir, "logs")
	tmpDir := filepath.Join(syncDir, "tmp")

	s.Settings.RunId = &wrapperspb.StringValue{Value: runID}
	s.Settings.SyncDir = &wrapperspb.StringValue{Value: syncDir}
	s.Settings.SyncFile = &wrapperspb.StringValue{
		Value: filepath.Join(syncDir, "run-"+runID+".wandb"),
	}
	s.Settings.FilesDir = &wrapperspb.StringValue{
		Value: filepath.Join(syncDir, "files"),
	}
	s.Settings.LogDir = &wrapperspb.StringValue{Value: logDir}
	s.Settings.LogInternal = &wrapperspb.StringValue{
		Value: filepath.Join(logDir, "debug-internal.log"),
	}
	s.Settings.LogUser = &wrapperspb.StringValue{
		Value: filepath.Join(logDir, "debug.log"),
	}
	s.Settings.TmpDir = &wrapperspb.StringValue{
		Value: tmpDir,
	}
	s.Settings.XTmpCodeDir = &wrapperspb.StringValue{
		Value: filepath.Join(tmpDir, "code"),
	}
}
