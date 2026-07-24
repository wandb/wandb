package encodingbench

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/encoding/protowire"
	"google.golang.org/protobuf/proto"
)

const FixtureSchemaVersion = 1

// FixtureManifest describes exported encoding benchmark fixtures.
type FixtureManifest struct {
	SchemaVersion int             `json:"schema_version"`
	Source        string          `json:"source"`
	Fixtures      []FixtureEntry  `json:"fixtures"`
}

// FixtureEntry is one workload × value_mode × codec combination.
type FixtureEntry struct {
	ID              string `json:"id"`
	Dataset         string `json:"dataset"`
	ValueMode       string `json:"value_mode"`
	PayloadFormat   string `json:"payload_format"`
	EnvelopeFormat  string `json:"envelope_format"`
	RowCount        int    `json:"row_count"`
	CellCount       int    `json:"cell_count"`
	BodyBytes       int    `json:"body_bytes"`
	EnvelopeBytes   int    `json:"envelope_bytes"`
	SHA256Body      string `json:"sha256_body"`
	SHA256Envelope  string `json:"sha256_envelope"`
}

// CodecWireNames maps SDK codec.Name() to Gorilla manifest fields.
func CodecWireNames(codecName string) (payloadFormat, envelopeFormat string, err error) {
	switch codecName {
	case "jsonl/json":
		return "jsonl", "json_envelope", nil
	case "row_proto/json":
		return "row_proto", "json_envelope", nil
	case "row_proto/native":
		return "row_proto", "proto_envelope", nil
	case "column_proto/json":
		return "column_proto", "json_envelope", nil
	case "column_proto/native":
		return "column_proto", "proto_envelope", nil
	default:
		return "", "", fmt.Errorf("unknown codec %q", codecName)
	}
}

// ExportFixtures writes envelope and body bytes plus manifest.json under dir.
func ExportFixtures(dir string) error {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create fixture dir: %w", err)
	}

	manifest := FixtureManifest{
		SchemaVersion: FixtureSchemaVersion,
		Source:        "sdk",
	}

	for _, workload := range SyntheticWorkloads() {
		fixtures, err := recordFixtures(workload.Rows)
		if err != nil {
			return fmt.Errorf("dataset %s: %w", workload.Name, err)
		}
		for _, fixture := range fixtures {
			for _, codec := range benchmarkCodecs() {
				encoded, err := codec.Encode(fixture.Records)
				if err != nil {
					return fmt.Errorf(
						"%s/%s/%s: encode: %w",
						workload.Name,
						fixture.Mode,
						codec.Name(),
						err,
					)
				}
				body, err := extractBodyBytes(codec, fixture.Records, encoded)
				if err != nil {
					return fmt.Errorf(
						"%s/%s/%s: extract body: %w",
						workload.Name,
						fixture.Mode,
						codec.Name(),
						err,
					)
				}
				payloadFormat, envelopeFormat, err := CodecWireNames(codec.Name())
				if err != nil {
					return err
				}
				id := fmt.Sprintf(
					"%s/%s/%s/%s",
					workload.Name,
					fixture.Mode,
					payloadFormat,
					envelopeFormat,
				)
				if err := writeFixtureFiles(dir, id, encoded.Data, body); err != nil {
					return err
				}
				rows, cells := recordCounts(fixture.Records)
				manifest.Fixtures = append(manifest.Fixtures, FixtureEntry{
					ID:             id,
					Dataset:        workload.Name,
					ValueMode:      string(fixture.Mode),
					PayloadFormat:  payloadFormat,
					EnvelopeFormat: envelopeFormat,
					RowCount:       rows,
					CellCount:      cells,
					BodyBytes:      len(body),
					EnvelopeBytes:  len(encoded.Data),
					SHA256Body:     sha256Hex(body),
					SHA256Envelope: sha256Hex(encoded.Data),
				})
			}
		}
	}

	manifestData, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal manifest: %w", err)
	}
	manifestData = append(manifestData, '\n')
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), manifestData, 0o644); err != nil {
		return fmt.Errorf("write manifest: %w", err)
	}
	return nil
}

// LoadManifest reads manifest.json from dir.
func LoadManifest(dir string) (*FixtureManifest, error) {
	data, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
	if err != nil {
		return nil, fmt.Errorf("read manifest: %w", err)
	}
	var manifest FixtureManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return nil, fmt.Errorf("parse manifest: %w", err)
	}
	return &manifest, nil
}

func writeFixtureFiles(dir, id string, envelope, body []byte) error {
	safeID := strings.ReplaceAll(id, "/", "__")
	envelopePath := filepath.Join(dir, safeID+".envelope.bin")
	bodyPath := filepath.Join(dir, safeID+".body.bin")
	if err := os.WriteFile(envelopePath, envelope, 0o644); err != nil {
		return fmt.Errorf("write %s: %w", envelopePath, err)
	}
	if err := os.WriteFile(bodyPath, body, 0o644); err != nil {
		return fmt.Errorf("write %s: %w", bodyPath, err)
	}
	return nil
}

func extractBodyBytes(
	codec EnvelopeCodec,
	records []*spb.HistoryRecord,
	encoded EncodedEnvelope,
) ([]byte, error) {
	switch codec.Name() {
	case "jsonl/json":
		content, err := unmarshalJSONEnvelope(encoded.Data)
		if err != nil {
			return nil, err
		}
		var body strings.Builder
		for rowIndex, line := range content {
			if rowIndex > 0 {
				body.WriteByte('\n')
			}
			body.WriteString(line)
		}
		if len(content) > 0 {
			body.WriteByte('\n')
		}
		return []byte(body.String()), nil
	case "row_proto/json", "row_proto/native":
		return marshalLengthDelimitedRecords(records)
	case "column_proto/json":
		content, err := unmarshalJSONEnvelope(encoded.Data)
		if err != nil {
			return nil, err
		}
		if len(content) != 1 {
			return nil, fmt.Errorf("columnar JSON envelope has %d content entries, want 1", len(content))
		}
		return base64.StdEncoding.DecodeString(content[0])
	case "column_proto/native":
		request := &BenchmarkFileStreamRequest{}
		if err := proto.Unmarshal(encoded.Data, request); err != nil {
			return nil, fmt.Errorf("unmarshal columnar envelope: %w", err)
		}
		batch := request.GetColumnarHistory()
		if batch == nil {
			return nil, fmt.Errorf("protobuf envelope does not contain columnar history")
		}
		return proto.MarshalOptions{Deterministic: true}.Marshal(batch)
	default:
		return nil, fmt.Errorf("unknown codec %q", codec.Name())
	}
}

func marshalLengthDelimitedRecords(records []*spb.HistoryRecord) ([]byte, error) {
	var result []byte
	for rowIndex, record := range records {
		encoded, err := proto.Marshal(record)
		if err != nil {
			return nil, fmt.Errorf("marshal row %d: %w", rowIndex, err)
		}
		result = protowire.AppendVarint(result, uint64(len(encoded)))
		result = append(result, encoded...)
	}
	return result, nil
}

func sha256Hex(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}
