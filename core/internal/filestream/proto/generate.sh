# Use import paths relative to the project root, which works better with IDEs.
proto_path="${PWD%'core/internal/filestream/proto'}"
protoc -I"$proto_path" \
    --go_out="$proto_path" \
    --go_opt=paths=source_relative \
    --go_opt=Mwandb/proto/wandb_base.proto=github.com/wandb/wandb/core/pkg/service_go_proto \
    --go_opt=Mwandb/proto/wandb_system_metrics.proto=github.com/wandb/wandb/core/pkg/service_go_proto \
    "$PWD/wandb_filestream_v1.proto"
