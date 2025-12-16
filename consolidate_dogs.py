"""
Consolidate dog records to ensure uniqueness across all events.
This script analyzes and merges duplicate dog records based on the combination
of DogName, Breed, and Owner, updating all Results records to use a single DogID
per unique (DogName, Breed, Owner) combination.
"""

import pyodbc
import sys
import argparse
from collections import defaultdict

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

def analyze_dog_duplicates(conn):
    """Analyze dogs to find potential duplicates (same name, breed, and owner)"""
    cursor = conn.cursor()
    
    print("Analyzing dog records for duplicates...")
    
    # Find dogs with the same name, breed, and owner (true duplicates)
    cursor.execute(f"""
        SELECT 
            DogName,
            Breed,
            Owner,
            COUNT(*) as RecordCount,
            STRING_AGG(CAST(DogID AS NVARCHAR), ', ') WITHIN GROUP (ORDER BY DogID) as DogIDs
        FROM [{SCHEMA}].[Dogs]
        GROUP BY DogName, Breed, Owner
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, DogName, Breed, Owner
    """)
    
    duplicates = cursor.fetchall()
    
    if duplicates:
        print(f"\nFound {len(duplicates)} duplicate dog records (same name, breed, and owner):")
        print("-" * 120)
        print(f"{'Dog Name':<35} {'Breed':<25} {'Owner':<30} {'Records':<8} {'DogIDs'}")
        print("-" * 120)
        
        for row in duplicates:
            dog_name, breed, owner, record_count, dog_ids = row
            print(f"{str(dog_name)[:34]:<35} {str(breed)[:24]:<25} {str(owner)[:29]:<30} {record_count:<8} {dog_ids}")
        
        return duplicates
    else:
        print("\nNo duplicate dog records found (same name, breed, and owner).")
        return []

def get_dog_statistics(conn):
    """Get statistics about dog records"""
    cursor = conn.cursor()
    
    cursor.execute(f"""
        SELECT 
            COUNT(*) as TotalDogs,
            COUNT(DISTINCT DogName) as UniqueDogNames,
            COUNT(DISTINCT Breed) as UniqueBreeds,
            COUNT(DISTINCT Owner) as UniqueOwners,
            COUNT(DISTINCT CONCAT(DogName, '|', ISNULL(Breed, ''), '|', ISNULL(Owner, ''))) as UniqueCombinations,
            COUNT(*) - COUNT(DISTINCT CONCAT(DogName, '|', ISNULL(Breed, ''), '|', ISNULL(Owner, ''))) as PotentialDuplicates
        FROM [{SCHEMA}].[Dogs]
    """)
    
    stats = cursor.fetchone()
    return stats

