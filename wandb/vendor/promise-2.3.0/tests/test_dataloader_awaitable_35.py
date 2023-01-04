from pytest import mark
from promise import Promise
from promise.dataloader import DataLoader


def id_loader(**options):
    load_calls = []

    resolve = options.pop("resolve", Promise.resolve)

    def fn(keys):
        load_calls.append(keys)
        return resolve(keys)

    identity_loader = DataLoader(fn, **options)
    return identity_loader, load_calls


@mark.asyncio
async def test_await_dataloader():
    identity_loader, load_calls = id_loader()

    async def load_multiple(identity_loader):
        one = identity_loader.load("load1")
        two = identity_loader.load("load2")
        return await Promise.all([one, two])

    result = await load_multiple(identity_loader)
    assert result == ["load1", "load2"]
    assert load_calls == [["load1"], ["load2"]]


@mark.asyncio
async def test_await_dataloader_safe_promise():
    identity_loader, load_calls = id_loader()

    @Promise.safe
    async def load_multiple(identity_loader):
        one = identity_loader.load("load1")
        two = identity_loader.load("load2")
        return await Promise.all([one, two])

    result = await load_multiple(identity_loader)
    assert result == ["load1", "load2"]
    assert load_calls == [["load1"], ["load2"]]


@mark.asyncio
async def test_await_dataloader_individual():
    identity_loader, load_calls = id_loader()

    async def load_one_then_two(identity_loader):
        one = await identity_loader.load("load1")
        two = await identity_loader.load("load2")
        return [one, two]

    result = await load_one_then_two(identity_loader)
    assert result == ["load1", "load2"]
    assert load_calls == [["load1"], ["load2"]]


@mark.asyncio
async def test_await_dataloader_individual_safe_promise():
    identity_loader, load_calls = id_loader()

    @Promise.safe
    async def load_one_then_two(identity_loader):
        one = await identity_loader.load("load1")
        two = await identity_loader.load("load2")
        return [one, two]

    result = await load_one_then_two(identity_loader)
    assert result == ["load1", "load2"]
    assert load_calls == [["load1"], ["load2"]]


@mark.asyncio
async def test_await_dataloader_two():
    identity_loader, load_calls = id_loader()

    async def load_one_then_two(identity_loader):
        one = await identity_loader.load("load1")
        two = await identity_loader.load("load2")
        return (one, two)

    result12 = await Promise.all([load_one_then_two(identity_loader)])


@mark.asyncio
async def test_await_dataloader_two_safe_promise():
    identity_loader, load_calls = id_loader()

    @Promise.safe
    async def load_one_then_two(identity_loader):
        one = await identity_loader.load("load1")
        two = await identity_loader.load("load2")
        return (one, two)

    result12 = await Promise.all([load_one_then_two(identity_loader)])
