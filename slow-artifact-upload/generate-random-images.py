import argparse
from pathlib import Path
from random import randrange

from PIL import Image, ImageDraw

parser = argparse.ArgumentParser(description="Generate a bunch of small random images")
parser.add_argument("n", type=lambda s: int(float(s)), help="number(s) of images to generate")
parser.add_argument("dest", type=Path, help="directory to write images to")


def random_image():
    rbyte = lambda: randrange(256)
    rrgba = lambda: (rbyte(), rbyte(), rbyte(), rbyte())
    im = Image.new('RGBA', (rbyte()+1, rbyte()+1), color=rrgba())
    d = ImageDraw.Draw(im)
    d.line(
        (randrange(im.width), randrange(im.height),
         randrange(im.width), randrange(im.height)),
        fill=rrgba(),
    )
    return im

def main(args):
    dest: Path = args.dest
    n: int = args.n

    dest.mkdir(parents=True, exist_ok=True)

    for i in range(n):
        if i%100 == 0: print(i, '/', n)
        random_image().save(dest / f'{i}.png')

if __name__ == "__main__":
    main(parser.parse_args())