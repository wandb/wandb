package launch_test

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/segmentio/encoding/json"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runconfig"
	. "github.com/wandb/wandb/core/pkg/launch"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func writeRequirements(t *testing.T, fdir string) {
	f, err := os.OpenFile(filepath.Join(fdir, REQUIREMENTS_FNAME), os.O_CREATE|os.O_WRONLY, 0777)
	assert.Nil(t, err)
	_, err = f.WriteString("wandb")
	assert.Nil(t, err)
	err = f.Sync()
	assert.Nil(t, err)
	f.Close()
}

func writeWandbMetadata(t *testing.T, fdir string, metadata map[string]interface{}) {
	f, err := os.OpenFile(filepath.Join(fdir, WANDB_METADATA_FNAME), os.O_CREATE|os.O_WRONLY, 0777)
	assert.Nil(t, err)
	metaDataString, err := json.Marshal(metadata)
	assert.Nil(t, err)
	_, err = f.Write(metaDataString)
	assert.Nil(t, err)
	err = f.Sync()
	assert.Nil(t, err)
	f.Close()
}

func writeDiffFile(t *testing.T, fdir string) {
	f, err := os.OpenFile(filepath.Join(fdir, DIFF_FNAME), os.O_CREATE|os.O_WRONLY, 0777)
	assert.Nil(t, err)
	_, err = f.WriteString("wandb")
	assert.Nil(t, err)
	err = f.Sync()
	assert.Nil(t, err)
	f.Close()
}

func toWrapperPb(val interface{}) interface{} {
	switch v := val.(type) {
	case string:
		return &wrapperspb.StringValue{
			Value: v,
		}
	case bool:
		return &wrapperspb.BoolValue{
			Value: v,
		}
	}
	return nil
}

func writeFile(t *testing.T, fdir string, fname string, content string) {
	f, err := os.OpenFile(filepath.Join(fdir, fname), os.O_CREATE|os.O_WRONLY, 0777)
	assert.Nil(t, err)
	_, err = f.WriteString(content)
	assert.Nil(t, err)
	err = f.Sync()
	assert.Nil(t, err)
	f.Close()
}

