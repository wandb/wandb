from wandb.apis import public

def test_api_key():
    api = public.Api(api_key="e5c418c17f40f87663b8c3495dfe16fe679b427b")
    art = api.artifact("timssweeney/dev_public_tables/run-2ase1uju-small_table_9:v0")
    art.download()

test_api_key()
