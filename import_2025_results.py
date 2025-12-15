"""
Import 2025 FastCAT Results from Excel into SQL Server database.
Assumes tables already exist in the sAKC schema (use create_fastcat_tables.py to create them).
"""

import pyodbc
import pandas as pd
from datetime import datetime
import sys
import os

# Configuration
EXCEL_FILE = r'Results\2025 FastCAT Results.xlsx'
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'

def get_connection():
    """Create SQL Server connection using Windows authentication"""
    connection_string = (
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'Trusted_Connection=yes;'
    )
    try:
        conn = pyodbc.connect(connection_string)
        return conn
    except pyodbc.Error as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

def verify_tables_exist(conn):
    """Verify that all required tables exist"""
    cursor = conn.cursor()
    
    try:
        required_tables = ['Events', 'Dogs', 'Results']
        missing_tables = []
        
        for table in required_tables:
            cursor.execute(f"""
                SELECT COUNT(*) FROM sys.tables 
                WHERE name = '{table}' AND schema_id = SCHEMA_ID('{SCHEMA}')
            """)
            if cursor.fetchone()[0] == 0:
                missing_tables.append(table)
        
        if missing_tables:
            print(f"Error: Required tables do not exist: {', '.join(missing_tables)}")
            print(f"Please run 'python create_fastcat_tables.py create' first to create the tables.")
            return False
        else:
            print(f"Verified: All required tables exist in schema {SCHEMA}.")
            return True
    except pyodbc.Error as e:
        print(f"Error verifying tables: {e}")
        return False

def read_excel_data(excel_file):
    """Read data from Excel file"""
    print(f"Reading Excel file: {excel_file}")
    
    if not os.path.exists(excel_file):
        print(f"Error: File not found: {excel_file}")
        sys.exit(1)
    
    try:
        df = pd.read_excel(excel_file, engine='openpyxl')
        print(f"Read {len(df)} rows from Excel file")
        print(f"Columns: {', '.join(df.columns.tolist())}")
        return df
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        sys.exit(1)

def normalize_data(df):
    """Normalize the data and prepare for insertion"""
    # Standardize column names (handle variations)
    column_mapping = {
        'Event Number': 'EventNumber',
        'EventNumber': 'EventNumber',
        'Event Name': 'EventName',
        'EventName': 'EventName',
        'Event Date': 'EventDate',
        'EventDate': 'EventDate',
        'Year': 'Year',
        'Total Starters': 'TotalStarters',
        'TotalStarters': 'TotalStarters',
        'Dog Name': 'DogName',
        'DogName': 'DogName',
        'Speed (MPH)': 'Speed',
        'Speed': 'Speed',
        'Time': 'Time',
        'Points': 'Points',
        'Ranking': 'Ranking',
        'Rank': 'Ranking',
        'Place': 'Ranking',
        'Handicap': 'Handicap',
        'Breed': 'Breed',
        'Owner': 'Owner',
        'City': 'City',
        'State': 'State',
        'Location': 'Location'
    }
    
    # Rename columns if they exist (case-insensitive matching)
    df.columns = df.columns.str.strip()  # Remove whitespace
    for old_name, new_name in column_mapping.items():
        # Case-insensitive matching
        matching_cols = [col for col in df.columns if col.lower() == old_name.lower()]
        if matching_cols:
            df.rename(columns={matching_cols[0]: new_name}, inplace=True)
    
    # Ensure required columns exist
    required_cols = ['EventNumber', 'DogName', 'Owner']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"Warning: Missing columns: {missing_cols}")
        print(f"Available columns: {df.columns.tolist()}")
    
    # Clean and prepare data
    df = df.copy()
    
    # Convert EventDate to datetime if it's not already
    if 'EventDate' in df.columns:
        df['EventDate'] = pd.to_datetime(df['EventDate'], errors='coerce')
        # Extract Year from EventDate if Year column doesn't exist or is empty
        if 'Year' not in df.columns or df['Year'].isna().all():
            if df['EventDate'].notna().any():
                df['Year'] = df['EventDate'].dt.year
        # If Year exists but has missing values, fill from EventDate
        elif 'Year' in df.columns and df['Year'].isna().any() and df['EventDate'].notna().any():
            mask = df['Year'].isna() & df['EventDate'].notna()
            df.loc[mask, 'Year'] = df.loc[mask, 'EventDate'].dt.year
    
    # Convert numeric columns
    if 'Year' in df.columns:
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').astype('Int64')
    if 'Speed' in df.columns:
        df['Speed'] = pd.to_numeric(df['Speed'], errors='coerce')
    if 'Time' in df.columns:
        df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
    if 'Points' in df.columns:
        df['Points'] = pd.to_numeric(df['Points'], errors='coerce')
    if 'Handicap' in df.columns:
        df['Handicap'] = pd.to_numeric(df['Handicap'], errors='coerce')
    if 'Ranking' in df.columns:
        df['Ranking'] = pd.to_numeric(df['Ranking'], errors='coerce').astype('Int64')
    if 'TotalStarters' in df.columns:
        df['TotalStarters'] = pd.to_numeric(df['TotalStarters'], errors='coerce').astype('Int64')
    
    # Fill NaN values with None for SQL
    df = df.where(pd.notnull(df), None)
    
    return df

