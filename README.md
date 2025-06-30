# Spotify logger
This project consists of two independent Python scripts that share a common database. The first script runs as a background worker, monitoring streaming activity and logging it to the database. The second script provides a set of RESTful APIs for exploring streaming statistics. <br>

## Configuration
This project requires environmental variables for Spotify credentials and database connection, which are set in `.env` file. <br>
Required environmental variables: <br>

| Variable         | Description                 |
|------------------|-----------------------------|
| SP_CLIENT_ID     | Spotify API client ID       |
| SP_CLIENT_SECRET | Spotify API client secret   |
| SP_REDIRECT_URI  | Spotify API redirect uri    |
| DB_HOST          | Database host               |
| DB_NAME          | Database name               |
| DB_USER          | Database username           |
| DB_PASSWORD      | Database password           |
| DB_PORT          | Database port               |

## WORKER.py
The script runs as a background worker that collects streaming activity using Spotify Web API. Activity is retrieved by calling Spotify's endpoint for the current playback state.<br>
**The frequency of requests is adjusted based on the playback state**:
* If music is playing, a request is sent every 5 seconds;
* If music is paused, a request is sent every 15 seconds;
* If playback state is unavailable (e.g., no active device), a request is sent every 60 seconds.

Logging is based on the artist and track name combination, rather than Spotify IDs. This is a deliberate choice to support logging local files, which do not have Spotify-assigned IDs. <br>

Up to 3 artists per song are logged. <br>

This script includes custom queueing logic that loads track combinations from `queue.json` file, where each combination consists of two tracks defined by Spotify-assigned IDs: `currentTrack` and `nextTrack`. When `currentTrack` is detected as playing, the script automatically queues the corresponding `nextTrack`. This logic is based on Spotify-assigned IDs; therefore, local files cannot be queued. <br>
