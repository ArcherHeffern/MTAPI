from dataclasses import dataclass
from datetime import timedelta
from pydantic import BaseModel
from requests import get
from typing import Optional, TypeAlias
from json import loads

Location: TypeAlias = list[float] | tuple[float, float]


@dataclass
class TravelDelta:
    duration: timedelta
    distance_meters: int


from typing import List, Literal
from pydantic import BaseModel


class DistanceDuration(BaseModel):
    text: str
    value: int


class Element(BaseModel):
    distance: DistanceDuration  # Meters
    duration: DistanceDuration  # Seconds
    status: Literal["OK", "NOT_FOUND", "ZERO_RESULTS", "MAX_ROUTE_LENGTH_EXCEEDED"]


class Row(BaseModel):
    elements: List[Element]


class DistanceMatrixResponse(BaseModel):
    destination_addresses: List[str]
    origin_addresses: List[str]
    rows: List[Row]
    status: Literal[
        "OK",
        "INVALID_REQUEST",
        "MAX_ELEMENTS_EXCEEDED",
        "MAX_DIMENSIONS_EXCEEDED",
        "OVER_DAILY_LIMIT",
        "OVER_QUERY_LIMIT",
        "REQUEST_DENIED",
        "UNKNOWN_ERROR",
    ]


class GoogleMapsService:
    def __init__(self, api_key: str):
        self.api_key: str = api_key
        self.walking_times_cache: dict[tuple[Location, Location], TravelDelta] = {}

    def walking_times(
        self, from_: tuple[float, float], tos: list[Location]
    ) -> list[Optional[TravelDelta]]:
        out: list[TravelDelta | None] = [None] * len(tos)
        to_find: list[Location] = []
        for i, to in enumerate(tos):
            if (from_, to) in self.walking_times_cache:
                out[i] = self.walking_times_cache[(from_, to)]
            elif (to, from_) in self.walking_times_cache:
                out[i] = self.walking_times_cache[(to, from_)]
            else:
                to_find.append(to)

        if not to_find:
            return out

        destination_string = ""
        for i, destination in enumerate(to_find):
            end = "" if i == len(to_find) - 1 else "%7C"
            destination_string += f"{destination[0]},{destination[1]}{end}"

        url = f"""
        https://maps.googleapis.com/maps/api/distancematrix/json?origins={from_[0]},{from_[1]}&destinations={destination_string}&units=imperial&key={self.api_key}&mode=walking
        """
        res = get(url)
        if res.status_code != 200:
            return out

        data = DistanceMatrixResponse.model_validate(loads(res.content.decode()))

        op = 0
        for row in data.rows:
            for element in row.elements:
                while out[op]:
                    op += 1
                if element.status != "OK":
                    op += 1
                else:
                    travel_delta = TravelDelta(
                        timedelta(seconds=element.duration.value),
                        element.distance.value,
                    )
                    out[op] = travel_delta
                    self.walking_times_cache[(from_, tos[op])] = travel_delta

        return out
