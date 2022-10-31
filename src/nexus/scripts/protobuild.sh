# go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
# mkdir -p proto
#cp ~/work/wb/wandb/wandb/proto/*.proto proto/

SRC_DIR=.
MOD=service/
INC=proto/

protoc -I=$INC \
    --go_opt=Mwandb_base.proto=$MOD \
    --go_opt=Mwandb_telemetry.proto=$MOD \
    --go_opt=Mwandb_internal.proto=$MOD \
    --go_out=. --proto_path=. wandb_internal.proto

protoc -I=$INC \
    --go_opt=Mwandb_base.proto=$MOD \
    --go_out=. --proto_path=. wandb_base.proto

protoc -I=$INC \
    --go_opt=Mwandb_base.proto=$MOD \
    --go_opt=Mwandb_telemetry.proto=$MOD \
    --go_out=. --proto_path=. wandb_telemetry.proto

protoc -I=$INC \
    --go_opt=Mwandb_base.proto=$MOD \
    --go_opt=Mwandb_telemetry.proto=$MOD \
    --go_opt=Mwandb_internal.proto=$MOD \
    --go_opt=Mwandb_server.proto=$MOD \
    --go_out=. --proto_path=. wandb_server.proto
