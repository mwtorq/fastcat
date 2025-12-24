"""
Add DogID column to FastCAT Dogs table and update all records with DogID values
from the Excel result files: 2021-2022, 2023-2024, and 2025 FastCAT Results.xlsx
"""

import pyodbc
import pandas as pd
import sys
import os
from pathlib import Path

# Configuration
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'

# Excel files to process
EXCEL_FILES = [
    r'Results\2021-2022 FastCAT Results.xlsx',
    r'Results\2023-2024 FastCAT Results.xlsx',
    r'Results\2025 FastCAT Results.xlsx'
]

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

def rename_dogid_to_dogsid(conn):
    """Rename DogID identity column to DogsID and update foreign key references"""
    cursor = conn.cursor()
    
    try:
        # Check if DogsID column already exists
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = '{SCHEMA}' 
            AND TABLE_NAME = 'Dogs' 
            AND COLUMN_NAME = 'DogsID'
        """)
        
        dogsid_exists = cursor.fetchone()[0] > 0
        
        if dogsid_exists:
            print(f"Column DogsID already exists in {SCHEMA}.Dogs table")
            return True
        
        # Check if DogID column exists (the identity column)
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = '{SCHEMA}' 
            AND TABLE_NAME = 'Dogs' 
            AND COLUMN_NAME = 'DogID'
        """)
        
        dogid_exists = cursor.fetchone()[0] > 0
        
        if not dogid_exists:
            print(f"Column DogID does not exist in {SCHEMA}.Dogs table - nothing to rename")
            return True
        
        print(f"\nRenaming DogID to DogsID in {SCHEMA}.Dogs table...")
        print("  This requires dropping and recreating foreign key constraints...")
        
        # Step 1: Drop foreign key constraint in Results table
        print("  Step 1: Dropping foreign key constraint in Results table...")
        cursor.execute(f"""
            -- Find and drop the foreign key constraint
            DECLARE @fk_name NVARCHAR(200)
            SELECT @fk_name = name 
            FROM sys.foreign_keys 
            WHERE parent_object_id = OBJECT_ID('[{SCHEMA}].[Results]')
            AND referenced_object_id = OBJECT_ID('[{SCHEMA}].[Dogs]')
            
            IF @fk_name IS NOT NULL
            BEGIN
                EXEC('ALTER TABLE [{SCHEMA}].[Results] DROP CONSTRAINT [' + @fk_name + ']')
            END
        """)
        
        # Step 2: Rename the column using sp_rename
        print("  Step 2: Renaming DogID column to DogsID...")
        cursor.execute(f"""
            EXEC sp_rename 
                '[{SCHEMA}].[Dogs].DogID', 
                'DogsID', 
                'COLUMN'
        """)
        
        # Step 3: Rename the column in Results table
        print("  Step 3: Renaming DogID column to DogsID in Results table...")
        cursor.execute(f"""
            EXEC sp_rename 
                '[{SCHEMA}].[Results].DogID', 
                'DogsID', 
                'COLUMN'
        """)
        
        # Step 4: Recreate foreign key constraint
        print("  Step 4: Recreating foreign key constraint...")
        cursor.execute(f"""
            ALTER TABLE [{SCHEMA}].[Results]
            ADD CONSTRAINT FK_Results_Dogs 
            FOREIGN KEY (DogsID) 
            REFERENCES [{SCHEMA}].[Dogs](DogsID)
        """)
        
        conn.commit()
        print(f"Successfully renamed DogID to DogsID in {SCHEMA}.Dogs and {SCHEMA}.Results tables")
        return True
        
    except pyodbc.Error as e:
        print(f"Error renaming column: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False

def add_dogid_column(conn):
    """Add AKCDogID column to Dogs table if it doesn't exist, or alter it to NVARCHAR if it's the wrong type"""
    cursor = conn.cursor()
    
    try:
        # Check if column already exists and get its data type
        cursor.execute(f"""
            SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = '{SCHEMA}' 
            AND TABLE_NAME = 'Dogs' 
            AND COLUMN_NAME = 'AKCDogID'
        """)
        
        result = cursor.fetchone()
        
        if result:
            data_type = result[0]
            max_length = result[1]
            
            # Check if it's the correct type (NVARCHAR with length 50)
            if data_type.upper() == 'NVARCHAR' and max_length == 50:
                print(f"Column AKCDogID already exists in {SCHEMA}.Dogs table with correct type (NVARCHAR(50))")
                return True
            else:
                # Column exists but has wrong type - alter it
                print(f"Column AKCDogID exists but has type {data_type}({max_length}). Altering to NVARCHAR(50)...")
                cursor.execute(f"""
                    ALTER TABLE [{SCHEMA}].[Dogs]
                    ALTER COLUMN AKCDogID NVARCHAR(50) NULL
                """)
                conn.commit()
                print(f"Successfully altered AKCDogID column to NVARCHAR(50)")
                return True
        else:
            # Column doesn't exist - add it
            print(f"Adding AKCDogID column to {SCHEMA}.Dogs table...")
            cursor.execute(f"""
                ALTER TABLE [{SCHEMA}].[Dogs]
                ADD AKCDogID NVARCHAR(50) NULL
            """)
            conn.commit()
            print(f"Successfully added AKCDogID column to {SCHEMA}.Dogs table")
            return True
        
    except pyodbc.Error as e:
        print(f"Error adding/altering column: {e}")
        conn.rollback()
        return False

def read_excel_dogids(excel_file):
    """Read DogID, DogName, and Owner from Excel file"""
    print(f"\nReading DogID data from: {excel_file}")
    
    if not os.path.exists(excel_file):
        print(f"  Warning: File not found: {excel_file}")
        return pd.DataFrame()
    
    try:
        # Read Excel file
        df = pd.read_excel(excel_file, engine='openpyxl')
        
        # Normalize column names (handle variations)
        column_mapping = {
            'DogID': 'DogID',
            'Dog ID': 'DogID',  # Handle space in column name
            'DogID': 'DogID',
            'DogName': 'DogName',
            'Dog Name': 'DogName',
            'Owner': 'Owner',
            'Owner Name': 'Owner'
        }
        
        # Find matching columns (case-insensitive)
        df.columns = df.columns.str.strip()
        for old_name, new_name in column_mapping.items():
            matching_cols = [col for col in df.columns if col.lower() == old_name.lower()]
            if matching_cols:
                df.rename(columns={matching_cols[0]: new_name}, inplace=True)
        
        # Check if required columns exist
        required_cols = ['DogID', 'DogName', 'Owner']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            print(f"  Warning: Missing columns in {excel_file}: {missing_cols}")
            print(f"  Available columns: {df.columns.tolist()}")
            return pd.DataFrame()
        
        # Select only the columns we need
        df = df[['DogID', 'DogName', 'Owner']].copy()
        
        # Remove rows with missing DogID
        df = df[df['DogID'].notna()].copy()
        
        # Convert DogID to string (AKC Dog IDs are alphanumeric like 'TS26029402', 'DN32656106')
        df['DogID'] = df['DogID'].astype(str).str.strip()
        
        # Remove rows where DogID is empty or 'nan'
        df = df[(df['DogID'] != '') & (df['DogID'] != 'nan')].copy()
        
        # Clean up DogName and Owner (strip whitespace, handle NaN)
        df['DogName'] = df['DogName'].astype(str).str.strip()
        df['Owner'] = df['Owner'].astype(str).str.strip()
        
        # Remove rows where DogName or Owner is empty or 'nan'
        df = df[(df['DogName'] != '') & (df['DogName'] != 'nan') & 
                (df['Owner'] != '') & (df['Owner'] != 'nan')].copy()
        
        # Remove duplicates, keeping the first occurrence (or you could keep the most common DogID)
        # Group by DogName and Owner, and take the first DogID (or mode if there are multiple)
        df_unique = df.groupby(['DogName', 'Owner'])['DogID'].first().reset_index()
        
        print(f"  Found {len(df_unique)} unique dog records with DogID")
        
        return df_unique
        
    except Exception as e:
        print(f"  Error reading {excel_file}: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()

def update_dogids(conn, dogid_df):
    """Update Dogs table with DogID values from DataFrame"""
    if dogid_df.empty:
        print("  No data to update")
        return 0
    
    cursor = conn.cursor()
    updated_count = 0
    not_found_count = 0
    error_count = 0
    total_records = len(dogid_df)
    
    try:
        print(f"\nUpdating Dogs table with DogID values...")
        print(f"  Total records to process: {total_records}")
        
        # Process in batches with periodic commits to avoid long transactions
        batch_size = 100
        batch_count = 0
        
        for idx, row in dogid_df.iterrows():
            dog_id = str(row['DogID']).strip()  # Keep as string for alphanumeric AKC IDs
            dog_name = str(row['DogName']).strip()
            owner = str(row['Owner']).strip()
            
            # Progress indicator every 100 records
            if (idx + 1) % 100 == 0:
                print(f"  Progress: {idx + 1}/{total_records} records processed (Updated: {updated_count}, Errors: {error_count}, Not found: {not_found_count})")
            
            try:
                # Update the Dogs table where DogName and Owner match
                cursor.execute(f"""
                    UPDATE [{SCHEMA}].[Dogs]
                    SET AKCDogID = ?
                    WHERE DogName = ? AND Owner = ?
                """, dog_id, dog_name, owner)
                
                rows_affected = cursor.rowcount
                
                if rows_affected > 0:
                    updated_count += rows_affected
                    batch_count += 1
                else:
                    not_found_count += 1
                    if not_found_count <= 10:  # Only print first 10 not found
                        print(f"    Not found: {dog_name} / {owner}")
                
                # Commit in batches to avoid long transactions
                if batch_count >= batch_size:
                    conn.commit()
                    batch_count = 0
                
            except pyodbc.Error as e:
                error_count += 1
                # Extract error message more safely
                error_msg = str(e)
                if hasattr(e, 'args') and len(e.args) > 1:
                    error_msg = str(e.args[1]) if len(e.args) > 1 else str(e)
                
                if error_count <= 10:  # Only print first 10 errors
                    print(f"    Error updating {dog_name} / {owner}: {error_msg}")
                elif error_count == 11:
                    print(f"    ... (suppressing further error messages)")
                
                # Rollback the failed statement but continue processing
                try:
                    conn.rollback()
                except:
                    pass  # Ignore rollback errors
                continue
        
        # Final commit for any remaining changes
        if batch_count > 0:
            conn.commit()
        
        print(f"\nUpdate summary:")
        print(f"  Updated: {updated_count} records")
        print(f"  Not found in database: {not_found_count} records")
        if error_count > 0:
            print(f"  Errors: {error_count} records")
        
        return updated_count
        
    except KeyboardInterrupt:
        print(f"\n\nUpdate interrupted by user.")
        print(f"  Progress: Updated {updated_count}, Errors: {error_count}, Not found: {not_found_count}")
        conn.rollback()
        return updated_count
    except Exception as e:
        print(f"\nError during update: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return updated_count

def main():
    """Main function"""
    print("=" * 80)
    print("Add DogID Column and Update FastCAT Dogs Table")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Step 1: Rename DogID identity column to DogsID
        print("\n" + "-" * 80)
        print("Step 1: Renaming DogID identity column to DogsID")
        print("-" * 80)
        if not rename_dogid_to_dogsid(conn):
            print("Failed to rename column. Exiting.")
            return
        
        # Step 2: Add AKCDogID column for Excel values
        print("\n" + "-" * 80)
        print("Step 2: Adding AKCDogID column to Dogs table")
        print("-" * 80)
        if not add_dogid_column(conn):
            print("Failed to add column. Exiting.")
            return
        
        # Step 3: Read DogID data from Excel files
        print("\n" + "-" * 80)
        print("Step 3: Reading DogID data from Excel files")
        print("-" * 80)
        
        all_dogids = pd.DataFrame()
        
        for excel_file in EXCEL_FILES:
            df = read_excel_dogids(excel_file)
            if not df.empty:
                all_dogids = pd.concat([all_dogids, df], ignore_index=True)
        
        if all_dogids.empty:
            print("\nNo DogID data found in any Excel files. Exiting.")
            return
        
        # Combine data from all files
        # If same dog (DogName + Owner) appears in multiple files with different DogIDs,
        # we'll use the most recent one (prioritize 2025 > 2023-2024 > 2021-2022)
        print(f"\nCombining data from all files...")
        print(f"  Total records before deduplication: {len(all_dogids)}")
        
        # Remove duplicates, keeping last occurrence (which would be from later files if processed in order)
        all_dogids = all_dogids.drop_duplicates(subset=['DogName', 'Owner'], keep='last')
        
        print(f"  Unique dog records after deduplication: {len(all_dogids)}")
        
        # Step 4: Update Dogs table
        print("\n" + "-" * 80)
        print("Step 4: Updating Dogs table with AKCDogID values")
        print("-" * 80)
        
        updated = update_dogids(conn, all_dogids)
        
        # Step 4: Summary
        print("\n" + "=" * 80)
        print("Summary")
        print("=" * 80)
        print(f"Total records processed: {len(all_dogids)}")
        print(f"Records updated: {updated}")
        print(f"Records not found in database: {len(all_dogids) - updated}")
        
        # Show some statistics
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT 
                COUNT(*) as TotalDogs,
                COUNT(AKCDogID) as DogsWithAKCDogID,
                COUNT(*) - COUNT(AKCDogID) as DogsWithoutAKCDogID
            FROM [{SCHEMA}].[Dogs]
        """)
        stats = cursor.fetchone()
        print(f"\nDatabase statistics:")
        print(f"  Total dogs in database: {stats[0]}")
        print(f"  Dogs with AKCDogID: {stats[1]}")
        print(f"  Dogs without AKCDogID: {stats[2]}")
        
        print("\n" + "=" * 80)
        print("Operation completed successfully!")
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

