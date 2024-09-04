// TODO: this code desperately needs love and refactoring
package launch

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/data_types"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/pkg/artifacts"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/core/pkg/utils"
)

type SourceType string

const (
	RepoSourceType     SourceType = "repo"
	ArtifactSourceType SourceType = "artifact"
	ImageSourceType    SourceType = "image"
	WandbConfigKey     string     = "@wandb.config"
)

const REQUIREMENTS_FNAME = "requirements.txt"
const FROZEN_REQUIREMENTS_FNAME = "requirements.frozen.txt"
const DIFF_FNAME = "diff.patch"
const WANDB_METADATA_FNAME = "wandb-metadata.json"
const BASE_JOB_VERSION = "v0"

type LogLevel int

const (
	Log LogLevel = iota
	Warn
	Error
)

type RunMetadata struct {
	SourceType    *SourceType `json:"source_type"`
	Partial       *string     `json:"_partial"`
	Git           *GitInfo    `json:"git"`
	Root          *string     `json:"root"`
	Docker        *string     `json:"docker"`
	Program       *string     `json:"program"`
	CodePathLocal *string     `json:"codePathLocal"`
	CodePath      *string     `json:"codePath"`
	Entrypoint    *[]string   `json:"entrypoint"`
	Python        *string     `json:"python"`
}

// Define the Source interface with a common method.
type Source interface {
	GetSourceType() SourceType
	GetSourceGit() *GitInfo
	GetSourceArtifact() *string
	GetSourceImage() *string
}

// Define the GitInfo struct.
type GitInfo struct {
	Remote *string `json:"remote"`
	Commit *string `json:"commit"`
}

// Define the GitSource struct that implements the Source interface.
type GitSource struct {
	Git          GitInfo  `json:"git"`
	Entrypoint   []string `json:"entrypoint"`
	Notebook     bool     `json:"notebook"`
	BuildContext *string  `json:"build_context,omitempty"`
	Dockerfile   *string  `json:"dockerfile,omitempty"`
}

func (g GitSource) GetSourceType() SourceType {
	return RepoSourceType
}

func (g GitSource) GetSourceGit() *GitInfo {
	return &g.Git
}

func (g GitSource) GetSourceArtifact() *string {
	return nil
}

func (g GitSource) GetSourceImage() *string {
	return nil
}

// Define the ArtifactSource struct that implements the Source interface.
type ArtifactSource struct {
	Artifact     string   `json:"artifact"`
	Entrypoint   []string `json:"entrypoint"`
	Notebook     bool     `json:"notebook"`
	BuildContext *string  `json:"build_context,omitempty"`
	Dockerfile   *string  `json:"dockerfile,omitempty"`
}

func (a ArtifactSource) GetSourceType() SourceType {
	return ArtifactSourceType
}

func (a ArtifactSource) GetSourceGit() *GitInfo {
	return nil
}

func (a ArtifactSource) GetSourceArtifact() *string {
	return &a.Artifact
}

func (a ArtifactSource) GetSourceImage() *string {
	return nil
}

// Define the ImageSource struct that implements the Source interface.
type ImageSource struct {
	Image string `json:"image"`
}

func (i ImageSource) GetSourceType() SourceType {
	return ImageSourceType
}

func (i ImageSource) GetSourceGit() *GitInfo {
	return nil
}

func (i ImageSource) GetSourceArtifact() *string {
	return nil
}

func (i ImageSource) GetSourceImage() *string {
	return &i.Image
}

// Define the JobSourceMetadata struct.
type JobSourceMetadata struct {
	Version string `json:"_version"`
	Source  Source `json:"source"`
	// this field is used by launch to determine the flow for launching the job
	// see public.py.Job for more info

	SourceType  SourceType                    `json:"source_type"`
	InputTypes  data_types.TypeRepresentation `json:"input_types"`
	OutputTypes data_types.TypeRepresentation `json:"output_types"`
	Runtime     *string                       `json:"runtime,omitempty"`
	Partial     *string                       `json:"_partial,omitempty"`
}

type ArtifactInfoForJob struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type JobBuilder struct {
	logger *observability.CoreLogger

	PartialJobID *string

	verbose bool

	Disable               bool
	settings              *spb.Settings
	RunCodeArtifact       *ArtifactInfoForJob
	aliases               []string
	isNotebookRun         bool
	runConfig             *runconfig.RunConfig
	wandbConfigParameters *launchWandbConfigParameters
	configFiles           []*configFileParameter
	saveShapeToMetadata   bool
}

