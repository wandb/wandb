FROM python:3.13

RUN apt-get update && apt-get install htop speedometer -y

RUN pip install wandb

COPY train.py .

ENTRYPOINT ["python3", "train.py"]
