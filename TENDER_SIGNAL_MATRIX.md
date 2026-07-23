# Tender Signal Colour Chart

Tender Designer now uses a shared colour system for dashboard rows, tender rows, and tender detail views.

| Signal | Colour | What it means | Automatic admin email |
| --- | --- | --- | --- |
| Critical | Rose / red tint | Submission is overdue, or the deadline is within 2 days while the tender is still in an early workflow stage. | Yes |
| Warning | Amber tint | Submission is within 7 days, the tender is blocked on RFI work, or an active tender is missing a submission date. | Yes |
| Watch | Blue tint | The tender is active and needs attention, but it is not yet in the danger window. | No |
| Healthy | Green tint | The tender is moving well and still has workable time before submission. | No |
| Completed | Deep green tint | The tender is already submitted or awarded. | No |
| Inactive | Slate tint | The tender is lost or cancelled and should fade into the background. | No |

## Decision Matrix

| Status / date condition | Signal | Reason |
| --- | --- | --- |
| `Lost` or `Cancelled` | Inactive | Closed records should not compete visually with live work. |
| `Submitted` or `Awarded` | Completed | Important, but not urgent. |
| Active tender with no submission date | Warning or Watch | The system cannot judge urgency properly until a date exists. |
| Active tender with a submission date before today | Critical | The tender is now overdue. |
| Due within 2 days and still `New`, `Documents Uploaded`, `Metadata Extracted`, `Items Extracted`, or `RFI Required` | Critical | Too close to deadline for the current workflow stage. |
| Due within 7 days and still `New`, `Documents Uploaded`, `Metadata Extracted`, `Items Extracted`, `RFI Required`, or `Ready For Review` | Warning | Tight deadline window. |
| `RFI Required` with under 14 days left | Warning | Supplier clarifications are still open too close to deadline. |
| `Ready For Review` | Watch | Human review is the main next step. |
| `Quoted` with time left | Healthy | Commercial progress is underway. |
| Active tender outside the warning windows | Healthy | Work can continue without immediate escalation. |

## Admin Warning Emails

The tender monitor agent watches active tenders in the background and emails the configured admin recipients when a tender enters a `Critical` or `Warning` state that has not already been reported for the current signal bucket.
