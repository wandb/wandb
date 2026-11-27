from wandb.proto import wandb_internal_pb2 as _wandb_internal_pb2
from wandb.proto import wandb_otel_pb2 as _wandb_otel_pb2
from wandb.proto import wandb_settings_pb2 as _wandb_settings_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ErrorType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    UNKNOWN_ERROR: _ClassVar[ErrorType]
    INCOMPLETE_RUN_HISTORY_ERROR: _ClassVar[ErrorType]
UNKNOWN_ERROR: ErrorType
INCOMPLETE_RUN_HISTORY_ERROR: ErrorType

class ServerApiInitRequest(_message.Message):
    __slots__ = ("settings", "service_name")
    SETTINGS_FIELD_NUMBER: _ClassVar[int]
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    settings: _wandb_settings_pb2.Settings
    service_name: str
    def __init__(self, settings: _Optional[_Union[_wandb_settings_pb2.Settings, _Mapping]] = ..., service_name: _Optional[str] = ...) -> None: ...

class ServerApiInitResponse(_message.Message):
    __slots__ = ("error_message", "api_id")
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    API_ID_FIELD_NUMBER: _ClassVar[int]
    error_message: str
    api_id: str
    def __init__(self, error_message: _Optional[str] = ..., api_id: _Optional[str] = ...) -> None: ...

class ApiRequest(_message.Message):
    __slots__ = ("api_id", "read_run_history_request", "features_request", "graphql_request", "download_file_request", "upload_file_request", "mark_run_files_uploaded_request", "stop_run_request", "auth_request", "create_custom_chart_request", "run_queue_operation_request", "open_telemetry_request", "read_run_console_logs_request")
    API_ID_FIELD_NUMBER: _ClassVar[int]
    READ_RUN_HISTORY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    FEATURES_REQUEST_FIELD_NUMBER: _ClassVar[int]
    GRAPHQL_REQUEST_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_FILE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_FILE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    MARK_RUN_FILES_UPLOADED_REQUEST_FIELD_NUMBER: _ClassVar[int]
    STOP_RUN_REQUEST_FIELD_NUMBER: _ClassVar[int]
    AUTH_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CREATE_CUSTOM_CHART_REQUEST_FIELD_NUMBER: _ClassVar[int]
    RUN_QUEUE_OPERATION_REQUEST_FIELD_NUMBER: _ClassVar[int]
    OPEN_TELEMETRY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    READ_RUN_CONSOLE_LOGS_REQUEST_FIELD_NUMBER: _ClassVar[int]
    api_id: str
    read_run_history_request: ReadRunHistoryRequest
    features_request: FeaturesRequest
    graphql_request: GraphQLRequest
    download_file_request: DownloadFileRequest
    upload_file_request: UploadFileRequest
    mark_run_files_uploaded_request: MarkRunFilesUploadedRequest
    stop_run_request: StopRunRequest
    auth_request: AuthRequest
    create_custom_chart_request: CreateCustomChartRequest
    run_queue_operation_request: RunQueueOperationRequest
    open_telemetry_request: _wandb_otel_pb2.OpenTelemetryRequest
    read_run_console_logs_request: ReadRunConsoleLogsRequest
    def __init__(self, api_id: _Optional[str] = ..., read_run_history_request: _Optional[_Union[ReadRunHistoryRequest, _Mapping]] = ..., features_request: _Optional[_Union[FeaturesRequest, _Mapping]] = ..., graphql_request: _Optional[_Union[GraphQLRequest, _Mapping]] = ..., download_file_request: _Optional[_Union[DownloadFileRequest, _Mapping]] = ..., upload_file_request: _Optional[_Union[UploadFileRequest, _Mapping]] = ..., mark_run_files_uploaded_request: _Optional[_Union[MarkRunFilesUploadedRequest, _Mapping]] = ..., stop_run_request: _Optional[_Union[StopRunRequest, _Mapping]] = ..., auth_request: _Optional[_Union[AuthRequest, _Mapping]] = ..., create_custom_chart_request: _Optional[_Union[CreateCustomChartRequest, _Mapping]] = ..., run_queue_operation_request: _Optional[_Union[RunQueueOperationRequest, _Mapping]] = ..., open_telemetry_request: _Optional[_Union[_wandb_otel_pb2.OpenTelemetryRequest, _Mapping]] = ..., read_run_console_logs_request: _Optional[_Union[ReadRunConsoleLogsRequest, _Mapping]] = ...) -> None: ...

