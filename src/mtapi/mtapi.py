from pathlib import Path
from time import sleep
from typing import Literal, Optional, TypeAlias, TypedDict
import contextlib, copy
from urllib import request
from collections import defaultdict
from itertools import islice
from operator import itemgetter
import math, json
import threading
import logging
from src.mtaproto.feedresponse import FeedResponse, Trip, TripStop, TZ
from datetime import timedelta, datetime

logger = logging.getLogger(__name__)


# List of pair: Lat, Lng
Location: TypeAlias = list[float] | tuple[float, float]


def distance(p1: Location, p2: Location) -> float:
    return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)


class StationDict(TypedDict):
    id: str
    location: Location
    name: str
    stops: dict[str, Location]


class Train(TypedDict):
    name: str
    time: datetime


class SerializedStation(TypedDict):
    name: str
    lat: float
    lng: float
    northbound_trains: list[Train]
    southbound_trains: list[Train]
    routes: set[str]
    last_update: datetime


logger = logging.getLogger(__name__)


class Station:
    def __init__(self, d: StationDict):
        self.d = d
        self.trains: dict[Literal["N", "S"], list[Train]] = {}
        self.clear_train_data()
        self.routes: set[str] = set()
        self.last_update: datetime

    def add_train(
        self,
        route_id: str,
        direction: Literal["N", "S"],
        train_time: datetime,
        feed_time: datetime,
    ):
        self.routes.add(route_id)
        self.trains[direction].append(Train(name=route_id, time=train_time))
        self.last_update = feed_time

    def clear_train_data(self):
        self.trains["N"] = []
        self.trains["S"] = []
        self.routes = set()
        self.last_update = datetime.now()

    def sort_trains(self, max_trains: int):
        self.trains["S"] = sorted(self.trains["S"], key=itemgetter("time"))[:max_trains]
        self.trains["N"] = sorted(self.trains["N"], key=itemgetter("time"))[:max_trains]

    def serialize(self) -> SerializedStation:
        out: SerializedStation = {
            "name": self.d["name"],
            "lat": self.d["location"][0],
            "lng": self.d["location"][1],
            "northbound_trains": self.trains["N"],
            "southbound_trains": self.trains["S"],
            "routes": self.routes,
            "last_update": self.last_update,
        }
        return out


