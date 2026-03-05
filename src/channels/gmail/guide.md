# Gmail & Calendar Service Account Setup

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Select or create a project
3. Click 'Create Service Account'
4. Give it a name (e.g. 'cogent-gmail')
5. Click 'Done' (no roles needed)
6. Click the service account > 'Keys' tab > 'Add Key' > 'Create new key' > JSON
7. Save the downloaded JSON key file

8. Enable APIs:
   - Gmail: https://console.cloud.google.com/apis/library/gmail.googleapis.com
   - Calendar: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com

9. Enable domain-wide delegation:
   - Go to the service account details
   - Check 'Enable Google Workspace Domain-wide Delegation'
   - Note the Client ID shown

10. Grant access in Google Workspace Admin:
    https://admin.google.com/ac/owl/domainwidedelegation
    - Click 'Add new'
    - Client ID: (from step 9)
    - Scopes (comma-separated):
      https://www.googleapis.com/auth/gmail.readonly,
      https://www.googleapis.com/auth/gmail.send,
      https://www.googleapis.com/auth/calendar,
      https://www.googleapis.com/auth/calendar.events
    - Click 'Authorize'

This command will read the service account JSON key and store it in
Secrets Manager. The cogent impersonates the target email address at runtime.