class ApiResponse(_message.Message):
    __slots__ = ("read_run_history_response", "features_response", "graphql_response", "download_file_response", "upload_file_response", "mark_run_files_uploaded_response", "stop_run_response", "auth_response", "create_custom_chart_response", "run_queue_operation_response", "read_run_console_logs_response", "api_error_response")
    READ_RUN_HISTORY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    FEATURES_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    GRAPHQL_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_FILE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_FILE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    MARK_RUN_FILES_UPLOADED_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STOP_RUN_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    AUTH_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CREATE_CUSTOM_CHART_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    RUN_QUEUE_OPERATION_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    READ_RUN_CONSOLE_LOGS_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    API_ERROR_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    read_run_history_response: ReadRunHistoryResponse
    features_response: FeaturesResponse
    graphql_response: GraphQLResponse
    download_file_response: DownloadFileResponse
    upload_file_response: UploadFileResponse
    mark_run_files_uploaded_response: MarkRunFilesUploadedResponse
    stop_run_response: StopRunResponse
    auth_response: AuthResponse
    create_custom_chart_response: CreateCustomChartResponse
    run_queue_operation_response: RunQueueOperationResponse
    read_run_console_logs_response: ReadRunConsoleLogsResponse
    api_error_response: ApiErrorResponse
    def __init__(self, read_run_history_response: _Optional[_Union[ReadRunHistoryResponse, _Mapping]] = ..., features_response: _Optional[_Union[FeaturesResponse, _Mapping]] = ..., graphql_response: _Optional[_Union[GraphQLResponse, _Mapping]] = ..., download_file_response: _Optional[_Union[DownloadFileResponse, _Mapping]] = ..., upload_file_response: _Optional[_Union[UploadFileResponse, _Mapping]] = ..., mark_run_files_uploaded_response: _Optional[_Union[MarkRunFilesUploadedResponse, _Mapping]] = ..., stop_run_response: _Optional[_Union[StopRunResponse, _Mapping]] = ..., auth_response: _Optional[_Union[AuthResponse, _Mapping]] = ..., create_custom_chart_response: _Optional[_Union[CreateCustomChartResponse, _Mapping]] = ..., run_queue_operation_response: _Optional[_Union[RunQueueOperationResponse, _Mapping]] = ..., read_run_console_logs_response: _Optional[_Union[ReadRunConsoleLogsResponse, _Mapping]] = ..., api_error_response: _Optional[_Union[ApiErrorResponse, _Mapping]] = ...) -> None: ...

class ApiErrorResponse(_message.Message):
    __slots__ = ("message", "error_type", "http_status")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_TYPE_FIELD_NUMBER: _ClassVar[int]
    HTTP_STATUS_FIELD_NUMBER: _ClassVar[int]
    message: str
    error_type: ErrorType
    http_status: int
    def __init__(self, message: _Optional[str] = ..., error_type: _Optional[_Union[ErrorType, str]] = ..., http_status: _Optional[int] = ...) -> None: ...

class ServerApiCleanupRequest(_message.Message):
    __slots__ = ("api_id",)
    API_ID_FIELD_NUMBER: _ClassVar[int]
    api_id: str
    def __init__(self, api_id: _Optional[str] = ...) -> None: ...

class FeaturesRequest(_message.Message):
    __slots__ = ("server", "org")
    SERVER_FIELD_NUMBER: _ClassVar[int]
    ORG_FIELD_NUMBER: _ClassVar[int]
    server: ServerFeaturesRequest
    org: OrgFeaturesRequest
    def __init__(self, server: _Optional[_Union[ServerFeaturesRequest, _Mapping]] = ..., org: _Optional[_Union[OrgFeaturesRequest, _Mapping]] = ...) -> None: ...

