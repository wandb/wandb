package launch

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/wandb/wandb/core/pkg/artifacts"
	"github.com/wandb/wandb/core/pkg/service"
)

type SourceType string

const (
	RepoSourceType     SourceType = "repo"
	ArtifactSourceType SourceType = "artifact"
	ImageSourceType    SourceType = "image"
)

const REQUIREMENTS_FNAME = "requirements.txt"
const FROZEN_REQUIREMENTS_FNAME = "requirements.frozen.txt"
const DIFF_FNAME = "diff.patch"
const WANDB_METADATA_FNAME = "wandb-metadata.json"

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
}

// Define the GitInfo struct.
type GitInfo struct {
	Remote *string `json:"remote"`
	Commit *string `json:"commit"`
}

// Define the GitSource struct that implements the Source interface.
type GitSource struct {
	Git        GitInfo  `json:"git"`
	Entrypoint []string `json:"entrypoint"`
	Notebook   bool     `json:"notebook"`
}

func (g GitSource) GetSourceType() SourceType {
	return RepoSourceType
}

// Define the ArtifactSource struct that implements the Source interface.
type ArtifactSource struct {
	Artifact   string   `json:"artifact"`
	Entrypoint []string `json:"entrypoint"`
	Notebook   bool     `json:"notebook"`
}

func (a ArtifactSource) GetSourceType() SourceType {
	return ArtifactSourceType
}

// Define the ImageSource struct that implements the Source interface.
type ImageSource struct {
	Image string `json:"image"`
}

func (i ImageSource) GetSourceType() SourceType {
	return ImageSourceType
}

// Define the JobSourceMetadata struct.
type JobSourceMetadata struct {
	Version     string                 `json:"_version"`
	Source      Source                 `json:"source"`
	SourceType  SourceType             `json:"source_type"`
	InputTypes  map[string]interface{} `json:"input_types"`
	OutputTypes map[string]interface{} `json:"output_types"`
	Runtime     *string                `json:"runtime,omitempty"`
	Partial     *string                `json:"_partial,omitempty"`
}

type ArtifactInfoForJob struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type PartialJobSource struct {
	JobName       string            `json:"job_name"`
	JobSourceInfo JobSourceMetadata `json:"job_source_info"`
}

type JobBuilder struct {
	settings        *service.Settings
	runCodeArtifact *ArtifactInfoForJob
	// disable          bool
	partialJobSource *PartialJobSource
	aliases          []string
	// jobSequenceId    *string
	// jobVersionAlias  *string
	isNotebookRun bool
}

