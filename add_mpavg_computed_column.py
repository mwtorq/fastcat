"""
Add MPHAvg computed column to FastCAT Results table.
MPHAvg = average of top 3 Speed values for the same AKCDogID in the same Year,
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

def create_mpavg_function(conn):
    """Create a scalar function to calculate MPHAvg"""
    cursor = conn.cursor()
    
    try:
        # Check if function already exists
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM sys.objects 
            WHERE object_id = OBJECT_ID('[{SCHEMA}].[fn_CalculateMPHAvg]')
            AND type = 'FN'
        """)
        
        function_exists = cursor.fetchone()[0] > 0
        
        if function_exists:
            print(f"Function [{SCHEMA}].[fn_CalculateMPHAvg] already exists. Dropping it...")
            cursor.execute(f"""
                DROP FUNCTION [{SCHEMA}].[fn_CalculateMPHAvg]
            """)
            conn.commit()
        
        print(f"Creating function [{SCHEMA}].[fn_CalculateMPHAvg]...")
        cursor.execute(f"""
            CREATE FUNCTION [{SCHEMA}].[fn_CalculateMPHAvg](
                @DogsID INT,
                @EventID INT
            )
            RETURNS DECIMAL(10,2)
            AS
            BEGIN
                DECLARE @Result DECIMAL(10,2)
                
                SELECT @Result = AVG(Speed)
                FROM (
                    SELECT TOP 3 
                        r.Speed
                    FROM [{SCHEMA}].[Results] r
                    INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
                    INNER JOIN [{SCHEMA}].[Events] e_current ON r.EventID = e_current.EventID
                    INNER JOIN [{SCHEMA}].[Events] e_target ON e_target.EventID = @EventID
                    WHERE r.DogsID = @DogsID
                        AND e_current.Year = e_target.Year
                        AND e_current.EventDate <= e_target.EventDate
                        AND r.Speed IS NOT NULL
                        AND r.Speed > 0
                    ORDER BY r.Speed DESC
                ) AS TopSpeeds
                
                RETURN ISNULL(@Result, 0)
            END
        """)
        conn.commit()
        print(f"Successfully created function [{SCHEMA}].[fn_CalculateMPHAvg]")
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

def add_mpavg_column(conn):
    """Add MPHAvg as a computed column"""
    cursor = conn.cursor()
    
    try:
        result = check_computed_column(cursor, 'MPHAvg')
        
        if result:
            is_computed = result[3] if result[3] is not None else 0
            computed_def = result[4] if result[4] else ''
            
            # Check if it's already the correct computed column
            if is_computed and 'fn_CalculateMPHAvg' in computed_def:
                print(f"Column MPHAvg already exists as a computed column with the correct formula")
                return True
            else:
                print(f"Dropping existing MPHAvg column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    DROP COLUMN MPHAvg
                """)
                conn.commit()
                print(f"Adding MPHAvg as computed column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    ADD MPHAvg AS CAST([{SCHEMA}].[fn_CalculateMPHAvg]([DogsID], [EventID]) AS DECIMAL(10,2))
                """)
                conn.commit()
                print(f"Successfully converted MPHAvg to computed column")
                return True
        else:
            print(f"Adding MPHAvg as computed column to {SCHEMA}.Results table...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD MPHAvg AS CAST([{SCHEMA}].[fn_CalculateMPHAvg]([DogsID], [EventID]) AS DECIMAL(10,2))
            """)
            conn.commit()
            print(f"Successfully added MPHAvg as computed column to {SCHEMA}.Results table")
            return True
        
    except pyodbc.Error as e:
        print(f"Error adding MPHAvg column: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("=" * 80)
    print("Add MPHAvg Computed Column to FastCAT Results Table")
    print("=" * 80)
    print(f"\nMPHAvg formula:")
    print(f"  Average of top 3 Speed values for the same AKCDogID")
    print(f"  in the same Year, up to and including the current EventDate")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Create the scalar function first
        print("\n" + "-" * 80)
        print("Creating scalar function for MPHAvg calculation")
        print("-" * 80)
        if not create_mpavg_function(conn):
            print("Failed to create function. Exiting.")
            return
        
        # Add MPHAvg computed column
        print("\n" + "-" * 80)
        print("Adding MPHAvg computed column")
        print("-" * 80)
        if not add_mpavg_column(conn):
            print("Failed to add MPHAvg column. Exiting.")
            return
        
        print("\n" + "=" * 80)
        print("Operation completed successfully!")
        print("=" * 80)
        print(f"\nMPHAvg computed column is now active:")
        print(f"  Calculates average of top 3 Speed values for the same dog")
        print(f"  in the same year, up to the current event date")
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




