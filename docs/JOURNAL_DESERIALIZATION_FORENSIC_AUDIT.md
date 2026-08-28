# Journal Deserialization Forensic Audit

## 1. Exact Root Exception
The swallowed exception is `pydantic_core._pydantic_core.ValidationError` caused by an `extra_forbidden` error. `DecisionReport` inherits from `DomainModel` which sets `model_config = ConfigDict(extra="forbid")`. Because `ValidationError` inherits from `ValueError`, the broad `except (ValueError, TypeError):` block in `_parse_report` quietly swallows the crash and logs the warning.

## 2. Exact Affected Field/Schema
The deserialization fails on the presence of the `mode_policies` field (a dict). This field was introduced in an intermediate development step just before the final `ModePolicyPresentation` refactor (which introduced the correct `mode_policy_results` tuple).

## 3. Number of Readable/Unreadable Rows
- **Total Rows:** 93
- **Readable Rows:** 92
- **Unreadable Rows:** 1
- **Oldest Unreadable:** Row 93
- **Newest Unreadable:** Row 93

## 4. Old vs New Row Compatibility
Backward compatibility for genuine historical data is fully intact and functioning perfectly. 
Rows 1 through 92 lack both `mode_policies` and `mode_policy_results`. They deserialize safely because `mode_policy_results` was implemented as `Optional` and defaults to `None`. 

## 5. Did `mode_policy_results` Cause This?
Not directly. The final `mode_policy_results` schema implementation is perfectly backward-compatible. The failure is caused strictly by the temporary existence of the `mode_policies` dict on the single transitional record (Row 93). Because Pydantic forbids extra fields, reading this ghost row fails.

## 6. Why Warnings Repeat So Frequently
The dashboard frontend makes 6 concurrent API requests (`/api/latest`, `/api/mode-policies`, `/api/health`, `/api/provider-status`, etc.) every 5 seconds. 
Every one of these endpoints calls `decision_journal.latest()`. 
`latest()` fetches all 93 rows into memory using `.fetchall()` and parses them descending. Since Row 93 is the newest, it always parses it first, fails, logs the warning, and then parses Row 92 (which succeeds and returns). 
6 concurrent API calls × 1 failure logged per call = 6 warnings every 5 seconds (72 warnings per minute).

## 7. WinError 10053 `ConnectionAbortedError`
This error is entirely benign client disconnect behavior. 
Because `ThreadingHTTPServer` handles the 6 concurrent API requests on separate threads, they all queue up synchronously at the `sqlite3` lock inside `latest()`. If the user navigates away or the browser drops the pending HTTP requests before the lock clears, the threads eventually finish the database read and attempt to flush data to a closed socket, resulting in `WinError 10053`.

## 8. FLASK_SECRET Recommendation
This warning is benign and safely ignored for localhost development. The dashboard is currently served entirely via Python's built-in `ThreadingHTTPServer`, which has no session state or secure cookies. A hardcoded secret should not be introduced to source control.

## 9. Minimal Safe Fix
To allow the system to silently accept (but discard) the ghost `mode_policies` field on Row 93 without loosening the strict `extra="forbid"` rule for the rest of the payload, we can simply add a dummy field to `DecisionReport`:
```python
mode_policies: dict | None = Field(default=None, exclude=True)
```
This tells Pydantic to accept the field during read, but exclude it from future writes and processing.

## 10. Rollback Risk Assessment
There is zero risk of data loss. Decision mathematics, core logic, and true historical data (Rows 1-92) remain perfectly stable and compliant. No rollbacks or data wipes are necessary.