class FeaturesResponse(_message.Message):
    __slots__ = ("server", "org")
    SERVER_FIELD_NUMBER: _ClassVar[int]
    ORG_FIELD_NUMBER: _ClassVar[int]
    server: ServerFeaturesResponse
    org: OrgFeaturesResponse
    def __init__(self, server: _Optional[_Union[ServerFeaturesResponse, _Mapping]] = ..., org: _Optional[_Union[OrgFeaturesResponse, _Mapping]] = ...) -> None: ...

class ServerFeaturesRequest(_message.Message):
    __slots__ = ("features",)
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    features: _containers.RepeatedScalarFieldContainer[_wandb_internal_pb2.ServerFeature]
    def __init__(self, features: _Optional[_Iterable[_Union[_wandb_internal_pb2.ServerFeature, str]]] = ...) -> None: ...

class ServerFeaturesResponse(_message.Message):
    __slots__ = ("enabled",)
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    enabled: _containers.RepeatedScalarFieldContainer[_wandb_internal_pb2.ServerFeature]
    def __init__(self, enabled: _Optional[_Iterable[_Union[_wandb_internal_pb2.ServerFeature, str]]] = ...) -> None: ...

class OrgFeaturesRequest(_message.Message):
    __slots__ = ("org", "features")
    ORG_FIELD_NUMBER: _ClassVar[int]
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    org: str
    features: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, org: _Optional[str] = ..., features: _Optional[_Iterable[str]] = ...) -> None: ...

class OrgFeaturesResponse(_message.Message):
    __slots__ = ("features",)
    class FeaturesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: bool
        def __init__(self, key: _Optional[str] = ..., value: bool = ...) -> None: ...
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    features: _containers.ScalarMap[str, bool]
    def __init__(self, features: _Optional[_Mapping[str, bool]] = ...) -> None: ...

class GraphQLRequest(_message.Message):
    __slots__ = ("query", "variables_json", "omit_variables", "omit_fragments", "omit_fields", "rename_fields")
    class RenameFieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    QUERY_FIELD_NUMBER: _ClassVar[int]
    VARIABLES_JSON_FIELD_NUMBER: _ClassVar[int]
    OMIT_VARIABLES_FIELD_NUMBER: _ClassVar[int]
    OMIT_FRAGMENTS_FIELD_NUMBER: _ClassVar[int]
    OMIT_FIELDS_FIELD_NUMBER: _ClassVar[int]
    RENAME_FIELDS_FIELD_NUMBER: _ClassVar[int]
    query: str
    variables_json: str
    omit_variables: _containers.RepeatedScalarFieldContainer[str]
    omit_fragments: _containers.RepeatedScalarFieldContainer[str]
    omit_fields: _containers.RepeatedScalarFieldContainer[str]
    rename_fields: _containers.ScalarMap[str, str]
    def __init__(self, query: _Optional[str] = ..., variables_json: _Optional[str] = ..., omit_variables: _Optional[_Iterable[str]] = ..., omit_fragments: _Optional[_Iterable[str]] = ..., omit_fields: _Optional[_Iterable[str]] = ..., rename_fields: _Optional[_Mapping[str, str]] = ...) -> None: ...

class GraphQLResponse(_message.Message):
    __slots__ = ("data_json",)
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    data_json: str
    def __init__(self, data_json: _Optional[str] = ...) -> None: ...

class DownloadFileRequest(_message.Message):
    __slots__ = ("path", "url", "size")
    PATH_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    path: str
    url: str
    size: int
    def __init__(self, path: _Optional[str] = ..., url: _Optional[str] = ..., size: _Optional[int] = ...) -> None: ...

class DownloadFileResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UploadFileRequest(_message.Message):
    __slots__ = ("path", "url", "headers")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PATH_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    path: str
    url: str
    headers: _containers.ScalarMap[str, str]
    def __init__(self, path: _Optional[str] = ..., url: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ...) -> None: ...

class UploadFileResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class MarkRunFilesUploadedRequest(_message.Message):
    __slots__ = ("entity", "project", "run_id", "files")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    run_id: str
    files: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., run_id: _Optional[str] = ..., files: _Optional[_Iterable[str]] = ...) -> None: ...

class MarkRunFilesUploadedResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AuthRequest(_message.Message):
    __slots__ = ("authenticate_request", "get_access_token_request")
    AUTHENTICATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    GET_ACCESS_TOKEN_REQUEST_FIELD_NUMBER: _ClassVar[int]
    authenticate_request: AuthenticateRequest
    get_access_token_request: GetAccessTokenRequest
    def __init__(self, authenticate_request: _Optional[_Union[AuthenticateRequest, _Mapping]] = ..., get_access_token_request: _Optional[_Union[GetAccessTokenRequest, _Mapping]] = ...) -> None: ...

class AuthResponse(_message.Message):
    __slots__ = ("authenticate_response", "get_access_token_response")
    AUTHENTICATE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    GET_ACCESS_TOKEN_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    authenticate_response: AuthenticateResponse
    get_access_token_response: GetAccessTokenResponse
    def __init__(self, authenticate_response: _Optional[_Union[AuthenticateResponse, _Mapping]] = ..., get_access_token_response: _Optional[_Union[GetAccessTokenResponse, _Mapping]] = ...) -> None: ...

class AuthenticateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AuthenticateResponse(_message.Message):
    __slots__ = ("default_entity", "username", "email", "teams", "flags_json")
    DEFAULT_ENTITY_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    TEAMS_FIELD_NUMBER: _ClassVar[int]
    FLAGS_JSON_FIELD_NUMBER: _ClassVar[int]
    default_entity: str
    username: str
    email: str
    teams: _containers.RepeatedScalarFieldContainer[str]
    flags_json: str
    def __init__(self, default_entity: _Optional[str] = ..., username: _Optional[str] = ..., email: _Optional[str] = ..., teams: _Optional[_Iterable[str]] = ..., flags_json: _Optional[str] = ...) -> None: ...

class GetAccessTokenRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetAccessTokenResponse(_message.Message):
    __slots__ = ("access_token",)
    ACCESS_TOKEN_FIELD_NUMBER: _ClassVar[int]
    access_token: str
    def __init__(self, access_token: _Optional[str] = ...) -> None: ...

class StopRunRequest(_message.Message):
    __slots__ = ("storage_id",)
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    storage_id: str
    def __init__(self, storage_id: _Optional[str] = ...) -> None: ...

class StopRunResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadRunConsoleLogsRequest(_message.Message):
    __slots__ = ("entity", "project", "run_id", "first", "after", "last")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    FIRST_FIELD_NUMBER: _ClassVar[int]
    AFTER_FIELD_NUMBER: _ClassVar[int]
    LAST_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    run_id: str
    first: int
    after: str
    last: int
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., run_id: _Optional[str] = ..., first: _Optional[int] = ..., after: _Optional[str] = ..., last: _Optional[int] = ...) -> None: ...

class ReadRunConsoleLogsResponse(_message.Message):
    __slots__ = ("lines", "end_cursor", "has_next_page", "total_lines")
    LINES_FIELD_NUMBER: _ClassVar[int]
    END_CURSOR_FIELD_NUMBER: _ClassVar[int]
    HAS_NEXT_PAGE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_LINES_FIELD_NUMBER: _ClassVar[int]
    lines: _containers.RepeatedCompositeFieldContainer[RunConsoleLogLine]
    end_cursor: str
    has_next_page: bool
    total_lines: int
    def __init__(self, lines: _Optional[_Iterable[_Union[RunConsoleLogLine, _Mapping]]] = ..., end_cursor: _Optional[str] = ..., has_next_page: bool = ..., total_lines: _Optional[int] = ...) -> None: ...