func MakeArtifactNameSafe(name string) string {
	// Replace characters that are not alphanumeric, underscore, hyphen, or period with underscore
	cleaned := regexp.MustCompile(`[^a-zA-Z0-9_\-.]`).ReplaceAllString(name, "_")

	if len(cleaned) <= 128 {
		return cleaned
	}

	// Truncate with dots in the middle using regex
	regex := regexp.MustCompile(`(^.{63}).*(.{63}$)`)
	truncated := regex.ReplaceAllString(cleaned, "$1..$2")

	return truncated

}

func NewJobBuilder(settings *spb.Settings, logger *observability.CoreLogger, verbose bool) *JobBuilder {
	jobBuilder := JobBuilder{
		settings:            settings,
		isNotebookRun:       settings.GetXJupyter().GetValue(),
		logger:              logger,
		Disable:             settings.GetDisableJobCreation().GetValue(),
		saveShapeToMetadata: false,
		verbose:             verbose,
	}
	return &jobBuilder
}

func (j *JobBuilder) logIfVerbose(msg string, level LogLevel) {

	switch {
	case level == Log:
		j.logger.Info(msg)
	case level == Warn:
		j.logger.Warn(msg)
	case level == Error:
		j.logger.Error(msg)
	default:
		j.logger.Info(msg)
	}

	if j.verbose {
		// TODO: we should pass messages back to the user
		// and print them there, instead of printing them here
		fmt.Println(msg)
	}
}

func (j *JobBuilder) handleMetadataFile() (*RunMetadata, error) {
	file, err := os.Open(filepath.Join(j.settings.FilesDir.Value, WANDB_METADATA_FNAME))
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var runMetadata RunMetadata
	err = json.NewDecoder(file).Decode(&runMetadata)
	if err != nil {
		return nil, err
	}

	return &runMetadata, nil
}

func (j *JobBuilder) getProgramRelpath(metadata RunMetadata, sourceType SourceType) *string {
	if j.isNotebookRun {
		if metadata.Program == nil {
			j.logIfVerbose(
				"Notebook 'program' path not found in metadata. See https://docs.wandb.ai/guides/launch/create-job",
				Warn,
			)
		}
		return metadata.Program
	}
	if sourceType == ArtifactSourceType {
		// if the job is set to be an artifact, use codePathLocal guaranteed
		// to be correct. 'codePath' uses the root path when in git repo
		// fallback to codePath if strictly codePathLocal not present
		if metadata.CodePathLocal != nil {
			return metadata.CodePathLocal
		}
	}
	return metadata.CodePath

}

func (j *JobBuilder) SetRunConfig(config runconfig.RunConfig) {
	j.runConfig = &config
}

func (j *JobBuilder) GetSourceType(metadata RunMetadata) (*SourceType, error) {
	var finalSourceType SourceType
	// user set source type via settings
	switch j.settings.GetJobSource().GetValue() {
	case string(ArtifactSourceType):
		if !j.hasArtifactJobIngredients() {
			j.logIfVerbose("No artifact job ingredients found, not creating job artifact", Warn)
			return nil, fmt.Errorf("no artifact job ingredients found, but source type set to artifact")
		}
		finalSourceType = ArtifactSourceType
		return &finalSourceType, nil
	case string(RepoSourceType):
		if !j.hasRepoJobIngredients(metadata) {
			j.logIfVerbose("No repo job ingredients found, not creating job artifact", Warn)
			return nil, fmt.Errorf("no repo job ingredients found, but source type set to repo")
		}
		finalSourceType = RepoSourceType
		return &finalSourceType, nil
	case string(ImageSourceType):
		if !j.hasImageJobIngredients(metadata) {
			j.logIfVerbose("No image job ingredients found, not creating job artifact", Warn)
			return nil, fmt.Errorf("no image job ingredients found, but source type set to image")
		}
		finalSourceType = ImageSourceType
		return &finalSourceType, nil
	default:
		// no source type set, try to determine source type
		if j.hasRepoJobIngredients(metadata) {
			finalSourceType = RepoSourceType
			return &finalSourceType, nil
		}
		if j.hasArtifactJobIngredients() {
			finalSourceType = ArtifactSourceType
			return &finalSourceType, nil
		}
		if j.hasImageJobIngredients(metadata) {
			finalSourceType = ImageSourceType
			return &finalSourceType, nil
		}
	}

	j.logIfVerbose("No job ingredients found, not creating job artifact", Warn)
	j.logger.Debug("jobBuilder: unable to determine source type")
	return nil, nil

}

