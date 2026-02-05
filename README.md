# Credits
This project is based on [jonthornton's](https://github.com/jonthorton/MTAPI) [MTAPI](https://github.com/jonthornton/MTAPI/) project, "a small HTTP server that converts the [MTA's realtime subway feed](https://api.mta.info/#/landing) from [Protocol Buffers/GTFS](https://developers.google.com/transit/gtfs/) to JSON". 

# This Fork
## Context
This is part of a project to create a dashboard in Google Chrome's new tab page to inform me which trains are nearby and when should I leave to just catch them.

## Changes
- Migrated build system from venv to uv
- Migrated backend server from Flask to FastAPI. As a result, we now have automated swagger documentation
- Greatly increased coverage of typing
- Modified existing routes to return more data
- Added a new API route to tell a user when to leave to catch nearby trains by integrating with train times and google maps Distance Matrix API. 

# Running the server
## DotEnv
1. Make a .env file using .env.sample for reference. 
2. Create a GOOGLE_MAPS_API_KEY which has access to Google Maps Distance Matrix API

```bash
uv run fastapi run --port 8002 # Prod
uv run fastapi dev --port 8002 # Dev
```

## Generating a Stations File
See the original repo for instructions

## License
The project is made available under the MIT license.
