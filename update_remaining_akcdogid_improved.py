"""
Improved script to update remaining AKCDogID values with multiple matching strategies.

This script uses more aggressive matching strategies:
1. Multiple similarity thresholds (0.85, 0.80, 0.75, 0.70)
2. Name-only matching when owner doesn't match but name is very close
3. Partial name matching (first few words)
4. Owner-only matching when names are similar enough
"""

import pyodbc
import sys
from pathlib import Path
import re
from difflib import SequenceMatcher
from collections import defaultdict

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
        f'Connection Timeout=30;'
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

def partial_name_match(name1, name2):
    """Check if first few words of names match"""
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)
    words1 = norm1.split()[:3]  # First 3 words
    words2 = norm2.split()[:3]
    
    if not words1 or not words2:
        return False
    
    # Check if all words in shorter list appear in longer list
    shorter = words1 if len(words1) <= len(words2) else words2
    longer = words2 if shorter == words1 else words1
    
    matches = sum(1 for word in shorter if word in longer)
    return matches >= min(2, len(shorter))  # At least 2 words or all if fewer

def owner_matches(html_owner, db_owner):
    """Check if owner from HTML matches owner from database"""
    if not html_owner or not db_owner:
        return False
    
    html_owner_lower = html_owner.lower().strip()
    db_owner_lower = db_owner.lower().strip()
    
    # Direct match
    if db_owner_lower in html_owner_lower or html_owner_lower in db_owner_lower:
        return True
    
    # Split by '/' or ',' and check parts
    html_parts = re.split(r'[/,]', html_owner_lower)
    html_parts = [part.strip() for part in html_parts if part.strip()]
    
    db_parts = re.split(r'[/,]', db_owner_lower)
    db_parts = [part.strip() for part in db_parts if part.strip()]
    
    for db_part in db_parts:
        for html_part in html_parts:
            if db_part in html_part or html_part in db_part:
                return True
    
    return False

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

def find_dog_id_multiple_strategies(dog_name, owner, catalog):
    """
    Try multiple matching strategies to find dog_id:
    1. Exact name + owner match (if both available)
    2. High similarity (0.85+) + owner match
    3. High similarity (0.85+) name only (if owner unavailable or very high similarity)
    4. Medium similarity (0.80+) + owner match
    5. Medium similarity (0.80+) name only (if owner unavailable)
    6. Lower similarity (0.75+) with owner match
    7. Partial name match (first few words) with owner match
    """
    best_match = None
    best_score = 0.0
    best_strategy = None
    
    norm_dog_name = normalize_name(dog_name)
    if not norm_dog_name:
        return None, None, None
    
    for entry in catalog:
        entry_name = entry.get('dog_name', '')
        entry_owner = entry.get('owner')
        entry_dog_id = entry.get('dog_id', '')
        
        if not entry_name or not entry_dog_id:
            continue
        
        name_sim = name_similarity(dog_name, entry_name)
        owner_match = owner_matches(entry_owner, owner) if (owner and entry_owner) else False
        
        # Strategy 1: Very high similarity (0.95+) - accept even without owner
        if name_sim >= 0.95:
            score = name_sim + (0.05 if owner_match else 0.0)
            if score > best_score:
                best_match = entry_dog_id
                best_score = score
                best_strategy = f"Very high similarity ({name_sim:.3f})"
        
        # Strategy 2: High similarity (0.85-0.95) + owner match
        elif name_sim >= 0.85 and owner_match:
            score = name_sim + 0.1
            if score > best_score:
                best_match = entry_dog_id
                best_score = score
                best_strategy = f"High similarity ({name_sim:.3f}) + owner match"
        
        # Strategy 3: High similarity (0.85-0.95) name only (if owner not available)
        elif name_sim >= 0.85 and not owner and not entry_owner:
            score = name_sim
            if score > best_score:
                best_match = entry_dog_id
                best_score = score
                best_strategy = f"High similarity ({name_sim:.3f}) name only"
        
        # Strategy 4: Medium-high similarity (0.80-0.85) + owner match
        elif name_sim >= 0.80 and owner_match:
            score = name_sim + 0.05
            if score > best_score:
                best_match = entry_dog_id
                best_score = score
                best_strategy = f"Medium-high similarity ({name_sim:.3f}) + owner match"
        
        # Strategy 5: Medium similarity (0.75-0.80) + owner match
        elif name_sim >= 0.75 and owner_match:
            score = name_sim + 0.03
            if score > best_score:
                best_match = entry_dog_id
                best_score = score
                best_strategy = f"Medium similarity ({name_sim:.3f}) + owner match"
        
        # Strategy 6: Partial name match + owner match
        elif partial_name_match(dog_name, entry_name) and owner_match:
            score = 0.70 + name_sim * 0.2  # Boost for partial match with owner
            if score > best_score:
                best_match = entry_dog_id
                best_score = score
                best_strategy = f"Partial name match + owner match ({name_sim:.3f})"
    
    return best_match, best_score, best_strategy

