"""
Convert Time and Handicap columns to computed columns in FastCAT Results table.
- Time = 204.545 / Speed
- Handicap = ROUND(Points/Speed, 1)
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

def convert_time_column(conn):
    """Convert Time to a computed column: 204.545 / Speed"""
    cursor = conn.cursor()
    
    try:
        result = check_computed_column(cursor, 'Time')
        expected_formula = '204.545/NULLIF([Speed],(0))'
        
        if result:
            is_computed = result[3] if result[3] is not None else 0
            computed_def = result[4] if result[4] else ''
            
            # Normalize the definition for comparison (remove spaces, handle NULLIF variations)
            normalized_def = computed_def.replace(' ', '').replace('"', "'").upper()
            expected_normalized = expected_formula.replace(' ', '').upper()
            
            if is_computed and expected_normalized in normalized_def:
                print(f"Column Time already exists as a computed column with the correct formula")
                return True
            else:
                print(f"Dropping existing Time column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    DROP COLUMN Time
                """)
                conn.commit()
                print(f"Adding Time as computed column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    ADD Time AS CAST(204.545 / NULLIF([Speed], 0) AS DECIMAL(10,3))
                """)
                conn.commit()
                print(f"Successfully converted Time to computed column")
                return True
        else:
            print(f"Adding Time as computed column to {SCHEMA}.Results table...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD Time AS CAST(204.545 / NULLIF([Speed], 0) AS DECIMAL(10,3))
            """)
            conn.commit()
            print(f"Successfully added Time as computed column to {SCHEMA}.Results table")
            return True
        
    except pyodbc.Error as e:
        print(f"Error converting Time column: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def convert_handicap_column(conn):
    """Convert Handicap to a computed column: ROUND(Points/Speed, 1)"""
    cursor = conn.cursor()
    
    try:
        result = check_computed_column(cursor, 'Handicap')
        expected_formula = 'ROUND([Points]/NULLIF([Speed],(0)),(1))'
        
        if result:
            is_computed = result[3] if result[3] is not None else 0
            computed_def = result[4] if result[4] else ''
            
            # Normalize the definition for comparison
            normalized_def = computed_def.replace(' ', '').replace('"', "'").upper()
            expected_normalized = expected_formula.replace(' ', '').upper()
            
            if is_computed and 'ROUND' in normalized_def and 'POINTS' in normalized_def and 'SPEED' in normalized_def:
                print(f"Column Handicap already exists as a computed column with the correct formula")
                return True
            else:
                print(f"Dropping existing Handicap column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    DROP COLUMN Handicap
                """)
                conn.commit()
                print(f"Adding Handicap as computed column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Results]
                    ADD Handicap AS CAST(ROUND([Points] / NULLIF([Speed], 0), 1) AS DECIMAL(10,2))
                """)
                conn.commit()
                print(f"Successfully converted Handicap to computed column")
                return True
        else:
            print(f"Adding Handicap as computed column to {SCHEMA}.Results table...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Results]
                ADD Handicap AS CAST(ROUND([Points] / NULLIF([Speed], 0), 1) AS DECIMAL(10,2))
            """)
            conn.commit()
            print(f"Successfully added Handicap as computed column to {SCHEMA}.Results table")
            return True
        
    except pyodbc.Error as e:
        print(f"Error converting Handicap column: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("=" * 80)
    print("Convert Time and Handicap to Computed Columns in FastCAT Results Table")
    print("=" * 80)
    print(f"\nComputed column formulas:")
    print(f"  Time = 204.545 / Speed")
    print(f"  Handicap = ROUND(Points / Speed, 1)")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Convert Time column
        print("\n" + "-" * 80)
        print("Converting Time to computed column")
        print("-" * 80)
        if not convert_time_column(conn):
            print("Failed to convert Time column. Exiting.")
            return
        
        # Convert Handicap column
        print("\n" + "-" * 80)
        print("Converting Handicap to computed column")
        print("-" * 80)
        if not convert_handicap_column(conn):
            print("Failed to convert Handicap column. Exiting.")
            return
        
        print("\n" + "=" * 80)
        print("Operation completed successfully!")
        print("=" * 80)
        print(f"\nComputed columns are now active:")
        print(f"  Time = 204.545 / Speed (returns NULL if Speed is 0)")
        print(f"  Handicap = ROUND(Points / Speed, 1) (returns NULL if Speed is 0)")
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



