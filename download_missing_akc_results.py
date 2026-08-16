"""
Download missing AKC result files that were not successfully downloaded.
Identifies events in the database that don't have corresponding HTML files
in the AKCResults folder and downloads only those.
"""

import pyodbc
import requests
import os
from pathlib import Path
import sys
import time
import urllib3
from datetime import datetime
import io

# Fix encoding for Windows console and ensure unbuffered output
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
else:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'
OUTPUT_FOLDER = 'AKCResults'
BASE_URL = "https://www.apps.akc.org/apps/events/search/index_results.cfm"

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

def get_expected_filename(event_number, event_name, year):
    """Generate expected filename for an event"""
    safe_event_name = "".join(c for c in event_name if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
    if not safe_event_name:
        safe_event_name = "Event"
    
    if year:
        filename = f"{year}_{event_number}_{safe_event_name}.html"
    else:
        filename = f"{event_number}_{safe_event_name}.html"
    
    # Remove any invalid filename characters
    filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()
    return filename

def get_missing_events(conn, output_folder):
    """Get events from database that don't have corresponding HTML files"""
    cursor = conn.cursor()
    
    try:
        # Get all events
        cursor.execute(f"""
            SELECT EventNumber, EventName, EventDate, Year
            FROM [{SCHEMA}].[Events]
            ORDER BY Year DESC, EventDate DESC, EventNumber
        """)
        
        all_events = []
        for row in cursor.fetchall():
            all_events.append({
                'EventNumber': row[0],
                'EventName': row[1] or '',
                'EventDate': row[2],
                'Year': row[3]
            })
        
        # Get set of existing filenames
        existing_files = set()
        if os.path.exists(output_folder):
            for filename in os.listdir(output_folder):
                if filename.endswith('.html'):
                    existing_files.add(filename.lower())  # Case-insensitive comparison
        
        # Find missing events by checking if expected filename exists
        missing_events = []
        for event in all_events:
            expected_filename = get_expected_filename(
                event['EventNumber'],
                event['EventName'],
                event['Year']
            )
            
            # Check if file exists (case-insensitive)
            if expected_filename.lower() not in existing_files:
                # Also check if event number appears in any existing filename
                # (in case event name changed or filename format is slightly different)
                event_number = str(event['EventNumber'])
                found = False
                for existing_file in existing_files:
                    if f"_{event_number}_" in existing_file or existing_file.startswith(f"{event['Year'] or ''}_{event_number}_"):
                        found = True
                        break
                
                if not found:
                    missing_events.append(event)
        
        return missing_events
        
    except pyodbc.Error as e:
        print(f"Error fetching events: {e}")
        return []

def build_results_url(event_number):
    """Build the URL for event results page"""
    params = f"?action=event_info&comp_type=FCAT&status=RSLT&int_ref=1&event_number={event_number}&cde_comp_group=FCAT"
    return BASE_URL + params

def download_result_file(event_number, event_name, event_date, year, output_folder, max_retries=2):
    """Download result file for a single event with retry logic"""
    url = build_results_url(event_number)
    
    # Create safe filename
    safe_event_name = "".join(c for c in event_name if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
    if not safe_event_name:
        safe_event_name = "Event"
    
    # Create filename with event number and year
    if year:
        filename = f"{year}_{event_number}_{safe_event_name}.html"
    else:
        filename = f"{event_number}_{safe_event_name}.html"
    
    # Remove any invalid filename characters
    filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()
    filepath = os.path.join(output_folder, filename)
    
    # Skip if file already exists (shouldn't happen, but check anyway)
    if os.path.exists(filepath):
        return {'status': 'exists', 'filepath': filepath, 'event_number': event_number}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.apps.akc.org/apps/events/search/'
    }
    
    # Retry logic for network errors
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=30)
            response.raise_for_status()
            
            # Save the HTML content
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            file_size = os.path.getsize(filepath)
            return {
                'status': 'success',
                'filepath': filepath,
                'event_number': event_number,
                'size': file_size
            }
            
        except requests.exceptions.Timeout as e:
            last_error = f"Timeout: {str(e)}"
            if attempt < max_retries:
                time.sleep(1)
                continue
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {str(e)}"
            if attempt < max_retries:
                time.sleep(2)
                continue
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            # Don't retry for HTTP errors (4xx, 5xx) - they're likely permanent
            break
    
    return {
        'status': 'error',
        'filepath': filepath,
        'event_number': event_number,
        'error': last_error or 'Unknown error'
    }

