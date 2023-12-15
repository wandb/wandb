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

func TestJobBuilder(t *testing.T) {
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

	t.Run("Build image sourced job", func(t *testing.T) {
		metadata := map[string]interface{}{
			"docker":   "testImage:testTag",
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

	t.Run("Disabled", func(t *testing.T) {
		settings := &service.Settings{
			Project: toWrapperPb("testProject").(*wrapperspb.StringValue),
			Entity:  toWrapperPb("testEntity").(*wrapperspb.StringValue),
			RunId:   toWrapperPb("testRunId").(*wrapperspb.StringValue),
		}
		jobBuilder := NewJobBuilder(settings, observability.NewNoOpLogger())
		jobBuilder.disable = true
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
