"""Find ALL dogs with NULL AKCDogID, including those without Results"""
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

# Check ALL dogs with NULL (no JOIN filter)
print("Checking all dogs with NULL AKCDogID (no Results filter)...")
cursor.execute(f"""
    SELECT DogsID, DogName, Owner, AKCDogID
    FROM [{SCHEMA}].[Dogs] 
    WHERE AKCDogID IS NULL OR AKCDogID = ''
    ORDER BY DogName
""")

rows = cursor.fetchall()
print(f"Found {len(rows)} dogs with NULL/empty AKCDogID")

if len(rows) > 0:
    print("\nFirst 20 dogs:")
    for i, row in enumerate(rows[:20], 1):
        print(f"{i}. DogsID: {row[0]}, Name: {row[1]}, Owner: {row[2]}")
    
    # Check how many have Results
    dogsids = [str(row[0]) for row in rows]
    placeholders = ','.join(['?' for _ in dogsids])
    
    cursor.execute(f"""
        SELECT COUNT(DISTINCT d.DogsID)
        FROM [{SCHEMA}].[Dogs] d
        INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
        WHERE d.DogsID IN ({placeholders})
    """, *dogsids)
    
    with_results = cursor.fetchone()[0]
    print(f"\nOf these {len(rows)} dogs, {with_results} have Results entries")
    
    # Show dogs with Results
    cursor.execute(f"""
        SELECT DISTINCT d.DogsID, d.DogName, d.Owner
        FROM [{SCHEMA}].[Dogs] d
        INNER JOIN [{SCHEMA}].[Results] r ON d.DogsID = r.DogsID
        WHERE d.DogsID IN ({placeholders})
        ORDER BY d.DogName
    """, *dogsids)
    
    with_results_rows = cursor.fetchall()
    print(f"\nDogs with NULL AKCDogID that have Results (first 20):")
    for i, row in enumerate(with_results_rows[:20], 1):
        print(f"{i}. DogsID: {row[0]}, Name: {row[1]}, Owner: {row[2]}")
else:
    print("\nNo dogs found with NULL/empty AKCDogID")

conn.close()