func TestJobBuilderRepo(t *testing.T) {
	t.Run("Build repo sourced job", func(t *testing.T) {
		metadata := map[string]interface{}{
			"python": "3.11.2",
			"git": map[string]interface{}{
				"commit": "1234567890",
				"remote": "example.com",
			},
			"codePath": "/path/to/train.py",
		}

		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeDiffFile(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Equal(t, "job-example.com__path_to_train.py", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 3, len(artifact.Manifest.Contents))
		assert.Equal(t, "148c5ecbb60815f037fd8ba2715ec1c6", artifact.Digest)
		for _, content := range artifact.Manifest.Contents {
			if content.Path == "wandb-job.json" {
				jobFile, err := os.Open(content.LocalPath)
				assert.Nil(t, err)
				defer jobFile.Close()
				assert.Nil(t, err)
				data := make(map[string]interface{})
				err = json.NewDecoder(jobFile).Decode(&data)
				assert.Nil(t, err)
				assert.Equal(t, "3.11.2", data["runtime"])
				assert.Equal(t, "1234567890", data["source"].(map[string]interface{})["git"].(map[string]interface{})["commit"])
				assert.Equal(t, "example.com", data["source"].(map[string]interface{})["git"].(map[string]interface{})["remote"])
				assert.Equal(t, []interface{}([]interface{}{"python3.11", "/path/to/train.py"}), data["source"].(map[string]interface{})["entrypoint"])
			}
		}
	})

	t.Run("Build repo sourced notebook job", func(t *testing.T) {
		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		_, err = os.Create(filepath.Join(fdir, "Untitled.ipynb"))
		assert.Nil(t, err)
		err = os.Chdir(fdir)
		assert.Nil(t, err)

		assert.Nil(t, err)
		metadata := map[string]interface{}{
			"python": "3.11.2",
			"git": map[string]interface{}{
				"commit": "1234567890",
				"remote": "example.com",
			},
			"program":       "Untitled.ipynb",
			"codePathLocal": "Untitled.ipynb",
			"root":          fdir,
		}
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeDiffFile(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:      toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:       toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:        toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir:     toWrapperPb(fdir).(*wrapperspb.StringValue),
			XJupyter:     toWrapperPb(true).(*wrapperspb.BoolValue),
			XJupyterRoot: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Equal(t, "job-example.com_Untitled.ipynb", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 3, len(artifact.Manifest.Contents))
		assert.Equal(t, "955b87b67813fcf514645b98ed9aaccf", artifact.Digest)
		for _, content := range artifact.Manifest.Contents {
			if content.Path == "wandb-job.json" {
				jobFile, err := os.Open(content.LocalPath)
				assert.Nil(t, err)
				defer jobFile.Close()
				assert.Nil(t, err)
				data := make(map[string]interface{})
				err = json.NewDecoder(jobFile).Decode(&data)
				assert.Nil(t, err)
				assert.Equal(t, "3.11.2", data["runtime"])
				assert.Equal(t, "1234567890", data["source"].(map[string]interface{})["git"].(map[string]interface{})["commit"])
				assert.Equal(t, "example.com", data["source"].(map[string]interface{})["git"].(map[string]interface{})["remote"])
				assert.Equal(t, []interface{}([]interface{}{"python3.11", "Untitled.ipynb"}), data["source"].(map[string]interface{})["entrypoint"])
			}
		}
	})
}
func TestJobBuilderArtifact(t *testing.T) {
	t.Run("Build artifact sourced job", func(t *testing.T) {
		metadata := map[string]interface{}{
			"python":   "3.11.2",
			"codePath": "/path/to/train.py",
		}

		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifactRecord := &service.ArtifactRecord{
			Name: "testArtifact",
			Type: "code",
		}
		jobBuilder.HandleLogArtifactResult(&service.LogArtifactResponse{ArtifactId: "testArtifactId"}, artifactRecord)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Equal(t, "job-testArtifact", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "53efc97d385924d4eeb9893d44552c3c", artifact.Digest)
		for _, content := range artifact.Manifest.Contents {
			if content.Path == "wandb-job.json" {
				jobFile, err := os.Open(content.LocalPath)
				assert.Nil(t, err)
				defer jobFile.Close()
				assert.Nil(t, err)
				data := make(map[string]interface{})
				err = json.NewDecoder(jobFile).Decode(&data)
				assert.Nil(t, err)
				assert.Equal(t, "3.11.2", data["runtime"])
				assert.Equal(t, "wandb-artifact://_id/testArtifactId", data["source"].(map[string]interface{})["artifact"])
				assert.Equal(t, "artifact", data["source_type"])
				assert.Equal(t, []interface{}([]interface{}{"python3.11", "/path/to/train.py"}), data["source"].(map[string]interface{})["entrypoint"])
			}
		}
	})

	t.Run("Build artifact sourced notebook job", func(t *testing.T) {
		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		_, err = os.Create(filepath.Join(fdir, "Untitled.ipynb"))
		assert.Nil(t, err)
		err = os.Chdir(fdir)
		assert.Nil(t, err)

		assert.Nil(t, err)
		metadata := map[string]interface{}{
			"python":        "3.11.2",
			"program":       "Untitled.ipynb",
			"codePathLocal": "Untitled.ipynb",
			"root":          fdir,
		}
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeDiffFile(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:      toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:       toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:        toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir:     toWrapperPb(fdir).(*wrapperspb.StringValue),
			XJupyter:     toWrapperPb(true).(*wrapperspb.BoolValue),
			XJupyterRoot: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifactRecord := &service.ArtifactRecord{
			Name: "testArtifact",
			Type: "code",
		}
		jobBuilder.HandleLogArtifactResult(&service.LogArtifactResponse{ArtifactId: "testArtifactId"}, artifactRecord)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Equal(t, "job-testArtifact", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "107ca7f9f6220f0c713f316664fa46f1", artifact.Digest)
		for _, content := range artifact.Manifest.Contents {
			if content.Path == "wandb-job.json" {
				jobFile, err := os.Open(content.LocalPath)
				assert.Nil(t, err)
				defer jobFile.Close()
				assert.Nil(t, err)
				data := make(map[string]interface{})
				err = json.NewDecoder(jobFile).Decode(&data)
				assert.Nil(t, err)
				assert.Equal(t, "3.11.2", data["runtime"])
				assert.Equal(t, "wandb-artifact://_id/testArtifactId", data["source"].(map[string]interface{})["artifact"])
				assert.Equal(t, "artifact", data["source_type"])
				assert.Equal(t, []interface{}([]interface{}{"python3.11", "Untitled.ipynb"}), data["source"].(map[string]interface{})["entrypoint"])
			}
		}
	})
}
func TestJobBuilderImage(t *testing.T) {
	t.Run("Build image sourced job", func(t *testing.T) {
		metadata := map[string]interface{}{
			"docker": "testImage:testTag",
			"python": "3.11.2",
		}

		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Equal(t, "job-testImage", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "e56fd338fa10f4b993f78e4530b30f76", artifact.Digest)
		assert.Equal(t, []string{"testTag"}, artifact.Aliases)
		for _, content := range artifact.Manifest.Contents {
			if content.Path == "wandb-job.json" {
				jobFile, err := os.Open(content.LocalPath)
				assert.Nil(t, err)
				defer jobFile.Close()
				assert.Nil(t, err)
				data := make(map[string]interface{})
				err = json.NewDecoder(jobFile).Decode(&data)
				assert.Nil(t, err)
				assert.Equal(t, "3.11.2", data["runtime"])
				assert.Equal(t, "image", data["source_type"])
				assert.Equal(t, "testImage:testTag", data["source"].(map[string]interface{})["image"])
			}
		}
	})
}
func TestJobBuilderDisabledOrMissingFiles(t *testing.T) {
	t.Run("Disabled", func(t *testing.T) {
		settings := &service.Settings{
			Project: toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:  toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:   toWrapperPb("testRunId").(*wrapperspb.StringValue),
			DisableJobCreation: &wrapperspb.BoolValue{
				Value: true,
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Nil(t, artifact)
	})

	t.Run("Missing requirements file", func(t *testing.T) {
		fdir := filepath.Join(os.TempDir(), "test")
		settings := &service.Settings{
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, artifact)
		assert.Nil(t, err)
	})

	t.Run("Missing metadata file", func(t *testing.T) {
		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)

		settings := &service.Settings{
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, artifact)
		assert.NotNil(t, err)
		assert.Contains(t, err.Error(), "wandb-metadata.json: no such file or directory")
	})

	t.Run("Missing python in metadata", func(t *testing.T) {
		metadata := map[string]interface{}{}
		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)

		settings := &service.Settings{
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, artifact)
		assert.Nil(t, err)
	})
}

func TestJobBuilderFromPartial(t *testing.T) {
	t.Run("Build from partial", func(t *testing.T) {
		metadata := map[string]interface{}{
			"python": "3.11.2",
		}

		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobName",
						SourceInfo: &service.JobSource{
							XVersion:   "v0",
							SourceType: "repo",
							Runtime:    "3.11.2",
							Source: &service.Source{
								Git: &service.GitSource{
									Entrypoint: []string{"a", "b"},
									GitInfo: &service.GitInfo{
										Commit: "1234567890",
										Remote: "example.com",
									},
									Notebook:     false,
									Dockerfile:   "Dockerfile",
									BuildContext: "context",
								},
							},
						},
					},
				},
			},
		}
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		artifact, err := jobBuilder.Build(nil)
		assert.Nil(t, err)
		assert.Equal(t, "job-testJobName", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "dfc5b8caa82c6b45d41986c787ab6e56", artifact.Digest)
		for _, content := range artifact.Manifest.Contents {
			if content.Path == "wandb-job.json" {
				jobFile, err := os.Open(content.LocalPath)
				assert.Nil(t, err)
				defer jobFile.Close()
				assert.Nil(t, err)
				data := make(map[string]interface{})
				err = json.NewDecoder(jobFile).Decode(&data)
				assert.Nil(t, err)
				assert.Equal(t, "3.11.2", data["runtime"])
				assert.Equal(t, "repo", data["source_type"])
				assert.Equal(t, []interface{}([]interface{}{"a", "b"}), data["source"].(map[string]interface{})["entrypoint"])
			}
		}
	})
}