def consolidate_dogs_by_name(conn, dry_run=True):
    """Consolidate dogs: keep one DogID per unique (DogName, Breed, Owner) combination, update all Results"""
    cursor = conn.cursor()
    
    print("\n" + "=" * 100)
    if dry_run:
        print("DRY RUN MODE - No changes will be made")
    else:
        print("CONSOLIDATION MODE - Changes will be committed")
    print("=" * 100)
    
    # Get all dogs grouped by name, breed, and owner
    cursor.execute(f"""
        SELECT 
            DogName,
            Breed,
            Owner,
            MIN(DogID) as KeepDogID,
            COUNT(*) as RecordCount,
            STRING_AGG(CAST(DogID AS NVARCHAR), ', ') WITHIN GROUP (ORDER BY DogID) as AllDogIDs
        FROM [{SCHEMA}].[Dogs]
        GROUP BY DogName, Breed, Owner
        HAVING COUNT(*) > 1
        ORDER BY DogName, Breed, Owner
    """)
    
    duplicates = cursor.fetchall()
    
    if not duplicates:
        print("\nNo duplicate dog records found (same name, breed, and owner).")
        return
    
    print(f"\nFound {len(duplicates)} duplicate dog records (same name, breed, and owner)")
    print("Will consolidate to use the minimum DogID for each (DogName, Breed, Owner) combination.\n")
    
    total_results_updated = 0
    total_dogs_removed = 0
    
    for dog_name, breed, owner, keep_dog_id, record_count, all_dog_ids in duplicates:
        # Get all DogIDs for this dog name, breed, and owner combination
        cursor.execute(f"""
            SELECT DogID
            FROM [{SCHEMA}].[Dogs]
            WHERE DogName = ? AND Breed = ? AND Owner = ?
            ORDER BY DogID
        """, dog_name, breed, owner)
        
        dog_records = cursor.fetchall()
        dog_ids_to_remove = [row[0] for row in dog_records if row[0] != keep_dog_id]
        
        if not dog_ids_to_remove:
            continue
        
        # Count results that need updating
        placeholders = ','.join('?' * len(dog_ids_to_remove))
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM [{SCHEMA}].[Results]
            WHERE DogID IN ({placeholders})
        """, *dog_ids_to_remove)
        
        results_count = cursor.fetchone()[0]
        
        print(f"Dog: {dog_name} | Breed: {breed} | Owner: {owner}")
        print(f"  Keeping DogID: {keep_dog_id}")
        print(f"  Removing DogIDs: {', '.join(map(str, dog_ids_to_remove))}")
        print(f"  Results to update: {results_count}")
        print(f"  Dog records to remove: {len(dog_ids_to_remove)}")
        
        if not dry_run:
            # Update Results table to use the kept DogID
            if results_count > 0:
                placeholders = ','.join('?' * len(dog_ids_to_remove))
                cursor.execute(f"""
                    UPDATE [{SCHEMA}].[Results]
                    SET DogID = ?
                    WHERE DogID IN ({placeholders})
                    AND NOT EXISTS (
                        SELECT 1 FROM [{SCHEMA}].[Results] r2
                        WHERE r2.EventID = [{SCHEMA}].[Results].EventID
                        AND r2.DogID = ?
                    )
                """, keep_dog_id, *dog_ids_to_remove, keep_dog_id)
                
                updated = cursor.rowcount
                print(f"  Updated {updated} result records")
                total_results_updated += updated
                
                # Delete any remaining duplicate results (same EventID, different DogID for same dog)
                cursor.execute(f"""
                    DELETE FROM [{SCHEMA}].[Results]
                    WHERE DogID IN ({placeholders})
                """, *dog_ids_to_remove)
                
                deleted = cursor.rowcount
                if deleted > 0:
                    print(f"  Deleted {deleted} duplicate result records")
            
            # Remove duplicate dog records
            placeholders = ','.join('?' * len(dog_ids_to_remove))
            cursor.execute(f"""
                DELETE FROM [{SCHEMA}].[Dogs]
                WHERE DogID IN ({placeholders})
            """, *dog_ids_to_remove)
            
            removed = cursor.rowcount
            print(f"  Removed {removed} duplicate dog records")
            total_dogs_removed += removed
        
        print()
    
    if not dry_run:
        conn.commit()
        print(f"\nConsolidation complete!")
        print(f"  Total results updated: {total_results_updated:,}")
        print(f"  Total dogs removed: {total_dogs_removed:,}")
    else:
        print("\nDRY RUN complete - no changes were made")
        print("Run with --execute to apply changes")

def show_dog_details(conn, dog_name=None):
    """Show detailed information about dog records"""
    cursor = conn.cursor()
    
    if dog_name:
        cursor.execute(f"""
            SELECT d.DogID, d.DogName, d.Breed, d.Owner,
                   COUNT(r.ResultID) as ResultCount
            FROM [{SCHEMA}].[Dogs] d
            LEFT JOIN [{SCHEMA}].[Results] r ON d.DogID = r.DogID
            WHERE d.DogName = ?
            GROUP BY d.DogID, d.DogName, d.Breed, d.Owner
            ORDER BY d.DogID
        """, dog_name)
    else:
        cursor.execute(f"""
            SELECT d.DogID, d.DogName, d.Breed, d.Owner,
                   COUNT(r.ResultID) as ResultCount
            FROM [{SCHEMA}].[Dogs] d
            LEFT JOIN [{SCHEMA}].[Results] r ON d.DogID = r.DogID
            GROUP BY d.DogID, d.DogName, d.Breed, d.Owner
            ORDER BY d.DogName, d.DogID
        """)
    
    dogs = cursor.fetchall()
    
    if dogs:
        print(f"\n{'DogID':<8} {'Dog Name':<40} {'Breed':<25} {'Owner':<30} {'Results':<8}")
        print("-" * 120)
        for row in dogs:
            dog_id, name, breed, owner, result_count = row
            print(f"{dog_id:<8} {str(name)[:39]:<40} {str(breed)[:24]:<25} {str(owner)[:29]:<30} {result_count:<8}")
    else:
        print("\nNo dog records found.")

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Consolidate dog records to ensure uniqueness across all events'
    )
    parser.add_argument(
        'action',
        choices=['analyze', 'consolidate', 'stats', 'details'],
        help='Action: analyze (find duplicates), consolidate (merge duplicates), stats (show statistics), details (show all dogs)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Execute consolidation (default is dry run)'
    )
    parser.add_argument(
        '--dog-name',
        type=str,
        help='Filter by specific dog name (for details action)'
    )
    
    args = parser.parse_args()
    
    print("=" * 100)
    print("FastCAT Dog Consolidation Script")
    print("=" * 100)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        if args.action == 'analyze':
            duplicates = analyze_dog_duplicates(conn)
            if duplicates:
                print(f"\nTotal: {len(duplicates)} duplicate dog records (same name, breed, and owner)")
        
        elif args.action == 'stats':
            stats = get_dog_statistics(conn)
            total_dogs, unique_names, unique_breeds, unique_owners, unique_combinations, potential_dups = stats
            print("\nDog Statistics:")
            print(f"  Total dog records: {total_dogs:,}")
            print(f"  Unique dog names: {unique_names:,}")
            print(f"  Unique breeds: {unique_breeds:,}")
            print(f"  Unique owners: {unique_owners:,}")
            print(f"  Unique (Name, Breed, Owner) combinations: {unique_combinations:,}")
            print(f"  Potential duplicates (same name, breed, owner): {potential_dups:,}")
            
            # Get results statistics
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Results]")
            total_results = cursor.fetchone()[0]
            print(f"  Total results: {total_results:,}")
        
        elif args.action == 'consolidate':
            consolidate_dogs_by_name(conn, dry_run=not args.execute)
        
        elif args.action == 'details':
            show_dog_details(conn, args.dog_name)
        
        print("\n" + "=" * 100)
        print("Operation completed successfully!")
        print("=" * 100)
        
    except Exception as e:
        print(f"\nError during operation: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        conn.close()
        print("\nDatabase connection closed.")

if __name__ == "__main__":
    main()



