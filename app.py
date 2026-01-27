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
from src.google_maps_api.google_maps_api import GoogleMapsService, TravelDelta
from src.mtapi.mtapi import (
    Location,
    Mtapi,
    SerializedStation,
    Train,
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
    distance_meters: int
    walking_time_seconds: int


class WrappedResponse[T: StationResponse](BaseModel):
    data: list[T]
    last_updated: datetime


class CloseTrain(BaseModel):
    id: str
    route: str
    route_color: str
    direction: str
    final_stop: str
    train_arrival_time: datetime
    walking_distance_meters: Optional[int]
    walking_time_seconds: Optional[float]
    when_to_leave: Optional[datetime]

    @classmethod
    def get_id(cls, route: str, direction: str) -> str:
        return f"{route}:{direction}"

    @staticmethod
    def create_status() -> str: ...


class CloseTrains(BaseModel):
    close_trains: list[CloseTrain]
    last_updated: datetime


class RoutesResponse(BaseModel):
    routes: list[str]
    last_updated: datetime


google_maps_service = GoogleMapsService(dotenv.GOOGLE_MAPS_API_KEY)


@app.get("/")
def index():
    return {
        "title": "MTAPI",
        "readme": "Visit https://github.com/jonthornton/MTAPI for more info",
    }


@app.get("/by-location")
def by_location(lat: float, lng: float) -> WrappedResponse[StationWithDistanceResponse]:
    nearby_stations = mta.get_by_point((lat, lng), 5)

    travel_destinations: list[Location] = [
        (station["lat"], station["lng"]) for station in nearby_stations
    ]

    # Find walking time
    walking_times: list[TravelDelta | None] = google_maps_service.walking_times(
        (lat, lng), travel_destinations
    )

    if not any(walking_times):
        raise HTTPException(status_code=500, detail="Could not fetch any walking times")

    output: WrappedResponse[StationWithDistanceResponse] = (
        _wrap_station_data_with_last_updated_time(nearby_stations, (lat, lng), walking_times)  # type: ignore
    )

    return output


# MTA Colors
BLUE = "#0062CF"
ORANGE = "#EB6800"
LIGHT_GREEN = "#799534"
BROWN = "#8E5C33"
GREY = "#7C858C"
YELLOW = "#F6BC26"
RED = "#D82233"
DARK_GREEN = "#009952"
PURPLE = "#9A38A1"
TEAL = "#008EB7"
MTA_BLUE = "#08179C"
ISA_BLUE = "#0078C6"


@dataclass(frozen=True)
class Route:
    color: str
    final_northbound_stop: str
    final_southbound_stop: str


ROUTE_MAP: dict[str, Route] = {
    # A/C/E (8 Av / Queens Blvd / Fulton)
    "A": Route(
        color=BLUE,
        final_northbound_stop="Inwood-207 St",
        final_southbound_stop="Far Rockaway-Mott Av",
    ),
    "C": Route(
        color=BLUE, final_northbound_stop="168 St", final_southbound_stop="Euclid Av"
    ),
    "E": Route(
        color=BLUE,
        final_northbound_stop="Jamaica Center-Parsons/Archer",
        final_southbound_stop="World Trade Center",
    ),
    # B/D/F/M (6 Av / Queens Blvd / Culver)
    "B": Route(
        color=ORANGE,
        final_northbound_stop="Bedford Park Blvd",
        final_southbound_stop="Brighton Beach",
    ),
    "D": Route(
        color=ORANGE,
        final_northbound_stop="Norwood-205 St",
        final_southbound_stop="Coney Island-Stillwell Av",
    ),
    "F": Route(
        color=ORANGE,
        final_northbound_stop="Jamaica-179 St",
        final_southbound_stop="Coney Island-Stillwell Av",
    ),
    "M": Route(
        color=ORANGE,
        final_northbound_stop="Forest Hills-71 Av",
        final_southbound_stop="Middle Village-Metropolitan Av",
    ),
    # Shuttles
    "FS": Route(
        color=ORANGE,
        final_northbound_stop="Franklin Av",
        final_southbound_stop="Prospect Park",
    ),
    "S": Route(
        color=GREY,
        final_northbound_stop="Times Sq-42 St",
        final_southbound_stop="Grand Central-42 St",
    ),
    # Crosstown / Canarsie
    "G": Route(
        color=LIGHT_GREEN,
        final_northbound_stop="Court Sq",
        final_southbound_stop="Church Av",
    ),
    "L": Route(
        color=GREY,
        final_northbound_stop="8 Av",
        final_southbound_stop="Canarsie-Rockaway Pkwy",
    ),
    # J/Z (Nassau / Jamaica)
    "J": Route(
        color=BROWN,
        final_northbound_stop="Jamaica Center-Parsons/Archer",
        final_southbound_stop="Broad St",
    ),
    "Z": Route(
        color=BROWN,
        final_northbound_stop="Jamaica Center-Parsons/Archer",
        final_southbound_stop="Broad St",
    ),
    # N/Q/R/W (Broadway)
    "N": Route(
        color=YELLOW,
        final_northbound_stop="Astoria-Ditmars Blvd",
        final_southbound_stop="Coney Island-Stillwell Av",
    ),
    "Q": Route(
        color=YELLOW,
        final_northbound_stop="96 St",
        final_southbound_stop="Coney Island-Stillwell Av",
    ),
    "R": Route(
        color=YELLOW,
        final_northbound_stop="Forest Hills-71 Av",
        final_southbound_stop="Bay Ridge-95 St",
    ),
    "W": Route(
        color=YELLOW,
        final_northbound_stop="Astoria-Ditmars Blvd",
        final_southbound_stop="Whitehall St-South Ferry",
    ),
    # 1/2/3 (7 Av)
    "1": Route(
        color=RED,
        final_northbound_stop="Van Cortlandt Park-242 St",
        final_southbound_stop="South Ferry",
    ),
    "2": Route(
        color=RED,
        final_northbound_stop="Wakefield-241 St",
        final_southbound_stop="Flatbush Av-Brooklyn College",
    ),
    "3": Route(
        color=RED,
        final_northbound_stop="Harlem-148 St",
        final_southbound_stop="New Lots Av",
    ),
    # 4/5/6 (Lexington)
    "4": Route(
        color=DARK_GREEN,
        final_northbound_stop="Woodlawn",
        final_southbound_stop="Crown Heights-Utica Av",
    ),
    "5": Route(
        color=DARK_GREEN,
        final_northbound_stop="Eastchester-Dyre Av",
        final_southbound_stop="Flatbush Av-Brooklyn College",
    ),
    "6": Route(
        color=DARK_GREEN,
        final_northbound_stop="Pelham Bay Park",
        final_southbound_stop="Brooklyn Bridge-City Hall",
    ),
    # Express variants (if you still want them keyed explicitly)
    "6S": Route(
        color=DARK_GREEN,
        final_northbound_stop="Pelham Bay Park",
        final_southbound_stop="Brooklyn Bridge-City Hall",
    ),
    "7": Route(
        color=PURPLE,
        final_northbound_stop="Flushing-Main St",
        final_southbound_stop="34 St-Hudson Yards",
    ),
    "7S": Route(
        color=PURPLE,
        final_northbound_stop="Flushing-Main St",
        final_southbound_stop="34 St-Hudson Yards",
    ),
    # T (planned / future)
    "T": Route(
        color=TEAL,
        final_northbound_stop="Broadway & Houston St (Phase 3)",
        final_southbound_stop="Hanover Sq (Phase 4)",
    ),
}


def compute_when_to_leave(
    train_arrival_time: datetime, walking_time_seconds: float
) -> datetime:
    return train_arrival_time - timedelta(walking_time_seconds)


@app.get("/by-location/renderable")
def by_location_renderable(lat: float, lng: float) -> CloseTrains:
    nearby_stations = mta.get_by_point((lat, lng), 5)

    travel_destinations: list[Location] = [
        (station["lat"], station["lng"]) for station in nearby_stations
    ]

    # Find walking time
    walking_times: list[TravelDelta | None] = google_maps_service.walking_times(
        (lat, lng), travel_destinations
    )

    close_trains: list[CloseTrain] = []
    last_updated = nearby_stations[0]["last_update"]
    for station_index, nearby_station in enumerate(nearby_stations):
        if nearby_station["last_update"] > last_updated:
            last_updated = nearby_station["last_update"]

        for direction, train in [
            ("N", nearby_station["northbound_trains"][0]),
            ("S", nearby_station["southbound_trains"][0]),
        ]:
            route = train["name"]
            if route not in ROUTE_MAP:
                raise HTTPException(
                    500, f"Route '{train["name"]}' not found in ROUTE_TO_COLOR_MAP"
                )
            route_data = ROUTE_MAP[route]
            route_color = route_data.color

            final_stop = (
                route_data.final_northbound_stop
                if direction == "N"
                else route_data.final_southbound_stop
            )
            walking_time = walking_times[station_index]
            if walking_time:
                walking_time_seconds = walking_time.duration.total_seconds()
                when_to_leave = compute_when_to_leave(
                    train["time"], walking_time_seconds
                )
            else:
                walking_time_seconds = None
                when_to_leave = None

            close_train = CloseTrain(
                id=CloseTrain.get_id(route, direction),
                route=route,
                route_color=route_color,
                direction=direction,
                final_stop=final_stop,
                train_arrival_time=train["time"],
                walking_distance_meters=(
                    walking_time.distance_meters if walking_time else None
                ),
                walking_time_seconds=walking_time_seconds,
                when_to_leave=when_to_leave,
            )
            close_trains.append(close_train)

    # TODO: Order by relevence

    return CloseTrains(close_trains=close_trains, last_updated=last_updated)


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
    walking_times: Optional[list[TravelDelta | None]] = None,
) -> WrappedResponse[StationResponse]:
    last_updated = data[0]["last_update"]
    station_responses: list[StationResponse] = []
    for i, d in enumerate(data):
        if distance and walking_times:
            t = walking_times[i]
            if t:
                station_response = StationWithDistanceResponse(
                    distance_meters=t.distance_meters,
                    walking_time_seconds=t.duration.total_seconds(),
                    **d,  # type: ignore
                )
            else:
                station_response = None
        else:
            assert not distance and not walking_times
            station_response = StationResponse(
                **d,  # type: ignore
            )

        if station_response:
            station_responses.append(station_response)
        if d["last_update"] > last_updated:
            last_updated = d["last_update"]

    return WrappedResponse(data=station_responses, last_updated=last_updated)
