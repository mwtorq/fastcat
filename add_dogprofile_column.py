"""
Convert DogProfile column to a computed column in FastCAT Dogs table.
The computed column concatenates the AKC URL base with the AKCDogID value.
"""

import pyodbc
import sys

# Configuration
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'
URL_BASE = 'https://www.apps.akc.org/apps/store/proxy/get_points.cfm?cde_comp_group=CONF&cde_product_type=COMP_REC&regnum='

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

def convert_to_computed_column(conn):
    """Convert DogProfile to a computed column based on AKCDogID"""
    cursor = conn.cursor()
    
    try:
        # Check if column already exists and if it's a computed column
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
                ON ccp.object_id = OBJECT_ID('[{SCHEMA}].[Dogs]')
                AND ccp.name = c.COLUMN_NAME
            WHERE c.TABLE_SCHEMA = '{SCHEMA}' 
            AND c.TABLE_NAME = 'Dogs' 
            AND c.COLUMN_NAME = 'DogProfile'
        """)
        
        result = cursor.fetchone()
        
        if result:
            is_computed = result[3] if result[3] is not None else 0
            computed_def = result[4] if result[4] else ''
            expected_def = f"'{URL_BASE}'+ISNULL([AKCDogID],'')"
            
            # Check if it's already the correct computed column
            if is_computed and expected_def in computed_def.replace(' ', '').replace('"', "'"):
                print(f"Column DogProfile already exists as a computed column with the correct formula")
                return True
            else:
                # Need to drop and recreate as computed column
                print(f"Dropping existing DogProfile column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Dogs]
                    DROP COLUMN DogProfile
                """)
                conn.commit()
                print(f"Adding DogProfile as computed column...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Dogs]
                    ADD DogProfile AS '{URL_BASE}' + ISNULL([AKCDogID], '')
                """)
                conn.commit()
                print(f"Successfully converted DogProfile to computed column")
                return True
        else:
            # Column doesn't exist - add it as computed column
            print(f"Adding DogProfile as computed column to {SCHEMA}.Dogs table...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Dogs]
                ADD DogProfile AS '{URL_BASE}' + ISNULL([AKCDogID], '')
            """)
            conn.commit()
            print(f"Successfully added DogProfile as computed column to {SCHEMA}.Dogs table")
            return True
        
    except pyodbc.Error as e:
        print(f"Error converting column: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("=" * 80)
    print("Convert DogProfile to Computed Column in FastCAT Dogs Table")
    print("=" * 80)
    print(f"\nComputed column formula:")
    print(f"  '{URL_BASE}' + ISNULL(AKCDogID, '')")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Convert DogProfile to computed column
        print("\n" + "-" * 80)
        print("Converting DogProfile to computed column")
        print("-" * 80)
        if not convert_to_computed_column(conn):
            print("Failed to convert column. Exiting.")
            return
        
        print("\n" + "=" * 80)
        print("Operation completed successfully!")
        print("=" * 80)
        print(f"\nDogProfile is now a computed column that automatically generates:")
        print(f"  {URL_BASE}<AKCDogID>")
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




