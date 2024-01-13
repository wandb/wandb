package artifacts

import (
	"crypto/md5"
	"fmt"
	"sort"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/lib/hashlib"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type ArtifactBuilder struct {
	artifactRecord   *pb.ArtifactRecord
	isDigestUpToDate bool
}

func NewArtifactBuilder(artifactRecord *pb.ArtifactRecord) *ArtifactBuilder {
	artifactClone := proto.Clone(artifactRecord).(*pb.ArtifactRecord)
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
	b.artifactRecord.Manifest = &pb.ArtifactManifest{
		Version:       1,
		StoragePolicy: "wandb-storage-policy-v1",
		StoragePolicyConfig: []*pb.StoragePolicyConfigItem{{
			Key:       "storageLayout",
			ValueJson: "\"V2\"",
		}},
	}
}

func (b *ArtifactBuilder) AddData(name string, dataMap map[string]interface{}) error {
	filename, digest, err := WriteJsonToFileWithDigest(dataMap)
	if err != nil {
		return err
	}
	b.artifactRecord.Manifest.Contents = append(b.artifactRecord.Manifest.Contents,
		&pb.ArtifactManifestEntry{
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

func (b *ArtifactBuilder) GetArtifact() *pb.ArtifactRecord {
	b.updateManifestDigest()
	return b.artifactRecord
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

	return hashlib.EncodeBytesAsHex(hasher.Sum(nil))
}
