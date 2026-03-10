# SESSION_CHECKLIST

Generated: 2026-02-11T18:21:54.670042+00:00

## Smoke Run
1. `POST http://localhost:8000/api/v1/admin/reserve/topup?gameType=crossword&targetCount=30`
   - Status: 200
   - Summary: jobId=job_reserve_topup_crossword_aa99eb7ff0 gameType=crossword inserted=0 reserveBefore=30 reserveAfter=30
2. `POST http://localhost:8000/api/v1/admin/reserve/topup?gameType=cryptic&targetCount=30`
   - Status: 200
   - Summary: jobId=job_reserve_topup_cryptic_1dcfd4ebbd gameType=cryptic inserted=0 reserveBefore=46 reserveAfter=46
3. `POST http://localhost:8000/api/v1/admin/publish/daily?gameType=crossword`
   - Status: 200
   - Summary: status=already_published gameType=crossword date=2026-02-11 puzzleId=seed_crossword_20260212_0_78a46f
4. `POST http://localhost:8000/api/v1/admin/publish/daily?gameType=cryptic`
   - Status: 200
   - Summary: status=already_published gameType=cryptic date=2026-02-11 puzzleId=puz_cryptic_20260212_4a905f2db1
5. `GET http://localhost:8000/api/v1/puzzles/daily?gameType=crossword`
   - Status: 200
   - Summary: id=seed_crossword_20260213_1_e87b98 gameType=crossword date=2026-02-12 title=Reserve Puzzle 2026-02-12
6. `GET http://localhost:8000/api/v1/puzzles/daily?gameType=cryptic&redact_answers=true`
   - Status: 200
   - Summary: id=puz_cryptic_20260212_4a905f2db1 gameType=cryptic date=2026-02-11 title=Cryptic Reserve 2026-02-11 · Snivy
7. `POST http://localhost:8000/api/v1/puzzles/cryptic/telemetry`
   - Status: 200
   - Summary: eventId=11 puzzleId=puz_cryptic_20260212_4a905f2db1 eventType=clue_view

## Raw Output Snippets
### `POST /admin/reserve/topup?gameType=crossword&targetCount=30`
```json
{"items":[{"jobId":"job_reserve_topup_crossword_aa99eb7ff0","gameType":"crossword","today":"2026-02-11","targetCount":30,"reserveCountBefore":30,"reserveCountAfter":30,"inserted":0,"rankerModelVersion":null}],"errors":[],"timezone":"Europe/London"}
```

### `POST /admin/reserve/topup?gameType=cryptic&targetCount=30`
```json
{"items":[{"jobId":"job_reserve_topup_cryptic_1dcfd4ebbd","gameType":"cryptic","today":"2026-02-11","targetCount":30,"reserveCountBefore":46,"reserveCountAfter":46,"inserted":0,"rankerModelVersion":"cryptic-ranker-20260211155123-ed35eb"}],"errors":[],"timezone":"Europe/London"}
```

### `POST /admin/publish/daily?gameType=crossword`
```json
{"status":"already_published","gameType":"crossword","date":"2026-02-11","puzzleId":"seed_crossword_20260212_0_78a46f","sourceDate":null,"reserveCount":30,"reserveThreshold":5,"lowReserve":false,"alertCreated":false}
```

### `POST /admin/publish/daily?gameType=cryptic`
```json
{"status":"already_published","gameType":"cryptic","date":"2026-02-11","puzzleId":"puz_cryptic_20260212_4a905f2db1","sourceDate":null,"reserveCount":46,"reserveThreshold":5,"lowReserve":false,"alertCreated":false}
```

### `GET /puzzles/daily?gameType=crossword`
```json
{"data":{"id":"seed_crossword_20260213_1_e87b98","date":"2026-02-12","gameType":"crossword","title":"Reserve Puzzle 2026-02-12","publishedAt":"2026-02-11T13:14:36.584816+00:00","timezone":"Europe/London","grid":{"width":15,"height":15,"cells":[{"x":0,"y":0,"isBlock":false,"solution":"P","entryIdAcross":"a1","entryIdDown":null},{"x":1,"y":0,"isBlock":false,"solution":"I","entryIdAcross":"a1","entryIdDown":null},{"x":2,"y":0,"isBlock":false,"solution":"K","entryIdAcross":"a1","entryIdDown":null},{"x":3,"y":0,"isBlock":false,"solution":"A","entryIdAcross":"a1","entryIdDown":null},{"x":4,"y":0,"is...
```

### `GET /puzzles/daily?gameType=cryptic&redact_answers=true`
```json
{"data":{"id":"puz_cryptic_20260212_4a905f2db1","date":"2026-02-11","gameType":"cryptic","title":"Cryptic Reserve 2026-02-11 · Snivy","publishedAt":"2026-02-11T15:40:22.434167+00:00","timezone":"Europe/London","grid":{"width":15,"height":15,"cells":[{"x":5,"y":7,"isBlock":false,"solution":null,"entryIdAcross":"a1","entryIdDown":null},{"x":6,"y":7,"isBlock":false,"solution":null,"entryIdAcross":"a1","entryIdDown":null},{"x":7,"y":7,"isBlock":false,"solution":null,"entryIdAcross":"a1","entryIdDown":null},{"x":8,"y":7,"isBlock":false,"solution":null,"entryIdAcross":"a1","entryIdDown":null},{"x":9...
```

### `POST /puzzles/cryptic/telemetry`
```json
{"data":{"id":11,"puzzleId":"puz_cryptic_20260212_4a905f2db1","candidateId":null,"eventType":"clue_view","sessionId":"session-checklist","eventValue":{"source":"SESSION_CHECKLIST.md"},"clientTs":"2026-02-11T18:21:54.662934+00:00","createdAt":"2026-02-11T18:21:54.667049+00:00"}}
```
