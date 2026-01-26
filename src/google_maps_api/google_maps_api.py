from datetime import timedelta
from typing import Optional
from mtapi.mtapi import Location


class GoogleMapsAPI:
    def __init__(self, api_key: str):
        self.api_key: str = api_key

    def walking_times(
        self, coords: list[tuple[Location, Location]]
    ) -> Optional[list[timedelta]]: ...
