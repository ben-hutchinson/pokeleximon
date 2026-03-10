# API Request/Response Examples

Base URL: `/api/v1`

## Health
### Request
```
GET /health
```

### Response
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

## Daily Puzzle
### Request
```
GET /api/v1/puzzles/daily?date=2026-02-10&gameType=crossword&redact_answers=false
```

### Response
```json
{
  "data": {
    "id": "puz_3f3c2a2e",
    "date": "2026-02-10",
    "gameType": "crossword",
    "title": "Electric Sparks",
    "publishedAt": "2026-02-10T00:00:00+00:00",
    "timezone": "Europe/London",
    "grid": {
      "width": 15,
      "height": 15,
      "cells": [
        { "x": 0, "y": 0, "isBlock": false, "solution": "P", "entryIdAcross": "a1", "entryIdDown": "d1" }
      ]
    },
    "entries": [
      { "id": "a1", "direction": "across", "number": 1, "answer": "PIKACHU", "clue": "Electric-type mascot", "length": 7, "cells": [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0]] }
    ],
    "metadata": {
      "difficulty": "easy",
      "themeTags": ["electric", "mascot"],
      "source": "curated",
      "generatorVersion": "0.1.0"
    }
  },
  "meta": {
    "redactedAnswers": false
  }
}
```

## Puzzle By Id
### Request
```
GET /api/v1/puzzles/puz_3f3c2a2e?redact_answers=true
```

### Response (answers redacted)
```json
{
  "data": {
    "id": "puz_3f3c2a2e",
    "date": "2026-02-10",
    "gameType": "crossword",
    "title": "Electric Sparks",
    "publishedAt": "2026-02-10T00:00:00+00:00",
    "timezone": "Europe/London",
    "grid": {
      "width": 15,
      "height": 15,
      "cells": [
        { "x": 0, "y": 0, "isBlock": false, "solution": null, "entryIdAcross": "a1", "entryIdDown": "d1" }
      ]
    },
    "entries": [
      { "id": "a1", "direction": "across", "number": 1, "answer": "", "clue": "Electric-type mascot", "length": 7, "cells": [[0,0],[1,0],[2,0],[3,0],[4,0],[5,0],[6,0]] }
    ],
    "metadata": {
      "difficulty": "easy",
      "themeTags": ["electric", "mascot"],
      "source": "curated",
      "generatorVersion": "0.1.0"
    }
  },
  "meta": {
    "redactedAnswers": true
  }
}
```

## Archive
### Request
```
GET /api/v1/puzzles/archive?gameType=crossword&limit=30
```

### Response
```json
{
  "data": {
    "items": [
      {
        "id": "puz_3f3c2a2e",
        "date": "2026-02-10",
        "gameType": "crossword",
        "title": "Electric Sparks",
        "difficulty": "easy",
        "publishedAt": "2026-02-10T00:00:00+00:00"
      }
    ],
    "cursor": null,
    "hasMore": false
  }
}
```

## Admin Generate
### Request
```
POST /api/v1/admin/generate?date=2026-02-10&gameType=crossword&force=false
```

### Response
```json
{
  "jobId": "job_generate_stub",
  "status": "queued"
}
```

## Admin Publish
### Request
```
POST /api/v1/admin/publish?date=2026-02-10&gameType=crossword
```

### Response
```json
{
  "status": "queued",
  "date": "2026-02-10",
  "gameType": "crossword"
}
```

## Admin Jobs
### Request
```
GET /api/v1/admin/jobs
```

### Response
```json
{
  "items": []
}
```

## Admin Cryptic Generate (Preview)
### Request
```
POST /api/v1/admin/cryptic/generate?limit=2&topK=2
```

### Response
```json
{
  "items": [
    {
      "answer": "FIRE STONE",
      "answerKey": "FIRESTONE",
      "enumeration": "4,5",
      "sourceType": "item",
      "sourceRef": "item/82",
      "sourceSlug": "fire-stone",
      "normalizationRule": "identity",
      "selected": {
        "clue": "Pokemon item with shorter parts joined (4,5)",
        "mechanism": "charade",
        "rankScore": 21.0,
        "validatorPassed": true,
        "validatorIssues": [],
        "wordplayPlan": "charade components: FIRE + STONE",
        "metadata": {
          "indicator": "with",
          "components": "FIRE|STONE"
        }
      },
      "candidates": []
    }
  ],
  "count": 1,
  "requestedLimit": 2,
  "topK": 2,
  "answerKey": null,
  "includeInvalid": false
}
```

## Admin Cryptic Train Ranker
### Request
```
POST /api/v1/admin/cryptic/train-ranker?promote=true
```

### Response
```json
{
  "jobId": "job_cryptic_ranker_train_abc123def4",
  "model": {
    "id": 1,
    "modelVersion": "cryptic-ranker-20260211162000-abc123",
    "modelType": "ranker",
    "isActive": true,
    "activatedAt": "2026-02-11T16:20:00+00:00",
    "trainedAt": "2026-02-11T16:20:00+00:00",
    "createdAt": "2026-02-11T16:20:00+00:00",
    "config": {},
    "metrics": {}
  }
}
```

## Admin Cryptic Models
### Request
```
GET /api/v1/admin/cryptic/models?limit=10
```

### Response
```json
{
  "items": [
    {
      "id": 1,
      "modelVersion": "cryptic-ranker-20260211162000-abc123",
      "modelType": "ranker",
      "isActive": true
    }
  ]
}
```

## Admin Activate Cryptic Model
### Request
```
POST /api/v1/admin/cryptic/models/cryptic-ranker-20260211162000-abc123/activate
```

### Response
```json
{
  "item": {
    "id": 1,
    "modelVersion": "cryptic-ranker-20260211162000-abc123",
    "isActive": true
  }
}
```

## Cryptic Telemetry
### Request
```
POST /api/v1/puzzles/cryptic/telemetry
```

```json
{
  "puzzleId": "puz_cryptic_20260324_f2e226a6f8",
  "eventType": "guess_submit",
  "sessionId": "sess_abc123",
  "eventValue": {
    "length": 9,
    "matchesLength": true
  },
  "clientTs": "2026-02-11T16:00:00Z"
}
```

### Response
```json
{
  "data": {
    "id": 101,
    "puzzleId": "puz_cryptic_20260324_f2e226a6f8",
    "candidateId": null,
    "eventType": "guess_submit",
    "sessionId": "sess_abc123",
    "eventValue": {
      "length": 9,
      "matchesLength": true
    },
    "clientTs": "2026-02-11T16:00:00+00:00",
    "createdAt": "2026-02-11T16:00:01+00:00"
  }
}
```

## Admin Job By Id
### Request
```
GET /api/v1/admin/jobs/job_generate_stub
```

### Response
```json
{
  "id": "job_generate_stub",
  "status": "queued"
}
```

## Admin Approve/Reject Puzzle
### Request
```
POST /api/v1/admin/puzzles/puz_3f3c2a2e/approve
```

### Response
```json
{
  "id": "puz_3f3c2a2e",
  "status": "approved"
}
```

### Request
```
POST /api/v1/admin/puzzles/puz_3f3c2a2e/reject
```

### Response
```json
{
  "id": "puz_3f3c2a2e",
  "status": "rejected"
}
```
