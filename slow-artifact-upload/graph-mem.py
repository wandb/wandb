import matplotlib.pyplot as plt, json


def main(path):
    header, *js = [json.loads(l) for l in open(path)]
    plt.plot(*zip(*((j["elapsed"], j["mem_used"] / 1e9) for j in js if j.get('mem_used') is not None)), label="GB used")
    avg_memgb_per_step = (
        max(j['mem_used'] for j in js if j.get('mem_used') is not None)
        / max(j['cur_step'] for j in js if j.get('cur_step') is not None)
    ) / 1e9
    plt.plot(*zip(*((j["elapsed"], j["cur_step"]*avg_memgb_per_step) for j in js if j.get('cur_step') is not None)), label=f"step (scaled to {avg_memgb_per_step*1e6:.01f}kB/step)")
    plt.legend()
    plt.xlabel("time elapsed")
    plt.ylabel("GB")
    plt.title(f'{header["image_kb"]}kB images, commit {header["commit_hash"][:9]}{"; DIRTY" if header["diff"].strip() else ""}')
    plt.show()


import argparse
parser = argparse.ArgumentParser()
parser.add_argument('path')
args = parser.parse_args()
main(args.path)