func (j *JobBuilder) getEntrypoint(programPath string, metadata RunMetadata) ([]string, error) {
	// if building a partial job from CLI, overwrite entrypoint and notebook
	// should already be in metadata from create_job
	if metadata.Partial != nil {
		// artifacts have a python and a code path but no entrypoint
		if metadata.Entrypoint != nil {
			return *metadata.Entrypoint, nil
		}
	}
	// python is not set for images on the create from CLI flow
	fullPython := metadata.Python
	if fullPython == nil {
		return nil, fmt.Errorf("missing python attribute in metadata class")
	}
	// drop everything after the last second .
	pythonVersion := strings.Join(strings.Split(*fullPython, ".")[:2], ".")
	return []string{fmt.Sprintf("python%s", pythonVersion), programPath}, nil

}

func (j *JobBuilder) makeJobName(derivedName string) string {
	if j.settings.JobName != nil {
		return j.settings.JobName.Value
	}
	return MakeArtifactNameSafe(fmt.Sprintf("job-%s", derivedName))
}

func (j *JobBuilder) hasRepoJobIngredients(metadata RunMetadata) bool {
	// notebook sourced jobs only work if the metadata has the root key filled from the run
	if metadata.Root == nil && j.isNotebookRun {
		return false
	}
	if metadata.Git != nil {
		return metadata.Git.Commit != nil && metadata.Git.Remote != nil
	}
	return false
}

func (j *JobBuilder) hasArtifactJobIngredients() bool {
	return j.RunCodeArtifact != nil
}

func (j *JobBuilder) hasImageJobIngredients(metadata RunMetadata) bool {
	return metadata.Docker != nil
}

func (j *JobBuilder) getSourceAndName(sourceType SourceType, programRelpath *string, metadata RunMetadata) (Source, *string, error) {
	switch {
	case sourceType == RepoSourceType:
		if programRelpath == nil {
			return nil, nil, fmt.Errorf("no program path found for repo sourced job")
		}
		return j.createRepoJobSource(*programRelpath, metadata)
	case sourceType == ArtifactSourceType:
		if programRelpath == nil {
			return nil, nil, fmt.Errorf("no program path found for artifact sourced job")
		}
		return j.createArtifactJobSource(*programRelpath, metadata)
	case sourceType == ImageSourceType:
		return j.createImageJobSource(metadata)
	default:
		// TODO: warn if source type was set to something different
		return nil, nil, nil
	}
}

func (j *JobBuilder) HandlePathsAboveRoot(programRelpath, root string) (string, error) {
	// git notebooks set root to the git root,
	// XJupyterRoot contains the path where the jupyter notebook was started
	// programRelpath contains the path from XJupyterRoot to the file
	// fullProgramPath here is actually the relpath from the root to the program
	rootRelPath, err := filepath.Rel(root, j.settings.GetXJupyterRoot().GetValue())
	if err != nil {
		return "", err
	}
	fullProgramPath := filepath.Clean(filepath.Join(rootRelPath, programRelpath))
	if strings.HasPrefix(fullProgramPath, "..") {
		splitPath := strings.Split(fullProgramPath, "/")
		countDots := 0
		for _, p := range splitPath {
			if p == ".." {
				countDots += 1
			}
			fullProgramPath = strings.Join(splitPath[2*countDots:], "/")
		}
	}
	return fullProgramPath, nil
}

func (j *JobBuilder) createRepoJobSource(programRelpath string, metadata RunMetadata) (*GitSource, *string, error) {
	j.logger.Debug("jobBuilder: creating repo job source")
	fullProgramPath := programRelpath
	if j.isNotebookRun {
		cwd, err := os.Getwd()
		if err != nil {
			return nil, nil, err
		}

		_, err = os.Stat(filepath.Join(cwd, filepath.Base(programRelpath)))
		if os.IsNotExist(err) {
			j.logIfVerbose("Unable to find program entrypoint in current directory, not creating job artifact.", Warn)
			return nil, nil, nil
		} else if err != nil {
			return nil, nil, err
		}

		if metadata.Root == nil || j.settings.XJupyterRoot == nil {
			return nil, nil, fmt.Errorf("no root path in metadata, or settings missing jupyter root, not creating job artifact")
		}
		fullProgramPath, err = j.HandlePathsAboveRoot(programRelpath, *metadata.Root)
		if err != nil {
			return nil, nil, err
		}
	}
	entryPoint, err := j.getEntrypoint(fullProgramPath, metadata)
	if err != nil {
		return nil, nil, err
	}
	source := &GitSource{
		Git:        *metadata.Git,
		Entrypoint: entryPoint,
		Notebook:   j.isNotebookRun,
	}
	rawName := fmt.Sprintf("%s_%s", *metadata.Git.Remote, programRelpath)
	name := j.makeJobName(rawName)
	return source, &name, nil

}

