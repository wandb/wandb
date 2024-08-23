package tensorboard

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wbvalue"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

// Emitter modifies the run with data from a TF event.
type Emitter interface {
	// SetTFStep sets the TFEvent step for this W&B history step.
	//
	// This is only added to the history if EmitHistory is used.
	SetTFStep(key pathtree.TreePath, step int64)

	// SetTFWallTime sets the TFEvent wall time for this W&B history step.
	//
	// This is only added to the history if EmitHistory is used.
	SetTFWallTime(wallTime float64)

	// EmitHistory sets the value of a metric in this history step.
	EmitHistory(key pathtree.TreePath, valueJSON string)

	// EmitChart saves a chart to the run configuration.
	EmitChart(key string, chart wbvalue.Chart) error

	// EmitTable uploads a table as a file and records metadata
	// in the run history.
	EmitTable(key pathtree.TreePath, table wbvalue.Table) error
}

type nestedKeyAndJSON struct {
	KeyPath pathtree.TreePath
	JSON    string
}

// tfEmitter collects updates to a run based on TF events.
type tfEmitter struct {
	historyStep  []nestedKeyAndJSON
	configValues []nestedKeyAndJSON
	mediaFiles   []string

	hasTFStep bool
	tfStepKey []string
	tfStep    int64

	hasWallTime bool
	tfWallTime  float64

	settings *settings.Settings
}

func NewTFEmitter(settings *settings.Settings) *tfEmitter {
	return &tfEmitter{settings: settings}
}

// Emit sends accumulated data to the run.
func (e *tfEmitter) Emit(extraWork runwork.ExtraWork) {
	if rec := e.filesRecord(); rec != nil {
		extraWork.AddRecord(rec)
	}

	if rec := e.configRecord(); rec != nil {
		extraWork.AddRecord(rec)
	}

	if rec := e.historyRecord(); rec != nil {
		extraWork.AddRecord(rec)
	}
}

func (e *tfEmitter) filesRecord() *service.Record {
	if len(e.mediaFiles) == 0 {
		return nil
	}

	var files []*service.FilesItem
	for _, relativePath := range e.mediaFiles {
		files = append(files,
			&service.FilesItem{
				Path:   relativePath,
				Policy: service.FilesItem_NOW,
				Type:   service.FilesItem_MEDIA,
			})
	}

	return &service.Record{
		Control: &service.Control{Local: true},
		RecordType: &service.Record_Files{
			Files: &service.FilesRecord{
				Files: files,
			},
		},
	}
}

func (e *tfEmitter) configRecord() *service.Record {
	if len(e.configValues) == 0 {
		return nil
	}

	var items []*service.ConfigItem
	for _, value := range e.configValues {
		items = append(items,
			&service.ConfigItem{
				NestedKey: value.KeyPath.Labels(),
				ValueJson: value.JSON,
			})
	}

	return &service.Record{
		Control: &service.Control{Local: true},
		RecordType: &service.Record_Config{
			Config: &service.ConfigRecord{
				Update: items,
			},
		},
	}
}

func (e *tfEmitter) historyRecord() *service.Record {
	if len(e.historyStep) == 0 {
		return nil
	}

	var items []*service.HistoryItem
	for _, value := range e.historyStep {
		items = append(items,
			&service.HistoryItem{
				NestedKey: value.KeyPath.Labels(),
				ValueJson: value.JSON,
			})
	}

	if e.hasTFStep {
		items = append(items,
			&service.HistoryItem{
				NestedKey: e.tfStepKey,
				ValueJson: fmt.Sprintf("%v", e.tfStep),
			})
	}

	if e.hasWallTime {
		items = append(items,
			&service.HistoryItem{
				Key:       "_timestamp",
				ValueJson: fmt.Sprintf("%v", e.tfWallTime),
			})
	}

	return &service.Record{
		Control: &service.Control{Local: true},
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_PartialHistory{
					PartialHistory: &service.PartialHistoryRequest{
						Item: items,

						// Setting "Flush" indicates that the event should be uploaded as
						// its own history row, rather than combined with future events.
						// Future events may contain new values for the same keys.
						Action: &service.HistoryAction{Flush: true},
					},
				},
			},
		},
	}
}

func (e *tfEmitter) SetTFStep(key pathtree.TreePath, step int64) {
	e.hasTFStep = true
	e.tfStepKey = key.Labels()
	e.tfStep = step
}

func (e *tfEmitter) SetTFWallTime(wallTime float64) {
	e.hasWallTime = true
	e.tfWallTime = wallTime
}

func (e *tfEmitter) EmitHistory(key pathtree.TreePath, valueJSON string) {
	e.historyStep = append(e.historyStep,
		nestedKeyAndJSON{
			KeyPath: key,
			JSON:    valueJSON,
		})
}

func (e *tfEmitter) EmitChart(key string, chart wbvalue.Chart) error {
	valueJSON, err := chart.ConfigValueJSON()
	if err != nil {
		return fmt.Errorf("error encoding chart metadata: %v", err)
	}

	e.configValues = append(e.configValues,
		nestedKeyAndJSON{
			KeyPath: chart.ConfigKey(key),
			JSON:    valueJSON,
		})
	return nil
}

func (e *tfEmitter) EmitTable(
	key pathtree.TreePath,
	table wbvalue.Table,
) error {
	content, err := table.FileContent()
	if err != nil {
		return fmt.Errorf("error serializing table data: %v", err)
	}

	maybeRunFilePath, err := tableRunRelativePath()
	if err != nil {
		return err
	}
	runRelativePath := *maybeRunFilePath
	fsPath := filepath.Join(e.settings.GetFilesDir(), string(runRelativePath))

	if _, err := os.Stat(fsPath); !os.IsNotExist(err) {
		return fmt.Errorf("table file exists: %v", err)
	}

	historyJSON, err := table.HistoryValueJSON(
		runRelativePath,
		string(utils.ComputeSHA256(content)),
		len(content),
	)
	if err != nil {
		return fmt.Errorf("error encoding table metadata: %v", err)
	}

	if err := os.MkdirAll(filepath.Dir(fsPath), 0777); err != nil {
		return fmt.Errorf("error creating directory: %v", err)
	}
	if err := os.WriteFile(fsPath, content, 0644); err != nil {
		return fmt.Errorf("error writing table to file: %v", err)
	}

	e.mediaFiles = append(e.mediaFiles, string(runRelativePath))
	e.historyStep = append(e.historyStep,
		nestedKeyAndJSON{
			KeyPath: key,
			JSON:    historyJSON,
		})
	return nil
}

func tableRunRelativePath() (*paths.RelativePath, error) {
	// NOTE: This could name an existing file by coincidence.
	//
	// We don't add the table key to avoid having to sanitize it
	// to be a valid filename.
	maybeRunFilePath, err := paths.Relative(
		filepath.Join(
			"media", "table",
			fmt.Sprintf(
				"%s.table.json",
				utils.ShortID(32),
			)),
	)

	if err != nil {
		return nil, err
	}

	return maybeRunFilePath, err
}
