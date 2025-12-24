"""
Optimize MPHAvg and Ranking by converting from computed columns to regular columns
maintained via triggers. This is much more performant than function-based computed columns.
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

def create_indexes(conn):
    """Create indexes to optimize MPHAvg and Ranking calculations"""
    cursor = conn.cursor()
    
    try:
        print("Creating indexes for performance...")
        
        # Index on Results for DogsID and EventID lookups
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Results_DogsID_EventID' AND object_id = OBJECT_ID('[{SCHEMA}].[Results]'))
            BEGIN
                CREATE NONCLUSTERED INDEX IX_Results_DogsID_EventID 
                ON [{SCHEMA}].[Results] (DogsID, EventID)
                INCLUDE (Speed, Points)
            END
        """)
        
        # Index on Events for Year and EventDate lookups
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Events_Year_EventDate' AND object_id = OBJECT_ID('[{SCHEMA}].[Events]'))
            BEGIN
                CREATE NONCLUSTERED INDEX IX_Events_Year_EventDate 
                ON [{SCHEMA}].[Events] (Year, EventDate)
                INCLUDE (EventID)
            END
        """)
        
        # Index on Dogs for Breed lookups
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Dogs_Breed' AND object_id = OBJECT_ID('[{SCHEMA}].[Dogs]'))
            BEGIN
                CREATE NONCLUSTERED INDEX IX_Dogs_Breed 
                ON [{SCHEMA}].[Dogs] (Breed)
                INCLUDE (DogsID)
            END
        """)
        
        # Index on Results for Speed filtering
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Results_Speed' AND object_id = OBJECT_ID('[{SCHEMA}].[Results]'))
            BEGIN
                CREATE NONCLUSTERED INDEX IX_Results_Speed 
                ON [{SCHEMA}].[Results] (Speed DESC)
                WHERE Speed IS NOT NULL AND Speed > 0
            END
        """)
        
        conn.commit()
        print("Successfully created indexes")
        return True
        
    except pyodbc.Error as e:
        print(f"Error creating indexes: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def convert_to_regular_columns(conn):
    """Convert computed columns to regular columns"""
    cursor = conn.cursor()
    
    try:
        # Check if MPHAvg is a computed column
        cursor.execute(f"""
            SELECT 
                CASE WHEN ccp.definition IS NOT NULL THEN 1 ELSE 0 END AS IS_COMPUTED
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN sys.computed_columns ccp 
                ON ccp.object_id = OBJECT_ID('[{SCHEMA}].[Results]')
                AND ccp.name = c.COLUMN_NAME
            WHERE c.TABLE_SCHEMA = '{SCHEMA}' 
            AND c.TABLE_NAME = 'Results' 
            AND c.COLUMN_NAME = 'MPHAvg'
        """)
        
        result = cursor.fetchone()
        mpavg_is_computed = result[0] if result else 0
        
        # Check if Ranking is a computed column
        cursor.execute(f"""
            SELECT 
                CASE WHEN ccp.definition IS NOT NULL THEN 1 ELSE 0 END AS IS_COMPUTED
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN sys.computed_columns ccp 
                ON ccp.object_id = OBJECT_ID('[{SCHEMA}].[Results]')
                AND ccp.name = c.COLUMN_NAME
            WHERE c.TABLE_SCHEMA = '{SCHEMA}' 
            AND c.TABLE_NAME = 'Results' 
            AND c.COLUMN_NAME = 'Ranking'
        """)
        
        result = cursor.fetchone()
        ranking_is_computed = result[0] if result else 0
        
        # Convert MPHAvg
        if mpavg_is_computed:
            print("Converting MPHAvg from computed column to regular column...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                DROP COLUMN MPHAvg
            """)
            conn.commit()
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD MPHAvg DECIMAL(10,2) NULL
            """)
            conn.commit()
            print("MPHAvg converted to regular column")
        
        # Convert Ranking
        if ranking_is_computed:
            print("Converting Ranking from computed column to regular column...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                DROP COLUMN Ranking
            """)
            conn.commit()
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD Ranking INT NULL
            """)
            conn.commit()
            print("Ranking converted to regular column")
        
        # Create indexes on the new columns
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Results_MPHAvg' AND object_id = OBJECT_ID('[{SCHEMA}].[Results]'))
            BEGIN
                CREATE NONCLUSTERED INDEX IX_Results_MPHAvg 
                ON [{SCHEMA}].[Results] (MPHAvg DESC)
                WHERE MPHAvg IS NOT NULL
            END
        """)
        
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Results_Ranking' AND object_id = OBJECT_ID('[{SCHEMA}].[Results]'))
            BEGIN
                CREATE NONCLUSTERED INDEX IX_Results_Ranking 
                ON [{SCHEMA}].[Results] (Ranking)
                WHERE Ranking IS NOT NULL
            END
        """)
        
        conn.commit()
        print("Indexes created on MPHAvg and Ranking columns")
        return True
        
    except pyodbc.Error as e:
        print(f"Error converting columns: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def create_update_stored_procedure(conn):
    """Create a stored procedure to efficiently update MPHAvg and Ranking"""
    cursor = conn.cursor()
    
    try:
        # Drop if exists
        cursor.execute(f"""
            IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('[{SCHEMA}].[sp_UpdateMPHAvgAndRanking]') AND type = 'P')
            BEGIN
                DROP PROCEDURE [{SCHEMA}].[sp_UpdateMPHAvgAndRanking]
            END
        """)
        conn.commit()
        
        print("Creating stored procedure to update MPHAvg and Ranking...")
        cursor.execute(f"""
            CREATE PROCEDURE [{SCHEMA}].[sp_UpdateMPHAvgAndRanking]
            AS
            BEGIN
                SET NOCOUNT ON;
                
                -- Update MPHAvg: For each result, calculate average of top 3 speeds
                -- up to that event date for that dog in that year
                UPDATE r_current
                SET MPHAvg = ISNULL((
                    SELECT AVG(CAST(Speed AS DECIMAL(10,2)))
                    FROM (
                        SELECT TOP 3 r.Speed
                        FROM [{SCHEMA}].[Results] r
                        INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                        INNER JOIN [{SCHEMA}].[Events] e_current ON e_current.EventID = r_current.EventID
                        WHERE r.DogsID = r_current.DogsID
                            AND e.Year = e_current.Year
                            AND e.EventDate <= e_current.EventDate
                            AND r.Speed IS NOT NULL
                            AND r.Speed > 0
                        ORDER BY r.Speed DESC
                    ) AS TopSpeeds
                ), 0)
                FROM [{SCHEMA}].[Results] r_current;
                
                -- Update Ranking: Rank by MPHAvg within Breed and Year, up to event date
                WITH RankedResults AS (
                    SELECT 
                        r.ResultID,
                        DENSE_RANK() OVER (
                            PARTITION BY d.Breed, e.Year, e.EventDate
                            ORDER BY r.MPHAvg DESC
                        ) AS NewRanking
                    FROM [{SCHEMA}].[Results] r
                    INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
                    INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                    WHERE r.MPHAvg IS NOT NULL
                )
                UPDATE r
                SET Ranking = rr.NewRanking
                FROM [{SCHEMA}].[Results] r
                INNER JOIN RankedResults rr ON r.ResultID = rr.ResultID;
            END
        """)
        conn.commit()
        print("Successfully created stored procedure")
        return True
        
    except pyodbc.Error as e:
        print(f"Error creating stored procedure: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def create_triggers(conn):
    """Create triggers to maintain MPHAvg and Ranking on insert/update"""
    cursor = conn.cursor()
    
    try:
        # Drop existing triggers
        cursor.execute(f"""
            IF EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('[{SCHEMA}].[tr_Results_UpdateMPHAvgRanking]') AND type = 'TR')
            BEGIN
                DROP TRIGGER [{SCHEMA}].[tr_Results_UpdateMPHAvgRanking]
            END
        """)
        conn.commit()
        
        print("Creating trigger to maintain MPHAvg and Ranking...")
        cursor.execute(f"""
            CREATE TRIGGER [{SCHEMA}].[tr_Results_UpdateMPHAvgRanking]
            ON [{SCHEMA}].[Results]
            AFTER INSERT, UPDATE, DELETE
            AS
            BEGIN
                SET NOCOUNT ON;
                
                -- Only recalculate if Speed, Points, DogsID, or EventID changed
                IF UPDATE(Speed) OR UPDATE(Points) OR UPDATE(DogsID) OR UPDATE(EventID)
                OR EXISTS (SELECT 1 FROM inserted) OR EXISTS (SELECT 1 FROM deleted)
                BEGIN
                    -- Recalculate all MPHAvg and Ranking values
                    -- Note: For very large tables, you may want to make this more selective
                    EXEC [{SCHEMA}].[sp_UpdateMPHAvgAndRanking];
                END
            END
        """)
        conn.commit()
        print("Successfully created trigger")
        return True
        
    except pyodbc.Error as e:
        print(f"Error creating trigger: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def initial_populate(conn):
    """Initially populate MPHAvg and Ranking values"""
    cursor = conn.cursor()
    
    try:
        print("Populating initial MPHAvg and Ranking values...")
        cursor.execute(f"""
            EXEC [{SCHEMA}].[sp_UpdateMPHAvgAndRanking]
        """)
        conn.commit()
        
        # Get count of updated rows
        cursor.execute(f"""
            SELECT COUNT(*) FROM [{SCHEMA}].[Results] WHERE MPHAvg IS NOT NULL
        """)
        count = cursor.fetchone()[0]
        print(f"Successfully populated {count} rows")
        return True
        
    except pyodbc.Error as e:
        print(f"Error populating values: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("=" * 80)
    print("Optimize MPHAvg and Ranking Performance")
    print("=" * 80)
    print(f"\nThis will:")
    print(f"  1. Convert computed columns to regular columns")
    print(f"  2. Create indexes for performance")
    print(f"  3. Create stored procedure for efficient updates")
    print(f"  4. Create trigger to maintain values automatically")
    print(f"  5. Populate initial values")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Step 1: Create indexes first
        print("\n" + "-" * 80)
        print("Step 1: Creating indexes")
        print("-" * 80)
        if not create_indexes(conn):
            print("Failed to create indexes. Exiting.")
            return
        
        # Step 2: Convert computed columns to regular columns
        print("\n" + "-" * 80)
        print("Step 2: Converting computed columns to regular columns")
        print("-" * 80)
        if not convert_to_regular_columns(conn):
            print("Failed to convert columns. Exiting.")
            return
        
        # Step 3: Create stored procedure
        print("\n" + "-" * 80)
        print("Step 3: Creating stored procedure")
        print("-" * 80)
        if not create_update_stored_procedure(conn):
            print("Failed to create stored procedure. Exiting.")
            return
        
        # Step 4: Create trigger
        print("\n" + "-" * 80)
        print("Step 4: Creating trigger")
        print("-" * 80)
        if not create_triggers(conn):
            print("Failed to create trigger. Exiting.")
            return
        
        # Step 5: Initial populate
        print("\n" + "-" * 80)
        print("Step 5: Populating initial values")
        print("-" * 80)
        if not initial_populate(conn):
            print("Failed to populate initial values. Exiting.")
            return
        
        print("\n" + "=" * 80)
        print("Optimization completed successfully!")
        print("=" * 80)
        print(f"\nMPHAvg and Ranking are now regular columns that are:")
        print(f"  - Indexed for fast queries")
        print(f"  - Automatically maintained by triggers on insert/update/delete")
        print(f"  - Can be manually updated using: EXEC [{SCHEMA}].[sp_UpdateMPHAvgAndRanking]")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nError during operation: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        raise
    finally:
        conn.close()
        print("\nDatabase connection closed.")

if __name__ == "__main__":
    main()