class RunConsoleLogLine(_message.Message):
    __slots__ = ("number", "timestamp", "level", "label", "content")
    NUMBER_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    number: int
    timestamp: str
    level: str
    label: str
    content: str
    def __init__(self, number: _Optional[int] = ..., timestamp: _Optional[str] = ..., level: _Optional[str] = ..., label: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class CreateCustomChartRequest(_message.Message):
    __slots__ = ("entity", "name", "display_name", "spec_type", "access", "spec")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    SPEC_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACCESS_FIELD_NUMBER: _ClassVar[int]
    SPEC_FIELD_NUMBER: _ClassVar[int]
    entity: str
    name: str
    display_name: str
    spec_type: str
    access: str
    spec: str
    def __init__(self, entity: _Optional[str] = ..., name: _Optional[str] = ..., display_name: _Optional[str] = ..., spec_type: _Optional[str] = ..., access: _Optional[str] = ..., spec: _Optional[str] = ...) -> None: ...

class CreateCustomChartResponse(_message.Message):
    __slots__ = ("chart_id",)
    CHART_ID_FIELD_NUMBER: _ClassVar[int]
    chart_id: str
    def __init__(self, chart_id: _Optional[str] = ...) -> None: ...

class RunQueueOperationRequest(_message.Message):
    __slots__ = ("create_default_resource_config_request", "create_run_queue_request", "upsert_run_queue_request")
    CREATE_DEFAULT_RESOURCE_CONFIG_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CREATE_RUN_QUEUE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    UPSERT_RUN_QUEUE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    create_default_resource_config_request: CreateDefaultResourceConfigRequest
    create_run_queue_request: CreateRunQueueRequest
    upsert_run_queue_request: UpsertRunQueueRequest
    def __init__(self, create_default_resource_config_request: _Optional[_Union[CreateDefaultResourceConfigRequest, _Mapping]] = ..., create_run_queue_request: _Optional[_Union[CreateRunQueueRequest, _Mapping]] = ..., upsert_run_queue_request: _Optional[_Union[UpsertRunQueueRequest, _Mapping]] = ...) -> None: ...

class RunQueueOperationResponse(_message.Message):
    __slots__ = ("create_default_resource_config_response", "create_run_queue_response", "upsert_run_queue_response")
    CREATE_DEFAULT_RESOURCE_CONFIG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CREATE_RUN_QUEUE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    UPSERT_RUN_QUEUE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    create_default_resource_config_response: CreateDefaultResourceConfigResponse
    create_run_queue_response: CreateRunQueueResponse
    upsert_run_queue_response: UpsertRunQueueResponse
    def __init__(self, create_default_resource_config_response: _Optional[_Union[CreateDefaultResourceConfigResponse, _Mapping]] = ..., create_run_queue_response: _Optional[_Union[CreateRunQueueResponse, _Mapping]] = ..., upsert_run_queue_response: _Optional[_Union[UpsertRunQueueResponse, _Mapping]] = ...) -> None: ...

class CreateDefaultResourceConfigRequest(_message.Message):
    __slots__ = ("entity_name", "resource", "config", "template_variables")
    ENTITY_NAME_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_VARIABLES_FIELD_NUMBER: _ClassVar[int]
    entity_name: str
    resource: str
    config: str
    template_variables: str
    def __init__(self, entity_name: _Optional[str] = ..., resource: _Optional[str] = ..., config: _Optional[str] = ..., template_variables: _Optional[str] = ...) -> None: ...

class CreateDefaultResourceConfigResponse(_message.Message):
    __slots__ = ("success", "default_resource_config_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_RESOURCE_CONFIG_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    default_resource_config_id: str
    def __init__(self, success: bool = ..., default_resource_config_id: _Optional[str] = ...) -> None: ...

class CreateRunQueueRequest(_message.Message):
    __slots__ = ("entity", "project", "queue_name", "access", "prioritization_mode", "default_resource_config_id")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    QUEUE_NAME_FIELD_NUMBER: _ClassVar[int]
    ACCESS_FIELD_NUMBER: _ClassVar[int]
    PRIORITIZATION_MODE_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_RESOURCE_CONFIG_ID_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    queue_name: str
    access: str
    prioritization_mode: str
    default_resource_config_id: str
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., queue_name: _Optional[str] = ..., access: _Optional[str] = ..., prioritization_mode: _Optional[str] = ..., default_resource_config_id: _Optional[str] = ...) -> None: ...

class CreateRunQueueResponse(_message.Message):
    __slots__ = ("success", "queue_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    QUEUE_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    queue_id: str
    def __init__(self, success: bool = ..., queue_id: _Optional[str] = ...) -> None: ...

class UpsertRunQueueRequest(_message.Message):
    __slots__ = ("entity_name", "project_name", "queue_name", "resource_type", "resource_config", "template_variables", "prioritization_mode", "external_links", "client_mutation_id")
    ENTITY_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    QUEUE_NAME_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_CONFIG_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_VARIABLES_FIELD_NUMBER: _ClassVar[int]
    PRIORITIZATION_MODE_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_LINKS_FIELD_NUMBER: _ClassVar[int]
    CLIENT_MUTATION_ID_FIELD_NUMBER: _ClassVar[int]
    entity_name: str
    project_name: str
    queue_name: str
    resource_type: str
    resource_config: str
    template_variables: str
    prioritization_mode: str
    external_links: str
    client_mutation_id: str
    def __init__(self, entity_name: _Optional[str] = ..., project_name: _Optional[str] = ..., queue_name: _Optional[str] = ..., resource_type: _Optional[str] = ..., resource_config: _Optional[str] = ..., template_variables: _Optional[str] = ..., prioritization_mode: _Optional[str] = ..., external_links: _Optional[str] = ..., client_mutation_id: _Optional[str] = ...) -> None: ...

class UpsertRunQueueResponse(_message.Message):
    __slots__ = ("success", "config_schema_validation_errors")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CONFIG_SCHEMA_VALIDATION_ERRORS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    config_schema_validation_errors: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, success: bool = ..., config_schema_validation_errors: _Optional[_Iterable[str]] = ...) -> None: ...

class ReadRunHistoryRequest(_message.Message):
    __slots__ = ("scan_run_history_init", "scan_run_history", "scan_run_history_cleanup", "download_run_history_init", "download_run_history", "download_run_history_status")
    SCAN_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    SCAN_RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    SCAN_RUN_HISTORY_CLEANUP_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_STATUS_FIELD_NUMBER: _ClassVar[int]
    scan_run_history_init: ScanRunHistoryInit
    scan_run_history: ScanRunHistory
    scan_run_history_cleanup: ScanRunHistoryCleanup
    download_run_history_init: DownloadRunHistoryInit
    download_run_history: DownloadRunHistory
    download_run_history_status: DownloadRunHistoryStatus
    def __init__(self, scan_run_history_init: _Optional[_Union[ScanRunHistoryInit, _Mapping]] = ..., scan_run_history: _Optional[_Union[ScanRunHistory, _Mapping]] = ..., scan_run_history_cleanup: _Optional[_Union[ScanRunHistoryCleanup, _Mapping]] = ..., download_run_history_init: _Optional[_Union[DownloadRunHistoryInit, _Mapping]] = ..., download_run_history: _Optional[_Union[DownloadRunHistory, _Mapping]] = ..., download_run_history_status: _Optional[_Union[DownloadRunHistoryStatus, _Mapping]] = ...) -> None: ...

class ReadRunHistoryResponse(_message.Message):
    __slots__ = ("scan_run_history_init", "run_history", "scan_run_history_cleanup", "download_run_history_init", "download_run_history", "download_run_history_status")
    SCAN_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    SCAN_RUN_HISTORY_CLEANUP_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_INIT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_RUN_HISTORY_STATUS_FIELD_NUMBER: _ClassVar[int]
    scan_run_history_init: ScanRunHistoryInitResponse
    run_history: RunHistoryResponse
    scan_run_history_cleanup: ScanRunHistoryCleanupResponse
    download_run_history_init: DownloadRunHistoryInitResponse
    download_run_history: DownloadRunHistoryResponse
    download_run_history_status: DownloadRunHistoryStatusResponse
    def __init__(self, scan_run_history_init: _Optional[_Union[ScanRunHistoryInitResponse, _Mapping]] = ..., run_history: _Optional[_Union[RunHistoryResponse, _Mapping]] = ..., scan_run_history_cleanup: _Optional[_Union[ScanRunHistoryCleanupResponse, _Mapping]] = ..., download_run_history_init: _Optional[_Union[DownloadRunHistoryInitResponse, _Mapping]] = ..., download_run_history: _Optional[_Union[DownloadRunHistoryResponse, _Mapping]] = ..., download_run_history_status: _Optional[_Union[DownloadRunHistoryStatusResponse, _Mapping]] = ...) -> None: ...

class ScanRunHistoryInit(_message.Message):
    __slots__ = ("entity", "project", "run_id", "keys", "use_cache")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    KEYS_FIELD_NUMBER: _ClassVar[int]
    USE_CACHE_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    run_id: str
    keys: _containers.RepeatedScalarFieldContainer[str]
    use_cache: bool
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., run_id: _Optional[str] = ..., keys: _Optional[_Iterable[str]] = ..., use_cache: bool = ...) -> None: ...

