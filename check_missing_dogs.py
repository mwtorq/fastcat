"""Check why dogs with NULL AKCDogID aren't being matched from HTML files."""

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

def main():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get dogs with NULL AKCDogID that have results
    cursor.execute(f'''
        SELECT DISTINCT d.DogsID, d.DogName, d.Owner, d.Breed
        FROM [{SCHEMA}].[Dogs] d
        INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
        WHERE d.AKCDogID IS NULL
        ORDER BY d.DogName
    ''')
    dogs = cursor.fetchall()
    print(f'Total dogs with NULL AKCDogID: {len(dogs)}')
    print()
    
    # Check first 10 dogs
    for dog in dogs[:10]:
        dogs_id, dog_name, owner, breed = dog
        print(f'--- {dog_name} / {owner} ---')
        
        # Get event numbers for this dog
        cursor.execute(f'''
            SELECT DISTINCT e.EventNumber
            FROM [{SCHEMA}].[Events] e
            INNER JOIN [{SCHEMA}].[Results] r ON e.EventID = r.EventID
            WHERE r.DogsID = ?
        ''', dogs_id)
        event_numbers = [str(row[0]) for row in cursor.fetchall()]
        print(f'  Event numbers: {event_numbers[:5]}...' if len(event_numbers) > 5 else f'  Event numbers: {event_numbers}')
        
        # Search for this dog in HTML files
        # Extract a unique part of the dog name (first significant word)
        name_parts = dog_name.split()
        # Skip common titles/prefixes
        search_terms = []
        for part in name_parts:
            if len(part) >= 4 and part.upper() not in ['THE', 'AND', 'FOR', 'CAA', 'CAX', 'CGC', 'TKN', 'TKI', 'TKA', 'BCAT', 'DCAT', 'FCAT', 'CGCA', 'CGCU']:
                search_terms.append(part)
                if len(search_terms) >= 2:
                    break
        
        if not search_terms:
            search_terms = [name_parts[0]]
        
        search_term = search_terms[0]
        print(f'  Searching for: {search_term}')
        
        found_in_html = False
        for event_num in event_numbers[:3]:  # Check first 3 events
            for html_file in Path('AKCResults').glob(f'*{event_num}*.html'):
                with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Search for dog_id links containing the search term
                pattern = r'dog_id=([A-Z0-9]+)[^>]*>([^<]*' + re.escape(search_term) + r'[^<]*)</a>'
                matches = list(re.finditer(pattern, content, re.IGNORECASE))
                
                if matches:
                    found_in_html = True
                    for m in matches:
                        html_dog_id = m.group(1)
                        html_dog_name = m.group(2).strip()
                        print(f'  FOUND in {html_file.name}:')
                        print(f'    HTML dog_id: {html_dog_id}')
                        print(f'    HTML name: {html_dog_name}')
                        print(f'    DB name:   {dog_name}')
                        
                        # Check if names match
                        if html_dog_name.lower().strip() == dog_name.lower().strip():
                            print(f'    --> EXACT MATCH! Should have been updated.')
                        else:
                            print(f'    --> Names differ slightly.')
                    break
            if found_in_html:
                break
        
        if not found_in_html:
            print(f'  NOT FOUND in any HTML file')
        print()
    
    conn.close()

if __name__ == '__main__':
    main()