def insert_events(conn, df):
    """Insert unique events into Events table"""
    cursor = conn.cursor()
    
    # Get unique events
    event_cols = ['EventNumber', 'EventName', 'EventDate', 'Year', 'City', 'State', 'Location', 'TotalStarters']
    available_cols = [col for col in event_cols if col in df.columns]
    events_df = df[available_cols].drop_duplicates(subset=['EventNumber'])
    
    print(f"\nInserting {len(events_df)} unique events...")
    
    event_id_map = {}  # Map EventNumber to EventID
    
    for _, row in events_df.iterrows():
        event_number = row['EventNumber']
        
        # Check if event already exists
        cursor.execute(f"""
            SELECT EventID FROM [{SCHEMA}].[Events]
            WHERE EventNumber = ?
        """, event_number)
        
        result = cursor.fetchone()
        if result:
            event_id = result[0]
        else:
            # Insert new event
            cursor.execute(f"""
                INSERT INTO [{SCHEMA}].[Events]
                (EventNumber, EventName, EventDate, Year, City, State, Location, TotalStarters)
                OUTPUT INSERTED.EventID
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, 
                row.get('EventNumber'),
                row.get('EventName'),
                row.get('EventDate'),
                row.get('Year'),
                row.get('City'),
                row.get('State'),
                row.get('Location'),
                row.get('TotalStarters')
            )
            event_id = cursor.fetchone()[0]
        
        event_id_map[event_number] = event_id
    
    conn.commit()
    print(f"Events inserted. Total unique events: {len(event_id_map)}")
    return event_id_map

def insert_dogs(conn, df):
    """Insert unique dogs into Dogs table"""
    cursor = conn.cursor()
    
    # Get unique dogs
    dog_cols = ['DogName', 'Breed', 'Owner']
    available_cols = [col for col in dog_cols if col in df.columns]
    dogs_df = df[available_cols].drop_duplicates(subset=['DogName', 'Owner'])
    
    print(f"\nInserting {len(dogs_df)} unique dogs...")
    
    dog_id_map = {}  # Map (DogName, Owner) to DogID
    
    for _, row in dogs_df.iterrows():
        dog_name = row['DogName']
        owner = row.get('Owner')
        
        # Check if dog already exists
        cursor.execute(f"""
            SELECT DogID FROM [{SCHEMA}].[Dogs]
            WHERE DogName = ? AND Owner = ?
        """, dog_name, owner)
        
        result = cursor.fetchone()
        if result:
            dog_id = result[0]
        else:
            # Insert new dog
            cursor.execute(f"""
                INSERT INTO [{SCHEMA}].[Dogs]
                (DogName, Breed, Owner)
                OUTPUT INSERTED.DogID
                VALUES (?, ?, ?)
            """, 
                dog_name,
                row.get('Breed'),
                owner
            )
            dog_id = cursor.fetchone()[0]
        
        dog_id_map[(dog_name, owner)] = dog_id
    
    conn.commit()
    print(f"Dogs inserted. Total unique dogs: {len(dog_id_map)}")
    return dog_id_map

def insert_results(conn, df, event_id_map, dog_id_map):
    """Insert results into Results table"""
    cursor = conn.cursor()
    
    print(f"\nInserting results...")
    
    inserted = 0
    skipped = 0
    errors = 0
    
    for idx, row in df.iterrows():
        try:
            event_number = row['EventNumber']
            dog_name = row['DogName']
            owner = row.get('Owner')
            
            # Get IDs
            event_id = event_id_map.get(event_number)
            dog_id = dog_id_map.get((dog_name, owner))
            
            if not event_id:
                print(f"Warning: Event not found for EventNumber: {event_number}")
                errors += 1
                continue
            
            if not dog_id:
                print(f"Warning: Dog not found for DogName: {dog_name}, Owner: {owner}")
                errors += 1
                continue
            
            # Check if result already exists
            cursor.execute(f"""
                SELECT ResultID FROM [{SCHEMA}].[Results]
                WHERE EventID = ? AND DogID = ?
            """, event_id, dog_id)
            
            if cursor.fetchone():
                skipped += 1
                continue
            
            # Insert result
            cursor.execute(f"""
                INSERT INTO [{SCHEMA}].[Results]
                (EventID, DogID, Speed, Time, Points, Ranking, Handicap)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, 
                event_id,
                dog_id,
                row.get('Speed'),
                row.get('Time'),
                row.get('Points'),
                row.get('Ranking'),
                row.get('Handicap')
            )
            inserted += 1
            
            if (idx + 1) % 1000 == 0:
                print(f"  Processed {idx + 1:,} rows... (inserted: {inserted:,}, skipped: {skipped:,})")
                conn.commit()
        
        except Exception as e:
            print(f"Error inserting result at row {idx + 1}: {e}")
            errors += 1
            continue
    
    conn.commit()
    print(f"\nResults inserted: {inserted:,}")
    print(f"Results skipped (duplicates): {skipped:,}")
    print(f"Errors: {errors:,}")

def main():
    """Main function"""
    print("=" * 60)
    print("FastCAT 2025 Results Import Script")
    print("=" * 60)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Verify tables exist
        if not verify_tables_exist(conn):
            sys.exit(1)
        
        # Read Excel data
        df = read_excel_data(EXCEL_FILE)
        
        # Normalize data
        df = normalize_data(df)
        
        # Insert data in normalized form
        event_id_map = insert_events(conn, df)
        dog_id_map = insert_dogs(conn, df)
        insert_results(conn, df, event_id_map, dog_id_map)
        
        print("\n" + "=" * 60)
        print("Import completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nError during import: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
        print("\nDatabase connection closed.")

if __name__ == "__main__":
    main()
