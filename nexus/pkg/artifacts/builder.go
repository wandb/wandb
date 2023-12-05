package artifacts

import (
	"crypto/md5"
	"encoding/json"
	"fmt"
	"os"
	"sort"

	"github.com/wandb/wandb/nexus/pkg/service"
	"github.com/wandb/wandb/nexus/pkg/utils"

	"google.golang.org/protobuf/proto"
)

type ArtifactBuilder struct {
	artifactRecord   *service.ArtifactRecord
	isDigestUpToDate bool
}

func NewArtifactBuilder(artifactRecord *service.ArtifactRecord) *ArtifactBuilder {
	artifactClone := proto.Clone(artifactRecord).(*service.ArtifactRecord)
	builder := &ArtifactBuilder{
		artifactRecord: artifactClone,
	}
	builder.initDefaultManifest()
	return builder
}

func (b *ArtifactBuilder) initDefaultManifest() {
	if b.artifactRecord.Manifest != nil {
		return
	}
	b.artifactRecord.Manifest = &service.ArtifactManifest{
		Version:       1,
		StoragePolicy: "wandb-storage-policy-v1",
		StoragePolicyConfig: []*service.StoragePolicyConfigItem{{
			Key:       "storageLayout",
			ValueJson: "\"V2\"",
		}},
	}
}

func (b *ArtifactBuilder) AddData(name string, dataMap map[string]interface{}) error {
	filename, digest, err := b.writeDataToFile(dataMap)
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

func (b *ArtifactBuilder) updateManifestDigest() {
	if b.isDigestUpToDate {
		return
	}
	manifest, err := NewManifestFromProto(b.artifactRecord.Manifest)
	if err != nil {
		panic("unable to create manifest (unexpected)")
	}
	manifestDigest := computeManifestDigest(&manifest)
	b.artifactRecord.Digest = manifestDigest
	b.isDigestUpToDate = true
}

func (b *ArtifactBuilder) GetArtifact() *service.ArtifactRecord {
	b.updateManifestDigest()
	return b.artifactRecord
}

func (b *ArtifactBuilder) writeDataToFile(dataMap map[string]interface{}) (filename string, digest string, rerr error) {
	// TODO: consolidate writeDataToFile with manifest.go WriteToFile
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

func computeManifestDigest(manifest *Manifest) string {
	type hashedEntry struct {
		name   string
		digest string
	}

	var entries []hashedEntry
	for name, entry := range manifest.Contents {
		entries = append(entries, hashedEntry{
			name:   name,
			digest: entry.Digest,
		})
	}

	sort.Slice(entries, func(i, j int) bool {
		return entries[i].name < entries[j].name
	})

	hasher := md5.New()
	hasher.Write([]byte("wandb-artifact-manifest-v1\n"))
	for _, entry := range entries {
		hasher.Write([]byte(fmt.Sprintf("%s:%s\n", entry.name, entry.digest)))
	}

	return utils.EncodeBytesAsHex(hasher.Sum(nil))
}
