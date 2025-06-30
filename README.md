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

## STATS.py
This script provides RESTful APIs for exploring streaming statistics. <br>
1. **Get statistics by streams** <br>
_Description_: Returns statistics based on streams. A track counts as a stream if it was played for at least 45 seconds. Each stream is counted for every artist on the track, whether they are the main or a featuring artist.<br>
_URL_: `/statistics/streams` <br>
_Method_: `GET` <br>
2. **Get statistics by duration** <br>
_Description_: Returns statistics based on actual playback time. All tracks played are counted in, regardless of how long they were played. The full time played is attributed to every artist on the track, whether they are the main or a featuring artist. <br>
_URL_: `/statistics/duration` <br>
_Method_: `GET` <br>
3. **Get total streaming time**<br>
_Description_: Returns the total time spent streaming. <br>
_URL_: `/statistics/total` <br>
_Method_: `GET` <br>

### API query parameters: <br>
* **Get statistics by streams** and **Get statistics by duration** <br>

  | Parameter | Type    | Info                                                                                            |
  |-----------|---------|-------------------------------------------------------------------------------------------------|
  | `artist`    | string  | Up to 3 artists can be provided by including the parameter multiple times.                    |
  | `track`     | string  | Only the beginning of the track name is required, but it must match exactly (case sensitive). |
  | `startDate` | date    | Allowed formats: `YYYY-MM-DD`,`YYYY MM DD` or `YYYY/MM/DD` with time `HH:MM:SS`. If the time is not provided, it will default to `00:00:00` to make the range inclusive.|
  | `endDate`   | date    | Allowed formats: `YYYY-MM-DD`,`YYYY MM DD` or `YYYY/MM/DD` with time `HH:MM:SS`. If the time is not provided, it will default to `23:59:59` to make the range inclusive.|
  | `limit`     | integer | Must be greater than 0 or it will be ignored (no limit applied).                              |
  | `type`      | string  | Allowed values: `tracks`, `artists`.                                                          |

* **Get total streaming time**
  | Parameter | Type    | Info                                                                                            |
  |-----------|---------|-------------------------------------------------------------------------------------------------|
  | `startDate` | date    | Allowed formats: `YYYY-MM-DD`,`YYYY MM DD` or `YYYY/MM/DD` with time `HH:MM:SS`. If the time is not provided, it will default to `00:00:00` to make the range inclusive. |
  | `endDate`   | date    | Allowed formats: `YYYY-MM-DD`,`YYYY MM DD` or `YYYY/MM/DD` with time `HH:MM:SS`. If the time is not provided, it will default to `23:59:59` to make the range inclusive. |


### Filtering options
* **Get statistics by streams** and **Get statistics by duration** <br>
  | Statistics                                   | Required parameters | Additional customization                                                                         |
  |----------------------------------------------|---------------------|--------------------------------------------------------------------------------------------------|
  | Top artists                                  | `type`=artists      | `limit` - limits the number of artists returned; `startDate` and/or `endDate` - defines the date range.  |
  | Top tracks                                   | `type`=tracks       | `limit` - limits the number of tracks returned; `startDate` and/or `endDate` - defines the date range.   |
  | Top tracks by artist                         | `artist`            | `limit` - limits the number of tracks returned; `startDate` and/or `endDate` - defines the date range.   |
  | Stream count/Time streamed for a specific song | `artist`, `track`   | `startDate` or/and `endDate` - defines the date range.                                                |

* **Get total streaming time**
  | Statistics                                   | Required parameters | Additional customization                                                                         |
  |----------------------------------------------|---------------------|--------------------------------------------------------------------------------------------------|
  | Total time spent streaming                   | -                   | `startDate` and/or `endDate` - defines the date range.                                           |
  | Total time spent streaming a specific artist | `artist`            |`startDate` and/or `endDate` - defines the date range.  |

## Database schema
This project uses a single shared PostgreSQL database that consists of two tables - `history` and `error_log`. 
### Tables
1. `history` <br>
_Description_: Stores streaming history data. <br>
_Schema_: <br>

    | name       |   type    |
    |------------|-----------|
    | id         | int8      |
    | artist1    | text      |
    | artist2    | text      |
    | artist3    | text      |
    | track_name | text      |
    | played_at  | timestamp |
    | progress   | int8      |
    | duration   | int8      |

2. `error_log` <br>
_Description_: Used to record any errors encountered. <br>
_Schema_: <br>

    | name        | type      |
    |-------------|-----------|
    | id          | int4      |
    | date        | timestamp |
    | description | text      |
    | type        | text      |
