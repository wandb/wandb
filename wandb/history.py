import csv
import os

from wandb import util

HISTORY_FNAME = 'wandb-history.csv'

class History(object):
    """Used to store data that changes over time during runs.

    This file can be read back into Python by converting all calling json.load()
    on all string values.
    """
    def __init__(self, field_names, out_dir='.'):
        self.out_file = open(os.path.join(out_dir, HISTORY_FNAME), 'w')
        self.out_csv = csv.DictWriter(self.out_file, fieldnames=field_names)
        self.out_csv.writeheader()
        self.out_file.flush()
    
    def add(self, row):
        row = {k: util.make_json_if_not_number(v) for k, v in row.items()}
        self.out_csv.writerow(row)
        self.out_file.flush()

    def close(self):
        self.out_file.close()