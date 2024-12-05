package settings

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/experimental/client-go/internal/uuid"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func NilIfZero[T comparable](x T) *T {
	var zero T
	if x == zero {
		return nil
	}
	return &x
}

func ZeroIfNil[T comparable](x *T) T {
	if x == nil {
		var zero T
		return zero
	}
	return *x
}

// Enum types for Mode
type Mode string

const (
	ModeOnline   Mode = "online"
	ModeOffline  Mode = "offline"
	ModeDisabled Mode = "disabled"
)

type Resume string

const (
	ResumeAllow Resume = "allow"
	ResumeMust  Resume = "must"
	ResumeNever Resume = "never"
	ResumeAuto  Resume = "auto"
)

type Console string

const (
	ConsoleAuto     Console = "auto"
	ConsoleOff      Console = "off"
	ConsoleWrap     Console = "wrap"
	ConsoleRedirect Console = "redirect"
	ConsoleWrapRaw  Console = "wrap_raw"
	ConsoleWrapEmul Console = "wrap_emu"
)

type Settings struct {
	ApiKey                string   `env:"WANDB_API_KEY"`
	BaseURL               string   `env:"WANDB_BASE_URL"`
	Console               Console  `env:"WANDB_CONSOLE"`
	DisableCode           bool     `env:"WANDB_DISABLE_CODE"`
	DisableGit            bool     `env:"WANDB_DISABLE_GIT"`
	DisableJobCreation    bool     `env:"WANDB_DISABLE_JOB_CREATION"`
	DisableStats          bool     `env:"WANDB_DISABLE_STATS"`
	DisableMeta           bool     `env:"WANDB_DISABLE_META"`
	Email                 string   `env:"WANDB_USER_EMAIL"`
	Entity                string   `env:"WANDB_ENTITY"`
	Username              string   `env:"WANDB_USERNAME"`
	Mode                  Mode     `env:"WANDB_MODE"`
	Resume                *Resume  `env:"WANDB_RESUME"`
	RunGroup              string   `env:"WANDB_GROUP"`
	RunJobType            string   `env:"WANDB_JOB_TYPE"`
	RunID                 string   `env:"WANDB_RUN_ID"`
	RunProject            string   `env:"WANDB_PROJECT"`
	RunName               string   `env:"WANDB_NAME"`
	RunNotes              string   `env:"WANDB_NOTES"`
	RunTags               []string `env:"WANDB_TAGS"`
	RootDir               string   `env:"WANDB_DIR"`
	wandbDir              string   `env:"WANDB_DIR"`
	timeSpec              time.Time
	resumed               bool
	FileStreamTimeout     float64 `env:"WANDB_FILE_STREAM_TIMEOUT"`
	StatsSampleRate       float64 `env:"WANDB_STATS_SAMPLE_RATE"`
	StatsSamplesToAverage int32   `env:"WANDB_STATS_SAMPLES_TO_AVERAGE"`
}

// New creates a new Settings object with default values.
func New() (*Settings, error) {
	//rootDir defaults to current working directory
	rootDir, err := os.Getwd()
	if err != nil {
		return nil, err
	}

	// Default to ".wandb" if "wandb" dir doesnt exist
	wandbDir := filepath.Join(rootDir, "wandb")
	if _, err := os.Stat(wandbDir); os.IsNotExist(err) {
		wandbDir = filepath.Join(rootDir, ".wandb")
	}

	return &Settings{
		BaseURL:            "https://api.wandb.ai",
		Console:            ConsoleAuto,
		RunID:              uuid.GenerateUniqueID(8),
		Mode:               ModeOnline,
		RootDir:            rootDir,
		timeSpec:           time.Now(),
		resumed:            false,
		DisableJobCreation: true,
		wandbDir:           wandbDir,
	}, nil
}

