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
from typing import Optional

from pydantic import BaseModel
from src.env_loader import DotEnvConfig
from google_maps_api.google_maps_api import GoogleMapsAPI
from src.mtapi.mtapi import (
    Location,
    Mtapi,
    SerializedStation,
    Train,
    distance as compute_distance,
)
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


dotenv = DotEnvConfig.load()


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


mta = Mtapi(
    stations_file=config.stations_file,
    max_trains=config.max_trains,
    max_minutes=config.max_minutes,
    expires_seconds=config.cache_seconds,
    threaded=config.threaded,
)


class StationResponse(BaseModel):
    name: str
    lat: float
    lng: float
    northbound_trains: list[Train]
    southbound_trains: list[Train]
    routes: set[str]


class StationWithDistanceResponse(StationResponse):
    distance: float
    walking_time: timedelta


class WrappedResponse[T: StationResponse](BaseModel):
    data: list[T]
    last_updated: datetime


class RoutesResponse(BaseModel):
    routes: list[str]
    last_updated: datetime


@app.get("/")
def index():
    return {
        "title": "MTAPI",
        "readme": "Visit https://github.com/jonthornton/MTAPI for more info",
    }


@app.get("/by-location")
def by_location(lat: float, lng: float) -> WrappedResponse[StationWithDistanceResponse]:
    nearby_stations = mta.get_by_point((lat, lng), 5)

    travel_coordinates: list[tuple[Location, Location]] = [
        ((lat, lng), (station["lat"], station["lng"])) for station in nearby_stations
    ]

    # Find walking time
    walking_times: Optional[list[timedelta]] = GoogleMapsAPI(
        dotenv.GOOGLE_MAPS_API_KEY
    ).walking_times(travel_coordinates)

    if not walking_times:
        raise HTTPException(status_code=500, detail="Could not fetch walking times")

    output: WrappedResponse[StationWithDistanceResponse] = (
        _wrap_station_data_with_last_updated_time(nearby_stations, (lat, lng), walking_times)  # type: ignore
    )

    # TODO: Order by relevence

    return output


@app.get("/by-route/{route}")
def by_route(route: str) -> WrappedResponse[StationResponse]:
    route = route.upper()
    try:
        data = mta.get_stations_of_route(route)
        return _wrap_station_data_with_last_updated_time(data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Station not found")


@app.get("/by-id/<id_string>")
def by_index(ids: list[str]):
    try:
        data = mta.get_by_id(ids)
        return _wrap_station_data_with_last_updated_time(data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Station not found")


@app.get("/routes")
def routes() -> RoutesResponse:
    return RoutesResponse(
        routes=sorted(mta.get_routes()), last_updated=mta.last_update()
    )


def _wrap_station_data_with_last_updated_time(
    data: list[SerializedStation],
    distance: Optional[Location] = None,
    walking_times: Optional[list[timedelta]] = None,
) -> WrappedResponse[StationResponse]:
    last_updated = data[0]["last_update"]
    station_responses: list[StationResponse] = []
    for i, d in enumerate(data):
        if distance and walking_times:
            station_response = StationWithDistanceResponse(
                distance=compute_distance(distance, (d["lat"], d["lng"])),
                walking_time=walking_times[i],
                **d,  # type: ignore
            )
        else:
            assert not distance and not walking_times
            station_response = StationResponse(
                **d,  # type: ignore
            )
        station_responses.append(station_response)
        if d["last_update"] > last_updated:
            last_updated = d["last_update"]

    return WrappedResponse(data=station_responses, last_updated=last_updated)
