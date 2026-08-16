"""
Diagnostic script to investigate dogs with NULL AKCDogID that couldn't be matched from HTML files.

This script:
1. Finds all dogs with NULL AKCDogID
2. Attempts various matching strategies to find why they weren't matched
3. Creates a detailed report of unmatched dogs with suggestions
"""

import pyodbc
import sys
from pathlib import Path
import re
from difflib import SequenceMatcher
from collections import defaultdict
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

def get_unmatched_dogs_with_details(conn):
    """Get dogs with NULL AKCDogID and their event information"""
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT DISTINCT 
                d.DogsID, 
                d.DogName, 
                d.Owner,
                e.EventNumber,
                e.EventName,
                e.EventDate
            FROM [{SCHEMA}].[Dogs] d
            INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
            INNER JOIN [{SCHEMA}].[Events] e ON r.EventID = e.EventID
            WHERE d.AKCDogID IS NULL OR d.AKCDogID = ''
            ORDER BY d.DogName, d.Owner, e.EventDate
        """)
        rows = cursor.fetchall()
        return [{
            'DogsID': row[0],
            'DogName': row[1],
            'Owner': row[2],
            'EventNumber': str(row[3]) if row[3] else None,
            'EventName': row[4],
            'EventDate': row[5]
        } for row in rows]
    except pyodbc.Error as e:
        print(f"Error querying dogs: {e}")
        return []

def find_best_candidates_in_catalog(dog_name, owner, catalog, min_similarity=0.70):
    """Find best matching candidates from catalog with detailed info"""
    candidates = []
    norm_dog_name = normalize_name(dog_name)
    
    if not norm_dog_name:
        return candidates
    
    for entry in catalog:
        entry_name = entry.get('dog_name', '')
        entry_owner = entry.get('owner')
        entry_dog_id = entry.get('dog_id', '')
        
        if not entry_name or not entry_dog_id:
            continue
        
        name_sim = name_similarity(dog_name, entry_name)
        
        if name_sim >= min_similarity:
            # Check owner match
            owner_match = False
            if owner and entry_owner:
                owner_lower = owner.lower().strip()
                entry_owner_lower = entry_owner.lower().strip()
                # Simple owner matching
                if owner_lower in entry_owner_lower or entry_owner_lower in owner_lower:
                    owner_match = True
            
            candidates.append({
                'dog_id': entry_dog_id,
                'html_name': entry_name,
                'html_owner': entry_owner,
                'name_similarity': name_sim,
                'owner_match': owner_match,
                'match_score': name_sim + (0.2 if owner_match else 0.0)
            })
    
    # Sort by match score
    candidates.sort(key=lambda x: x['match_score'], reverse=True)
    return candidates[:10]  # Return top 10 candidates

def main():
    """Main diagnostic function"""
    print("=" * 80)
    print("Diagnostic: Investigating Unmatched AKCDogID Dogs")
    print("=" * 80)
    
    conn = get_connection()
    
    try:
        # Step 1: Get unmatched dogs
        print("\nStep 1: Finding dogs with NULL AKCDogID...")
        dogs_details = get_unmatched_dogs_with_details(conn)
        
        # Group by unique dog (DogsID)
        unique_dogs = {}
        for dog in dogs_details:
            dogsid = dog['DogsID']
            if dogsid not in unique_dogs:
                unique_dogs[dogsid] = {
                    'DogsID': dogsid,
                    'DogName': dog['DogName'],
                    'Owner': dog['Owner'],
                    'EventNumbers': set(),
                    'Events': []
                }
            if dog['EventNumber']:
                unique_dogs[dogsid]['EventNumbers'].add(dog['EventNumber'])
                unique_dogs[dogsid]['Events'].append({
                    'EventNumber': dog['EventNumber'],
                    'EventName': dog['EventName'],
                    'EventDate': dog['EventDate']
                })
        
        print(f"Found {len(unique_dogs)} unique dogs with NULL AKCDogID")
        print(f"Total event entries: {len(dogs_details)}")
        
        # Step 2: Build catalog from relevant HTML files
        print("\nStep 2: Building catalog from HTML files...")
        script_dir = Path(__file__).parent
        akcresults_folder = script_dir / AKCRESULTS_FOLDER
        
        if not akcresults_folder.exists():
            print(f"ERROR: AKCResults folder not found: {akcresults_folder}")
            return
        
        all_html_files = list(akcresults_folder.glob('*.html'))
        
        # Get all event numbers from unmatched dogs
        all_event_numbers = set()
        for dog_data in unique_dogs.values():
            all_event_numbers.update(dog_data['EventNumbers'])
        
        print(f"Looking for HTML files matching {len(all_event_numbers)} event numbers...")
        
        # Filter and catalog HTML files
        catalog = []
        matching_files = 0
        missing_files = []
        
        for html_file in all_html_files:
            event_num = extract_event_number_from_filename(html_file.name)
            if event_num and event_num in all_event_numbers:
                matching_files += 1
                entries = extract_dog_entries_from_html(html_file)
                catalog.extend(entries)
        
        # Check for missing HTML files
        html_event_numbers = set()
        for html_file in all_html_files:
            event_num = extract_event_number_from_filename(html_file.name)
            if event_num:
                html_event_numbers.add(event_num)
        
        for event_num in all_event_numbers:
            if event_num not in html_event_numbers:
                missing_files.append(event_num)
        
        print(f"  Found {matching_files} matching HTML files")
        print(f"  Cataloged {len(catalog)} dog entries")
        print(f"  Missing HTML files for {len(missing_files)} event numbers")
        
        if missing_files:
            print(f"\n  Missing event numbers (first 10): {', '.join(sorted(missing_files)[:10])}")
        
        # Step 3: Try to find matches with relaxed criteria
        print("\nStep 3: Attempting relaxed matching...")
        
        results = []
        for dogsid, dog_data in unique_dogs.items():
            dog_name = dog_data['DogName']
            owner = dog_data['Owner']
            
            # Try to find best candidates
            candidates = find_best_candidates_in_catalog(dog_name, owner, catalog, min_similarity=0.70)
            
            # Check if HTML files exist for this dog's events
            has_html_files = bool(dog_data['EventNumbers'] & html_event_numbers)
            
            result = {
                'DogsID': dogsid,
                'DogName': dog_name,
                'Owner': owner,
                'EventNumbers': ', '.join(sorted(dog_data['EventNumbers'])),
                'EventCount': len(dog_data['EventNumbers']),
                'HasHTMLFiles': has_html_files,
                'BestCandidate': candidates[0] if candidates else None,
                'CandidateCount': len(candidates),
                'AllCandidates': candidates[:5]  # Top 5 for detail
            }
            results.append(result)
        
        # Step 4: Generate report
        print("\nStep 4: Generating diagnostic report...")
        
        report_file = script_dir / 'unmatched_akcdogid_report.csv'
        
        with open(report_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'DogsID', 'DogName', 'Owner', 'EventNumbers', 'EventCount',
                'HasHTMLFiles', 'BestCandidate_DogID', 'BestCandidate_Name',
                'BestCandidate_Owner', 'BestCandidate_Similarity', 'BestCandidate_OwnerMatch',
                'Top5Candidates'
            ])
            
            for result in results:
                best = result['BestCandidate']
                writer.writerow([
                    result['DogsID'],
                    result['DogName'],
                    result['Owner'] or '',
                    result['EventNumbers'],
                    result['EventCount'],
                    'Yes' if result['HasHTMLFiles'] else 'No',
                    best['dog_id'] if best else '',
                    best['html_name'] if best else '',
                    best['html_owner'] if best else '',
                    f"{best['name_similarity']:.3f}" if best else '',
                    'Yes' if (best and best['owner_match']) else 'No',
                    '; '.join([f"{c['dog_id']} ({c['name_similarity']:.2f})" for c in result['AllCandidates']])
                ])
        
        print(f"\nReport saved to: {report_file}")
        
        # Step 5: Summary statistics
        print("\n" + "=" * 80)
        print("Summary Statistics")
        print("=" * 80)
        
        total = len(results)
        
        if total == 0:
            print("No unmatched dogs found! All dogs have AKCDogID set.")
            print("\nThis could mean:")
            print("  - All dogs were successfully matched")
            print("  - Or the query needs adjustment")
            return
        
        has_html = sum(1 for r in results if r['HasHTMLFiles'])
        has_candidates = sum(1 for r in results if r['BestCandidate'])
        has_good_match = sum(1 for r in results if r['BestCandidate'] and r['BestCandidate']['name_similarity'] >= 0.85)
        has_owner_match = sum(1 for r in results if r['BestCandidate'] and r['BestCandidate']['owner_match'])
        
        print(f"Total unmatched dogs: {total}")
        print(f"Dogs with HTML files available: {has_html} ({has_html/total*100:.1f}%)")
        print(f"Dogs with potential candidates (similarity >= 0.70): {has_candidates} ({has_candidates/total*100:.1f}%)")
        print(f"Dogs with good name matches (similarity >= 0.85): {has_good_match} ({has_good_match/total*100:.1f}%)")
        print(f"Dogs with owner matches: {has_owner_match} ({has_owner_match/total*100:.1f}%)")
        print(f"Dogs with no HTML files: {total - has_html} ({(total-has_html)/total*100:.1f}%)")
        print(f"Dogs with no candidates: {total - has_candidates} ({(total-has_candidates)/total*100:.1f}%)")
        
        # Show examples
        print("\n" + "-" * 80)
        print("Sample: Dogs with good matches but not matched (first 10)")
        print("-" * 80)
        good_but_unmatched = [r for r in results if r['BestCandidate'] and r['BestCandidate']['name_similarity'] >= 0.85][:10]
        for r in good_but_unmatched:
            print(f"\n  DB: {r['DogName']} / {r['Owner']}")
            print(f"     Best match: {r['BestCandidate']['html_name']} / {r['BestCandidate']['html_owner']}")
            print(f"     Similarity: {r['BestCandidate']['name_similarity']:.3f}, Owner match: {r['BestCandidate']['owner_match']}")
            print(f"     Dog ID: {r['BestCandidate']['dog_id']}")
        
        print("\n" + "-" * 80)
        print("Sample: Dogs with no HTML files (first 10)")
        print("-" * 80)
        no_html = [r for r in results if not r['HasHTMLFiles']][:10]
        for r in no_html:
            print(f"  {r['DogName']} / {r['Owner']}")
            print(f"    Events: {r['EventNumbers']}")
        
        print("\n" + "=" * 80)
        print("Diagnostic complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nError during operation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    main()

