# Walkthrough

Here's what I fixed and why.

**Clients could see each other's revenue.** The cache stored totals by property ID only, and both tenants have a `prop-001`. Whichever client loaded first, the other got their numbers. The cache key now includes the tenant, and the offline mock data does too.

**Totals were off by a cent.** Revenue went through floats, so amounts like 333.333 + 333.333 + 333.334 didn't land on exactly 1000.00. Money now stays as a decimal rounded to cents, and the API sends it as a string so the frontend can't reintroduce float error.

**Bookings landed in the wrong month.** Month boundaries were calculated in UTC. A check-in late on Feb 29 UTC is actually March in Paris, so months are now based on the property's own timezone.

**The property dropdown showed everyone's properties.** The dashboard now only lists the logged-in tenant's properties, with the right names.

**The dashboard went blank after that change.** The auth code was overwriting the user's tenant ID with `null`, so the dropdown had nothing to show. It now keeps the tenant ID from the login response.

I also added a `.gitignore` for `__pycache__`, `node_modules` and `.env`.
