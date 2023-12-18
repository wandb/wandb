package launch

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Equal(t, "job-example.com__path_to_train.py", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 3, len(artifact.Manifest.Contents))
		assert.Equal(t, "5c90116a39060cbe9ec20345f6a34a58", artifact.Digest)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Equal(t, "job-example.com_Untitled.ipynb", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 3, len(artifact.Manifest.Contents))
		assert.Equal(t, "f73138bfafbc03f6344d412a06cd15d2", artifact.Digest)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifactRecord := &service.Record{
			RecordType: &service.Record_Artifact{
				Artifact: &service.ArtifactRecord{
					Name: "testArtifact",
					Type: "code",
				},
			},
		}
		jobBuilder.HandleLogArtifactResult(&service.LogArtifactResponse{ArtifactId: "testArtifactId"}, artifactRecord)
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Equal(t, "job-testArtifact", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "ba0c50457c5a7c43e0bf8d4aa2b4e624", artifact.Digest)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifactRecord := &service.Record{
			RecordType: &service.Record_Artifact{
				Artifact: &service.ArtifactRecord{
					Name: "testArtifact",
					Type: "code",
				},
			},
		}
		jobBuilder.HandleLogArtifactResult(&service.LogArtifactResponse{ArtifactId: "testArtifactId"}, artifactRecord)
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Equal(t, "job-testArtifact", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "74d3666a82ca9688d697e6a8f1104155", artifact.Digest)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Equal(t, "job-testImage", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "88eb8ffd0b505c81017a215206de813b", artifact.Digest)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Nil(t, artifact)
	})

	t.Run("Missing requirements file", func(t *testing.T) {
		fdir := filepath.Join(os.TempDir(), "test")
		settings := &service.Settings{
			FilesDir: toWrapperPb(fdir).(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
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

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifact, err := jobBuilder.Build()
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		artifactRecord := &service.Record{
			RecordType: &service.Record_UseArtifact{
				UseArtifact: &service.UseArtifactRecord{
					Id:   "testID",
					Type: "job",
					Name: "partialArtifact",
					Partial: &service.PartialJobArtifact{
						JobName: "job-testJobName",
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
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		artifact, err := jobBuilder.Build()
		assert.Nil(t, err)
		assert.Equal(t, "job-testJobName", artifact.Name)
		assert.Equal(t, "testProject", artifact.Project)
		assert.Equal(t, "testEntity", artifact.Entity)
		assert.Equal(t, "testRunId", artifact.RunId)
		assert.Equal(t, 2, len(artifact.Manifest.Contents))
		assert.Equal(t, "0e0399505d5bc9d1538ec4ab72199589", artifact.Digest)
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

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
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

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
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

		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.Equal(t, "job-testJobNameImage", jobBuilder.PartialJobSource.JobName)
		assert.Equal(t, ImageSourceType, jobBuilder.PartialJobSource.JobSourceInfo.SourceType)
		assert.Equal(t, ImageSourceType, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceType())
		assert.Equal(t, "testImage:v0", *jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceImage())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceGit())
		assert.Nil(t, jobBuilder.PartialJobSource.JobSourceInfo.Source.GetSourceArtifact())
		assert.Equal(t, "3.11.2", *jobBuilder.PartialJobSource.JobSourceInfo.Runtime)
	})

	t.Run("HandleUseArtifactRecord disabeld when use non partial artifact job", func(t *testing.T) {
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.disable)

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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.disable)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.disable)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.disable)
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
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.HandleUseArtifactRecord(artifactRecord)
		assert.True(t, jobBuilder.disable)
	})
}
func TestJobBuilderGetSourceType(t *testing.T) {
	t.Run("getSourceType job type specified repo", func(t *testing.T) {
		sourceType := RepoSourceType
		noRepoIngrediantsError := "no repo job ingredients found, but source type set to repo"
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
				expectedError:      &noRepoIngrediantsError,
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		for _, testCase := range testCases {
			res, err := jobBuilder.getSourceType(testCase.metadata)
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

	t.Run("getSourceType job type specified artifact", func(t *testing.T) {
		sourceType := ArtifactSourceType
		noArtifactIngrediantsError := "no artifact job ingredients found, but source type set to artifact"
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
				expectedError:      &noArtifactIngrediantsError,
			},
		}

		for index, testCase := range testCases {
			jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
			if index == 0 {
				jobBuilder.runCodeArtifact = &ArtifactInfoForJob{
					ID:   "testID",
					Name: "testName",
				}
			}
			res, err := jobBuilder.getSourceType(testCase.metadata)
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
		noImageIngrediantsError := "no image job ingredients found, but source type set to image"
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
				expectedError:      &noImageIngrediantsError,
			},
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		for _, testCase := range testCases {

			res, err := jobBuilder.getSourceType(testCase.metadata)
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