func (j *JobBuilder) createArtifactJobSource(programRelPath string, metadata RunMetadata) (*ArtifactSource, *string, error) {
	j.logger.Debug("jobBuilder: creating artifact job source")
	var fullProgramRelPath string
	// TODO: should we just always exit early if the path doesn't exist?
	if j.isNotebookRun && !j.settings.GetXColab().GetValue() {
		fullProgramRelPath = programRelPath
		// if the resolved path doesn't exist, then we shouldn't make a job because it will fail
		// but we should check because when users call log code in a notebook the code artifact
		// starts at the directory the notebook is in instead of the jupyter core
		if _, err := os.Stat(programRelPath); os.IsNotExist(err) {
			fullProgramRelPath = filepath.Base(programRelPath)
			if _, err := os.Stat(filepath.Base(fullProgramRelPath)); os.IsNotExist(err) {
				j.logIfVerbose("No program path found when generating artifact job source for a non-colab notebook run. See https://docs.wandb.ai/guides/launch/create-job", Warn)
				return nil, nil, err
			}
		}
	} else {
		fullProgramRelPath = programRelPath
	}

	entrypoint, err := j.getEntrypoint(fullProgramRelPath, metadata)
	if err != nil {
		return nil, nil, err
	}
	// TODO: update executable to a method that supports pex
	source := &ArtifactSource{
		Artifact:   "wandb-artifact://_id/" + j.RunCodeArtifact.ID,
		Notebook:   j.isNotebookRun,
		Entrypoint: entrypoint,
	}
	name := j.makeJobName(j.RunCodeArtifact.Name)

	return source, &name, nil
}

func (j *JobBuilder) createImageJobSource(metadata RunMetadata) (*ImageSource, *string, error) {
	j.logger.Debug("jobBuilder: creating image job source")
	if metadata.Docker == nil {
		return nil, nil, fmt.Errorf("no docker image provided for image sourced job")
	}
	imageName := *metadata.Docker

	rawImageName := imageName
	if tagIndex := strings.LastIndex(imageName, ":"); tagIndex != -1 {
		tag := imageName[tagIndex+1:]

		// if tag looks properly formatted, assume it's a tag
		// regex: alphanumeric and "_", "-", "."
		if matched, _ := regexp.MatchString(`^[a-zA-Z0-9_\-\.]+$`, tag); matched {
			rawImageName = strings.Replace(imageName, fmt.Sprintf(":%s", tag), "", 1)
			j.aliases = append(j.aliases, tag)
		}
	}

	source := &ImageSource{
		Image: imageName,
	}
	name := j.makeJobName(rawImageName)

	return source, &name, nil
}

