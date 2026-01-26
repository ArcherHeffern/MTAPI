from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values


@dataclass
class DotEnvConfig:
    GOOGLE_MAPS_API_KEY: str

    @staticmethod
    def load(dotenv_path: Optional[Path] = None) -> "DotEnvConfig":
        vals = {}
        env = dotenv_values(dotenv_path=dotenv_path)
        for field in fields(DotEnvConfig):
            f: Field = field  # type: ignore
            field_name = f.name  # type: ignore
            field_type = f.type  # type: ignore
            try:
                v = env[field_name]
            except KeyError:
                print(f".env missing key {field_name}")
                raise Exception()
            try:
                v = field_type(v)  # type: ignore
            except:
                print(f"Failed to parse key {field_name} as type {field_type}")
                raise Exception()
            vals[field_name] = v

        return DotEnvConfig(**vals)  # type: ignore
