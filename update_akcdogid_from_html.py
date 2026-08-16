"""
Update AKCDogID for dogs where it is NULL by scraping dog_id values from HTML files in AKCResults folder.

This script:
1. Finds all dogs in sAKC.Dogs where AKCDogID is NULL
2. Identifies event numbers for events where these dogs have Results entries
3. Catalogs dog_id values only from HTML files matching those event numbers (optimized one-time pass)
4. Cross-references the catalog to find dog_id for each dog using name and owner matching
5. Updates the AKCDogID for matching dogs

The script shows what it's doing and updates the database in batches.
"""

import pyodbc
import sys
import os
from pathlib import Path
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, parse_qs
from difflib import SequenceMatcher

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

def check_connection(conn):
    """Check if database connection is still alive"""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return True
    except (pyodbc.Error, AttributeError):
        return False

def ensure_connection(conn):
    """Ensure database connection is alive, reconnect if needed"""
    if not check_connection(conn):
        print("  Connection lost, reconnecting...")
        try:
            conn.close()
        except:
            pass
        conn = get_connection()
        print("  Reconnected successfully.")
    return conn

def get_dogs_with_null_akcdogid(conn):
    """
    Get all dogs where AKCDogID is NULL or empty.
    Returns dogs with their DogName and Owner for matching.
    """
    cursor = conn.cursor()
    try:
        # Check for NULL, empty string, or whitespace-only
        cursor.execute(f"""
            SELECT DISTINCT 
                d.DogsID, 
                d.DogName, 
                d.Owner
            FROM [{SCHEMA}].[Dogs] d
            INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
            WHERE d.AKCDogID IS NULL OR LTRIM(RTRIM(ISNULL(d.AKCDogID, ''))) = ''
            ORDER BY d.DogName, d.Owner
        """)
        rows = cursor.fetchall()
        dogs = [{
            'DogsID': row[0], 
            'DogName': row[1], 
            'Owner': row[2]
        } for row in rows]
        
        # Also check without JOIN to see if there are any differences
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM [{SCHEMA}].[Dogs] 
            WHERE AKCDogID IS NULL OR LTRIM(RTRIM(ISNULL(AKCDogID, ''))) = ''
        """)
        total_null = cursor.fetchone()[0]
        
        print(f"  Total dogs with NULL/empty AKCDogID (all): {total_null}")
        print(f"  Dogs with NULL/empty AKCDogID that have Results: {len(dogs)}")
        
        return dogs
    except pyodbc.Error as e:
        print(f"Error querying dogs: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_event_numbers_for_dogs_with_null_akcdogid(conn):
    """
    Get distinct EventNumbers for events where dogs with NULL AKCDogID have Results.
    Returns a set of event numbers (as strings).
    """
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT DISTINCT e.EventNumber
            FROM [{SCHEMA}].[Events] e
            INNER JOIN [{SCHEMA}].[Results] r ON e.EventID = r.EventID
            INNER JOIN [{SCHEMA}].[Dogs] d ON r.DogsID = d.DogsID
            WHERE d.AKCDogID IS NULL
        """)
        rows = cursor.fetchall()
        event_numbers = {str(row[0]) for row in rows}
        return event_numbers
    except pyodbc.Error as e:
        print(f"Error querying event numbers: {e}")
        return set()

def normalize_name(name):
    """Normalize a name for comparison (remove extra spaces, convert to lowercase)"""
    if not name:
        return ''
    # Remove extra whitespace and convert to lowercase
    normalized = ' '.join(name.split()).lower()
    return normalized

def name_similarity(name1, name2):
    """Calculate similarity between two names (0.0 to 1.0)"""
    if not name1 or not name2:
        return 0.0
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)
    return SequenceMatcher(None, norm1, norm2).ratio()

def extract_dog_id_from_url(url):
    """Extract dog_id parameter from URL"""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if 'dog_id' in params:
            return params['dog_id'][0]
        return None
    except:
        return None

