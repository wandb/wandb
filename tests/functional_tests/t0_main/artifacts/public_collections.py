import wandb


def main():
    run = wandb.init(entity="mock_server_entity", project="test")
    art = wandb.Artifact("test_artifact", type="model")
    art.add_file("public_collection.py")
    run.link_artifact(art, "mock_server_entity/test/test_port")
    run.finish()

    collections = wandb.Api().artifact_type("model", "test").collections()
    assert len(collections) == 2


if __name__ == "__main__":
    main()
