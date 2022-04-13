import matplotlib.pyplot as plt, json


def main(path):
    header, *js = [json.loads(l) for l in open(path)]
    plt.plot(*zip(*((j["elapsed"], j["mem_used"] / 1e9) for j in js if j.get('mem_used') is not None)), label="GB used")
    plt.plot(
        *zip(
            *(
                (
                    j["elapsed"],
                    j["queue_size"]
                    * max(j["mem_used"] for j in js if j.get('mem_used') is not None)
                    / 1e9
                    / max(j["queue_size"] or 0 for j in js),
                )
                for j in js
                if j.get("queue_size") is not None
            )
        ),
        label=f"queue size (arbitrarily scaled, max={max(j['queue_size'] or 0 for j in js)})",
    )
    plt.legend()
    plt.xlabel("time elapsed")
    plt.ylabel("GB")
    plt.title(f'{header["image_kb"]}kB images, queue cap = {header["queue_cap_size"]}, commit {header["commit_hash"][:9]}{"; DIRTY" if header["diff"].strip() else ""}')
    plt.show()


import argparse
parser = argparse.ArgumentParser()
parser.add_argument('path')
args = parser.parse_args()
main(args.path)
