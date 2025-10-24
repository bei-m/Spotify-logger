from flask import Flask, jsonify, request
import datetime as d
from datetime import datetime
from psycopg_pool import ConnectionPool
import os
import tzlocal
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

#----------------------------------------------DB CONNECTION-----------------------------------------------------------
#using cloud hosted PostgreSQL database
host = os.environ['DB_HOST']
db_name = os.environ['DB_NAME']
user = os.environ['DB_USER']
password = os.environ['DB_PASSWORD']
port = os.environ['DB_PORT']

conninfo = f"host={host} port={port} dbname={db_name} user={user} password={password} sslmode='require'" 
pool = ConnectionPool(conninfo=conninfo, min_size=1, max_size=5, timeout=30)

#use time zone from the environment if set; otherwise default to system time zone
if 'IANA_TIMEZONE' in os.environ:
    current_timezone = os.environ['IANA_TIMEZONE']
else:
    current_timezone = tzlocal.get_localzone_name()

#format ms to largest possible time unit
def format_time(ms):
    if ms is None:
        return "0 s"
    seconds = int(ms // 1000)
    time = d.timedelta(seconds=seconds)
    days = time.days
    hours, remainder = divmod(time.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    result = ""
    hours += days*24
    if hours:
        result = str(hours) + "h " + str(minutes) + "m " + str(seconds) + "s"
    elif minutes:
        result = str(minutes)+ "m " + str(seconds) + "s"
    elif seconds:
        result = str(seconds) + "s"
    else:
        result = "0 s"
    
    return result

def format_result(results):
    for record in results: #if records contain artists, rewrite them as a list
        if record.get('artist1'): 
            artists = [record['artist1']]
            record.pop('artist1')
            for i in range (2,4):
                if record[f"artist{i}"] is not None:
                    artists.append(record[f"artist{i}"])
                record.pop(f"artist{i}")
            record['artists'] = ", ".join(artists)
            artists.clear()
        else:
            break
    return results

def format_date(date, date_type='start'):
    #convert date to ISO format
    date = date.replace(" ", "-").replace("/", "-")
    new_date = datetime.fromisoformat(date)
    #format end date to make date interval inclusive
    if date_type=='end' and len(date.strip())==10:
        new_date = new_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    #add timezone
    datetz = new_date.replace(tzinfo=ZoneInfo(current_timezone))
    return datetz

@app.route('/statistics/streams', methods=['GET'])
def get_stats_by_streams():
    artists = request.args.getlist('artist') 
    name = request.args.get('track') 
    start = request.args.get('startDate') 
    end = request.args.get('endDate') 
    limit = request.args.get('limit', 0)
    analysis_type = request.args.get('type')
    
    if len(request.args)<1: #a minimum of one parameter is required
        return jsonify({"error":"No parameters were selected."}), 400
    elif len(request.args)==1 and 'limit' in request.args: #"limit" cannot be the only one parameter
        return jsonify({"error":"Select additional parameters."}), 400
    
    #parameter checking
    if name and not artists: #name requires artist, as song names are not unique
        return jsonify({"error":"Missing data: enter at least one artist."}), 400
    
    if len(artists)>3: #up to 3 artists per track are logged
        return jsonify({"error": "Too many artists entered. The maximum allowed is 3."}), 400
    
    if len(artists)>1 and not name: #when more than 1 artist is provided, statistics are for a specific track
        return jsonify({"error":"Missing data: enter a track name."}), 400
    
    if artists and analysis_type: #type ignored when artists are provided
        analysis_type = None
    
    if analysis_type and analysis_type not in ['tracks', 'artists']: #general statistics can be either by tracks or artists 
        return jsonify({"error":"Invalid type selected. Allowed types: 'artists', 'tracks'."}), 400
    
    if (start or end) and (not analysis_type and not artists): #interval cannot be the only parameter
        return jsonify({"error":"Select additional parameters."}), 400
    
    if start and end:
        start = format_date(start)
        end = format_date(end, 'end')
        if end<start:
            return jsonify({"error":"The end date cannot be earlier than the start date."}), 400
    
    #---------------------------------------------QUERY FORMATION
    #query parts included in every query
    from_part = " FROM history "
    ending = " ORDER BY streams DESC "
    #query parts that will be formed dynamically based on parameters 
    select_part = ["SELECT COUNT(*) as streams"]
    where_part = ["WHERE progress>=45000 "]
    group_part = []
    params = []
    
    #artist, name and type parameters handling
    if artists and name:
        num = len(artists)
        temp = []
        for i in range (1,4):
            field = f"artist{i}"
            select_part.append(field)
            group_part.append(field)
            variables = ",".join(["%s"]*num)
            temp.append(f"{field} IN ({variables})")
            params.extend(artists)
        temp = " OR ".join(temp)
        where_part.append("("+temp+")")
        select_part.append("track_name")
        where_part.append("track_name LIKE %s")
        group_part.append("track_name")  
        params.append(name + '%')
    elif artists and not name:
        select_part.append("track_name ")
        where_part.append("(artist1 = %s OR artist2 = %s OR artist3 = %s)")
        group_part.append("track_name ")
        params.extend([artists[0]]*3)
    elif not artists and not name and analysis_type:
        if analysis_type=="artists": #general statistics - top artists
            select_part.append("artist")
            group_part.append("artist")
            from_part = """
            FROM (
                SELECT played_at, artist1 as artist, track_name, progress FROM history
                UNION ALL
                SELECT played_at, artist2 as artist, track_name, progress FROM history WHERE artist2 IS NOT NULL
                UNION ALL
                SELECT played_at, artist3 as artist, track_name, progress FROM history WHERE artist3 IS NOT NULL
            ) as temp
            """
        elif analysis_type=="tracks": #general statistics - top tracks
            select_part.append("CONCAT_WS(', ', artist1, artist2, artist3) as artists, track_name ")
            group_part.append("artist1, artist2, artist3, track_name ")
    
    #start and end parameters handling   
    if start and end:
        where_part.append("played_at BETWEEN %s and %s")
        params.append(start)
        params.append(end)
    elif start and not end:
        start = format_date(start)
        where_part.append(" played_at >= %s")
        params.append(start)
    elif end and not start:
        end = format_date(end, 'end')
        where_part.append("played_at <= %s ")
        params.append(end)
    
    #limit parameter handling
    if int(limit)>0:
        ending += "\nLIMIT %s"
        params.append(limit)
        
    query = ", ".join(select_part) + from_part + " AND ".join(where_part) + " GROUP BY " + ", ".join(group_part) + ending
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            result = format_result(result)
    if result:
        return jsonify(result), 200
    else:
         return jsonify({"message":"No data found for the selected parameters."}), 200
    
@app.route('/statistics/duration', methods=['GET'])
def get_stats_by_duration():
    artists = request.args.getlist('artist') 
    name = request.args.get('track') 
    start = request.args.get('startDate') 
    end = request.args.get('endDate') 
    limit = request.args.get('limit', 0)
    analysis_type = request.args.get('type')
    
    if len(request.args)<1:  #a minimum of one parameter is required
        return jsonify({"error":"No parameters were selected."}), 400
    elif len(request.args)==1 and 'limit' in request.args: #"limit" cannot be the only one parameter
        return jsonify({"error":"Select additional parameters."}), 400
    
    #parameter checking
    if name and not artists: #name requires artist, as song names are not unique
        return jsonify({"error":"Missing data: enter at least one artist."}), 400
    
    if len(artists)>3: #up to 3 artists per track are logged
        return jsonify({"error": "Too many artists entered. The maximum allowed is 3."}), 400
    
    if len(artists)>1 and not name: #when more than 1 artist is provided, statistics are for a specific track
        return jsonify({"error":"Missing data: enter a track name."}), 400
    
    if artists and analysis_type: #type ignored when artists are provided
        analysis_type = None
        
    if analysis_type and analysis_type not in ['tracks', 'artists']: #general statistics can be either by tracks or artists 
        return jsonify({"error":"Invalid type selected. Allowed types: 'artists', 'tracks'."}), 400
    
    if (start or end) and (not analysis_type and not artists): #interval cannot be the only parameter
        return jsonify({"error":"Select additional parameters."}), 400
    
    if start and end:
        start = format_date(start)
        end = format_date(end, 'end')
        if end<start:
            return jsonify({"error":"The end date cannot be earlier than the start date."}), 400
    
    #---------------------------------------------QUERY FORMATION
    #query parts included in every query
    from_part = "FROM history "
    ending = "\nORDER BY ms DESC "
    #query parts that will be formed dynamically based on parameters
    select_part = []
    where_part = []
    where_temp = []
    group_part = []
    params = []
    
    #artist, name and type parameters handling
    if artists and name:
        num = len(artists)
        temp = []
        for i in range (1,4): 
            field = f"artist{i}"
            select_part.append(field)
            group_part.append(field)
            variables = ",".join(["%s"]*num)
            temp.append(f"{field} IN ({variables})")
            params.extend(artists)
        temp = " OR ".join(temp)
        where_temp.append("("+temp+")")
        select_part.append("track_name")
        where_temp.append("track_name LIKE %s")
        group_part.append("track_name")  
        params.append(name + '%')
    elif artists and not name:
        select_part.append("track_name ")
        where_temp.append("(artist1 = %s OR artist2 = %s OR artist3 = %s)")
        group_part.append("track_name ")
        params.extend([artists[0]]*3)
    elif not artists and not name and analysis_type:
        if analysis_type=="artists": #general statistics - top artists
            select_part.append("artist")
            group_part.append("artist")
            from_part = """
            FROM (
                SELECT played_at, artist1 as artist, track_name, progress FROM history
                UNION ALL
                SELECT played_at, artist2 as artist, track_name, progress FROM history WHERE artist2 IS NOT NULL
                UNION ALL
                SELECT played_at, artist3 as artist, track_name, progress FROM history WHERE artist3 IS NOT NULL
            ) as temp
            """
        elif analysis_type=="tracks": #general statistics - top tracks
            select_part.append("CONCAT_WS(', ', artist1, artist2, artist3) as artists, track_name ")
            group_part.append("artist1, artist2, artist3, track_name ")
    
    #start and end parameter handling   
    if start and end:
        where_temp.append(" played_at BETWEEN %s and %s ")
        params.append(start)
        params.append(end)
    elif start and not end:
        start = format_date(start)
        where_temp.append("played_at >= %s ")
        params.append(start)
    elif end and not start:
        end = format_date(end, 'end')
        where_temp.append(" played_at <= %s ")
        params.append(end)
    
    #limit parameter handling
    if int(limit)>0:
        ending += "\nLIMIT %s"
        params.append(limit)
    
    if len(where_temp)>0:
        where_part = "WHERE " + " AND ".join(where_temp)
    else:
        where_part = ""
    select_part.append("sum(progress) as ms ")
    
    query = "SELECT " + ", ".join(select_part) + from_part + where_part + " GROUP BY " + ", ".join(group_part) + ending
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            result = format_result(result)
    for row in result:
        row['totalDuration'] = format_time(row['ms'])
        row.pop('ms')
      
    if result:
        return jsonify(result), 200
    else:
        return jsonify({"message":"No data found for the selected parameters."}), 200
   
@app.route('/statistics/total', methods=['GET'])
def get_streaming_time():
    start = request.args.get('startDate')
    end = request.args.get('endDate')
    artists = request.args.getlist('artist')

    if len(artists)>1:
        return jsonify({"error":"Too many artists entered. Only one artist is allowed."}), 400
    
    if start and end:
        start = format_date(start)
        end = format_date(end, 'end')
        if end<start:
            return jsonify({"error":"The end date cannot be earlier than the start date."}), 400
        
    params = []
    where_temp = []
    query_start = "SELECT SUM(progress) as ms \nFROM history "
    if start:
        start = format_date(start)
        where_temp.append("played_at>%s")
        params.append(start)
    if end:
        end = format_date(end, 'end')
        where_temp.append("played_at<%s")
        params.append(end)
    if artists:
        artist = artists[0]
        temp = []
        for i in range (1,4):
            temp.append(f"artist{i} like %s")
        temp = " OR ".join(temp)
        where_temp.append("("+temp+")")
        params.extend([artist]*3)
    
    if len(where_temp)>0:
        where_part = " WHERE " + " AND ".join(where_temp)
    else:
        where_part = ""
           
    query = query_start + where_part
    
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
    for row in result:
        if artists:
            row['artist']=artists[0]
        row['total streaming time'] = format_time(row['ms'])
        row.pop('ms')
    if result:
        return jsonify(result), 200
    else:
        return jsonify({"message":"No data found for the selected parameters."}), 200


if __name__ == '__main__':
    app.run(debug=True)
