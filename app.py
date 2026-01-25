# coding: utf-8
"""
mta-api-sanity
~~~~~~

Expose the MTA's real-time subway feed as a json api

:copyright: (c) 2014 by Jon Thornton.
:license: BSD, see LICENSE for more details.
"""

from dataclasses import dataclass
from pathlib import Path
from mtapi.mtapi import Mtapi
import json
from datetime import datetime
from functools import wraps, reduce
import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class Config:
    max_trains: int = 10
    max_minutes: int = 30
    cache_seconds: int = 60
    threaded: bool = True
    stations_file: Path = Path("./data/stations.json")


# Override this config
config = Config(max_trains=1)

# set debug logging
if app.debug:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            if isinstance(o, datetime):
                return o.isoformat()
            iterable = iter(o)
        except TypeError:
            pass
        else:
            return list(iterable)
        return json.JSONEncoder.default(self, o)


mta = Mtapi(
    stations_file=config.stations_file,
    max_trains=config.max_trains,
    max_minutes=config.max_minutes,
    expires_seconds=config.cache_seconds,
    threaded=config.threaded,
)


def response_wrapper(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        resp = f(*args, **kwargs)

        if not isinstance(resp, Response):
            # custom JSON encoder; this is important
            resp = Response(
                response=json.dumps(resp, cls=CustomJSONEncoder),
                status=200,
                mimetype="application/json",
            )

        return resp

    return decorated_function


@app.route("/")
@response_wrapper
def index():
    return {
        "title": "MTAPI",
        "readme": "Visit https://github.com/jonthornton/MTAPI for more info",
    }


@app.get("/by-location")
def by_location(lat: float, long: float):
    data = mta.get_by_point((lat, long), 5)
    return _make_envelope(data)


@app.route("/by-route/<route>", methods=["GET"])
@response_wrapper
def by_route(route):

    if route.islower():
        return redirect(request.host_url + "by-route/" + route.upper(), code=301)

    try:
        data = mta.get_by_route(route)
        return _make_envelope(data)
    except KeyError as e:
        resp = Response(
            response=json.dumps({"error": "Station not found"}),
            status=404,
            mimetype="application/json",
        )


@app.route("/by-id/<id_string>", methods=["GET"])
@response_wrapper
def by_index(id_string):
    ids = id_string.split(",")
    try:
        data = mta.get_by_id(ids)
        return _make_envelope(data)
    except KeyError as e:
        resp = Response(
            response=json.dumps({"error": "Station not found"}),
            status=404,
            mimetype="application/json",
        )


@app.route("/routes", methods=["GET"])
@response_wrapper
def routes():
    return {"data": sorted(mta.get_routes()), "updated": mta.last_update()}


def _envelope_reduce(a, b):
    if a["last_update"] and b["last_update"]:
        return a if a["last_update"] < b["last_update"] else b
    elif a["last_update"]:
        return a
    else:
        return b


def _make_envelope(data):
    time = None
    if data:
        time = reduce(_envelope_reduce, data)["last_update"]

    return {"data": data, "updated": time}


if __name__ == "__main__":
    app.run(use_reloader=False)
