DENMART ADMIN LOGIN HOTFIX - 2026-10-04

Replace only:
  routes/auth.py

in the existing GitHub project with the included file.

Admin login URL:
  /control

Reason:
The deployed project copy had a stale routes/auth.py that called the removed
routes.admin._dashboard() function after successful authentication. The fixed
file calls routes.admin.dashboard(), which is the current dashboard endpoint.

No Procfile, database reset, APK change, or unrelated file replacement is required.