func (j *JobBuilder) Build(
	ctx context.Context,
	client graphql.Client,
	output map[string]interface{},
) (artifact *spb.ArtifactRecord, rerr error) {
	j.logger.Debug("jobBuilder: building job artifact")
	if j.Disable {
		j.logger.Debug("jobBuilder: disabled")
		return nil, nil
	}
	if j.PartialJobID != nil {
		// If we have a partial job source we just update the
		// metadata and don't build the job.
		typed_output := data_types.ResolveTypes(output)
		metadata, err := j.MakeJobMetadata(&typed_output)
		if err != nil {
			return nil, err
		}
		_, err = gql.UpdateArtifact(
			ctx, client, *j.PartialJobID, &metadata,
		)
		if err != nil {
			return nil, err
		}
		return nil, nil
	}

	fileDir := j.settings.FilesDir.GetValue()
	_, err := os.Stat(filepath.Join(fileDir, REQUIREMENTS_FNAME))
	if os.IsNotExist(err) {
		j.logger.Debug("jobBuilder: no requirements.txt found")
		j.logIfVerbose(
			"No requirements.txt found, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job",
			Warn,
		)
		return nil, nil
	}

	metadata, err := j.handleMetadataFile()
	if err != nil {
		j.logger.Debug("jobBuilder: error handling metadata file", "error", err)
		return nil, err
	}

	if metadata.Python == nil {
		j.logger.Debug("jobBuilder: no python version found in metadata")
		j.logIfVerbose("No python version found in metadata, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job", Warn)
		return nil, nil
	}

	var sourceInfo JobSourceMetadata
	var name *string
	var sourceType *SourceType

	sourceType, err = j.GetSourceType(*metadata)
	if err != nil {
		return nil, err
	}
	if sourceType == nil {
		j.logger.Debug("jobBuilder: unable to determine source type")
		j.logIfVerbose("No source type found, not creating job artifact", Warn)
		return nil, nil
	}
	programRelpath := j.getProgramRelpath(*metadata, *sourceType)
	// all jobs except image jobs need to specify a program path
	if *sourceType != ImageSourceType && programRelpath == nil {
		j.logger.Debug("jobBuilder: no program path found")
		j.logIfVerbose("No program path found, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job", Warn)
		return nil, nil
	}

	var jobSource Source
	jobSource, name, err = j.getSourceAndName(*sourceType, programRelpath, *metadata)
	if err != nil {
		return nil, err
	} else if jobSource == nil || name == nil {
		j.logger.Debug("jobBuilder: no job source or name found")
		return nil, nil
	}
	sourceInfo.Source = jobSource
	sourceInfo.SourceType = *sourceType

	sourceInfo.Version = BASE_JOB_VERSION

	// inject partial field for create job CLI flow
	if metadata.Partial != nil {
		sourceInfo.Partial = metadata.Partial
	}

	sourceInfo.Runtime = metadata.Python
	if output != nil {
		sourceInfo.OutputTypes = data_types.ResolveTypes(output)
	}
	var metadataString string
	if j.saveShapeToMetadata {
		metadataString, err = j.MakeJobMetadata(&sourceInfo.OutputTypes)
		if err != nil {
			return nil, err
		}
		sourceInfo.InputTypes = data_types.ResolveTypes(map[string]interface{}{})
	} else {
		metadataString = ""
		if j.runConfig == nil {
			sourceInfo.InputTypes = data_types.ResolveTypes(map[string]interface{}{})
		} else {
			sourceInfo.InputTypes = data_types.ResolveTypes(j.runConfig.CloneTree())
		}
	}

	baseArtifact := &spb.ArtifactRecord{
		Entity:           j.settings.GetEntity().GetValue(),
		Project:          j.settings.Project.Value,
		RunId:            j.settings.RunId.Value,
		Name:             *name,
		Metadata:         metadataString,
		Type:             "job",
		Aliases:          append(j.aliases, "latest"),
		Finalize:         true,
		ClientId:         utils.GenerateAlphanumericSequence(128),
		SequenceClientId: utils.GenerateAlphanumericSequence(128),
		UseAfterCommit:   true,
		UserCreated:      true,
	}

	return j.buildArtifact(baseArtifact, sourceInfo, fileDir, *sourceType)
}

func (j *JobBuilder) buildArtifact(
	baseArtifact *spb.ArtifactRecord,
	sourceInfo JobSourceMetadata,
	fileDir string,
	sourceType SourceType,
) (*spb.ArtifactRecord, error) {
	artifactBuilder := artifacts.NewArtifactBuilder(baseArtifact)

	err := artifactBuilder.AddFile(filepath.Join(fileDir, REQUIREMENTS_FNAME), FROZEN_REQUIREMENTS_FNAME)
	if err != nil {
		return nil, err
	}

	err = artifactBuilder.AddData("wandb-job.json", sourceInfo)
	if err != nil {
		return nil, err
	}

	if sourceType == RepoSourceType {
		_, err = os.Stat(filepath.Join(fileDir, DIFF_FNAME))
		if err == nil {
			err = artifactBuilder.AddFile(filepath.Join(fileDir, DIFF_FNAME), DIFF_FNAME)
			if err != nil {
				return nil, err
			}
		} else if !os.IsNotExist(err) {
			return nil, err
		}
	}
	return artifactBuilder.GetArtifact(), nil
}

func (j *JobBuilder) HandleUseArtifactRecord(record *spb.Record) {
	j.logger.Debug("jobBuilder: handling use artifact record")
	// configure job builder to either not build a job, because a full job has been used
	// or to configure to build a complete job from a partial job
	useArtifact := record.GetUseArtifact()
	if useArtifact == nil || useArtifact.Type != "job" {
		return
	}

	if useArtifact.Type == "job" && useArtifact.Partial == nil {
		j.logger.Debug("jobBuilder: run comes from used, nonpartial, job. Disabling job builder")
		j.Disable = true
		return
	}

	// if empty job name, disable job builder
	if useArtifact.Partial != nil && len(useArtifact.Partial.JobName) == 0 {
		j.logger.Debug("jobBuilder: no job name found in partial use artifact record, disabling job builder")
		j.Disable = true
		return
	}

	j.PartialJobID = &useArtifact.Id
}