class ScanRunHistoryInitResponse(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class ScanRunHistory(_message.Message):
    __slots__ = ("min_step", "max_step", "request_id")
    MIN_STEP_FIELD_NUMBER: _ClassVar[int]
    MAX_STEP_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    min_step: int
    max_step: int
    request_id: int
    def __init__(self, min_step: _Optional[int] = ..., max_step: _Optional[int] = ..., request_id: _Optional[int] = ...) -> None: ...

class RunHistoryResponse(_message.Message):
    __slots__ = ("history_rows",)
    HISTORY_ROWS_FIELD_NUMBER: _ClassVar[int]
    history_rows: _containers.RepeatedCompositeFieldContainer[HistoryRow]
    def __init__(self, history_rows: _Optional[_Iterable[_Union[HistoryRow, _Mapping]]] = ...) -> None: ...

class HistoryRow(_message.Message):
    __slots__ = ("history_items",)
    HISTORY_ITEMS_FIELD_NUMBER: _ClassVar[int]
    history_items: _containers.RepeatedCompositeFieldContainer[ParquetHistoryItem]
    def __init__(self, history_items: _Optional[_Iterable[_Union[ParquetHistoryItem, _Mapping]]] = ...) -> None: ...

class ParquetHistoryItem(_message.Message):
    __slots__ = ("key", "value_json")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_JSON_FIELD_NUMBER: _ClassVar[int]
    key: str
    value_json: str
    def __init__(self, key: _Optional[str] = ..., value_json: _Optional[str] = ...) -> None: ...

class ScanRunHistoryCleanup(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class ScanRunHistoryCleanupResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DownloadRunHistoryInit(_message.Message):
    __slots__ = ("entity", "project", "run_id", "download_dir", "require_complete_history")
    ENTITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_DIR_FIELD_NUMBER: _ClassVar[int]
    REQUIRE_COMPLETE_HISTORY_FIELD_NUMBER: _ClassVar[int]
    entity: str
    project: str
    run_id: str
    download_dir: str
    require_complete_history: bool
    def __init__(self, entity: _Optional[str] = ..., project: _Optional[str] = ..., run_id: _Optional[str] = ..., download_dir: _Optional[str] = ..., require_complete_history: bool = ...) -> None: ...

class DownloadRunHistoryInitResponse(_message.Message):
    __slots__ = ("request_id", "contains_live_data")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CONTAINS_LIVE_DATA_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    contains_live_data: bool
    def __init__(self, request_id: _Optional[int] = ..., contains_live_data: bool = ...) -> None: ...

class DownloadRunHistory(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class DownloadRunHistoryResponse(_message.Message):
    __slots__ = ("downloaded_files", "errors")
    class ErrorsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DOWNLOADED_FILES_FIELD_NUMBER: _ClassVar[int]
    ERRORS_FIELD_NUMBER: _ClassVar[int]
    downloaded_files: _containers.RepeatedScalarFieldContainer[str]
    errors: _containers.ScalarMap[str, str]
    def __init__(self, downloaded_files: _Optional[_Iterable[str]] = ..., errors: _Optional[_Mapping[str, str]] = ...) -> None: ...

class IncompleteRunHistoryError(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DownloadRunHistoryStatus(_message.Message):
    __slots__ = ("request_id",)
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: int
    def __init__(self, request_id: _Optional[int] = ...) -> None: ...

class DownloadRunHistoryStatusResponse(_message.Message):
    __slots__ = ("operation_stats",)
    OPERATION_STATS_FIELD_NUMBER: _ClassVar[int]
    operation_stats: _wandb_internal_pb2.OperationStats
    def __init__(self, operation_stats: _Optional[_Union[_wandb_internal_pb2.OperationStats, _Mapping]] = ...) -> None: ...
