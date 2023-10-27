package artifacts

import (
	"encoding/json"
	"os"

	"github.com/wandb/wandb/nexus/pkg/service"
	"github.com/wandb/wandb/nexus/pkg/utils"
)

type ArtifactBuilder struct {
	artifactRecord *service.ArtifactRecord
	isDigestUpToDate bool
}

func NewArtifactBuilder(artifactRecord *service.ArtifactRecord) *ArtifactBuilder {
	return &ArtifactBuilder{
		artifactRecord: artifactRecord,
	}
}

func (b *ArtifactBuilder) AddData(name string, dataMap map[string]interface{}) error {
	filename, digest, err := b.writeToFile(dataMap)
	if err != nil {
		return err
	}
	b.artifactRecord.Manifest.Contents = append(b.artifactRecord.Manifest.Contents,
		&service.ArtifactManifestEntry{
			Path:      name,
			Digest:    digest,
			LocalPath: filename,
		})
	b.isDigestUpToDate = false
	return nil
}

func (b *ArtifactBuilder) updateManifestDigest() error {
	if b.isDigestUpToDate {
		return nil
	}
	manifest, err := NewManifestFromProto(b.artifactRecord.Manifest)
	if err != nil {
		return err
	}
	manifestDigest := manifest.ComputeDigest()
	b.artifactRecord.Digest = manifestDigest
	b.isDigestUpToDate = true
	return nil
}

func (b *ArtifactBuilder) GetArtifact() *service.ArtifactRecord {
	_ = b.updateManifestDigest()
	return b.artifactRecord
}

func (b *ArtifactBuilder) writeToFile(dataMap map[string]interface{}) (filename string, digest string, rerr error) {
	data, rerr := json.Marshal(dataMap)
	if rerr != nil {
		return
	}

	f, rerr := os.CreateTemp("", "tmpfile-")
	if rerr != nil {
		return
	}
	defer f.Close()
	_, rerr = f.Write(data)
	if rerr != nil {
		return
	}
	filename = f.Name()

	digest, rerr = utils.ComputeB64MD5(data)
	return
}
