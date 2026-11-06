# Example outcomes

```json
{"status":"success","accepted":true,"stats":{"baseline":true,"added":0,"removed":0,"modified":0}}
```

This is an abbreviated illustrative report, not a newly observed municipal result.
The initial accepted snapshot establishes a baseline. A rejected duplicate key
has `status=failed`, no diff and no trusted-head change. A suspicious valid
publication has `status=quarantined`; review it before explicit CLI approval.

Copy examples/public_csv.yaml and replace its example.org placeholder with a real
licensed HTTPS CSV. Run `sentinel run --config your.yaml` from the repository root.