def owner_matches(html_owner, db_owner):
    """
    Check if owner from HTML matches owner from database.
    Handles cases where HTML has multiple owners separated by '/' or ','
    """
    if not html_owner or not db_owner:
        return False
    
    html_owner_lower = html_owner.lower().strip()
    db_owner_lower = db_owner.lower().strip()
    
    # Direct match
    if db_owner_lower in html_owner_lower:
        return True
    
    # Split HTML owner by '/' or ',' and check if any part matches
    html_parts = re.split(r'[/,]', html_owner_lower)
    html_parts = [part.strip() for part in html_parts if part.strip()]
    
    # Split DB owner similarly
    db_parts = re.split(r'[/,]', db_owner_lower)
    db_parts = [part.strip() for part in db_parts if part.strip()]
    
    # Check if any part from DB owner appears in HTML owner parts
    for db_part in db_parts:
        for html_part in html_parts:
            if db_part in html_part or html_part in db_part:
                return True
    
    return False

def extract_dog_entries_from_html(html_file_path):
    """
    Extract all dog entries (name, owner, dog_id) from a single HTML file.
    Returns a list of dictionaries with 'dog_name', 'owner', and 'dog_id' keys.
    Uses regex to extract dog_id, names, and owners directly from HTML for speed.
    """
    entries = []
    try:
        with open(html_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Use regex to quickly find all links with dog_id - much faster than parsing
        # Pattern: <a class="white" href="/apps/store/index.cfm?...dog_id=XXXXX">DOG NAME</a>
        # More flexible pattern to handle whitespace variations
        link_pattern = r'<a[^>]*class=["\']white["\'][^>]*href=["\']([^"\']*dog_id=([^"\'&]+)[^"\']*)["\'][^>]*>([^<]+)</a>'
        link_matches = re.finditer(link_pattern, content, re.IGNORECASE)
        
        for match in link_matches:
            dog_id = match.group(2).strip()
            link_text_raw = match.group(3).strip()
            match_start = match.start()
            match_end = match.end()
            
            # Decode HTML entities in dog name
            link_text = link_text_raw.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
            link_text = ' '.join(link_text.split())  # Normalize whitespace
            
            if not dog_id or not link_text:
                continue
            
            # Extract owner from HTML after the link
            # Pattern: After the closing </a>, there's typically:
            # - A </div> for the link
            # - A <div> with breed info (optional, in <i> tags)
            # - A <div> with owner info (text after &nbsp; or whitespace, before </div> or </td>)
            owner = None
            try:
                # Look for owner in the next 800 characters after the link (to capture breed div + owner div)
                search_after = content[match_end:match_end + 800]
                
                # Pattern: Find the owner text that appears after the breed div (if present) or directly after link div
                # Owner appears in: <div>&nbsp;OWNER NAME</td> or <div>OWNER NAME</td>
                # Skip breed info which is typically in <i> tags
                
                # First, try to find owner after breed div pattern
                # Pattern: </a></div><div>...breed in <i>...</div><div>...owner...</td>
                owner_pattern = r'</div>\s*<div[^>]*>[\s\S]*?<i>[^<]*</i>\s*</div>\s*<div[^>]*>\s*(?:&nbsp;)?\s*([^<]+?)(?:</td>|</div>)'
                owner_match = re.search(owner_pattern, search_after, re.IGNORECASE)
                
                if not owner_match:
                    # If breed pattern didn't match, try simpler pattern: owner directly after link
                    # Look for <div> with owner text (not in tags, not breed/stats keywords)
                    simple_pattern = r'</div>\s*<div[^>]*>\s*(?:&nbsp;)?([^<]+?)(?:</td>|</div>)'
                    owner_match = re.search(simple_pattern, search_after, re.IGNORECASE)
                
                if owner_match:
                    owner_candidate = owner_match.group(1).strip()
                    # Clean up owner text
                    owner_candidate = owner_candidate.replace('&nbsp;', ' ').replace('&amp;', '&')
                    owner_candidate = ' '.join(owner_candidate.split())  # Normalize whitespace
                    
                    # Filter out obviously wrong matches
                    if owner_candidate and len(owner_candidate) > 0 and len(owner_candidate) < 200:
                        # Additional check: owner shouldn't look like breed info, stats, or be empty
                        if not re.search(r'\b(All American Dog|American|Kennel|Club|MPH|pts|mph|valign|colspan|font|face|sans-serif)\b', owner_candidate, re.IGNORECASE):
                            # Should contain at least one letter (owner names have letters)
                            if re.search(r'[A-Za-z]', owner_candidate):
                                owner = owner_candidate
            except Exception:
                # If owner extraction fails, continue without owner
                owner = None
            
            # Ensure we're creating a proper dictionary entry
            entry_dict = {
                'dog_name': str(link_text) if link_text else '',
                'owner': str(owner) if owner else None,
                'dog_id': str(dog_id) if dog_id else ''
            }
            # Only add if dog_name and dog_id are present
            if entry_dict['dog_name'] and entry_dict['dog_id']:
                entries.append(entry_dict)
        
        return entries
    except Exception as e:
        # Silently skip errors for individual files
        return []

def extract_event_number_from_filename(filename):
    """
    Extract event number from HTML filename.
    Files are named like: "2018_2018000712_Basenji Club of America Inc.html"
    Returns the event number (e.g., "2018000712") or None if not found.
    """
    # Event numbers are typically 10 digits starting with 20
    match = re.search(r'20\d{8}', filename)
    if match:
        return match.group(0)
    return None

def catalog_all_dog_ids(akcresults_folder, event_numbers=None):
    """
    Catalog all dog_id values from HTML files in AKCResults folder.
    If event_numbers is provided, only processes HTML files that match those event numbers.
    Returns a list of dictionaries with 'dog_name', 'owner', and 'dog_id' keys.
    """
    akcresults_path = Path(akcresults_folder)
    
    if not akcresults_path.exists():
        print(f"  ERROR: AKCResults folder not found: {akcresults_folder}")
        return []
    
    all_html_files = list(akcresults_path.glob('*.html'))
    
    # Filter HTML files by event number if provided
    if event_numbers:
        html_files = []
        for html_file in all_html_files:
            event_num = extract_event_number_from_filename(html_file.name)
            if event_num and event_num in event_numbers:
                html_files.append(html_file)
        
        print(f"  Filtering HTML files by event numbers...")
        print(f"    Total HTML files: {len(all_html_files)}")
        print(f"    Relevant event numbers: {len(event_numbers)}")
        print(f"    Matching HTML files: {len(html_files)}")
    else:
        html_files = all_html_files
    
    print(f"  Cataloging dog_id values from {len(html_files)} HTML files...")
    print()
    
    catalog = []
    processed = 0
    files_with_entries = 0
    
    for html_file in html_files:
        entries = extract_dog_entries_from_html(html_file)
        
        if entries:
            catalog.extend(entries)
            files_with_entries += 1
            # Show details for files with entries (but limit output for very large catalogs)
            if files_with_entries <= 20 or files_with_entries % 100 == 0:
                print(f"    [{processed + 1}/{len(html_files)}] {html_file.name}: Found {len(entries)} dog entries (total: {len(catalog)} entries)")
        
        processed += 1
        
        # Progress summary every 100 files
        if processed % 100 == 0:
            print(f"    Progress: {processed}/{len(html_files)} files processed, {len(catalog)} total entries, {files_with_entries} files with entries")
        
        # Show progress every 10 files for first 50 files
        if processed <= 50 and processed % 10 == 0:
            print(f"    ... {processed} files processed, {len(catalog)} entries found so far ...")
    
    print()
    print(f"  Catalog complete:")
    print(f"    - Processed {processed} HTML files")
    print(f"    - Found {len(catalog)} total dog entries")
    print(f"    - {files_with_entries} files contained dog entries")
    print(f"    - {processed - files_with_entries} files had no dog entries")
    
    return catalog

def build_catalog_index(catalog):
    """
    Build an index of the catalog to speed up lookups.
    Creates a dictionary keyed by normalized name first word, with list of entries.
    """
    index = {}
    for entry in catalog:
        # Ensure entry is a dictionary
        if not isinstance(entry, dict):
            continue
            
        try:
            # Use get() to safely access dictionary keys
            dog_name = entry.get('dog_name')
            if not dog_name:
                continue
                
            # Use first word of normalized name as key for faster lookup
            norm_name = normalize_name(dog_name)
            if norm_name:
                first_word = norm_name.split()[0] if norm_name.split() else norm_name
                if first_word not in index:
                    index[first_word] = []
                index[first_word].append(entry)
        except (AttributeError, TypeError):
            # Skip invalid entries (AttributeError for .get() on non-dict, TypeError for other issues)
            continue
    return index

def find_dog_id_in_catalog(catalog, catalog_index, dog_name, owner=None, min_similarity=0.80):
    """
    Search catalog for a dog name and return dog_id if found.
    Uses the index to only check relevant entries.
    Matches on both name and owner when both are available.
    Returns dog_id if found, None otherwise.
    """
    best_match = None
    best_similarity = 0.0
    
    try:
        norm_dog_name = normalize_name(dog_name)
        if not norm_dog_name:
            return None
        
        # Get first word to use as index key
        words = norm_dog_name.split()
        first_word = words[0] if words else norm_dog_name
        
        if not first_word:
            return None
        
        # Get candidates from index (entries with same first word)
        candidates = []
        if isinstance(catalog_index, dict) and first_word in catalog_index:
            index_entries = catalog_index[first_word]
            if isinstance(index_entries, list):
                # Filter to ensure only dictionaries are included
                candidates = [e for e in index_entries if isinstance(e, dict) and 'dog_name' in e and 'dog_id' in e]
        
        # Also check similar first words (for typos/variations)
        # Always check similar keys but limit to avoid performance issues
        if len(first_word) >= 3 and isinstance(catalog_index, dict):
            prefix = first_word[:3]
            # More efficient: iterate directly instead of creating full list first
            similar_count = 0
            for key in catalog_index.keys():
                if isinstance(key, str) and key.startswith(prefix) and key != first_word:
                    index_entries = catalog_index[key]
                    if isinstance(index_entries, list):
                        # Filter to ensure only dictionaries are included
                        new_candidates = [e for e in index_entries if isinstance(e, dict) and 'dog_name' in e and 'dog_id' in e]
                        candidates.extend(new_candidates)
                        similar_count += 1
                        # Limit to 30 similar keys for performance, but always check some
                        if similar_count >= 30:
                            break
        
        # Remove duplicates while preserving order (use dog_id as unique key)
        seen_ids = set()
        unique_candidates = []
        for c in candidates:
            dog_id = c.get('dog_id')
            if dog_id and dog_id not in seen_ids:
                seen_ids.add(dog_id)
                unique_candidates.append(c)
        candidates = unique_candidates
        
        # If no candidates from index, try a broader search on first 5000 entries
        if not candidates and isinstance(catalog, list):
            # Try broader search - look at first 5000 entries
            for e in catalog[:5000]:
                if isinstance(e, dict) and 'dog_name' in e and 'dog_id' in e:
                    candidates.append(e)
        
        # Limit candidates to avoid performance issues
        # Prioritize exact first word matches
        if len(candidates) > 500:
            exact_matches = []
            other_matches = []
            for c in candidates:
                c_name = normalize_name(c.get('dog_name', ''))
                c_first = c_name.split()[0] if c_name.split() else ''
                if c_first == first_word:
                    exact_matches.append(c)
                else:
                    other_matches.append(c)
            # Take all exact matches plus up to 500 total (reduced for performance)
            candidates = exact_matches + other_matches[:max(0, 500 - len(exact_matches))]
        
        # Search through candidates
        for entry in candidates:
            entry_name = entry.get('dog_name')
            entry_owner = entry.get('owner')
            entry_dog_id = entry.get('dog_id')
            
            if not entry_name or not entry_dog_id:
                continue
            
            # Quick check: if names are very different in length, skip expensive similarity calc
            norm_entry_name = normalize_name(entry_name)
            len_diff = abs(len(norm_dog_name) - len(norm_entry_name))
            max_len = max(len(norm_dog_name), len(norm_entry_name))
            # Only skip if length difference is very large (> 75%), allow some variation
            if max_len > 0 and len_diff > max_len * 0.75:
                continue  # Skip if length difference is > 75%, likely not a match
            
            # Check if dog name matches (with similarity threshold)
            name_sim = name_similarity(dog_name, entry_name)
            
            if name_sim >= min_similarity and name_sim > best_similarity:
                # If owner is provided in both DB and HTML, require owner match (strict matching)
                if owner and entry_owner:
                    if owner_matches(entry_owner, owner):
                        # Both name and owner match
                        best_match = entry_dog_id
                        best_similarity = name_sim
                    # If owner doesn't match, skip this entry (strict matching)
                elif owner and not entry_owner:
                    # DB has owner but HTML doesn't - can't verify owner, so use name match only
                    # Accept name match if it meets the similarity threshold
                    best_match = entry_dog_id
                    best_similarity = name_sim
                elif not owner:
                    # No owner in DB to verify - just use name match
                    best_match = entry_dog_id
                    best_similarity = name_sim
    
    except Exception as e:
        # If any error occurs, return None
        return None
    
    return best_match

def update_akcdogid(conn, dogsid, akcdogid):
    """Update AKCDogID for a dog"""
    try:
        # Ensure connection is alive
        conn = ensure_connection(conn)
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
    print("Update AKCDogID from HTML Files")
    print("=" * 80)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...")
    conn = get_connection()
    print("Connected successfully.")
    
    try:
        # Step 1: Get dogs with NULL AKCDogID
        print("\n" + "-" * 80)
        print("Step 1: Finding dogs with NULL AKCDogID")
        print("-" * 80)
        
        dogs = get_dogs_with_null_akcdogid(conn)
        print(f"Found {len(dogs)} dogs with NULL AKCDogID")
        
        if len(dogs) == 0:
            print("No dogs to update. Exiting.")
            return
        
        # Step 2: Get event numbers for events where these dogs have results
        print("\n" + "-" * 80)
        print("Step 2: Finding relevant event numbers")
        print("-" * 80)
        
        event_numbers = get_event_numbers_for_dogs_with_null_akcdogid(conn)
        print(f"Found {len(event_numbers)} event numbers where dogs with NULL AKCDogID have results")
        
        if len(event_numbers) == 0:
            print("  No relevant events found. Exiting.")
            return
        
        # Show sample of event numbers (first 10)
        event_list = sorted(list(event_numbers))
        if len(event_list) <= 10:
            print(f"  Event numbers: {', '.join(event_list)}")
        else:
            print(f"  Event numbers (first 10): {', '.join(event_list[:10])} ... and {len(event_list) - 10} more")
        
        # Step 3: Catalog dog_id values from relevant HTML files only
        print("\n" + "-" * 80)
        print("Step 3: Cataloging dog_id values from relevant HTML files")
        print("-" * 80)
        
        # Get the script directory to find AKCResults folder
        script_dir = Path(__file__).parent
        akcresults_folder = script_dir / AKCRESULTS_FOLDER
        
        catalog = catalog_all_dog_ids(akcresults_folder, event_numbers)
        
        if len(catalog) == 0:
            print("  No dog entries found in HTML files. Exiting.")
            return
        
        # Step 4: Build catalog index for faster lookups
        print("\n" + "-" * 80)
        print("Step 4: Building catalog index for faster lookups")
        print("-" * 80)
        print(f"  Building index from {len(catalog)} catalog entries...")
        catalog_index = build_catalog_index(catalog)
        print(f"  Index built: {len(catalog_index)} index keys")
        
        # Step 5: Search catalog for each dog
        print("\n" + "-" * 80)
        print("Step 5: Searching catalog for dog_id values")
        print("-" * 80)
        print(f"Searching catalog for {len(dogs)} dogs...")
        
        updates = []
        not_found = []
        errors = []
        updated_count = 0
        BATCH_SIZE = 100  # Update database in batches to avoid connection timeouts
        
        for idx, dog in enumerate(dogs, 1):
            # Progress reporting every 10 dogs for better feedback
            if idx % 10 == 0 or idx == 1:
                print(f"[{idx}/{len(dogs)}] Processing... (Found: {len(updates)}, Updated: {updated_count}, Not found: {len(not_found)}, Errors: {len(errors)})")
            
            try:
                dog_id = find_dog_id_in_catalog(catalog, catalog_index, dog['DogName'], dog['Owner'])
                
                if dog_id:
                    updates.append({
                        'DogsID': dog['DogsID'],
                        'DogName': dog['DogName'],
                        'Owner': dog['Owner'],
                        'AKCDogID': dog_id
                    })
                    
                    # Update database in batches to avoid connection timeouts
                    if len(updates) >= BATCH_SIZE:
                        # Ensure connection is alive before batch update
                        conn = ensure_connection(conn)
                        # Update this batch
                        for update in updates:
                            if update_akcdogid(conn, update['DogsID'], update['AKCDogID']):
                                updated_count += 1
                        updates = []  # Clear batch after updating
                else:
                    not_found.append({
                        'DogsID': dog['DogsID'],
                        'DogName': dog['DogName'],
                        'Owner': dog['Owner']
                    })
                    # Don't print individual results, only progress summaries
                    
            except Exception as e:
                errors.append({
                    'DogsID': dog['DogsID'],
                    'DogName': dog['DogName'],
                    'Owner': dog['Owner'],
                    'Error': str(e)
                })
                print(f"  [{idx}/{len(dogs)}] ✗ Error: {e}")
        
        # Step 6: Show summary
        print("\n" + "=" * 80)
        print("Summary")
        print("=" * 80)
        print(f"Total dogs processed: {len(dogs)}")
        print(f"Dogs with dog_id found: {len(updates) + updated_count} (updated: {updated_count}, remaining: {len(updates)})")
        print(f"Dogs not found in HTML files: {len(not_found)}")
        print(f"Errors: {len(errors)}")
        
        if not_found:
            print("\n" + "-" * 80)
            print("Dogs not found in HTML files (first 10):")
            print("-" * 80)
            for dog in not_found[:10]:
                print(f"  {dog['DogName']} / {dog['Owner']}")
            if len(not_found) > 10:
                print(f"  ... and {len(not_found) - 10} more")
        
        if errors:
            print("\n" + "-" * 80)
            print("Errors (first 10):")
            print("-" * 80)
            for error in errors[:10]:
                print(f"  {error['DogName']} / {error['Owner']}: {error['Error']}")
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more")
        
        # Step 7: Update remaining updates in database (final batch)
        # Note: Most updates are already applied in batches during Step 6 to avoid connection timeouts
        if updates:
            print("\n" + "-" * 80)
            print("Step 7: Updating final batch of database records")
            print("-" * 80)
            
            # Ensure connection is alive before final batch update
            conn = ensure_connection(conn)
            for update in updates:
                if update_akcdogid(conn, update['DogsID'], update['AKCDogID']):
                    updated_count += 1
        
        print(f"\nTotal updated: {updated_count} dogs successfully.")
        
        print("\n" + "=" * 80)
        print("Script completed successfully!")
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
        try:
            conn.close()
            print("\nDatabase connection closed.")
        except:
            pass

if __name__ == "__main__":
    main()

