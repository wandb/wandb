"""Build and optinally push the launch agent image."""
import argparse
import os

from wandb.docker import build, push

DOCKERFILE = """
FROM python:3.9-bullseye
LABEL maintainer='Weights & Biases <support@wandb.com>'

# install git
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y git \
    && apt-get -qy autoremove \
    && apt-get clean && rm -r /var/lib/apt/lists/*


# Copy source code and install
COPY .. /src
RUN pip install --no-cache-dir "/src[launch]"

# user set up
RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 launch_agent
USER launch_agent
WORKDIR /home/launch_agent
RUN chown -R launch_agent /home/launch_agent

ENTRYPOINT ["wandb", "launch-agent"]
"""

DOCKERIGNORE = """
.tox/
"""


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push image after creation. This requires that you enter a tag that includes a registry via --tag",
    )
    parser.add_argument("--tag", default="wandb-launch-agent", help="Tag for the image")
    parser.add_argument(
        "--platform", default="linux/amd64", help="Platform to use, e.g. 'linux/amd64'"
    )
    return parser.parse_args()


def main():
    """Build the launch agent image."""
    args = parse_args()
    build_context = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dockerfile_path = os.path.join(build_context, "Dockerfile")
    dockerignore_path = os.path.join(build_context, ".dockerignore")
    with open(dockerfile_path, "w") as f:
        f.write(DOCKERFILE)
    with open(dockerignore_path, "w") as f:
        f.write(DOCKERIGNORE)
    build(
        tags=[args.tag],
        file=dockerfile_path,
        context_path=build_context,
        platform=args.platform,
    )
    if args.push:
        image, tag = args.tag.split(":")
        push(image, tag)

    # Remove the dockerfui
    os.remove(dockerfile_path)
    os.remove(dockerignore_path)


if __name__ == "__main__":
    main()
