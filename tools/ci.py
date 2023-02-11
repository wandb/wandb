#!/usr/bin/env python

import datetime
import math
import os
import sys
import http.client
import json
import urllib
import subprocess
import sqlite3
import pandas as pd
import functools

import parseperf


DB_FILE = "ci.db"
CIRCLECI_API_TOKEN = "CIRCLECI_TOKEN"
api_token = os.environ.get(CIRCLECI_API_TOKEN)

conn = http.client.HTTPSConnection("circleci.com")

headers = { 'authorization': f"Basic {api_token}" }


def get_all_items(base, params=None):
    params = params or {}
    all_items = []
    page_token = None
    done = False

    while not done:
        if page_token:
            params["page-token"] = page_token
        purl = urllib.parse.urlencode(params)
        url = f"{base}?{purl}"
        conn.request("GET", url, headers=headers)
        res = conn.getresponse()
        data = res.read()
        g = json.loads(data)
        # print("JUNK", g)
        items = g["items"]
        page_token = g["next_page_token"]
        done = not(page_token) or (len(items) == 0)
        all_items.extend(items)
    return all_items


def restore_table(table):
    db = sqlite3.connect(DB_FILE)
    try:
        df = pd.read_sql_query(f"SELECT * from {table}", db)
    except pd.io.sql.DatabaseError:
        return None
    return df


def save_table(items, table, exclude):
    db = sqlite3.connect(DB_FILE)

    index = 0
    keys = list(items[0].keys())
    for i in exclude:
        keys.remove(i)
    df = pd.DataFrame.from_records(items, **{} if index else dict(columns=keys))
    written = 0
    db_replace = True
    if_exists = "replace" if db_replace else "fail"
    print(df)
    written += df.to_sql(
        table, con=db, index=False, if_exists="append" if index else if_exists
    )
    return df


def dbcache(table, exclude=None, invalidate=False): 
    def my_decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not invalidate:
                df = restore_table(table)
                if df is not None:
                    return df
            items = func(*args, **kwargs)
            df = save_table(items, table, exclude=exclude or ())
            return df
        return wrapper
    return my_decorator


@dbcache("pipelines", exclude=("errors", "trigger", "vcs"))
def get_pipelines():
    params={"branch": "main"}
    base = "/api/v2/project/gh/wandb/wandb/pipeline"
    all_items = get_all_items(base, params)
    return all_items


@dbcache("workflows")
def get_workflows(pipeline_ids):
    all_items = []
    for pipe_id in pipeline_ids:
        base = f"/api/v2/pipeline/{pipe_id}/workflow"
        items = get_all_items(base)
        all_items.extend(items)
    return all_items


@dbcache("jobs", exclude=("dependencies",))
def get_jobs(workflow_ids):
    all_items = []
    for work_id in workflow_ids:
        base = f"/api/v2/workflow/{work_id}/job"
        items = get_all_items(base)
        all_items.extend(items)
        # print("jobs:", len(all_items))
    return all_items


@dbcache("artifacts")
def get_artifacts(job_numbers, jobs=None):
    all_items = []
    now = datetime.datetime.now()
    for n, job_number in enumerate(job_numbers):
        # print("TRY", job_number)
        if jobs is not None:
            got = jobs.loc[jobs["job_number"] == float(job_number)]
            # print("FOUND", got)
            if not got.empty:
                started = got["started_at"].values[0]
                if not started:
                    continue
                started = started.rstrip("Z")
                dt = datetime.datetime.fromisoformat(started)
                if dt < now - datetime.timedelta(days=32):
                    print("skip", dt)
                    continue
        if math.isnan(job_number):
            continue
        job_number = int(job_number)
        base = f"/api/v2/project/gh/wandb/wandb/{job_number}/artifacts"
        items = get_all_items(base)
        # print("GOT", items)
        for i in items:
            i["job_number"] = job_number
        all_items.extend(items)
        print("arts:", job_number, n, len(job_numbers), len(all_items))
    return all_items


def junk():
    urls = []
    for i in items:
        if i["path"] != "test-results/junit-yea.xml":
            continue
        urls.append(i["url"])

    # urls = map(lambda x: x["url"], items)
    fname = f"data/junit-yea-{job}.xml"
    if os.path.exists(fname):
        print("exists", fname)
        return
    for url in urls:
        grab(url, fname)


def grab(url, fname):
    if os.path.exists(fname):
        return
    s, o = subprocess.getstatusoutput(
        f'curl -L  -o {fname} -H "Circle-Token: {api_token}" {url!r}'
    )
    assert s == 0


def get_works(pipes):
    for pipe in pipes:
        print("pipe", pipe)
        work_id = get_pipe_works(pipe)
        if not work_id:
            continue
        job_ids = get_jobs(work_id)
        print("jobs", job_ids)
        for job in job_ids:
            if not job:
                continue
            art = get_art(job)


def grab_artifacts(arts):
    fnames = []
    for _index, row in arts.iterrows():
        pth = row["path"]
        url = row["url"]
        num = row["job_number"]
        node = row["node_index"]
        if not pth.startswith("test-results/"):
            continue
        pth = pth.replace("/", "_")
        fname = f"data/{num}_{node}_{pth}"
        grab(url, fname)
        # print(fname)
        fnames.append((num, fname))
    return fnames


def parse_reports(fnames):
    all_reports = []
    for jobnum, fname in fnames:
        reports = parseperf.parse_junit_perf(fname)
        reports = list(reports)
        for r in reports:
            r.jobnum = jobnum
        all_reports.extend(reports)
    return all_reports


def process(reports, jobs):
    import wandb
    run = wandb.init()
    for r in reports:
        if r.name == ":wandb:import::mean":
            job_number = r.jobnum
            got = jobs.loc[jobs["job_number"] == float(job_number)]
            started = got["started_at"].values[0]
            started = started.rstrip("Z")
            dt = datetime.datetime.fromisoformat(started)
            print(job_number, dt, float(r.value))
            run.log(dict(dt=dt, import_time=float(r.value)))


pipeline_ids = get_pipelines()["id"].tolist()
workflow_ids = get_workflows(pipeline_ids)["id"].tolist()
jobs = get_jobs(workflow_ids)
#job_numbers = get_jobs(workflow_ids)["job_number"].tolist()
job_numbers = jobs["job_number"].tolist()
# job_numbers = [388896, 388419, 338849, 373405]
# job_numbers = [388896, 388419, 338849, 373405]
arts = get_artifacts(job_numbers, jobs=jobs)
# print(arts)
fnames = grab_artifacts(arts)
reports = parse_reports(fnames)

process(reports, jobs)
# print("ARTS", arts)
