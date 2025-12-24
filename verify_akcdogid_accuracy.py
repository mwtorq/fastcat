"""
Verify that existing AKCDogID values in the database are correct by checking against HTML files.

This script:
1. Finds dogs that have AKCDogID set
2. Checks if those AKCDogIDs actually match the dog's name/owner in HTML files
3. Identifies potentially incorrect AKCDogID values
"""

import pyodbc
import sys
from pathlib import Path
import re
from difflib import SequenceMatcher
import csv

# Configuration
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'
AKCRESULTS_FOLDER = r'AKCResults'

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

def normalize_name(name):
    """Normalize a name for comparison"""
    if not name:
        return ''
    return ' '.join(name.split()).lower()

def name_similarity(name1, name2):
    """Calculate similarity between two names (0.0 to 1.0)"""
    if not name1 or not name2:
        return 0.0
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)
    return SequenceMatcher(None, norm1, norm2).ratio()

def extract_dog_entries_from_html(html_file_path):
    """Extract all dog entries (name, owner, dog_id) from a single HTML file"""
    entries = []
    try:
        with open(html_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        link_pattern = r'<a[^>]*class=["\']white["\'][^>]*href=["\']([^"\']*dog_id=([^"\'&]+)[^"\']*)["\'][^>]*>([^<]+)</a>'
        link_matches = re.finditer(link_pattern, content, re.IGNORECASE)
        
        for match in link_matches:
            dog_id = match.group(2).strip()
            link_text_raw = match.group(3).strip()
            match_end = match.end()
            
            link_text = link_text_raw.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
            link_text = ' '.join(link_text.split())
            
            if not dog_id or not link_text:
                continue
            
            # Extract owner
            owner = None
            try:
                search_after = content[match_end:match_end + 800]
                owner_pattern = r'</div>\s*<div[^>]*>[\s\S]*?<i>[^<]*</i>\s*</div>\s*<div[^>]*>\s*(?:&nbsp;)?\s*([^<]+?)(?:</td>|</div>)'
                owner_match = re.search(owner_pattern, search_after, re.IGNORECASE)
                
                if not owner_match:
                    simple_pattern = r'</div>\s*<div[^>]*>\s*(?:&nbsp;)?([^<]+?)(?:</td>|</div>)'
                    owner_match = re.search(simple_pattern, search_after, re.IGNORECASE)
                
                if owner_match:
                    owner_candidate = owner_match.group(1).strip()
                    owner_candidate = owner_candidate.replace('&nbsp;', ' ').replace('&amp;', '&')
                    owner_candidate = ' '.join(owner_candidate.split())
                    
                    if owner_candidate and len(owner_candidate) > 0 and len(owner_candidate) < 200:
                        if not re.search(r'\b(All American Dog|American|Kennel|Club|MPH|pts|mph|valign|colspan|font|face|sans-serif)\b', owner_candidate, re.IGNORECASE):
                            if re.search(r'[A-Za-z]', owner_candidate):
                                owner = owner_candidate
            except Exception:
                owner = None
            
            entries.append({
                'dog_name': link_text,
                'owner': owner,
                'dog_id': dog_id
            })
        
        return entries
    except Exception as e:
        return []

def extract_event_number_from_filename(filename):
    """Extract event number from HTML filename"""
    match = re.search(r'20\d{8}', filename)
    if match:
        return match.group(0)
    return None

def get_dogs_with_akcdogid(conn, limit=None):
    """Get dogs that have AKCDogID set"""
    cursor = conn.cursor()
    try:
        if limit:
            query = f"""
                SELECT TOP {limit} DISTINCT
                    d.DogsID, 
                    d.DogName, 
                    d.Owner,
                    d.AKCDogID,
                    e.EventNumber
                FROM [{SCHEMA}].[Dogs] d
                INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                WHERE d.AKCDogID IS NOT NULL AND d.AKCDogID != ''
                ORDER BY d.DogName, d.Owner
            """
        else:
            query = f"""
                SELECT DISTINCT 
                    d.DogsID, 
                    d.DogName, 
                    d.Owner,
                    d.AKCDogID,
                    e.EventNumber
                FROM [{SCHEMA}].[Dogs] d
                INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
                INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
                WHERE d.AKCDogID IS NOT NULL AND d.AKCDogID != ''
                ORDER BY d.DogName, d.Owner
            """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        return [{
            'DogsID': row[0],
            'DogName': row[1],
            'Owner': row[2],
            'AKCDogID': row[3],
            'EventNumber': str(row[4]) if row[4] else None
        } for row in rows]
    except pyodbc.Error as e:
        print(f"Error querying dogs: {e}")
        return []

def verify_akcdogid_in_html(dog_name, owner, akcdogid, catalog):
    """Verify if the AKCDogID actually matches this dog in HTML files"""
    # First, try exact match
    for entry in catalog:
        if entry.get('dog_id') == akcdogid:
            entry_name = entry.get('dog_name', '')
            entry_owner = entry.get('owner')
            
            name_sim = name_similarity(dog_name, entry_name)
            
            # Check owner match
            owner_match = False
            if owner and entry_owner:
                owner_lower = owner.lower().strip()
                entry_owner_lower = entry_owner.lower().strip()
                if owner_lower in entry_owner_lower or entry_owner_lower in owner_lower:
                    owner_match = True
            
            return {
                'found': True,
                'html_name': entry_name,
                'html_owner': entry_owner,
                'name_similarity': name_sim,
                'owner_match': owner_match,
                'is_correct': name_sim >= 0.85 and (not owner or not entry_owner or owner_match)
            }
    
    return {
        'found': False,
        'html_name': None,
        'html_owner': None,
        'name_similarity': 0.0,
        'owner_match': False,
        'is_correct': False
    }

def main():
    """Main verification function"""
    print("=" * 80)
    print("Verify AKCDogID Accuracy")
    print("=" * 80)
    
    conn = get_connection()
    
    try:
        # Step 1: Get all dogs with AKCDogID
        print("\nStep 1: Getting dogs with AKCDogID set...")
        print("(Checking all dogs for verification - this may take a while)")
        dogs = get_dogs_with_akcdogid(conn, limit=None)
        print(f"Found {len(dogs)} dogs to verify")
        
        if not dogs:
            print("No dogs with AKCDogID found.")
            return
        
        # Step 2: Get event numbers
        event_numbers = {dog['EventNumber'] for dog in dogs if dog['EventNumber']}
        print(f"These dogs have {len(event_numbers)} unique event numbers")
        
        # Step 3: Build catalog from HTML files
        print("\nStep 2: Building catalog from HTML files...")
        script_dir = Path(__file__).parent
        akcresults_folder = script_dir / AKCRESULTS_FOLDER
        
        if not akcresults_folder.exists():
            print(f"ERROR: AKCResults folder not found: {akcresults_folder}")
            return
        
        all_html_files = list(akcresults_folder.glob('*.html'))
        print(f"Found {len(all_html_files)} HTML files")
        
        # Build catalog for relevant events
        catalog = []
        catalog_by_dogid = {}  # dog_id -> entry
        
        for html_file in all_html_files:
            event_num = extract_event_number_from_filename(html_file.name)
            if event_num and event_num in event_numbers:
                entries = extract_dog_entries_from_html(html_file)
                catalog.extend(entries)
                for entry in entries:
                    dog_id = entry.get('dog_id')
                    if dog_id:
                        catalog_by_dogid[dog_id] = entry
        
        print(f"Cataloged {len(catalog)} dog entries")
        print(f"Unique dog_ids in catalog: {len(catalog_by_dogid)}")
        
        # Step 4: Verify each dog's AKCDogID
        print("\nStep 3: Verifying AKCDogID values...")
        
        results = []
        correct = 0
        incorrect = 0
        not_found = 0
        
        for idx, dog in enumerate(dogs, 1):
            if idx % 100 == 0:
                print(f"  Verified {idx}/{len(dogs)} dogs...")
            
            verification = verify_akcdogid_in_html(
                dog['DogName'],
                dog['Owner'],
                dog['AKCDogID'],
                catalog
            )
            
            if verification['found']:
                if verification['is_correct']:
                    correct += 1
                else:
                    incorrect += 1
            else:
                not_found += 1
            
            results.append({
                'DogsID': dog['DogsID'],
                'DogName': dog['DogName'],
                'Owner': dog['Owner'],
                'AKCDogID': dog['AKCDogID'],
                'EventNumber': dog['EventNumber'],
                **verification
            })
        
        # Step 5: Generate report
        print("\nStep 4: Generating verification report...")
        
        report_file = script_dir / 'akcdogid_verification_report.csv'
        
        with open(report_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'DogsID', 'DogName', 'Owner', 'AKCDogID', 'EventNumber',
                'FoundInHTML', 'HTML_Name', 'HTML_Owner', 'NameSimilarity', 
                'OwnerMatch', 'IsCorrect'
            ])
            
            for result in results:
                writer.writerow([
                    result['DogsID'],
                    result['DogName'],
                    result['Owner'] or '',
                    result['AKCDogID'],
                    result['EventNumber'] or '',
                    'Yes' if result['found'] else 'No',
                    result['html_name'] or '',
                    result['html_owner'] or '',
                    f"{result['name_similarity']:.3f}",
                    'Yes' if result['owner_match'] else 'No',
                    'Yes' if result['is_correct'] else 'No'
                ])
        
        print(f"\nReport saved to: {report_file}")
        
        # Step 6: Summary
        print("\n" + "=" * 80)
        print("Verification Summary")
        print("=" * 80)
        print(f"Total dogs verified: {len(results)}")
        print(f"Correct AKCDogID: {correct} ({correct/len(results)*100:.1f}%)")
        print(f"Incorrect AKCDogID: {incorrect} ({incorrect/len(results)*100:.1f}%)")
        print(f"AKCDogID not found in HTML: {not_found} ({not_found/len(results)*100:.1f}%)")
        
        # Show examples of incorrect
        if incorrect > 0:
            print("\n" + "-" * 80)
            print("Sample: Potentially incorrect AKCDogID (first 10)")
            print("-" * 80)
            incorrect_dogs = [r for r in results if r['found'] and not r['is_correct']][:10]
            for r in incorrect_dogs:
                print(f"\n  DB: {r['DogName']} / {r['Owner']}")
                print(f"     AKCDogID: {r['AKCDogID']}")
                print(f"     HTML: {r['html_name']} / {r['html_owner']}")
                print(f"     Similarity: {r['name_similarity']:.3f}, Owner match: {r['owner_match']}")
        
        if not_found > 0:
            print("\n" + "-" * 80)
            print("Sample: AKCDogID not found in HTML (first 10)")
            print("-" * 80)
            not_found_dogs = [r for r in results if not r['found']][:10]
            for r in not_found_dogs:
                print(f"  {r['DogName']} / {r['Owner']} -> AKCDogID: {r['AKCDogID']}")
        
        print("\n" + "=" * 80)
        print("Verification complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nError during operation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
