SELECT [EventID]
      ,[EventNumber]
      ,[EventName]
      ,[EventDate]
      ,[Year]
      ,[City]
      ,[State]
      ,[Location]
      ,[TotalStarters]
  FROM [FastCAT].[sAKC].[Events]

SELECT [EventID]
      ,[EventNumber]
      ,[EventName]
      ,[EventDate]
      ,[Year]
      ,[City]
      ,[State]
      ,[Location]
      ,[TotalStarters]
  FROM [FastCAT].[sAKC].[Events]
  WHERE Year IN (2023,2024)

  --delete [FastCAT].[sAKC].[Events] where year in (2023,2024)
  --delete [FastCAT].[sAKC].[Events] where eventdate='1970-01-01'