func (j *JobBuilder) MakeFilesAndSchemas() (map[string]any, map[string]any, error) {
	files := make(map[string]any)
	file_schemas := make(map[string]any)
	for _, configFile := range j.configFiles {
		files[configFile.relpath] = j.generateConfigFileSchema(configFile)
		if configFile.inputSchema != nil {
			var inputSchemaMap map[string]any
			err := json.Unmarshal([]byte(*configFile.inputSchema), &inputSchemaMap)
			if err != nil {
				return nil, nil, err
			}
			file_schemas[configFile.relpath] = inputSchemaMap
		}
	}
	return files, file_schemas, nil
}

// Makes job input schema into a json string to be stored as artifact metadata.
func (j *JobBuilder) MakeJobMetadata(output *data_types.TypeRepresentation) (string, error) {
	metadata := make(map[string]any)
	input_types := make(map[string]any)
	input_schemas := make(map[string]any)
	if len(j.configFiles) > 0 {
		files, file_schemas, err := j.MakeFilesAndSchemas()
		if err != nil {
			return "", err
		}
		input_types["files"] = files
		if len(file_schemas) > 0 {
			input_schemas["files"] = file_schemas
		}
	}
	if j.runConfig != nil && j.wandbConfigParameters != nil {
		runConfigTypes, err := j.inferRunConfigTypes()
		if err == nil {
			input_types[WandbConfigKey] = runConfigTypes
		} else {
			j.logger.Debug("jobBuilder: error inferring run config types", "error", err)
		}
		if j.wandbConfigParameters.inputSchema != nil {
			var inputSchemaMap map[string]any
			err = json.Unmarshal([]byte(*j.wandbConfigParameters.inputSchema), &inputSchemaMap)
			if err != nil {
				return "", err
			}
			input_schemas[WandbConfigKey] = inputSchemaMap
		}
	}

	metadata["input_types"] = input_types
	if output != nil {
		metadata["output_types"] = data_types.ResolveTypes(*output)
	}
	if len(input_schemas) > 0 {
		metadata["input_schemas"] = input_schemas
	}

	metadataBytes, err := json.Marshal(metadata)
	if err != nil {
		return "", err
	}
	return string(metadataBytes), nil
}

func (j *JobBuilder) HandleLogArtifactResult(response *spb.LogArtifactResponse, record *spb.ArtifactRecord) {
	if j == nil {
		return
	}
	j.logger.Debug("jobBuilder: handling log artifact result")
	if response == nil || response.ErrorMessage != "" {
		return
	}
	if record.GetType() == "code" {
		j.RunCodeArtifact = &ArtifactInfoForJob{
			ID:   response.ArtifactId,
			Name: record.Name,
		}
	}
}

// Configure a new job input for the job builder.
//
// This method is called when a user declares a new variable input for their
// job. The request specifies the source of the input (a file or the run config)
// and sets of keys in that config to include or exclude from the input. The
// key sets are expressed as path prefixes in the config.
func (j *JobBuilder) HandleJobInputRequest(request *spb.JobInputRequest) {
	// If job builder is disabled. This happens if run is created from a job.
	if j == nil {
		return
	}
	j.saveShapeToMetadata = true
	j.logger.Debug("jobBuilder: handling job input request")
	if request == nil {
		j.logger.Error("jobBuilder: job input request is nil")
		return
	}
	source := request.GetInputSource()
	switch source := source.GetSource().(type) {
	case *spb.JobInputSource_File:
		schema := utils.NilIfZero(request.GetInputSchema())
		newInput, err := newFileInputFromProto(
			source,
			request.GetIncludePaths(),
			request.GetExcludePaths(),
			schema,
		)
		if err != nil {
			j.logger.Error("jobBuilder: error creating file input from request", "error", err)
			return
		}
		j.configFiles = append(j.configFiles, newInput)
	case *spb.JobInputSource_RunConfig:
		if j.wandbConfigParameters == nil {
			j.wandbConfigParameters = newWandbConfigParameters()
		}
		j.wandbConfigParameters.appendIncludePaths(request.GetIncludePaths())
		j.wandbConfigParameters.appendExcludePaths(request.GetExcludePaths())
		j.wandbConfigParameters.inputSchema = utils.NilIfZero(request.InputSchema)
	}
}
