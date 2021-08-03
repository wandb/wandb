import json

# Monkey patch Prodigy dataset loading for testing
# Would bypass the requirement to maintain local SQL database for storing Prodigy files
class connect:
    def __init__(self):
        pass

    def get_dataset(self, dataset):
        # load sample JSONL dataset
        json_list = []
        if dataset == "ner":
            with open('prodigy_sample_dataset.jsonl', 'r') as json_file:
                json_list = list(json_file)
        return json_list