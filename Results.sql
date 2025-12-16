SELECT [ResultID]
      ,[EventID]
      ,[DogID]
      ,[Speed]
      ,[Time]
      ,[Points]
      ,[Ranking]
      ,[Handicap]
  FROM [FastCAT].[sAKC].[Results]

SELECT r.[ResultID]
      ,r.[EventID]
      ,e.[EventName]
      ,e.[Year]
      ,e.[EventDate]
      ,e.[City]
      ,e.[State]
      ,r.[DogID]
      ,d.[DogName]
      ,d.[Breed]
      ,d.[Owner]
      ,r.[Speed]
      ,r.[Time]
      ,r.[Points]
      ,r.[Ranking]
      ,r.[Handicap]
  FROM [FastCAT].[sAKC].[Results] r
  JOIN [FastCAT].[sAKC].[Events] e ON r.EventID=e.EventID
  JOIN [FastCAT].[sAKC].[Dogs] d ON r.DogID=d.DogID
  ORDER BY e.Year DESC,e.EventDate DESC,e.EventName,d.Breed,r.DogID

  --delete [FastCAT].[sAKC].[Results]