func TestJobBuilderCodeJobFromPartial(t *testing.T) {
	t.Run("Build code job from partial", func(t *testing.T) {
		metadata := map[string]interface{}{
			"python": "3.11.2",
		}

		fdir := filepath.Join(os.TempDir(), "test")
		err := os.MkdirAll(fdir, 0777)
		assert.Nil(t, err)
		writeRequirements(t, fdir)
		writeWandbMetadata(t, fdir, metadata)

		defer os.RemoveAll(fdir)
		settings := &service.Settings{
			Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobName",
						SourceInfo: &service.JobSource{
							XVersion:   "0.17.0",
							SourceType: "artifact",
							Runtime:    "3.11.2",
							Source: &service.Source{
								Artifact: &service.ArtifactInfo{
									Artifact:     "testArtifactId",
									Entrypoint:   []string{"a", "b"},
									Dockerfile:   "Dockerfile",
									BuildContext: "context",
								},
							},
						},
					},
				},
			},
		}
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		artifact, err := jobBuilder.Build(map[string]interface{}{})
		assert.Nil(t, err)
		assert.Equal(t, "job-testJobName", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "f457273fd1b4bee4177ded847e048d48", artifact.Digest)
	})
}

func TestJobBuilderHandleUseArtifactRecord(t *testing.T) {
	t.Run("HandleUseArtifactRecord repo type", func(t *testing.T) {
		settings := &service.Settings{
			Project: toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:  toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:   toWrapperPb("testRunId").(*wrapperspb.StringValue),
		}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobNameImage",
						SourceInfo: &service.JobSource{
							SourceType: "repo",
							Runtime:    "3.11.2",
							Source: &service.Source{
								Git: &service.GitSource{
									Entrypoint: []string{"a", "b"},
									GitInfo: &service.GitInfo{
										Commit: "1234567890",
										Remote: "example.com",
									},
									Notebook: false,
								},
							},
						},
					},
				},
			},
		}

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.Equal(t, "job-testJobNameImage", jobBuilder.PartialJobSource.JobName)
		assert.Equal(t, RepoSourceType, jobBuilder.PartialJobSource.JobSourceInfo.SourceType)
		assert.Equal(t, RepoSourceType, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceType())
		assert.Equal(t, "1234567890", *jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceGit().Commit)
		assert.Equal(t, "example.com", *jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceGit().Remote)
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceImage())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceArtifact())
		assert.Equal(t, "3.11.2", *jobBuilder.PartialJobSource.JobSourceInfo.Runtime)
	})

	t.Run("HandleUseArtifactRecord artifact type", func(t *testing.T) {
		settings := &service.Settings{
			Project: toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:  toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:   toWrapperPb("testRunId").(*wrapperspb.StringValue),
		}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobNameArtifact",
						SourceInfo: &service.JobSource{
							SourceType: "artifact",
							Runtime:    "3.11.2",
							Source: &service.Source{
								Artifact: &service.ArtifactInfo{
									Artifact:   "testArtifactId:v0",
									Entrypoint: []string{"a", "b"},
								},
							},
						},
					},
				},
			},
		}

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.Equal(t, "job-testJobNameArtifact", jobBuilder.PartialJobSource.JobName)
		assert.Equal(t, ArtifactSourceType, jobBuilder.PartialJobSource.JobSourceInfo.SourceType)
		assert.Equal(t, ArtifactSourceType, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceType())
		assert.Equal(t, "testArtifactId:v0", *jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceArtifact())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceGit())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceImage())
		assert.Equal(t, "3.11.2", *jobBuilder.PartialJobSource.JobSourceInfo.Runtime)
	})

	t.Run("HandleUseArtifactRecord image type", func(t *testing.T) {
		settings := &service.Settings{
			Project: toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:  toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:   toWrapperPb("testRunId").(*wrapperspb.StringValue),
		}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobNameImage",
						SourceInfo: &service.JobSource{
							SourceType: "image",
							Runtime:    "3.11.2",
							Source: &service.Source{
								Image: &service.ImageSource{
									Image: "testImage:v0",
								},
							},
						},
					},
				},
			},
		}

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.Equal(t, "job-testJobNameImage", jobBuilder.PartialJobSource.JobName)
		assert.Equal(t, ImageSourceType, jobBuilder.PartialJobSource.JobSourceInfo.SourceType)
		assert.Equal(t, ImageSourceType, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceType())
		assert.Equal(t, "testImage:v0", *jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceImage())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceGit())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceArtifact())
		assert.Equal(t, "3.11.2", *jobBuilder.PartialJobSource.JobSourceInfo.Runtime)
	})

	t.Run("HandleUseArtifactRecord disabled when use non partial artifact job", func(t *testing.T) {
		settings := &service.Settings{}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:      "testID",
					Type:    "job",
					Name:    "partialArtifact",
					Partial: nil,
				},
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.Disable)

	})

	t.Run("HandleUseArtifactRecord disables job builder when handling partial job with no name", func(t *testing.T) {
		settings := &service.Settings{}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "",
						SourceInfo: &service.JobSource{
							SourceType: "image",
							Runtime:    "3.11.2",
							Source: &service.Source{
								Image: &service.ImageSource{
									Image: "testImage:v0",
								},
							},
						},
					},
				},
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.Disable)
	})

	t.Run("HandleUseArtifactRecord disables job builder when handling partial job indicating repo type without git info", func(t *testing.T) {
		settings := &service.Settings{}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobNameImage",
						SourceInfo: &service.JobSource{
							SourceType: "repo",
							Runtime:    "3.11.2",
							Source:     &service.Source{},
						},
					},
				},
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.Disable)
	})

	t.Run("HandleUseArtifactRecord disables job builder when handling partial job indicating artifact type without artifact info", func(t *testing.T) {
		settings := &service.Settings{}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobNameImage",
						SourceInfo: &service.JobSource{
							SourceType: "artifact",
							Runtime:    "3.11.2",
							Source:     &service.Source{},
						},
					},
				},
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.Disable)
	})

	t.Run("HandleUseArtifactRecord disables job builder when handling partial job indicating image type without image info", func(t *testing.T) {
		settings := &service.Settings{}
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobNameImage",
						SourceInfo: &service.JobSource{
							SourceType: "image",
							Runtime:    "3.11.2",
							Source:     &service.Source{},
						},
					},
				},
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.Disable)
	})
}
func TestJobBuilderGetSourceType(t *testing.T) {
	t.Run("GetSourceType job type specified repo", func(t *testing.T) {
		sourceType := RepoSourceType
		noRepoIngredientsError := "no repo job ingredients found, but source type set to repo"
		commit := "1234567890"
		remote := "example.com"
		settings := &service.Settings{
			JobSource: &wrapperspb.StringValue{
				Value: string(sourceType),
			},
		}

		testCases := []struct {
			metadata           RunMetadata
			expectedSourceType *SourceType
			expectedError      *string
		}{
			{
				metadata: RunMetadata{
					Git: &GitInfo{
						Commit: &commit,
						Remote: &remote,
					},
				},
				expectedSourceType: &sourceType,
				expectedError:      nil,
			},
			{
				metadata:           RunMetadata{},
				expectedSourceType: nil,
				expectedError:      &noRepoIngredientsError,
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		for _, testCase := range testCases {
			res, err := jobBuilder.GetSourceType(testCase.metadata)
			if testCase.expectedSourceType != nil {
				assert.Equal(t, *testCase.expectedSourceType, *res)
			} else {
				assert.Nil(t, res)
			}

			if testCase.expectedError != nil {
				assert.Equal(t, *testCase.expectedError, err.Error())
			} else {
				assert.Nil(t, err)
			}
		}
	})

	t.Run("GetSourceType job type specified artifact", func(t *testing.T) {
		sourceType := ArtifactSourceType
		noArtifactIngredientsError := "no artifact job ingredients found, but source type set to artifact"
		settings := &service.Settings{
			JobSource: &wrapperspb.StringValue{
				Value: string(sourceType),
			},
		}

		testCases := []struct {
			metadata           RunMetadata
			expectedSourceType *SourceType
			expectedError      *string
		}{
			{
				metadata:           RunMetadata{},
				expectedSourceType: &sourceType,
				expectedError:      nil,
			},
			{
				metadata:           RunMetadata{},
				expectedSourceType: nil,
				expectedError:      &noArtifactIngredientsError,
			},
		}

		for index, testCase := range testCases {
			jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
			if index == 0 {
				jobBuilder.RunCodeArtifact = &ArtifactInfoForJob{
					ID:   "testID",
					Name: "testName",
				}
			}
			res, err := jobBuilder.GetSourceType(testCase.metadata)
			if testCase.expectedSourceType != nil {
				assert.Equal(t, *testCase.expectedSourceType, *res)
			} else {
				assert.Nil(t, res)
			}

			if testCase.expectedError != nil {
				assert.Equal(t, *testCase.expectedError, err.Error())
			} else {
				assert.Nil(t, err)
			}
		}
	})

	t.Run("getSourceType job type specified image", func(t *testing.T) {
		sourceType := ImageSourceType
		imageName := "testImage"
		noImageIngredientsError := "no image job ingredients found, but source type set to image"
		settings := &service.Settings{
			JobSource: &wrapperspb.StringValue{
				Value: string(sourceType),
			},
		}

		testCases := []struct {
			metadata           RunMetadata
			expectedSourceType *SourceType
			expectedError      *string
		}{
			{
				metadata: RunMetadata{
					Docker: &imageName,
				},
				expectedSourceType: &sourceType,
				expectedError:      nil,
			},
			{
				metadata:           RunMetadata{},
				expectedSourceType: nil,
				expectedError:      &noImageIngredientsError,
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		for _, testCase := range testCases {

			res, err := jobBuilder.GetSourceType(testCase.metadata)
			if testCase.expectedSourceType != nil {
				assert.Equal(t, *testCase.expectedSourceType, *res)
			} else {
				assert.Nil(t, res)
			}

			if testCase.expectedError != nil {
				assert.Equal(t, *testCase.expectedError, err.Error())
			} else {
				assert.Nil(t, err)
			}
		}
	})
}

func TestUtilFunctions(t *testing.T) {

	t.Run("makeArtifactNameSafe truncates to 128 characters", func(t *testing.T) {
		name := MakeArtifactNameSafe("this is a very long name that is longer than 128 characters and should be truncated down to one hundred and twenty eight characters with the first 63 chars, and the last 63 chars separated by ..")
		assert.Equal(t, "this_is_a_very_long_name_that_is_longer_than_128_characters_and.._with_the_first_63_chars__and_the_last_63_chars_separated_by_..", name)

	})
	t.Run("handlePathsAboveRoot works when notebook started above git root", func(t *testing.T) {
		settings := &service.Settings{
			XJupyterRoot: toWrapperPb("/path/to/jupyterRoot").(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		path, err := jobBuilder.HandlePathsAboveRoot("gitRoot/a/notebook.ipynb", "/path/to/jupyterRoot/gitRoot")
		assert.Nil(t, err)
		assert.Equal(t, "a/notebook.ipynb", path)
	})
	t.Run("handlePathsAboveRoot works when notebook started below git root", func(t *testing.T) {
		settings := &service.Settings{
			XJupyterRoot: toWrapperPb("/path/to/gitRoot/jupyterRoot").(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		path, err := jobBuilder.HandlePathsAboveRoot("a/notebook.ipynb", "/path/to/gitRoot")
		assert.Nil(t, err)
		assert.Equal(t, "jupyterRoot/a/notebook.ipynb", path)
	})

	t.Run("handlePathsAboveRoot works when notebook started at git root", func(t *testing.T) {
		settings := &service.Settings{
			XJupyterRoot: toWrapperPb("/path/to/gitRoot").(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
		path, err := jobBuilder.HandlePathsAboveRoot("a/notebook.ipynb", "/path/to/gitRoot")
		assert.Nil(t, err)
		assert.Equal(t, "a/notebook.ipynb", path)
	})
}

func TestWandbConfigParameters(t *testing.T) {
	// Test that if WandbConfigParametersRecord is set on the job builder
	// then inputs will be filtered to only include the parameters specified
	// in the WandbConfigParametersRecord.

	metadata := map[string]interface{}{
		"python": "3.11.2",
		"git": map[string]interface{}{
			"commit": "1234567890",
			"remote": "example.com",
		},
		"codePath": "/path/to/train.py",
	}

	fdir := filepath.Join(os.TempDir(), "test")
	err := os.MkdirAll(fdir, 0777)
	assert.Nil(t, err)
	writeRequirements(t, fdir)
	writeDiffFile(t, fdir)
	writeWandbMetadata(t, fdir, metadata)

	defer os.RemoveAll(fdir)
	settings := &service.Settings{
		Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
		Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
		RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
		FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
	}
	jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)
	jobBuilder.SetRunConfig(*runconfig.NewFrom(
		map[string]interface{}{
			"key1": "value1",
			"key2": "value2",
			"key3": map[string]interface{}{
				"key4": map[string]interface{}{
					"key6": "value6",
					"key7": "value7",
				},
				"key5": "value5",
			},
		},
	))
	jobBuilder.HandleJobInputRequest(&service.JobInputRequest{
		InputSource: &service.JobInputSource{
			Source: &service.JobInputSource_RunConfig{},
		},
		IncludePaths: []*service.JobInputPath{{Path: []string{"key1"}}, {Path: []string{"key3", "key4"}}},
		ExcludePaths: []*service.JobInputPath{{Path: []string{"key3", "key4", "key6"}}},
	})
	artifact, err := jobBuilder.Build(nil)
	assert.Nil(t, err)
	var artifactMetadata map[string]interface{}
	err = json.Unmarshal([]byte(artifact.Metadata), &artifactMetadata)
	inputs := artifactMetadata["input_types"].(map[string]interface{})
	assert.Nil(t, err)
	assert.Equal(t, map[string]interface{}{
		WandbConfigKey: map[string]interface{}{
			"params": map[string]interface{}{
				"type_map": map[string]interface{}{
					"key1": map[string]interface{}{
						"wb_type": "string",
					},
					"key3": map[string]interface{}{
						"params": map[string]interface{}{
							"type_map": map[string]interface{}{
								"key4": map[string]interface{}{
									"wb_type": "typedDict",
									"params": map[string]interface{}{
										"type_map": map[string]interface{}{
											"key7": map[string]interface{}{
												"wb_type": "string",
											},
										},
									},
								},
							},
						},
						"wb_type": "typedDict",
					},
				},
			},
			"wb_type": "typedDict",
		},
	}, inputs)
}

func TestConfigFileParameters(t *testing.T) {
	// Test that if ConfigFileParametersRecord is set on the job builder
	// then inputs will be filtered to only include the parameters specified
	// in the ConfigFileParametersRecord.

	metadata := map[string]interface{}{
		"python": "3.11.2",
		"git": map[string]interface{}{
			"commit": "1234567890",
			"remote": "example.com",
		},
		"codePath": "/path/to/train.py",
	}
	fdir := filepath.Join(os.TempDir(), "test")
	err := os.MkdirAll(fdir, 0777)
	assert.Nil(t, err)
	writeRequirements(t, fdir)
	writeDiffFile(t, fdir)
	writeWandbMetadata(t, fdir, metadata)
	configDir := filepath.Join(fdir, "configs")
	err = os.Mkdir(configDir, 0777)
	assert.Nil(t, err)
	yamlContents := "key1: value1\nkey2: value2\nkey3:\n  key4:\n    key6: value6\n    key7: value7\n  key5: value5\n"
	writeFile(t, configDir, "config.yaml", yamlContents)
	defer os.RemoveAll(fdir)
	settings := &service.Settings{
		Project:  toWrapperPb("testProject").(*wrapperspb.StringValue),
		Entity:   toWrapperPb("testEntity").(*wrapperspb.StringValue),
		RunId:    toWrapperPb("testRunId").(*wrapperspb.StringValue),
		FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
	}
	jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger(), true)

	jobBuilder.HandleJobInputRequest(&service.JobInputRequest{
		InputSource: &service.JobInputSource{
			Source: &service.JobInputSource_File{
				File: &service.JobInputSource_ConfigFileSource{
					Path: "config.yaml",
				},
			},
		},
		IncludePaths: []*service.JobInputPath{{Path: []string{"key1"}}, {Path: []string{"key3"}}},
		ExcludePaths: []*service.JobInputPath{{Path: []string{"key3", "key4"}}},
	})
	artifact, err := jobBuilder.Build(nil)

	assert.Nil(t, err)
	var artifactMetadata map[string]interface{}
	err = json.Unmarshal([]byte(artifact.Metadata), &artifactMetadata)
	inputs := artifactMetadata["input_types"].(map[string]interface{})
	fmt.Println(inputs)
	files := inputs["files"].(map[string]interface{})
	assert.Nil(t, err)
	assert.Equal(t, map[string]interface{}{
		"config.yaml": map[string]interface{}{
			"params": map[string]interface{}{
				"type_map": map[string]interface{}{
					"key1": map[string]interface{}{
						"wb_type": "string",
					},
					"key3": map[string]interface{}{
						"params": map[string]interface{}{
							"type_map": map[string]interface{}{
								"key5": map[string]interface{}{
									"wb_type": "string",
								},
							},
						},
						"wb_type": "typedDict",
					},
				},
			},
			"wb_type": "typedDict",
		},
	}, files)
}
