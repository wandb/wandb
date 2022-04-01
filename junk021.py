import asyncio
import datetime


i = 4

results = []


# asynchronously iterate over awaitable iterables
# async def async_iterate(iterable):
#     async for item in iterable:
#         print(item)


async def process(items):
    # print(items)
    for ii, item in enumerate(items):
        if ii > 1:
            await asyncio.sleep(1)
        print(datetime.datetime.now(), item)
        results.append(item)


# asynchronously iterate over multiple lists one element at a time
async def async_iterate(*lists):
    tasks = []
    for item_list in lists:
        # await process(item_list)
        task = asyncio.create_task(process(item_list))
        tasks.append(task)
    await asyncio.gather(*tasks)


def main():
    asyncio.run(async_iterate(['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']))


def main2():
    asyncio.run(async_iterate(['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']))


if __name__ == "__main__":
    main()
    main2()
    print(results)
