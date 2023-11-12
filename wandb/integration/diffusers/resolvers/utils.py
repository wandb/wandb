def chunkify(input_list, chunk_size):
    chunk_size = max(1, chunk_size)
    return [
        input_list[i : i + chunk_size] for i in range(0, len(input_list), chunk_size)
    ]
