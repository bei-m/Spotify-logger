import spotipy
from spotipy.oauth2 import SpotifyOAuth
import asyncio
from spotipy.exceptions import SpotifyException
import datetime as d
from datetime import datetime
from psycopg_pool import ConnectionPool
import json
import os
from dotenv import load_dotenv
load_dotenv()

scope = "user-read-recently-played user-read-playback-state user-modify-playback-state"

#----------------------------------------------LOGIN-SPOTIFY-----------------------------------------------------------
client_id = os.environ['SP_CLIENT_ID']
client_secret = os.environ['SP_CLIENT_SECRET']
redirect_uri = os.environ['SP_REDIRECT_URI']
    
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri=redirect_uri, 
    scope=scope))

#----------------------------------------------DB CONNECTION-----------------------------------------------------------
#using cloud hosted PostgreSQL database
host = os.environ['DB_HOST']
db_name = os.environ['DB_NAME']
user = os.environ['DB_USER']
password = os.environ['DB_PASSWORD']
port = os.environ['DB_PORT']

conninfo = f"host={host} port={port} dbname={db_name} user={user} password={password} sslmode='require'" 
pool = ConnectionPool(conninfo=conninfo, min_size=1, max_size=5, timeout=30)

#custom queueing
with open('queue.json', 'r') as file:
    queue_combos = json.load(file)
last_song = ""
added = False
queue_config = bool(len(queue_combos)>0)

#log errors to database table "error_log"
def log_error(error, code):
    time = datetime.now()
    query = f"INSERT INTO error_log (date, type, description) VALUES (%s, %s, %s) RETURNING id;"
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            try: 
                cursor.execute(query, (time, code, error))
                id = cursor.fetchone()[0]
                msg = f"Error logged. ID: {id}"
                print(msg)
            except Exception as e:
                exep = str(e)
                print(f"{time} Exception couldn't be written to database: {exep}\n")
    
def compare_dates (old_date, duration):
    difference = datetime.now() - old_date
    difference = difference.total_seconds() * 1000
    
    return difference<duration

def insert_record(data):
    required = ['artists', 'name', 'progress', 'duration']
    for field in required:
        if field not in data or field==" ":
            log_error("400", "Insert record, missing data: {field}.")
            return
    
    #new record
    artists = data['artists']
    name = data['name']
    duration = data['duration']
    progress = data['progress']
    
    #log up to 3 artists per track
    artist1, artist2, artist3 = (artists+[None]*3)[:3]
    if artist1==None:
        artist1 = "No artist"
    
    #get last record
    query = f"SELECT * FROM history ORDER BY played_at DESC LIMIT 1;"
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            if rows:
                columns = [desc[0] for desc in cursor.description]
                result = [dict(zip(columns, row)) for row in rows]
                
                #data from last record
                id = result[0]['id']
                old_duration = result[0]['duration']
                old_progress = result[0]['progress']
                old_date = result[0]['played_at']
                if result[0]['artist1']==artist1 and result[0]['track_name']==name: #the same song playing
                    if old_progress<=progress and compare_dates(old_date, old_duration):
                        query = f"UPDATE history SET progress = %s WHERE id = %s"
                        cursor.execute(query, (progress, id))
                    else: #song was replayed
                        played_at = datetime.now() 
                        if old_duration-old_progress<6000 and compare_dates(old_date, old_duration): #song was replayed with less than 6s remaining (may happen due to 5s logging interval)
                            query = f"UPDATE history SET progress = %s WHERE id = %s;"
                            cursor.execute(query, (old_duration, id))
                        query = f"\nINSERT INTO history (artist1, artist2, artist3, played_at, track_name, progress, duration)\nVALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;"
                        cursor.execute(query, (artist1, artist2, artist3, played_at, name, progress, duration))
                        id = cursor.fetchone()[0]
                else:
                    if old_duration - old_progress < 6000: #previous song had less than 6s remaining (may happen due to 5s logging interval)
                        query = f"UPDATE history SET progress = %s WHERE id = %s;"
                        cursor.execute(query, (old_duration, id))
                    #new song playing, inserting new record
                    played_at = datetime.now()
                    query = f"INSERT INTO history (artist1, artist2, artist3, played_at, track_name, progress, duration)\nVALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;"
                    cursor.execute(query, (artist1, artist2, artist3, played_at, name, progress, duration))
                    id = cursor.fetchone()[0]
    print(f"Updated/inserted. ID: {id}\n")
    
async def get_data():
    while True:
        global last_song, added
        try:
            artists = []
            #get current playback state
            current = sp.current_user_playing_track()
            if current is not None:
                if current['is_playing']:
                    for artist in current['item']['artists']:
                        artists.append(artist['name'])
                    current_id = current.get('item', {}).get('id', None)
                    song = current['item']['name']
                    progress = current['progress_ms']
                    duration = current['item']['duration_ms']
                    record = {
                        "artists": artists,
                        "name": song,
                        "progress": progress,
                        "duration": duration 
                    }

                    insert_record(record)
                    
                    #queue handling
                    if queue_config:
                        if current_id: #songs without id cannot be queued
                            for combo in queue_combos:
                                #ensure the song is added once
                                if last_song!=current_id:
                                    last_song = current_id
                                    added = False
                                
                                if not added:
                                    if current_id in combo['currentTrack']:
                                        users_queue = sp.queue()
                                        next_song = users_queue['queue'][0]['id']
                                        if not next_song==combo['nextTrack']:
                                            sp.add_to_queue(combo['nextTrack'])
                                        added = True
                                        break
                    await asyncio.sleep(5)
                else: #false when paused
                    await asyncio.sleep(30)
            else: #playback not available or active
                await asyncio.sleep(60)
        #handle errors
        #Spotify specific errors
        except SpotifyException as e:
            status = getattr(e, 'http_status', 'N/A')
            log_error(str(e), str(status))
            print("Spotify exception caught. Check error log.\n")
            await asyncio.sleep(15)
        #all other errors
        except Exception as e:
            log_error(str(e), str(type(e).__name__))
            print("Exception caught. Check error log.\n")
            await asyncio.sleep(15)
            
async def main():
    await asyncio.gather(
        get_data()
    )

asyncio.run(main())