def update_akcdogid(conn, dogsid, akcdogid):
    """Update AKCDogID for a dog"""
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE [{SCHEMA}].[Dogs]
            SET AKCDogID = ?
            WHERE DogsID = ?
        """, akcdogid, dogsid)
        conn.commit()
        return cursor.rowcount > 0
    except pyodbc.Error as e:
        print(f"    Error updating AKCDogID: {e}")
        try:
            conn.rollback()
        except:
            pass
        return False

def main():
    """Main function"""
    print("=" * 80)
    print("Update Remaining AKCDogID with Improved Matching")
    print("=" * 80)
    
    conn = get_connection()
    
    try:
        # Step 1: Get dogs with NULL AKCDogID
        print("\nStep 1: Finding dogs with NULL AKCDogID...")
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT DISTINCT 
                d.DogsID, 
                d.DogName, 
                d.Owner
            FROM [{SCHEMA}].[Dogs] d
            INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
            WHERE d.AKCDogID IS NULL
            ORDER BY d.DogName, d.Owner
        """)
        rows = cursor.fetchall()
        dogs = [{'DogsID': row[0], 'DogName': row[1], 'Owner': row[2]} for row in rows]
        print(f"Found {len(dogs)} dogs with NULL AKCDogID")
        
        if not dogs:
            print("No dogs to update.")
            return
        
        # Step 2: Get event numbers
        print("\nStep 2: Getting event numbers...")
        cursor.execute(f"""
            SELECT DISTINCT e.EventNumber
            FROM [{SCHEMA}].[Events] e
            INNER JOIN [{SCHEMA}].[Results] r ON e.EventID = r.EventID
            INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
            WHERE d.AKCDogID IS NULL
        """)
        event_numbers = {str(row[0]) for row in cursor.fetchall()}
        print(f"Found {len(event_numbers)} relevant event numbers")
        
        # Step 3: Build catalog
        print("\nStep 3: Building catalog from HTML files...")
        script_dir = Path(__file__).parent
        akcresults_folder = script_dir / AKCRESULTS_FOLDER
        
        catalog = []
        html_files = list(akcresults_folder.glob('*.html'))
        
        for html_file in html_files:
            event_num = extract_event_number_from_filename(html_file.name)
            if event_num and event_num in event_numbers:
                entries = extract_dog_entries_from_html(html_file)
                catalog.extend(entries)
        
        print(f"Cataloged {len(catalog)} dog entries from HTML files")
        
        # Step 4: Try improved matching
        print("\nStep 4: Matching dogs using improved strategies...")
        
        updates = []
        not_found = []
        
        for idx, dog in enumerate(dogs, 1):
            if idx % 50 == 0 or idx == 1:
                print(f"[{idx}/{len(dogs)}] Processing... (Found: {len(updates)}, Not found: {len(not_found)})")
            
            dog_id, score, strategy = find_dog_id_multiple_strategies(
                dog['DogName'], 
                dog['Owner'], 
                catalog
            )
            
            if dog_id:
                updates.append({
                    'DogsID': dog['DogsID'],
                    'DogName': dog['DogName'],
                    'Owner': dog['Owner'],
                    'AKCDogID': dog_id,
                    'Score': score,
                    'Strategy': strategy
                })
            else:
                not_found.append(dog)
        
        # Step 5: Show results and ask for confirmation
        print("\n" + "=" * 80)
        print("Matching Results")
        print("=" * 80)
        print(f"Total dogs: {len(dogs)}")
        print(f"Potential matches found: {len(updates)}")
        print(f"Still not found: {len(not_found)}")
        
        if updates:
            print("\nSample matches (first 10):")
            for update in updates[:10]:
                print(f"  {update['DogName']} / {update['Owner']}")
                print(f"    -> {update['AKCDogID']} (Score: {update['Score']:.3f}, Strategy: {update['Strategy']})")
        
        if not_found:
            print("\nStill not found (first 10):")
            for dog in not_found[:10]:
                print(f"  {dog['DogName']} / {dog['Owner']}")
        
        # Step 6: Update database
        if updates:
            print("\n" + "=" * 80)
            print(f"Updating {len(updates)} dogs in database...")
            print("=" * 80)
            
            updated_count = 0
            for update in updates:
                if update_akcdogid(conn, update['DogsID'], update['AKCDogID']):
                    updated_count += 1
                    if updated_count <= 10:
                        print(f"  Updated: {update['DogName']} -> {update['AKCDogID']}")
            
            print(f"\nSuccessfully updated {updated_count} dogs.")
        
        print("\n" + "=" * 80)
        print("Script completed!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nError during operation: {e}")
        import traceback
        traceback.print_exc()
        try:
            conn.rollback()
        except:
            pass
    finally:
        conn.close()

if __name__ == "__main__":
    main()
