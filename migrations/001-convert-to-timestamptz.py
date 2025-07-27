import os
from dotenv import load_dotenv
import psycopg
import tzlocal

load_dotenv()

#use time zone from the environment if set; otherwise default to system time zone
if 'IANA_TIMEZONE' in os.environ:
    current_timezone = os.environ['IANA_TIMEZONE']
else:
    current_timezone = tzlocal.get_localzone_name()

#----------------------------------------------DB CONNECTION-----------------------------------------------------------
#using cloud hosted PostgreSQL database
host = os.environ['DB_HOST']
db_name = os.environ['DB_NAME']
user = os.environ['DB_USER']
password = os.environ['DB_PASSWORD']
port = os.environ['DB_PORT']

conninfo = f"host={host} port={port} dbname={db_name} user={user} password={password} sslmode='require'" 

with psycopg.connect(conninfo) as conn:
    with conn.cursor() as cursor:
        #convert 'played_at' from local time to UTC timestamptz
        query=f"""
            ALTER TABLE history
            ALTER COLUMN played_at TYPE timestamptz
            USING date AT TIME ZONE '{current_timezone}';
        """
        cursor.execute(query)
        conn.commit()