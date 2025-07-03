# Use import paths relative to the project root, which works better with IDEs.
proto_path="${PWD%'core/internal/monitor/tpuproto'}"
protoc -I"$proto_path" \
    --go_out="$proto_path" \
    --go_opt=paths=source_relative \
    --go-grpc_out="$proto_path" \
    --go-grpc_opt=paths=source_relative \
    "$PWD/tpu_metric_service.proto"