class Mtapi(object):

    _FEED_URLS = [
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",  # 1234567S
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",  # L
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",  # NRQW
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",  # BDFM
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",  # ACE
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",  # (SIR)
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",  # JZ
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",  # G
    ]

    def __init__(
        self,
        stations_file: Path,
        expires_seconds: int = 60,
        max_trains: int = 10,
        max_minutes: int = 30,
        threaded: bool = False,
    ):
        self._MAX_TRAINS: int = max_trains
        self._MAX_MINUTES: int = max_minutes
        self._EXPIRES_SECONDS: int = expires_seconds
        self._THREADED: bool = threaded
        self._stations: dict[str, Station] = {}
        self._stops_to_stations: dict[str, str] = {}
        self._routes: dict[str, set[str]] = {}
        self._read_lock: threading.RLock = threading.RLock()

        # initialize the stations database
        unparsed_stations: dict[str, StationDict] = {}
        try:
            with open(stations_file, "r") as f:
                unparsed_stations = json.load(f)
                for id in unparsed_stations:
                    self._stations[id] = Station(unparsed_stations[id])
                self._stops_to_stations = self._build_stops_index(self._stations)

        except IOError:
            print(f"Couldn't load stations file {str(stations_file)}")
            exit()

        self.update()

        if threaded:
            self.threader = MtapiThreader(self, expires_seconds)
            self.threader.start_timer()

    @staticmethod
    def _build_stops_index(stations: dict[str, Station]) -> dict[str, str]:
        stops: dict[str, str] = {}
        for station_id in stations.keys():
            for stop_id in stations[station_id].d["stops"].keys():
                stops[stop_id] = station_id

        return stops

    def _load_mta_feed(self, feed_url: str) -> Optional[FeedResponse]:
        try:
            r = request.Request(feed_url)
            with contextlib.closing(request.urlopen(r)) as r:
                data: str = r.read()
                return FeedResponse(data)

        except Exception as e:
            logger.error("Couldn't connect to MTA server: " + str(e))
            return None

    def update(self):
        logger.info("updating...")
        self._last_update = datetime.now(TZ)

        # create working copy for thread safety
        stations = copy.deepcopy(self._stations)

        # clear old times
        for id in stations:
            stations[id].clear_train_data()

        routes: defaultdict[str, set[str]] = defaultdict(set)

        for feed_url in self._FEED_URLS:
            mta_data = self._load_mta_feed(feed_url)

            if not mta_data:
                continue

            max_time = self._last_update + timedelta(minutes=self._MAX_MINUTES)

            for entity in mta_data.get_entity():
                trip = Trip(entity)

                if not trip.is_valid():
                    continue

                direction: Literal["N", "S"] = trip.get_direction()
                route_id: str = trip.get_route_id().upper()

                for update in entity.trip_update.stop_time_update:
                    trip_stop = TripStop(update)

                    if (
                        trip_stop.get_time() < self._last_update
                        or trip_stop.get_time() > max_time
                    ):
                        continue

                    stop_id: str = trip_stop.get_stop_id()

                    if stop_id not in self._stops_to_stations:
                        logger.info("Stop %s not found", stop_id)
                        continue

                    station_id = self._stops_to_stations[stop_id]
                    stations[station_id].add_train(
                        route_id,
                        direction,
                        trip_stop.get_time(),
                        mta_data.get_timestamp(),
                    )

                    routes[route_id].add(stop_id)

        # sort by time
        for id in stations:
            stations[id].sort_trains(self._MAX_TRAINS)

        with self._read_lock:
            self._routes = routes
            self._stations = stations

    def last_update(self):
        return self._last_update

    def get_by_point(self, point: Location, limit: int = 5) -> list[SerializedStation]:
        if self.is_expired():
            self.update()

        with self._read_lock:
            sortable_stations = copy.deepcopy(self._stations).values()

        sorted_stations = sorted(
            sortable_stations, key=lambda s: distance(s.d["location"], point)
        )
        serialized_stations = map(lambda s: s.serialize(), sorted_stations)

        return list(islice(serialized_stations, limit))

    def get_routes(self) -> list[str]:
        return list(self._routes.keys())

    def get_stations_of_route(self, route: str) -> list[SerializedStation]:
        route = route.upper()

        if self.is_expired():
            self.update()

        with self._read_lock:
            out = [
                self._stations[self._stops_to_stations[k]].serialize()
                for k in self._routes[route]
            ]

        out.sort(key=lambda x: x["name"])
        return out

    def get_by_id(self, ids: list[str]) -> list[SerializedStation]:
        if self.is_expired():
            self.update()

        with self._read_lock:
            out = [self._stations[k].serialize() for k in ids]

        return out

    def is_expired(self) -> bool:
        if self._THREADED and self.threader and self.threader.restart_if_dead():
            return False
        elif self._EXPIRES_SECONDS:
            age = datetime.now(TZ) - self._last_update
            return age.total_seconds() > self._EXPIRES_SECONDS
        else:
            return False


class MtapiThreader(object):

    LOCK_TIMEOUT = 300
    update_lock = threading.Lock()
    update_lock_time = datetime.now()

    def __init__(self, mtapi: Mtapi, expires_seconds: int = 60):
        self.mtapi = mtapi
        self.EXPIRES_SECONDS = expires_seconds

    def start_timer(self):
        """Start a long-lived thread to loop infinitely and trigger updates at
        some regular interval."""

        logger.info("Starting update thread...")
        self.timer_thread = threading.Thread(target=self.update_timer)
        self.timer_thread.daemon = True
        self.timer_thread.start()

    def update_timer(self):
        """This method runs in its own thread. Run feed updates in short-lived
        threads."""
        while True:
            sleep(self.EXPIRES_SECONDS)
            self.update_thread = threading.Thread(target=self.locked_update)
            self.update_thread.start()

    def locked_update(self):
        if not self.update_lock.acquire(False):
            logger.info("Update locked!")

            lock_age = datetime.now() - self.update_lock_time
            if lock_age.total_seconds() < self.LOCK_TIMEOUT:
                return
            else:
                self.update_lock = threading.Lock()
                logger.warning("Cleared expired update lock")

        self.update_lock_time = datetime.now()

        self.mtapi.update()

        self.update_lock.release()

    def restart_if_dead(self):
        if not self.timer_thread.is_alive():
            logger.warning("Timer died")
            self.start_timer()
            return True

        return False
