"""Check for dogs with NULL or empty AKCDogID using various methods"""
import pyodbc

SERVER = r'localhost\SQLEXPRESS'
DATABASE = 'FastCAT'
SCHEMA = 'sAKC'

conn = pyodbc.connect(
    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
    f'SERVER={SERVER};'
    f'DATABASE={DATABASE};'
    f'Trusted_Connection=yes;'
)

cursor = conn.cursor()

# Check 1: IS NULL
cursor.execute(f'SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE AKCDogID IS NULL')
null_count = cursor.fetchone()[0]
print(f"1. Dogs with AKCDogID IS NULL: {null_count}")

# Check 2: Empty string
cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE AKCDogID = ''")
empty_count = cursor.fetchone()[0]
print(f"2. Dogs with AKCDogID = '': {empty_count}")

# Check 3: NULL or empty
cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE AKCDogID IS NULL OR AKCDogID = ''")
null_or_empty = cursor.fetchone()[0]
print(f"3. Dogs with AKCDogID IS NULL OR '': {null_or_empty}")

# Check 4: LEN check (for whitespace/empty)
cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE LEN(ISNULL(AKCDogID, '')) = 0")
len_zero = cursor.fetchone()[0]
print(f"4. Dogs with LEN(AKCDogID) = 0: {len_zero}")

# Check 5: LTRIM/RTRIM check
cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE LTRIM(RTRIM(ISNULL(AKCDogID, ''))) = ''")
trimmed_empty = cursor.fetchone()[0]
print(f"5. Dogs with trimmed AKCDogID = '': {trimmed_empty}")

# Check 6: Sample some NULL values directly
cursor.execute(f'SELECT TOP 5 DogsID, DogName, Owner, AKCDogID FROM [{SCHEMA}].[Dogs] WHERE AKCDogID IS NULL')
null_samples = cursor.fetchall()
print(f"\n6. Sample dogs with IS NULL (first 5):")
for row in null_samples:
    print(f"   DogsID: {row[0]}, Name: {row[1]}, AKCDogID type: {type(row[3])}, value: {repr(row[3])}")

# Check 7: Check if there are any that have Results
cursor.execute(f"""
    SELECT COUNT(DISTINCT d.DogsID)
    FROM [{SCHEMA}].[Dogs] d
    INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
    WHERE d.AKCDogID IS NULL
""")
with_results_null = cursor.fetchone()[0]
print(f"\n7. Dogs with NULL AKCDogID that have Results: {with_results_null}")

# Check 8: Get total count
cursor.execute(f'SELECT COUNT(*) FROM [{SCHEMA}].[Dogs]')
total = cursor.fetchone()[0]
print(f"\nTotal dogs in database: {total}")

# Check 9: Try getting actual rows
cursor.execute(f'SELECT TOP 10 DogsID, DogName, Owner FROM [{SCHEMA}].[Dogs] WHERE AKCDogID IS NULL')
rows = cursor.fetchall()
print(f"\n9. Sample rows with NULL (first 10): {len(rows)} found")
for row in rows[:5]:
    print(f"   DogsID: {row[0]}, Name: {row[1]}, Owner: {row[2]}")

conn.close()
