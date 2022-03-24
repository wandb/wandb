FROM python:3.9-buster

RUN useradd -m -s /bin/bash --create-home --no-log-init -u 1000 -g 0 test
USER test
WORKDIR /home/test
COPY multi_run.sh /home/test/
COPY multi_run.py /home/test/
COPY test1.py /home/test/
COPY test2.py /home/test/
RUN pip install --no-cache-dir git+https://github.com/wandb/client.git@gong/deployable-launch-agent-v2#egg=wandb


CMD ["python", "./multi_run.py"]