func (s *Settings) FromEnv() *Settings {
	target := reflect.ValueOf(s).Elem()
	targetType := target.Type()

	for i := 0; i < targetType.NumField(); i++ {
		field := targetType.Field(i)
		envName := field.Tag.Get("env")
		if envName == "" {
			continue
		}
		envValue := os.Getenv(envName)
		if envValue == "" {
			continue
		}
		fieldValue := target.Field(i)
		if !fieldValue.CanSet() {
			continue
		}
		switch fieldValue.Kind() {
		case reflect.String:
			fieldValue.SetString(envValue)
		case reflect.Ptr:
			if field.Name == "Resume" {
				resumeValue := Resume(envValue)
				fieldValue.Set(reflect.ValueOf(&resumeValue))
			} else {
				fieldValue.Set(reflect.ValueOf(&envValue))
			}
		case reflect.Bool:
			boolValue, err := strconv.ParseBool(envValue)
			if err != nil {
				continue
			}
			fieldValue.SetBool(boolValue)
		case reflect.Float32, reflect.Float64:
			// Convert string to float
			floatValue, err := strconv.ParseFloat(envValue, 64)
			if err != nil {
				continue
			}
			fieldValue.SetFloat(floatValue)
		case reflect.Int32, reflect.Int64:
			intValue, err := strconv.ParseInt(envValue, 10, 64)
			if err != nil {
				continue
			}
			fieldValue.SetInt(intValue)
		case reflect.Slice:
			if fieldValue.Type().Elem().Kind() == reflect.String {
				// Split comma-separated string into slice
				fieldValue.Set(reflect.ValueOf(strings.Split(envValue, ",")))
			}
		}
	}
	return s
}

func (s *Settings) FromSettings(source *Settings) *Settings {
	// use reflection to copy all non-zero fields from settings to s
	sourceValue := reflect.ValueOf(source)
	targetValue := reflect.ValueOf(s)

	if sourceValue.Kind() == reflect.Ptr {
		sourceValue = sourceValue.Elem()
	}
	if targetValue.Kind() == reflect.Ptr {
		targetValue = targetValue.Elem()
	}

	for i := 0; i < sourceValue.NumField(); i++ {
		sourceField := sourceValue.Field(i)
		targetField := targetValue.Field(i)
		if sourceField.IsZero() || !targetField.CanSet() {
			continue
		}
		targetField.Set(sourceField)
	}
	return s
}

