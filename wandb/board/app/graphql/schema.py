import logging

import graphene
from graphene import relay
from .loader import data, find_run
from app.models import History, Events
import getpass

logger = logging.getLogger(__name__)

# Missing: state, commit, runTime, job


class UserType(graphene.ObjectType):
    id = graphene.ID(required=True)
    email = graphene.String()
    username = graphene.String()
    photoUrl = graphene.String()
    admin = graphene.String()
    defaultFramework = graphene.String()

    def resolve_id(self, info, **args):
        return "id"

    def resolve_photoUrl(self, info, **args):
        return "/unknown.jpeg"

    def resolve_username(self, info, **args):
        return getpass.getuser()


class LogLine(graphene.ObjectType):
    line = graphene.String()
    number = graphene.Int()
    level = graphene.String()
    id = graphene.String()


class LogLineConnection(relay.Connection):
    class Meta:
        node = LogLine


class SweepType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    createdAt = graphene.String()
    updatedAt = graphene.String()
    description = graphene.String()
    state = graphene.String()
    user = graphene.Field(UserType)


class SweepConnectionType(relay.Connection):
    class Meta:
        node = SweepType


class FileType(graphene.ObjectType):
    id = graphene.String()
    name = graphene.String()
    url = graphene.String(upload=graphene.Boolean())
    sizeBytes = graphene.Int()
    updatedAt = graphene.String()


class FileConnectionType(relay.Connection):
    class Meta:
        node = FileType


class Run(graphene.ObjectType):
    class Meta:
        interfaces = (relay.Node, )

    id = graphene.ID(required=True)
    name = graphene.String()
    path = graphene.String()
    host = graphene.String()
    createdAt = graphene.String()
    description = graphene.String()
    github = graphene.String()
    commit = graphene.String()
    state = graphene.String()
    patch = graphene.String()
    config = graphene.types.json.JSONString()
    summaryMetrics = graphene.types.json.JSONString()
    systemMetrics = graphene.types.json.JSONString()
    heartbeatAt = graphene.String()
    events = graphene.List(graphene.String)
    history = graphene.List(graphene.String)
    logLines = relay.ConnectionField(
        LogLineConnection)

    framework = graphene.String()
    shouldStop = graphene.Boolean()
    sweep = graphene.Field(SweepType)
    fileCount = graphene.Int()
    exampleTableColumns = graphene.types.json.JSONString()
    exampleTableTypes = graphene.types.json.JSONString()
    exampleTable = graphene.types.json.JSONString()
    files = relay.ConnectionField(FileConnectionType)

    user = graphene.Field(UserType)

    def resolve_logLines(self, info, **args):
        return []

    def resolve_files(self, info, **args):
        return []

    def resolve_fileCount(self, info, **args):
        return 2

    def resolve_name(self, info, **args):
        return self.id

    def resolve_history(self, info, **args):
        return History(self.path).read().split("\n")

    def resolve_events(self, info, **args):
        return Events(self.path).read().split("\n")

    def resolve_exampleTable(self, info, **args):
        return ""

    def resolve_user(self, info, **args):
        return UserType()


class BucketType(Run):
    pass


class RunConnection(relay.Connection):
    class Meta:
        node = Run


class BucketConnection(relay.Connection):
    class Meta:
        node = BucketType


class Project(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String()
    access = graphene.String()
    entityName = graphene.String()
    description = graphene.String()
    createdAt = graphene.String()
    summaryMetrics = graphene.String()
    views = graphene.JSONString()
    runCount = graphene.Int()
    bucketCount = graphene.Int()

    runs = relay.ConnectionField(
        RunConnection, entityName=graphene.String(), names=graphene.List(graphene.String),
        jobKey=graphene.String(), order=graphene.String())
    buckets = relay.ConnectionField(
        BucketConnection, entityName=graphene.String(), names=graphene.List(graphene.String),
        jobKey=graphene.String(), order=graphene.String())

    run = graphene.Field(Run, name=graphene.String())
    bucket = graphene.Field(BucketType, name=graphene.String())
    sweeps = relay.ConnectionField(SweepConnectionType)

    def resolve_sweeps(self, info, **args):
        return []

    def resolve_run(self, info, **args):
        return find_run(args["name"])

    def resolve_bucket(self, info, **args):
        return find_run(args["name"])

    def resolve_entityName(self, info, **args):
        return "board"

    def resolve_runs(self, info, **args):
        return data["Runs"]

    def resolve_buckets(self, info, **args):
        return data["Runs"]

    def resolve_id(self, info, **args):
        return "default"

    def resolve_name(self, info, **args):
        return "default"

    def resolve_summaryMetrics(self, info, **args):
        return "{}"


class ModelType(Project):
    pass


class Query(graphene.ObjectType):
    project = graphene.Field(
        Project, name=graphene.String(), entityName=graphene.String())
    model = graphene.Field(
        ModelType, name=graphene.String(), entityName=graphene.String())
    viewer = graphene.Field(
        UserType
    )

    def resolve_project(self, info, **args):
        return Project()

    def resolve_model(self, info, **args):
        return ModelType()

    def resolve_viewer(self, info, **args):
        return UserType()


schema = graphene.Schema(query=Query, types=[Project, Run])
