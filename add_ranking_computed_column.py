"""
Add Ranking computed column to FastCAT Results table.
Ranking = rank (descending) on MPHAvg, grouped by Breed and Year,
          up to and including the current EventDate.
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

def create_ranking_function(conn):
    """Create a scalar function to calculate Ranking"""
    cursor = conn.cursor()
    
    try:
        # Check if function already exists
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM sys.objects 
            WHERE object_id = OBJECT_ID('[{SCHEMA}].[fn_CalculateRanking]')
            AND type = 'FN'
        """)
        
        function_exists = cursor.fetchone()[0] > 0
        
        if function_exists:
            print(f"Function [{SCHEMA}].[fn_CalculateRanking] already exists. Dropping it...")
            cursor.execute(f"""
                DROP FUNCTION [{SCHEMA}].[fn_CalculateRanking]
            """)
            conn.commit()
        
        print(f"Creating function [{SCHEMA}].[fn_CalculateRanking]...")
        cursor.execute(f"""
            CREATE FUNCTION [{SCHEMA}].[fn_CalculateRanking](
                @ResultID INT,
                @DogsID INT,
                @EventID INT
            )
            RETURNS INT
            AS
            BEGIN
                DECLARE @Result INT
                DECLARE @Breed NVARCHAR(100)
                DECLARE @Year INT
                DECLARE @EventDate DATE
                DECLARE @MPHAvg DECIMAL(10,2)
                
                -- Get the breed, year, event date, and MPHAvg for this result
                SELECT 
                    @Breed = d.Breed,
                    @Year = e.Year,
                    @EventDate = e.EventDate,
                    @MPHAvg = [{SCHEMA}].[fn_CalculateMPHAvg](r.DogsID, r.EventID)
                FROM [{SCHEMA}].[Results] r
                INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                WHERE r.ResultID = @ResultID
                
                -- If breed, year, event date, or MPHAvg is NULL, return NULL
                IF @Breed IS NULL OR @Year IS NULL OR @EventDate IS NULL OR @MPHAvg IS NULL
                    RETURN NULL
                
                -- Calculate ranking: count how many dogs have higher or equal MPHAvg
                -- Use DENSE_RANK logic: count distinct MPHAvg values that are >= current
                SELECT @Result = COUNT(DISTINCT [{SCHEMA}].[fn_CalculateMPHAvg](r.DogsID, r.EventID)) + 1
                FROM [{SCHEMA}].[Results] r
                INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                WHERE d.Breed = @Breed
                    AND e.Year = @Year
                    AND e.EventDate <= @EventDate
                    AND [{SCHEMA}].[fn_CalculateMPHAvg](r.DogsID, r.EventID) > @MPHAvg
                
                RETURN @Result
            END
        """)
        conn.commit()
        print(f"Successfully created function [{SCHEMA}].[fn_CalculateRanking]")
        return True
        
    except pyodbc.Error as e:
        print(f"Error creating function: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def check_computed_column(cursor, column_name):
    """Check if a column exists and if it's a computed column"""
    cursor.execute(f"""
        SELECT 
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.IS_NULLABLE,
            CASE 
                WHEN ccp.definition IS NOT NULL THEN 1 
                ELSE 0 
            END AS IS_COMPUTED,
            ccp.definition AS COMPUTED_DEFINITION
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN sys.computed_columns ccp 
            ON ccp.object_id = OBJECT_ID('[{SCHEMA}].[Results]')
            AND ccp.name = c.COLUMN_NAME
        WHERE c.TABLE_SCHEMA = '{SCHEMA}' 
        AND c.TABLE_NAME = 'Results' 
        AND c.COLUMN_NAME = '{column_name}'
    """)
    return cursor.fetchone()

def add_ranking_column(conn):
    """Add Ranking as a computed column"""
    cursor = conn.cursor()
    
    try:
        result = check_computed_column(cursor, 'Ranking')
        
        if result:
            is_computed = result[3] if result[3] is not None else 0
            computed_def = result[4] if result[4] else ''
            
            # Check if it's already the correct computed column
            if is_computed and 'fn_CalculateRanking' in computed_def:
                print(f"Column Ranking already exists as a computed column with the correct formula")
                return True
            else:
                print(f"Dropping existing Ranking column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    DROP COLUMN Ranking
                """)
                conn.commit()
                print(f"Adding Ranking as computed column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    ADD Ranking AS CAST([{SCHEMA}].[fn_CalculateRanking]([ResultID], [DogsID], [EventID]) AS INT)
                """)
                conn.commit()
                print(f"Successfully converted Ranking to computed column")
                return True
        else:
            print(f"Adding Ranking as computed column to {SCHEMA}.Results table...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD Ranking AS CAST([{SCHEMA}].[fn_CalculateRanking]([ResultID], [DogsID], [EventID]) AS INT)
            """)
            conn.commit()
            print(f"Successfully added Ranking as computed column to {SCHEMA}.Results table")
            return True
        
    except pyodbc.Error as e:
        print(f"Error adding Ranking column: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("=" * 80)
    print("Add Ranking Computed Column to FastCAT Results Table")
    print("=" * 80)
    print(f"\nRanking formula:")
    print(f"  Rank (descending) on MPHAvg")
    print(f"  Grouped by Breed and Year")
    print(f"  Up to and including the current EventDate")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Create the scalar function first
        print("\n" + "-" * 80)
        print("Creating scalar function for Ranking calculation")
        print("-" * 80)
        if not create_ranking_function(conn):
            print("Failed to create function. Exiting.")
            return
        
        # Add Ranking computed column
        print("\n" + "-" * 80)
        print("Adding Ranking computed column")
        print("-" * 80)
        if not add_ranking_column(conn):
            print("Failed to add Ranking column. Exiting.")
            return
        
        print("\n" + "=" * 80)
        print("Operation completed successfully!")
        print("=" * 80)
        print(f"\nRanking computed column is now active:")
        print(f"  Ranks dogs by MPHAvg (descending) within each Breed and Year")
        print(f"  Only considers events up to the current event date")
        print(f"  Uses DENSE_RANK to handle ties (same MPHAvg = same rank)")
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




