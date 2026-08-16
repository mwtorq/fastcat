"""Quick script to check AKCDogID status in database"""
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

# Check NULL
cursor.execute(f'SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE AKCDogID IS NULL')
null_count = cursor.fetchone()[0]
print(f"Dogs with NULL AKCDogID: {null_count}")

# Check empty string
cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE AKCDogID = ''")
empty_count = cursor.fetchone()[0]
print(f"Dogs with empty string AKCDogID: {empty_count}")

# Check NULL or empty
cursor.execute(f"SELECT COUNT(*) FROM [{SCHEMA}].[Dogs] WHERE AKCDogID IS NULL OR AKCDogID = ''")
null_or_empty = cursor.fetchone()[0]
print(f"Dogs with NULL or empty AKCDogID: {null_or_empty}")

# Check total
cursor.execute(f'SELECT COUNT(*) FROM [{SCHEMA}].[Dogs]')
total = cursor.fetchone()[0]
print(f"Total dogs: {total}")

# Check with results
cursor.execute(f"""
    SELECT COUNT(DISTINCT d.DogsID)
    FROM [{SCHEMA}].[Dogs] d
    INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
    WHERE d.AKCDogID IS NULL OR d.AKCDogID = ''
""")
with_results = cursor.fetchone()[0]
print(f"Dogs with NULL/empty AKCDogID that have Results: {with_results}")

conn.close()

