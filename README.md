# FastCAT Results Database

A comprehensive system for scraping, storing, and analyzing FastCAT (Fast Coursing Ability Test) results from the AKC (American Kennel Club).

## Database Schema

The database uses a third normal form structure with the following tables in the `sAKC` schema:

- **Events**: Event information (event number, name, date, location, etc.)
- **Dogs**: Dog information (name, breed, owner, AKC Dog ID, profile URL)
- **Results**: Individual run results linking Events and Dogs (speed, time, points, ranking, etc.)

## Scripts Overview

Scripts are listed in alphabetical order:

#### `add_computed_columns_results.py`
Converts `Time` and `Handicap` columns to computed columns in the Results table.

**Computed columns:**
- `Time = 204.545 / Speed` (returns NULL if Speed is 0)
- `Handicap = ROUND(Points / Speed, 1)` (returns NULL if Speed is 0)

**Usage:**
```bash
python add_computed_columns_results.py
```

#### `add_dogid_column_and_update.py`
Adds `AKCDogID` column to Dogs table and populates it from Excel result files.

**Process:**
1. Renames existing `DogID` identity column to `DogsID` (if needed)
2. Adds `AKCDogID` as `NVARCHAR(50)` column
3. Reads DogID values from Excel files (2021-2022, 2023-2024, 2025 FastCAT Results.xlsx)
4. Updates Dogs table by matching DogName and Owner

**Note:** Handles alphanumeric AKC registration numbers (e.g., 'MA85130701', 'PR22228406')

**Usage:**
```bash
python add_dogid_column_and_update.py
```

#### `add_dogprofile_column.py`
Adds or converts `DogProfile` column to a computed column in the Dogs table.

**Formula:** Concatenates AKC URL base with AKCDogID value
```
'https://www.apps.akc.org/apps/store/proxy/get_points.cfm?cde_comp_group=CONF&cde_product_type=COMP_REC&regnum=' + AKCDogID
```

**Usage:**
```bash
python add_dogprofile_column.py
```

#### `add_event_location_address_columns.py`
Adds `EventLocation` and `EventAddress` columns to the Events table.

**Usage:**
```bash
python add_event_location_address_columns.py
```

#### `add_mpavg_computed_column.py` (DEPRECATED)
Originally added `MPHAvg` as a computed column. **Note:** This has been superseded by `optimize_mpavg_ranking.py` which uses regular columns for better performance.

#### `add_ranking_computed_column.py` (DEPRECATED)
Originally added `Ranking` as a computed column. **Note:** This has been superseded by `optimize_mpavg_ranking.py` which uses regular columns for better performance.

#### `consolidate_dogs.py`
Consolidates dog records to ensure uniqueness across all events.

**Process:**
1. Analyzes duplicate dog records based on (DogName, Breed, Owner) combination
2. Merges duplicate records
3. Updates all Results records to use a single DogsID per unique combination

**Usage:**
```bash
python consolidate_dogs.py [--dry-run]
```

#### `convert_xlsb_to_xlsx.py`
Converts Excel Binary (.xlsb) files to Excel Open XML (.xlsx) format.

**Usage:**
```bash
python convert_xlsb_to_xlsx.py
```

#### `create_fastcat_tables.py`
Creates or manages FastCAT database tables in the `sAKC` schema.

**Actions:**
- `create`: Create tables if they don't exist
- `drop`: Drop all tables
- `clear`: Clear all data from tables (keeps structure)
- `verify`: Verify that required tables exist
- `recreate`: Drop and recreate tables

**Usage:**
```bash
python create_fastcat_tables.py [create|drop|clear|verify|recreate]
```

#### `download_akc_results.py`
Downloads all AKC result files from index_results pages using event numbers from Events table.

**Process:**
1. Queries Events table for all event numbers
2. Builds URLs for AKC results pages
3. Downloads HTML result pages
4. Saves files to `AKCResults` folder with naming convention: `{Year}_{EventNumber}_{EventName}.html`

**Features:**
- Skips files that already exist
- Retry logic for network errors
- Progress reporting
- Rate limiting (0.5 second delay between requests)

**Usage:**
```bash
python download_akc_results.py
```

#### `download_missing_akc_results.py`
Downloads missing AKC result files that were not successfully downloaded previously.

**Process:**
1. Identifies events in database that don't have corresponding HTML files in AKCResults folder
2. Downloads only those missing files
3. Uses same naming convention as `download_akc_results.py`

**Usage:**
```bash
python download_missing_akc_results.py
```

#### `extract_dog_data.py`
Extracts Fast CAT event results from AKC website with dog registration numbers. The dog_id parameter in the dog URL is the dog registration number.

**Usage:**
```bash
python extract_dog_data.py
```

#### `extract_fcat_results.py`
General-purpose FastCAT results extraction script.

#### `extract_fcat_results_2021_2022.py`
Extracts 2021-2022 FastCAT results.

#### `extract_fcat_results_2023_2024.py`
Extracts 2023-2024 FastCAT results.

#### `extract_fcat_results_2025.py`
Extracts 2025 FastCAT results.

#### `filter_fastcat.py`
Filters Excel files to remove certain rows (e.g., removes rows where year != 2025).

**Note:** This appears to be a utility script for data cleanup/manipulation.

#### `fix_ranking_calculation.py`
Fixes the Ranking calculation in `sp_UpdateMPHAvgAndRanking` stored procedure.

