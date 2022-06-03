import json

# Monkey patch Prodigy dataset loading for testing
# Would bypass the requirement to maintain local database for storing Prodigy files.


class Database:
    def get_dataset(self, dataset):
        # load sample dataset in JSON format
        file_name = dataset + ".json"
        with open("prodigy_test_resources/" + file_name) as f:
            data = json.load(f)
            return data
        return []


class Connect:
    def connect(self):
        # initialize sample database
        database = Database()
        return database
