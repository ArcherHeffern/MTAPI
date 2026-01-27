from typing import Any, Literal, Sequence
from src.mtaproto import nyct_subway_pb2
from pytz import timezone
from datetime import datetime

TZ = timezone("US/Eastern")


class FeedResponse(object):

    def __init__(self, response_string: str):
        self._pb_data = nyct_subway_pb2.gtfs__realtime__pb2.FeedMessage()
        self._pb_data.ParseFromString(response_string)  # type: ignore

    def get_timestamp(self) -> datetime:
        return datetime.fromtimestamp(self._pb_data.header.timestamp, TZ)  # type: ignore

    def get_entity(self) -> Any:
        return self.__get_attr("entity")  # type: ignore

    def __get_attr(self, name):  # type: ignore
        return getattr(self._pb_data, name)  # type: ignore


class Trip(object):
    def __init__(self, pb_data):  # type: ignore
        self._pb_data = pb_data

    def get_route_id(self) -> str:
        if self._pb_data.trip_update.trip.route_id == "GS":  # type: ignore
            return "S"
        else:
            return self._pb_data.trip_update.trip.route_id  # type: ignore

    def get_direction(self) -> Literal["N", "S"]:
        trip_meta = self._pb_data.trip_update.trip.Extensions[  # type: ignore
            nyct_subway_pb2.nyct_trip_descriptor
        ]
        return nyct_subway_pb2.NyctTripDescriptor.Direction.Name(trip_meta.direction)[0]  # type: ignore

    def is_valid(self) -> bool:
        return bool(self._pb_data.trip_update)  # type: ignore


class TripStop(object):
    def __init__(self, pb_data):  # type: ignore
        self._pb_data = pb_data

    def get_time(self) -> datetime:
        raw_time = self._pb_data.arrival.time or self._pb_data.departure.time  # type: ignore
        return datetime.fromtimestamp(raw_time, TZ)  # type: ignore

    def get_stop_id(self) -> str:
        return str(self._pb_data.stop_id[:3])  # type: ignore

    def __get_attr(self, name):  # type: ignore
        return getattr(self._pb_data, name)  # type: ignore

    # def __getattr__(self, name):

    #     return getattr(self._pb_data, name)
