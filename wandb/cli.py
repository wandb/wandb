# -*- coding: utf-8 -*-

import click
from wandb import Api
import random
import time
import os
import re

api = Api()

@click.group()
def main(args=None):
    """Console script for wandb"""
    pass

@main.command()
def models():
    click.echo(click.style("Latest Models", fg="red", bold=True))
    for model in api.list_models()['models']['edges']:
        click.echo("".join(
            (click.style(model['node']['ndbId'], fg="blue", bold=True), 
            " - ", 
            model['node']['description'].split("\n")[0])
        ))

@main.command()
@click.option("--model", envvar='WANDB_MODEL', help="The model you wish to upload to.")
@click.option("--description", help="A description of this revision")
@click.argument("file")
def upload(model, file, description):
    kind = "model" if re.search(r'(meta|json)$', file) else "weights"
    click.echo("Uploading {kind} to model: {model}".format(
        kind=kind,
        model=click.style(model, bold=True)))
    url = api.upload_url(model, "%sUrl" % kind)
    with open(file, 'rb') as f:
        length = os.fstat(f.fileno()).st_size
        with click.progressbar(length=length, label='Uploading %s' % kind,
                            fill_char=click.style('&', fg='green')) as bar:
            api.upload_file( url, f, lambda bites: bar.update(bites) )

@main.command()
@click.option("--model", envvar='WANDB_MODEL', help="The model you want to download.")
@click.option("--kind", type=click.Choice(['model', 'weights']))
def download(model, kind = "weights"):
    click.echo("Downloading {kind} file for {model}".format(
        kind=kind,
        model=click.style(model, bold=True)
    ))

    url = api.download_url(model, "%sUrl" % kind)
    if os.getenv('DEBUG'):
        url = url.replace("s://api.wandb.ai", "://localhost:5000")
    length, response = api.download_file(url)
    with click.progressbar(length=length, label='Downloading %s' % kind,
                           fill_char=click.style('&', fg='green')) as bar:
        with open(url.split("/")[-1], "wb") as f:
            for data in response.iter_content(chunk_size=4096):
                f.write(data)
                bar.update(len(data))

if __name__ == "__main__":
    main()
