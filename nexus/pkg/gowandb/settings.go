package gowandb

import (
	"crypto/rand"
	"encoding/base64"
	"os"
	"path/filepath"
	"time"

	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

type SettingsWrap struct {
	*service.Settings
}

func randomString(length int) string {
	randomBytes := make([]byte, length)
	if _, err := rand.Read(randomBytes); err != nil {
		return "test"
	}
	return base64.URLEncoding.EncodeToString(randomBytes)[:length]
}

func NewSettings(args ...any) *SettingsWrap {

	runID := randomString(8)

	rootDir, err := os.Getwd()
	if err != nil {
		panic(err)
	}
	wandbDir := filepath.Join(rootDir, ".wandb")
	timeStamp := time.Now().Format("20060102_150405")
	runMode := "run"

	syncDir := filepath.Join(wandbDir, runMode+"-"+timeStamp+"-"+runID)
	logDir := filepath.Join(syncDir, "logs")
	tmpDir := filepath.Join(syncDir, "tmp")

	settings := &service.Settings{
		RunId: &wrapperspb.StringValue{
			Value: runID,
		},
		BaseUrl: &wrapperspb.StringValue{
			Value: "https://api.wandb.ai",
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
		SyncDir: &wrapperspb.StringValue{
			Value: syncDir,
		},
		SyncFile: &wrapperspb.StringValue{
			Value: filepath.Join(syncDir, "run-"+runID+".wandb"),
		},
		LogDir: &wrapperspb.StringValue{
			Value: logDir,
		},
		LogInternal: &wrapperspb.StringValue{
			Value: filepath.Join(logDir, "debug-internal.log"),
		},
		LogUser: &wrapperspb.StringValue{
			Value: filepath.Join(logDir, "debug.log"),
		},
		FilesDir: &wrapperspb.StringValue{
			Value: filepath.Join(syncDir, "files"),
		},
		TmpDir: &wrapperspb.StringValue{
			Value: tmpDir,
		},
		XTmpCodeDir: &wrapperspb.StringValue{
			Value: filepath.Join(tmpDir, "code"),
		},
		XDisableStats: &wrapperspb.BoolValue{
			Value: true,
		},
		XOffline: &wrapperspb.BoolValue{
			Value: false,
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
	return &SettingsWrap{settings}
}
