# from promise import Promise
# from promise.dataloader import DataLoader


# def id_loader(**options):
#     load_calls = []

#     def fn(keys):
#         load_calls.append(keys)
#         return Promise.resolve(keys)

#     identity_loader = DataLoader(fn, **options)
#     return identity_loader, load_calls


# def test_batches_multiple_requests():
#     identity_loader, load_calls = id_loader()

#     @Promise.safe
#     def safe():
#         promise1 = identity_loader.load(1)
#         promise2 = identity_loader.load(2)
#         return promise1, promise2

#     promise1, promise2 = safe()
#     value1, value2 = Promise.all([promise1, promise2]).get()
#     assert value1 == 1
#     assert value2 == 2

#     assert load_calls == [[1, 2]]


# def test_batches_multiple_requests_two():
#     identity_loader, load_calls = id_loader()

#     @Promise.safe
#     def safe():
#         promise1 = identity_loader.load(1)
#         promise2 = identity_loader.load(2)
#         return Promise.all([promise1, promise2])

#     p = safe()
#     value1, value2 = p.get()

#     assert value1 == 1
#     assert value2 == 2

#     assert load_calls == [[1, 2]]


# @Promise.safe
# def test_batches_multiple_requests_safe():
#     identity_loader, load_calls = id_loader()

#     promise1 = identity_loader.load(1)
#     promise2 = identity_loader.load(2)

#     p = Promise.all([promise1, promise2])

#     value1, value2 = p.get()

#     assert value1 == 1
#     assert value2 == 2

#     assert load_calls == [[1, 2]]