**Issue fixed:** Previous version was incorrectly partitioning by EventDate, causing all results to be ranked as 1.

**Note:** Ranking calculation is computationally expensive (O(n²)) and may take 10-30 minutes for large datasets (1M+ rows).

**Usage:**
```bash
python fix_ranking_calculation.py
```

#### `import_2021_2022_results.py`
Imports 2021-2022 FastCAT Results from Excel into SQL Server database.

**Source:** `Results/2021-2022 FastCAT Results.xlsx`

**Usage:**
```bash
python import_2021_2022_results.py
```

#### `import_2023_2024_results.py`
Imports 2023-2024 FastCAT Results from Excel into SQL Server database.

**Source:** `Results/2023-2024 FastCAT Results.xlsx`

**Usage:**
```bash
python import_2023_2024_results.py
```

#### `import_2025_results.py`
Imports 2025 FastCAT Results from Excel into SQL Server database.

**Source:** `Results/2025 FastCAT Results.xlsx`

**Usage:**
```bash
python import_2025_results.py
```

#### `optimize_mpavg_ranking.py`
**RECOMMENDED:** Optimizes MPHAvg and Ranking calculations by converting from computed columns to regular columns maintained via triggers.

**Improvements:**
- Converts computed columns to regular columns (can be indexed)
- Creates performance indexes
- Creates stored procedure `sp_UpdateMPHAvgAndRanking` for efficient batch updates
- Creates trigger `tr_Results_UpdateMPHAvgRanking` to automatically maintain values
- Populates initial values

**MPHAvg formula:** Average of top 3 Speed values for the same dog in the same year, up to and including the current EventDate.

**Ranking formula:** DENSE_RANK on MPHAvg (descending) within Breed and Year, considering events up to the current EventDate.

**Usage:**
```bash
python optimize_mpavg_ranking.py
```

**Manual update:**
```sql
EXEC [sAKC].[sp_UpdateMPHAvgAndRanking]
```

#### `scrape_and_import_fastcat.py`
Main script for scraping Fast CAT events from AKC Event Calendar and importing results into database.

**Process:**
1. Scrapes event numbers from the calendar for a date range
2. Checks if events already exist in the database
3. Scrapes results for new events
4. Inserts events, dogs, and results into the FastCAT database

**Usage:**
```bash
python scrape_and_import_fastcat.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

#### `scrape_event_calendar_range.py`
Scrapes AKC Event Calendar for Fast CAT events across a date range.

**Features:**
- Takes start and end dates as parameters
- Runs headless (no visible browser window)
- Collects all event numbers and dates

**Usage:**
```bash
python scrape_event_calendar_range.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

#### `update_akcdogid_from_html.py`
Updates `AKCDogID` for dogs where it is NULL by scraping dog_id values from HTML files.

**Process:**
1. Finds all dogs where AKCDogID is NULL
2. Identifies event numbers for events where these dogs have Results entries
3. Catalogs dog_id values from matching HTML files in AKCResults folder
4. Cross-references to find dog_id for each dog using name matching
5. Updates AKCDogID for matching dogs

**Usage:**
```bash
python update_akcdogid_from_html.py
```

## Database Configuration

All scripts use the following configuration:

```python
SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'
```

**Authentication:** Windows Authentication (Trusted_Connection=yes)

## Dependencies

Common dependencies used across scripts:

- `pyodbc`: SQL Server database connectivity
- `pandas`: Data manipulation and Excel file reading
- `requests`: HTTP requests for web scraping
- `beautifulsoup4`: HTML parsing
- `selenium`: Web browser automation
- `openpyxl`: Excel file reading/writing

## Directory Structure

```
fastcat/
├── AKCResults/          # Downloaded HTML result files
├── Results/             # Excel result files
├── *.py                 # Python scripts
└── README.md           # This file
```

## Workflow Examples

### Initial Setup
1. `create_fastcat_tables.py create` - Create database tables
2. `add_computed_columns_results.py` - Add computed columns (Time, Handicap)
3. `add_dogprofile_column.py` - Add DogProfile computed column
4. `optimize_mpavg_ranking.py` - Optimize MPHAvg and Ranking (recommended)

### Importing Historical Data
1. `import_2021_2022_results.py` - Import 2021-2022 data
2. `import_2023_2024_results.py` - Import 2023-2024 data
3. `import_2025_results.py` - Import 2025 data
4. `add_dogid_column_and_update.py` - Add and populate AKCDogID
5. `consolidate_dogs.py` - Clean up duplicate dog records

### Ongoing Data Collection
1. `scrape_and_import_fastcat.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD` - Scrape new events
2. `download_akc_results.py` - Download HTML result pages
3. `update_akcdogid_from_html.py` - Update missing AKCDogID values

### Maintenance
1. `fix_ranking_calculation.py` - Fix ranking if issues occur
2. `download_missing_akc_results.py` - Download any missing HTML files
3. `EXEC [sAKC].[sp_UpdateMPHAvgAndRanking]` - Manually refresh MPHAvg and Ranking

## Notes

- **Performance:** The Ranking calculation is computationally expensive. For large datasets, expect 10-30 minutes for updates.
- **Computed Columns:** Some columns (Time, Handicap, DogProfile) are computed columns that are calculated on-the-fly. MPHAvg and Ranking are stored columns maintained by triggers for better performance.
- **Indexes:** The `optimize_mpavg_ranking.py` script creates several indexes for performance. Ensure these exist before running ranking updates.
