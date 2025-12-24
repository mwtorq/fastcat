"""
Download all AKC result files from index_results pages using event numbers from Events table.
Stores the files in an AKCResults subfolder.
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
    # Use line buffering for immediate output
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    # Also set Python's internal buffering to unbuffered as backup
    sys.stdout = sys.stdout if hasattr(sys.stdout, 'buffer') else sys.stdout
else:
    # Ensure line buffering on other platforms too
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

def get_event_numbers(conn):
    """Get all event numbers from Events table"""
    cursor = conn.cursor()
    
    try:
        cursor.execute(f"""
            SELECT EventNumber, EventName, EventDate, Year
            FROM [{SCHEMA}].[Events]
            ORDER BY Year DESC, EventDate DESC, EventNumber
        """)
        
        events = []
        for row in cursor.fetchall():
            events.append({
                'EventNumber': row[0],
                'EventName': row[1] or '',
                'EventDate': row[2],
                'Year': row[3]
            })
        
        return events
    except pyodbc.Error as e:
        print(f"Error fetching event numbers: {e}")
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
    
    # Skip if file already exists
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
                time.sleep(1)  # Wait before retry
                continue
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {str(e)}"
            if attempt < max_retries:
                time.sleep(2)  # Wait longer for connection errors
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
    print("Download AKC Result Files", flush=True)
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
        # Get all event numbers
        print("\nFetching event numbers from Events table...", flush=True)
        events = get_event_numbers(conn)
        
        if not events:
            print("No events found in database.", flush=True)
            return
        
        print(f"Found {len(events)} events to download", flush=True)
        
        # Download files
        print("\n" + "-" * 80, flush=True)
        print("Downloading result files...", flush=True)
        print("-" * 80, flush=True)
        
        success_count = 0
        exists_count = 0
        error_count = 0
        errors = []
        start_time = time.time()
        
        for i, event in enumerate(events, 1):
            event_number = event['EventNumber']
            event_name = event['EventName']
            event_date = event['EventDate']
            year = event['Year']
            
            # Show progress every 10 events or for new downloads
            show_details = (i % 10 == 0) or (i == 1) or (i == len(events))
            
            if show_details:
                print(f"\n[{i}/{len(events)}] Event {event_number} ({year or 'N/A'})", flush=True)
                if event_name:
                    print(f"  Name: {event_name[:60]}", flush=True)
            
            result = download_result_file(event_number, event_name, event_date, year, str(output_folder))
            
            if result['status'] == 'success':
                success_count += 1
                if show_details:
                    print(f"  [OK] Downloaded: {os.path.basename(result['filepath'])} ({result['size']:,} bytes)", flush=True)
            elif result['status'] == 'exists':
                exists_count += 1
                # Only show exists message for first few or every 50th
                if exists_count <= 5 or exists_count % 50 == 0:
                    print(f"  [-] Already exists: {os.path.basename(result['filepath'])}", flush=True)
            else:
                error_count += 1
                error_msg = result.get('error', 'Unknown error')
                print(f"  [ERROR] Event {event_number}: {error_msg}", flush=True)
                errors.append({
                    'event_number': event_number,
                    'error': error_msg
                })
            
            # Progress summary every 50 events
            if i % 50 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                remaining = (len(events) - i) / rate if rate > 0 else 0
                print(f"  Progress: {i}/{len(events)} | Downloaded: {success_count} | Exists: {exists_count} | Errors: {error_count} | ETA: {remaining:.0f}s", flush=True)
            
            # Be polite - small delay between requests
            if i < len(events):
                time.sleep(0.5)
        
        # Summary
        print("\n" + "=" * 80)
        print("Download Summary")
        print("=" * 80)
        print(f"Total events: {len(events)}")
        print(f"Successfully downloaded: {success_count}")
        print(f"Already existed: {exists_count}")
        print(f"Errors: {error_count}")
        
        if errors:
            print(f"\nErrors encountered:")
            for err in errors[:10]:  # Show first 10 errors
                print(f"  Event {err['event_number']}: {err['error']}")
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more errors")
        
        print(f"\nFiles saved to: {output_folder.absolute()}")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print(f"\n\nDownload interrupted by user.")
        elapsed = time.time() - start_time if 'start_time' in locals() else 0
        print(f"  Progress: {i if 'i' in locals() else 0}/{len(events) if 'events' in locals() else 0} events processed")
        print(f"  Downloaded: {success_count if 'success_count' in locals() else 0}")
        print(f"  Already existed: {exists_count if 'exists_count' in locals() else 0}")
        print(f"  Errors: {error_count if 'error_count' in locals() else 0}")
        if elapsed > 0:
            print(f"  Time elapsed: {elapsed:.1f} seconds")
    except Exception as e:
        print(f"\nError during operation: {e}", flush=True)
        import traceback
        traceback.print_exc()
        # Show partial summary even on error
        if 'success_count' in locals():
            print(f"\nPartial summary before error:", flush=True)
            print(f"  Processed: {i if 'i' in locals() else 0} events", flush=True)
            print(f"  Downloaded: {success_count}", flush=True)
            print(f"  Already existed: {exists_count}", flush=True)
            print(f"  Errors: {error_count}", flush=True)
    finally:
        if 'conn' in locals():
            conn.close()
            print("\nDatabase connection closed.", flush=True)

if __name__ == "__main__":
    main()

