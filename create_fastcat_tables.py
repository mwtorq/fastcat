"""
Create or clear FastCAT database tables in the sAKC schema.
This script manages the third normal form tables:
- Events: Event information
- Dogs: Dog information
- Results: Individual run results linking Events and Dogs
"""

import pyodbc
import sys
import argparse

# Configuration
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

def create_schema(conn):
    """Create sAKC schema if it doesn't exist"""
    cursor = conn.cursor()
    
    try:
        print(f"Creating schema {SCHEMA} if it doesn't exist...")
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = '{SCHEMA}')
            BEGIN
                EXEC('CREATE SCHEMA [{SCHEMA}]')
            END
        """)
        conn.commit()
        print(f"Schema {SCHEMA} created/verified successfully.")
    except pyodbc.Error as e:
        print(f"Error creating schema: {e}")
        conn.rollback()
        raise

def drop_tables(conn):
    """Drop all tables in the sAKC schema"""
    cursor = conn.cursor()
    
    try:
        print(f"Dropping tables in schema {SCHEMA}...")
        
        # Drop tables in correct order (respecting foreign key constraints)
        tables = ['Results', 'Dogs', 'Events']
        
        for table in tables:
            print(f"  Dropping table {SCHEMA}.{table}...")
            cursor.execute(f"""
                IF EXISTS (SELECT * FROM sys.tables WHERE name = '{table}' AND schema_id = SCHEMA_ID('{SCHEMA}'))
                BEGIN
                    DROP TABLE [{SCHEMA}].[{table}]
                END
            """)
        
        conn.commit()
        print("All tables dropped successfully.")
    except pyodbc.Error as e:
        print(f"Error dropping tables: {e}")
        conn.rollback()
        raise

def create_tables(conn):
    """Create third normal form tables in the sAKC schema"""
    cursor = conn.cursor()
    
    try:
        # Create Events table
        print(f"Creating table {SCHEMA}.Events...")
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Events' AND schema_id = SCHEMA_ID('{SCHEMA}'))
            BEGIN
                CREATE TABLE [{SCHEMA}].[Events] (
                    EventID INT IDENTITY(1,1) PRIMARY KEY,
                    EventNumber NVARCHAR(50) NOT NULL,
                    EventName NVARCHAR(255),
                    EventDate DATE,
                    Year INT,
                    City NVARCHAR(100),
                    State NVARCHAR(50),
                    Location NVARCHAR(255),
                    TotalStarters INT,
                    CONSTRAINT UQ_Events_EventNumber UNIQUE (EventNumber)
                )
            END
        """)
        
        # Create Dogs table
        print(f"Creating table {SCHEMA}.Dogs...")
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Dogs' AND schema_id = SCHEMA_ID('{SCHEMA}'))
            BEGIN
                CREATE TABLE [{SCHEMA}].[Dogs] (
                    DogID INT IDENTITY(1,1) PRIMARY KEY,
                    DogName NVARCHAR(255) NOT NULL,
                    Breed NVARCHAR(100),
                    Owner NVARCHAR(255),
                    CONSTRAINT UQ_Dogs_DogNameOwner UNIQUE (DogName, Owner)
                )
            END
        """)
        
        # Create Results table
        print(f"Creating table {SCHEMA}.Results...")
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Results' AND schema_id = SCHEMA_ID('{SCHEMA}'))
            BEGIN
                CREATE TABLE [{SCHEMA}].[Results] (
                    ResultID INT IDENTITY(1,1) PRIMARY KEY,
                    EventID INT NOT NULL,
                    DogID INT NOT NULL,
                    Speed DECIMAL(10,2),
                    Time DECIMAL(10,3),
                    Points DECIMAL(10,2),
                    Ranking INT,
                    Handicap DECIMAL(10,2),
                    CONSTRAINT FK_Results_Events FOREIGN KEY (EventID) REFERENCES [{SCHEMA}].[Events](EventID),
                    CONSTRAINT FK_Results_Dogs FOREIGN KEY (DogID) REFERENCES [{SCHEMA}].[Dogs](DogID),
                    CONSTRAINT UQ_Results_EventDog UNIQUE (EventID, DogID)
                )
            END
        """)
        
        conn.commit()
        print("All tables created/verified successfully.")
        
    except pyodbc.Error as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
        raise

def clear_tables(conn):
    """Clear all data from tables (but keep table structure)"""
    cursor = conn.cursor()
    
    try:
        print(f"Clearing data from tables in schema {SCHEMA}...")
        
        # Clear tables in correct order (respecting foreign key constraints)
        tables = ['Results', 'Dogs', 'Events']
        
        for table in tables:
            print(f"  Clearing table {SCHEMA}.{table}...")
            cursor.execute(f"""
                IF EXISTS (SELECT * FROM sys.tables WHERE name = '{table}' AND schema_id = SCHEMA_ID('{SCHEMA}'))
                BEGIN
                    TRUNCATE TABLE [{SCHEMA}].[{table}]
                END
            """)
        
        conn.commit()
        print("All tables cleared successfully.")
    except pyodbc.Error as e:
        print(f"Error clearing tables: {e}")
        conn.rollback()
        raise

def verify_tables(conn):
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
            print(f"Warning: Missing tables: {', '.join(missing_tables)}")
            return False
        else:
            print(f"All required tables exist in schema {SCHEMA}.")
            return True
    except pyodbc.Error as e:
        print(f"Error verifying tables: {e}")
        return False

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Create or manage FastCAT database tables in the sAKC schema'
    )
    parser.add_argument(
        'action',
        choices=['create', 'drop', 'clear', 'verify', 'recreate'],
        help='Action to perform: create (create tables), drop (drop tables), clear (clear data), verify (check if tables exist), recreate (drop and recreate)'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("FastCAT Database Table Management")
    print("=" * 60)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        if args.action == 'create':
            create_schema(conn)
            create_tables(conn)
            
        elif args.action == 'drop':
            drop_tables(conn)
            
        elif args.action == 'clear':
            clear_tables(conn)
            
        elif args.action == 'verify':
            create_schema(conn)
            verify_tables(conn)
            
        elif args.action == 'recreate':
            print("\nRecreating tables (drop and create)...")
            drop_tables(conn)
            create_schema(conn)
            create_tables(conn)
        
        print("\n" + "=" * 60)
        print("Operation completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nError during operation: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
        print("\nDatabase connection closed.")

if __name__ == "__main__":
    main()



