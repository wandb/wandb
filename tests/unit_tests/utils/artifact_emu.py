import copy


class ArtifactEmulator:
    def __init__(self, random_str, ctx, base_url):
        self._random_str = random_str
        self._ctx = ctx
        self._artifacts = {}
        self._artifacts_by_id = {}
        self._files = {}
        self._base_url = base_url
        self._portfolio_links = {}

    def create(self, variables):
        collection_name = variables["artifactCollectionNames"][0]
        state = "PENDING"
        aliases = []
        latest = None
        art_id = variables.get("digest", "")

        # Find most recent artifact
        versions = self._artifacts.get(collection_name)
        if versions:
            last_version = versions[-1]
            latest = {"id": last_version["digest"], "versionIndex": len(versions) - 1}
        art_seq = {"id": art_id, "latestArtifact": latest}

        aliases.append(dict(artifactCollectionName=collection_name, alias="latest"))

        base_url = self._base_url
        direct_url = f"{base_url}/storage?file=wandb_manifest.json"
        art_data = {
            "id": art_id,
            "digest": "abc123",
            "state": state,
            "labels": [],
            "aliases": aliases,
            "artifactSequence": art_seq,
            "currentManifest": dict(file=dict(directUrl=direct_url)),
        }

        response = {"data": {"createArtifact": {"artifact": copy.deepcopy(art_data)}}}

        # save in artifact emu object
        art_seq["name"] = collection_name
        art_data["artifactSequence"] = art_seq
        art_data["state"] = "COMMITTED"
        art_type = variables.get("artifactTypeName")
        if art_type:
            art_data["artifactType"] = {"id": 1, "name": art_type}
        art_save = copy.deepcopy(art_data)
        self._artifacts.setdefault(collection_name, []).append(art_save)
        self._artifacts_by_id[art_id] = art_save

        # save in context
        self._ctx["artifacts_created"].setdefault(collection_name, {})
        self._ctx["artifacts_created"][collection_name].setdefault("num", 0)
        self._ctx["artifacts_created"][collection_name]["num"] += 1
        if art_type:
            self._ctx["artifacts_created"][collection_name]["type"] = art_type

        return response

    def link(self, variables):
        pfolio_name = variables.get("artifactPortfolioName")
        artifact_id = variables.get("artifactID") or variables.get("clientID")
        if not pfolio_name or not artifact_id:
            raise ValueError(
                "query variables must contain artifactPortfolioName and either artifactID or clientID"
            )
        aliases = variables.get("aliases")
        # We automatically create a portfolio for the user if we can't find the one given.
        links = self._portfolio_links.setdefault(pfolio_name, [])
        if not any(map(lambda x: x["id"] == artifact_id, links)):
            art = {"id": artifact_id, "aliases": [a["alias"] for a in aliases]}
            links.append(art)

        self._ctx["portfolio_links"].setdefault(pfolio_name, {})
        num = len(links)
        self._ctx["portfolio_links"][pfolio_name]["num"] = num
        response = {"data": {"linkArtifact": {"versionIndex": num - 1}}}
        return response

    def create_files(self, variables):
        base_url = self._base_url
        response = {
            "data": {
                "createArtifactFiles": {
                    "files": {
                        "edges": [
                            {
                                "node": {
                                    "id": idx,
                                    "name": af["name"],
                                    "displayName": af["name"],
                                    "uploadUrl": f"{base_url}/storage?file={af['name']}&id={af['artifactID']}",
                                    "uploadHeaders": [],
                                    "artifact": {"id": af["artifactID"]},
                                },
                            }
                            for idx, af in enumerate(variables["artifactFiles"])
                        ],
                    },
                },
            },
        }
        return response

    def query(self, variables, query=None):
        public_api_query_str = "query Artifact($id: ID!) {"
        public_api_query_str2 = "query ArtifactWithCurrentManifest($id: ID!) {"
        art_id = variables.get("id")
        art_name = variables.get("name")
        assert art_id or art_name

        is_public_api_query = query and (
            query.startswith(public_api_query_str)
            or query.startswith(public_api_query_str2)
        )

        if art_name:
            collection_name, version = art_name.split(":", 1)
            artifact = None
            artifacts = self._artifacts.get(collection_name)
            if artifacts:
                if version == "latest":
                    version_num = len(artifacts)
                else:
                    assert version.startswith("v")
                    version_num = int(version[1:])
                artifact = artifacts[version_num - 1]
                # TODO: add alias info?
        elif art_id:
            artifact = self._artifacts_by_id[art_id]

        if is_public_api_query:
            response = {"data": {"artifact": artifact}}
        else:
            response = {"data": {"project": {"artifact": artifact}}}
        return response

    def file(self, entity, digest):
        # TODO?
        return "ARTIFACT %s" % digest, 200

    def storage(self, request):
        fname = request.args.get("file")
        if request.method == "PUT":
            data = request.get_data(as_text=True)
            self._files.setdefault(fname, "")
            # TODO: extend? instead of overwrite, possible to differentiate wandb_manifest.json artifactid?
            self._files[fname] = data
        data = ""
        if request.method == "GET":
            data = self._files[fname]
        return data, 200
