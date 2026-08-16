"""
Temporary script to add EventLocation and EventAddress columns to Events table.
EventLocation goes before EventDate, EventAddress goes before City.
"""

import pyodbc
import sys

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

def add_columns(conn):
    """Add EventLocation and EventAddress columns to Events table"""
    cursor = conn.cursor()
    
    try:
        print(f"Adding columns to {SCHEMA}.Events table...")
        
        # Check if EventLocation column exists
        cursor.execute(f"""
            SELECT COUNT(*) FROM sys.columns 
            WHERE object_id = OBJECT_ID('[{SCHEMA}].[Events]') 
            AND name = 'EventLocation'
        """)
        event_location_exists = cursor.fetchone()[0] > 0
        
        # Check if EventAddress column exists
        cursor.execute(f"""
            SELECT COUNT(*) FROM sys.columns 
            WHERE object_id = OBJECT_ID('[{SCHEMA}].[Events]') 
            AND name = 'EventAddress'
        """)
        event_address_exists = cursor.fetchone()[0] > 0
        
        if event_location_exists and event_address_exists:
            print("Both EventLocation and EventAddress columns already exist.")
            return
        
        # SQL Server doesn't support ALTER TABLE ... ADD COLUMN ... BEFORE/AFTER
        # We need to create a new table with the correct column order, copy data, drop old, rename new
        
        if not event_location_exists or not event_address_exists:
            print("Creating new table with correct column order...")
            
            # Create new table with all columns in correct order
            cursor.execute(f"""
                -- Create new table with correct column order
                CREATE TABLE [{SCHEMA}].[Events_New] (
                    EventID INT IDENTITY(1,1) PRIMARY KEY,
                    EventNumber NVARCHAR(50) NOT NULL,
                    EventName NVARCHAR(255),
                    EventLocation NVARCHAR(255),
                    EventDate DATE,
                    Year INT,
                    EventAddress NVARCHAR(255),
                    City NVARCHAR(100),
                    State NVARCHAR(50),
                    Location NVARCHAR(255),
                    TotalStarters INT,
                    CONSTRAINT UQ_Events_EventNumber_New UNIQUE (EventNumber)
                )
            """)
            
            # Copy data from old table to new table
            print("Copying data from old table to new table...")
            cursor.execute(f"""
                SET IDENTITY_INSERT [{SCHEMA}].[Events_New] ON;
                
                INSERT INTO [{SCHEMA}].[Events_New] 
                (EventID, EventNumber, EventName, EventLocation, EventDate, Year, EventAddress, City, State, Location, TotalStarters)
                SELECT 
                    EventID,
                    EventNumber,
                    EventName,
                    NULL AS EventLocation,  -- New column, initially NULL
                    EventDate,
                    Year,
                    NULL AS EventAddress,  -- New column, initially NULL
                    City,
                    State,
                    Location,
                    TotalStarters
                FROM [{SCHEMA}].[Events]
                
                SET IDENTITY_INSERT [{SCHEMA}].[Events_New] OFF;
            """)
            
            # Drop foreign key constraints from Results table
            print("Dropping foreign key constraints...")
            cursor.execute(f"""
                IF EXISTS (SELECT * FROM sys.foreign_keys WHERE name = 'FK_Results_Events')
                BEGIN
                    ALTER TABLE [{SCHEMA}].[Results] DROP CONSTRAINT FK_Results_Events
                END
            """)
            
            # Drop old table
            print("Dropping old table...")
            cursor.execute(f"""
                DROP TABLE [{SCHEMA}].[Events]
            """)
            
            # Rename new table
            print("Renaming new table...")
            cursor.execute(f"""
                EXEC sp_rename '[{SCHEMA}].[Events_New]', 'Events'
            """)
            
            # Recreate foreign key constraint
            print("Recreating foreign key constraint...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD CONSTRAINT FK_Results_Events 
                FOREIGN KEY (EventID) REFERENCES [{SCHEMA}].[Events](EventID)
            """)
            
            conn.commit()
            print("Columns added successfully!")
        else:
            print("Columns already exist.")
            
    except pyodbc.Error as e:
        conn.rollback()
        print(f"Error adding columns: {e}")
        raise

def main():
    """Main function"""
    print("=" * 60)
    print("Add EventLocation and EventAddress Columns")
    print("=" * 60)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        add_columns(conn)
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