func (s *Settings) ToProto() *spb.Settings {
	return &spb.Settings{
		ApiKey:         &wrapperspb.StringValue{Value: s.ApiKey},
		XOffline:       &wrapperspb.BoolValue{Value: s.IsOffline()},
		SyncDir:        &wrapperspb.StringValue{Value: s.GetSyncDir()},
		SyncFile:       &wrapperspb.StringValue{Value: s.GetSyncFile()},
		RunId:          &wrapperspb.StringValue{Value: s.RunID},
		ProjectUrl:     &wrapperspb.StringValue{Value: s.GetProjectURL()},
		RunUrl:         &wrapperspb.StringValue{Value: s.GetRunURL()},
		Project:        &wrapperspb.StringValue{Value: s.RunProject},
		Entity:         &wrapperspb.StringValue{Value: s.Entity},
		XStartTime:     &wrapperspb.DoubleValue{Value: float64(s.timeSpec.Unix())},
		XStartDatetime: &wrapperspb.StringValue{Value: s.timeSpec.Format("20060102_150405")},
		Timespec:       &wrapperspb.StringValue{Value: s.timeSpec.Format("20060102_150405")},

		RootDir:     &wrapperspb.StringValue{Value: s.RootDir},
		LogDir:      &wrapperspb.StringValue{Value: s.GetLogDir()},
		LogInternal: &wrapperspb.StringValue{Value: s.GetLogInternalFile()},
		LogUser:     &wrapperspb.StringValue{Value: s.GetLogUserFile()},
		FilesDir:    &wrapperspb.StringValue{Value: s.GetFilesDir()},

		BaseUrl: &wrapperspb.StringValue{Value: s.BaseURL},

		Username: &wrapperspb.StringValue{Value: s.Username},
		Email:    &wrapperspb.StringValue{Value: s.Email},

		Resume: &wrapperspb.StringValue{Value: string(ZeroIfNil(s.Resume))},

		DisableGit:         &wrapperspb.BoolValue{Value: s.DisableGit},
		DisableCode:        &wrapperspb.BoolValue{Value: s.DisableCode},
		XDisableStats:      &wrapperspb.BoolValue{Value: s.DisableStats},
		XDisableMeta:       &wrapperspb.BoolValue{Value: s.DisableMeta},
		DisableJobCreation: &wrapperspb.BoolValue{Value: s.DisableJobCreation},

		Console: &wrapperspb.StringValue{Value: string(s.Console)},

		XNoop: &wrapperspb.BoolValue{Value: s.IsDisabled()},

		CodeDir: &wrapperspb.StringValue{Value: s.GetCodeDir()},

		Mode: &wrapperspb.StringValue{Value: string(s.Mode)},

		Resumed: &wrapperspb.BoolValue{Value: s.resumed},

		RunGroup:   &wrapperspb.StringValue{Value: s.RunGroup},
		RunJobType: &wrapperspb.StringValue{Value: s.RunJobType},
		RunName:    &wrapperspb.StringValue{Value: s.RunName},
		RunNotes:   &wrapperspb.StringValue{Value: s.RunNotes},
		RunTags:    &spb.ListStringValue{Value: s.RunTags},

		TmpDir: &wrapperspb.StringValue{Value: s.GetTmpDir()},

		XFileStreamTimeoutSeconds: &wrapperspb.DoubleValue{
			Value: s.FileStreamTimeout,
		},
		XStatsSampleRateSeconds: &wrapperspb.DoubleValue{
			Value: s.StatsSampleRate,
		},
		XStatsSamplesToAverage: &wrapperspb.Int32Value{
			Value: s.StatsSamplesToAverage,
		},
	}
}

// Computed fields

func (s *Settings) GetStartTime() time.Time {
	return s.timeSpec
}

func (s *Settings) IsOffline() bool {
	return s.Mode == ModeOffline
}

func (s *Settings) IsDisabled() bool {
	return s.Mode == ModeDisabled
}

func (s *Settings) GetRunMode() string {
	if s.IsOffline() {
		return "offline-run"
	}
	return "run"
}

func (s *Settings) GetSyncDir() string {
	dirName := fmt.Sprintf("%s-%s-%s", s.GetRunMode(), s.timeSpec.Format("20060102_150405"), s.RunID)
	return filepath.Join(s.wandbDir, dirName)
}

func (s *Settings) GetSyncFile() string {
	fileName := fmt.Sprintf("run-%s.wandb", s.RunID)
	return filepath.Join(s.GetSyncDir(), fileName)
}

func (s *Settings) GetLogDir() string {
	return filepath.Join(s.GetSyncDir(), "logs")
}

func (s *Settings) GetFilesDir() string {
	return filepath.Join(s.GetSyncDir(), "files")
}

func (s *Settings) GetLogInternalFile() string {
	return filepath.Join(s.GetLogDir(), "debug-internal.log")
}

func (s *Settings) GetLogUserFile() string {
	return filepath.Join(s.GetLogDir(), "debug.log")
}

func (s *Settings) GetTmpDir() string {
	return filepath.Join(s.GetSyncDir(), "tmp")
}

func (s *Settings) GetCodeDir() string {
	return filepath.Join(s.GetTmpDir(), "code")
}

func (s *Settings) GetProjectURL() string {
	appURL := strings.Replace(s.BaseURL, "//api.", "//", 1)
	return fmt.Sprintf("%s/%s/%s", appURL, s.Entity, s.RunProject)
}

func (s *Settings) GetRunURL() string {
	return fmt.Sprintf("%s/runs/%s", s.GetProjectURL(), s.RunID)
}