def main():
    """Main function"""
    print("=" * 80, flush=True)
    print("Download Missing AKC Result Files", flush=True)
    print("=" * 80, flush=True)
    
    # Create output folder
    output_folder = Path(OUTPUT_FOLDER)
    output_folder.mkdir(exist_ok=True)
    print(f"\nOutput folder: {output_folder.absolute()}", flush=True)
    
    # Connect to database
    print(f"\nConnecting to {SERVER}.{DATABASE}...", flush=True)
    conn = get_connection()
    print("Connected successfully.", flush=True)
    
    try:
        # Identify missing events
        print("\nIdentifying missing HTML files...", flush=True)
        missing_events = get_missing_events(conn, str(output_folder))
        
        if not missing_events:
            print("No missing files found. All events have corresponding HTML files.", flush=True)
            return
        
        print(f"Found {len(missing_events)} missing HTML files to download", flush=True)
        
        # Download files
        print("\n" + "-" * 80, flush=True)
        print("Downloading missing result files...", flush=True)
        print("-" * 80, flush=True)
        
        success_count = 0
        error_count = 0
        errors = []
        start_time = time.time()
        
        for i, event in enumerate(missing_events, 1):
            event_number = event['EventNumber']
            event_name = event['EventName']
            event_date = event['EventDate']
            year = event['Year']
            
            # Show details for all events (since we're only downloading missing ones)
            print(f"\n[{i}/{len(missing_events)}] Event {event_number} ({year or 'N/A'})", flush=True)
            if event_name:
                print(f"  Name: {event_name[:60]}", flush=True)
            
            result = download_result_file(event_number, event_name, event_date, year, str(output_folder))
            
            if result['status'] == 'success':
                success_count += 1
                print(f"  [OK] Downloaded: {os.path.basename(result['filepath'])} ({result['size']:,} bytes)", flush=True)
            elif result['status'] == 'exists':
                print(f"  [-] Already exists: {os.path.basename(result['filepath'])}", flush=True)
            else:
                error_count += 1
                error_msg = result.get('error', 'Unknown error')
                print(f"  [ERROR] {error_msg}", flush=True)
                errors.append({
                    'event_number': event_number,
                    'error': error_msg
                })
            
            # Progress summary every 10 events
            if i % 10 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                remaining = (len(missing_events) - i) / rate if rate > 0 else 0
                print(f"  Progress: {i}/{len(missing_events)} | Downloaded: {success_count} | Errors: {error_count} | ETA: {remaining:.0f}s", flush=True)
            
            # Be polite - small delay between requests
            if i < len(missing_events):
                time.sleep(0.5)
        
        # Summary
        print("\n" + "=" * 80, flush=True)
        print("Download Summary", flush=True)
        print("=" * 80, flush=True)
        print(f"Total missing events: {len(missing_events)}", flush=True)
        print(f"Successfully downloaded: {success_count}", flush=True)
        print(f"Errors: {error_count}", flush=True)
        
        if errors:
            print(f"\nErrors encountered:", flush=True)
            for err in errors:
                print(f"  Event {err['event_number']}: {err['error']}", flush=True)
        
        print(f"\nFiles saved to: {output_folder.absolute()}", flush=True)
        print("=" * 80, flush=True)
        
    except KeyboardInterrupt:
        print(f"\n\nDownload interrupted by user.", flush=True)
        elapsed = time.time() - start_time if 'start_time' in locals() else 0
        print(f"  Progress: {i if 'i' in locals() else 0}/{len(missing_events) if 'missing_events' in locals() else 0} events processed", flush=True)
        print(f"  Downloaded: {success_count if 'success_count' in locals() else 0}", flush=True)
        print(f"  Errors: {error_count if 'error_count' in locals() else 0}", flush=True)
        if elapsed > 0:
            print(f"  Time elapsed: {elapsed:.1f} seconds", flush=True)
    except Exception as e:
        print(f"\nError during operation: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        if 'conn' in locals():
            conn.close()
            print("\nDatabase connection closed.", flush=True)

if __name__ == "__main__":
    main()




