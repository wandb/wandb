import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--wandb_project", type=str, default=None, help="Cool")
good, bad = parser.parse_known_args()

print(good)
print("---")
print(bad)