func makeArtifactNameSafe(name string) string {
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

func isNotbookRunFromSettings(settings *service.Settings) bool {
	xJupyter := settings.GetXJupyter()
	if xJupyter != nil {
		return xJupyter.Value
	}
	return false
}

func isColabRunFromSettings(settings *service.Settings) bool {
	xColab := settings.GetXColab()
	if xColab != nil {
		return xColab.Value
	}
	return false
}

func NewJobBuilder(settings *service.Settings) JobBuilder {
	isNotebookRun := isNotbookRunFromSettings(settings)
	jobBuilder := JobBuilder{
		settings:      settings,
		isNotebookRun: isNotebookRun,
	}
	return jobBuilder
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
			fmt.Println(
				"Notebook 'program' path not found in metadata. See https://docs.wandb.ai/guides/launch/create-job",
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

func (j *JobBuilder) getSourceType(metadata RunMetadata) *SourceType {
	var finalSourceType SourceType
	// user set source type via settings
	if j.settings.JobSource != nil {
		sourceType := j.settings.JobSource.Value
		switch sourceType {
		case string(ArtifactSourceType):
			finalSourceType = ArtifactSourceType
			return &finalSourceType
		case string(RepoSourceType):
			finalSourceType = RepoSourceType
			return &finalSourceType
		case string(ImageSourceType):
			finalSourceType = ImageSourceType
			return &finalSourceType
		}
	}
	if j.hasRepoJobIngredients(metadata) {
		finalSourceType = RepoSourceType
		return &finalSourceType
	}
	if j.hasArtifactJobIngredients() {
		finalSourceType = ArtifactSourceType
		return &finalSourceType
	}
	if j.hasImageJobIngredients(metadata) {
		finalSourceType = ImageSourceType
		return &finalSourceType
	}
	// TODO: log
	return nil

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
	return makeArtifactNameSafe(fmt.Sprintf("job-%s", derivedName))
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
	return j.runCodeArtifact != nil
}

func (j *JobBuilder) hasImageJobIngredients(metadata RunMetadata) bool {
	return metadata.Docker != nil
}

func (j *JobBuilder) buildRepoJobSource(programRelpath string, metadata RunMetadata) (*GitSource, *string, error) {
	fullProgramPath := programRelpath
	if j.isNotebookRun {
		cwd, err := os.Getwd()
		if err != nil {
			return nil, nil, err
		}
		_, err = os.Stat(filepath.Join(cwd, filepath.Base(programRelpath)))
		if os.IsNotExist(err) {
			return nil, nil, nil
		} else if err != nil {
			return nil, nil, err
		}

		if metadata.Root == nil || j.settings.XJupyterRoot == nil {
			return nil, nil, nil
		}
		// git notebooks set the root to the git root,
		// jupyter_root contains the path where the jupyter notebook was started
		// program_relpath contains the path from jupyter_root to the file
		// full program path here is actually the relpath from the program to the git root
		rootRelPath, err := filepath.Rel(j.settings.XJupyterRoot.Value, *metadata.Root)
		if err != nil {
			return nil, nil, err
		}
		fullProgramPath = filepath.Clean(filepath.Join(rootRelPath, programRelpath))
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

func (j *JobBuilder) buildArtifactJobSource(programRelPath string, metadata RunMetadata) (*ArtifactSource, *string, error) {
	var fullProgramRelPath string
	// TODO: should we just always exit early if the path doesn't exist?
	if j.isNotebookRun && !isColabRunFromSettings(j.settings) {
		cwd, err := os.Getwd()
		if err != nil {
			return nil, nil, err
		}
		fullProgramRelPath := filepath.Join(cwd, programRelPath)

		// if the resolved path doesn't exist, then we shouldn't make a job because it will fail
		// but we should check because when users call log code in a notebook the code artifact
		// starts at the directory the notebook is in instead of the jupyter core
		if _, err := os.Stat(fullProgramRelPath); os.IsNotExist(err) {
			fullProgramRelPath = filepath.Base(programRelPath)
			if _, err := os.Stat(filepath.Base(fullProgramRelPath)); os.IsNotExist(err) {
				fmt.Println("No program path found when generating artifact job source for a non-colab notebook run. See https://docs.wandb.ai/guides/launch/create-job")
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
		Artifact:   "wandb-artifact://_id/" + j.runCodeArtifact.ID,
		Notebook:   j.isNotebookRun,
		Entrypoint: entrypoint,
	}
	name := j.makeJobName(j.runCodeArtifact.Name)

	return source, &name, nil
}
func (j *JobBuilder) buildImageJobSource(metadata RunMetadata) (*ImageSource, *string, error) {
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

func (j *JobBuilder) Build() (artifact *service.ArtifactRecord, rerr error) {
	fileDir := j.settings.FilesDir.GetValue()
	_, err := os.Stat(filepath.Join(fileDir, REQUIREMENTS_FNAME))
	if os.IsNotExist(err) {
		fmt.Println(
			"No requirements.txt found, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job",
		)
		return nil, nil
	}

	metadata, err := j.handleMetadataFile()
	if err != nil {
		return nil, err
	} else if metadata == nil {
		fmt.Printf("Ensure read and write access to run files dir: %s, control this via the WANDB_DIR env var. See https://docs.wandb.ai/guides/track/environment-variables\n", j.settings.FilesDir.Value)
		return nil, nil
	}

	if metadata.Python == nil {
		fmt.Println("No python version found in metadata, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job")
		return nil, nil
	}

	var sourceInfo JobSourceMetadata
	var name *string
	var sourceType *SourceType
	// this flow is from using a partial job artifact that was created by the CLI to make a run
	if j.partialJobSource != nil {
		name = &j.partialJobSource.JobName
		sourceInfo = j.partialJobSource.JobSourceInfo
		_sourceType := sourceInfo.Source.GetSourceType()
		sourceType = &_sourceType
	} else {
		sourceType = j.getSourceType(*metadata)
		if sourceType == nil {
			fmt.Println("No source type found, not creating job artifact")
			return nil, nil
		}
		programRelpath := j.getProgramRelpath(*metadata, *sourceType)

		// all jobs except image jobs need to specify a program path
		if *sourceType != ImageSourceType && programRelpath == nil {
			fmt.Println("No program path found, not creating job artifact. See https://docs.wandb.ai/guides/launch/create-job")
			return nil, nil
		}

		var jobSource Source
		jobSource, name, err = j.getSourceAndName(*sourceType, *programRelpath, *metadata)
		if err != nil {
			return nil, err
		}
		sourceInfo.Source = jobSource
		sourceInfo.SourceType = *sourceType

		sourceInfo.Version = "v0"
	}
	// inject partial field for create job CLI flow
	if metadata.Partial != nil {
		sourceInfo.Partial = metadata.Partial
	}

	sourceInfo.Runtime = metadata.Python
	// TODO: Send and retrieve types from protobuffs
	sourceInfo.InputTypes = make(map[string]interface{})
	sourceInfo.OutputTypes = make(map[string]interface{})

	baseArtifact := &service.ArtifactRecord{
		Entity:   j.settings.Entity.Value,
		Project:  j.settings.Project.Value,
		RunId:    j.settings.RunId.Value,
		Name:     *name,
		Metadata: "",
		Type:     "job",
		Aliases:  j.aliases,
		Finalize: true,
	}

	artifactBuilder := artifacts.NewArtifactBuilder(baseArtifact)

	err = artifactBuilder.AddFile(filepath.Join(fileDir, REQUIREMENTS_FNAME), FROZEN_REQUIREMENTS_FNAME)
	if err != nil {
		return nil, err
	}

	stringSourceInfo, err := json.Marshal(sourceInfo)
	if err != nil {
		return nil, err
	}

	var mapSourceInfo map[string]interface{}

	err = json.Unmarshal(stringSourceInfo, &mapSourceInfo)
	if err != nil {
		return nil, err
	}

	err = artifactBuilder.AddData("wandb-job.json", mapSourceInfo)
	if err != nil {
		return nil, err
	}

	if *sourceType == RepoSourceType {
		_, err = os.Stat(filepath.Join(fileDir, DIFF_FNAME))
		if !os.IsNotExist(err) {
			err = artifactBuilder.AddFile(filepath.Join(fileDir, DIFF_FNAME), DIFF_FNAME)
			if err != nil {
				return nil, err
			}
		} else if err != nil {
			return nil, err
		}
	}

	return artifactBuilder.GetArtifact(), nil
}

func (j *JobBuilder) getSourceAndName(sourceType SourceType, programRelpath string, metadata RunMetadata) (Source, *string, error) {
	switch {
	case sourceType == RepoSourceType:
		return j.buildRepoJobSource(programRelpath, metadata)
	case sourceType == ArtifactSourceType:
		return j.buildArtifactJobSource(programRelpath, metadata)
	case sourceType == ImageSourceType:
		return j.buildImageJobSource(metadata)
	default:
		// TODO: warn if source type was set to something different
		return nil, nil, nil
	}
}
