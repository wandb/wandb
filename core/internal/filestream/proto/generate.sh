# Use import paths relative to the project root, which works better with IDEs.
proto_path="${PWD%'core/internal/filestream/proto'}"
protoc -I"$proto_path" \
    --go_out="$proto_path" \
    --go_opt=paths=source_relative \
    "$PWD/wandb_filestream_v1.proto"
