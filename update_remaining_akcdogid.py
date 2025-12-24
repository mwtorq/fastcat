"""
Update remaining AKCDogID values for dogs where it is NULL.
Simple approach: exact name matching from HTML files.
"""

import pyodbc
import re
from pathlib import Path

SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'

def get_connection():
    connection_string = (
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'Trusted_Connection=yes;'
    )
    return pyodbc.connect(connection_string)

def normalize_name(name):
    """Normalize a name for comparison"""
    if not name:
        return ''
    return ' '.join(name.split()).lower()

def main():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Step 1: Get dogs with NULL AKCDogID that have results
    print("Step 1: Finding dogs with NULL AKCDogID...")
    cursor.execute(f'''
        SELECT DISTINCT d.DogsID, d.DogName, d.Owner
        FROM [{SCHEMA}].[Dogs] d
        INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
        WHERE d.AKCDogID IS NULL
        ORDER BY d.DogName
    ''')
    dogs = cursor.fetchall()
    print(f"  Found {len(dogs)} dogs with NULL AKCDogID")
    
    if not dogs:
        print("No dogs to update.")
        return
    
    # Step 2: Get event numbers for these dogs
    print("\nStep 2: Getting event numbers for these dogs...")
    cursor.execute(f'''
        SELECT DISTINCT e.EventNumber
        FROM [{SCHEMA}].[Events] e
        INNER JOIN [{SCHEMA}].[Results] r ON e.EventID = r.EventID
        INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
        WHERE d.AKCDogID IS NULL
    ''')
    event_numbers = {str(row[0]) for row in cursor.fetchall()}
    print(f"  Found {len(event_numbers)} relevant event numbers")
    
    # Step 3: Build catalog from HTML files
    print("\nStep 3: Cataloging dog_id values from HTML files...")
    catalog = {}  # dog_name (normalized) -> dog_id
    
    akcresults = Path('AKCResults')
    html_files = []
    for html_file in akcresults.glob('*.html'):
        # Extract event number from filename
        match = re.search(r'20\d{8}', html_file.name)
        if match and match.group(0) in event_numbers:
            html_files.append(html_file)
    
    print(f"  Processing {len(html_files)} HTML files...")
    
    for i, html_file in enumerate(html_files):
        if (i + 1) % 100 == 0:
            print(f"    Processed {i + 1}/{len(html_files)} files, {len(catalog)} entries...")
        
        with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Find all dog_id links
        pattern = r'dog_id=([A-Z0-9]+)[^>]*>([^<]+)</a>'
        for match in re.finditer(pattern, content, re.IGNORECASE):
            dog_id = match.group(1).strip()
            dog_name = match.group(2).strip()
            # Decode HTML entities
            dog_name = dog_name.replace('&nbsp;', ' ').replace('&amp;', '&')
            dog_name = ' '.join(dog_name.split())  # Normalize whitespace
            
            if dog_id and dog_name:
                norm_name = normalize_name(dog_name)
                # Store the most recent dog_id for each name
                catalog[norm_name] = dog_id
    
    print(f"  Catalog complete: {len(catalog)} unique dog names")
    
    # Step 4: Update dogs
    print("\nStep 4: Updating dogs...")
    updated = 0
    not_found = 0
    
    for i, (dogs_id, dog_name, owner) in enumerate(dogs):
        norm_name = normalize_name(dog_name)
        
        if norm_name in catalog:
            dog_id = catalog[norm_name]
            try:
                cursor.execute(f'''
                    UPDATE [{SCHEMA}].[Dogs]
                    SET AKCDogID = ?
                    WHERE DogsID = ?
                ''', dog_id, dogs_id)
                conn.commit()
                updated += 1
            except Exception as e:
                print(f"  Error updating {dog_name}: {e}")
        else:
            not_found += 1
        
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(dogs)} (Updated: {updated}, Not found: {not_found})")
    
    print(f"\nComplete!")
    print(f"  Updated: {updated}")
    print(f"  Not found: {not_found}")
    
    # Show dogs that weren't found
    if not_found > 0:
        print(f"\nDogs not found in HTML files:")
        for dogs_id, dog_name, owner in dogs:
            norm_name = normalize_name(dog_name)
            if norm_name not in catalog:
                print(f"  {dog_name} / {owner}")
    
    conn.close()

if __name__ == '__main__':
    main()
