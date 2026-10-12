# Connecting your real accounts

> **These steps are for the version installed on your computer.** The
> [web app](https://hanozpatel.github.io/finance-dashboard/) runs entirely in your
> browser and has no server to hold the secret keys banks require, so there you
> import your bank's CSV export instead (Accounts tab → Import a CSV) — see
> [section 4](#4-apple-card-and-apple-savings--csv-and-by-hand) for how CSV import
> works.

The app runs on made-up demo data until you connect something. Most people's
accounts fall into three groups, and each has one route:

| Your account | Route | Examples |
|---|---|---|
| Checking, savings, credit cards | **Plaid** | Chase, Bank of America, Wells Fargo, Capital One, Amex |
| Brokerages | **SnapTrade** | Robinhood, Fidelity, Schwab, Vanguard, E*TRADE |
| Anything no aggregator reaches | **CSV import or by hand** | Apple Card, Apple Savings |

Both providers have free tiers that cover one household, and neither needs a
business registration.

Everything you enter stays on your machine. Access tokens are encrypted with
AES-256-GCM before they touch the database, and the API only listens on
localhost.

---

## 1. Plaid credentials — once, for every bank and card

1. Sign up at **https://dashboard.plaid.com/signup**.
2. **Team Settings → Keys** gives you a `client_id` and a **Sandbox** secret
   immediately. Sandbox works right away with test logins (`user_good` /
   `pass_good`) if you want to watch the flow work before pointing it at a real
   bank.
3. For real data you want the **Trial plan**. Since 15 April 2026 this is the
   default path for new US and Canadian signups: free, approved automatically
   for most people after identity verification, and good for **10 linked Items**
   — plenty for one household. It includes both products this app uses,
   `transactions` and `investments`.

   If your application gets flagged for manual review, Plaid's team follows up
   by email in two to three business days. Describe it honestly: a personal,
   single-user, read-only financial dashboard.

   Beyond 10 Items, or for products outside the Trial bundle, you would have to
   apply for full Production access. Nothing here needs that.

### Configure

Edit `finance-dashboard/backend/.env`:

```bash
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET=your_production_secret
PLAID_ENV=production
```

Restart the backend (`make backend`, or restart `make dev`). The Accounts tab
should now show both Plaid cards as **Ready**.

---

## 2. Banks and credit cards

Accounts tab → **Link a bank or card**. Do it twice, once per institution:
every bank is a separate login and becomes a separate connection.

1. Search for your bank. Most large banks use OAuth, so Plaid hands you to the
   bank's own login page — you are typing your password into your bank, not into
   this app.
2. Complete the bank's MFA, then choose which accounts to share.
3. Repeat for each bank or card issuer.

This link requests only the `transactions` product, and asks for two years of
history. What you actually get back is whatever the bank exposes, usually 12–24
months.

**The first sync returns about a month, and that is normal.** Plaid hands over
recent transactions immediately and keeps pulling the rest in the background —
the full two years arrives minutes later, not seconds. The connection is saved
either way; press **Sync** again and the backfill lands in one go.

There is no webhook here (nothing on the public internet could reach a laptop),
so the app cannot be told when the backfill is ready. Pressing Sync is how it
finds out. If a newly linked account looks short on history, that is the fix.

After the first link, syncing is incremental — the app stores a cursor per
connection and asks Plaid only for what changed. That includes transactions the
bank later corrects or reverses, which are updated and deleted here to match.
Your own edits are never touched: a restated amount will not undo a category you
set.

---

## 3. Brokerages — via SnapTrade

Brokerages go through **SnapTrade**, which specialises in them — including
Robinhood, which publishes no API of its own and often will not link through
Plaid. Its Personal tier is free for your own household, needs no
business registration, and connects read-only — trading is never requested.

### Get credentials

1. Sign up at **https://snaptrade.com** and choose the Personal tier.
2. From the dashboard, copy the **client ID** and **consumer key**.
3. Put them in `finance-dashboard/backend/.env`:

   ```bash
   SNAPTRADE_CLIENT_ID=your_client_id
   SNAPTRADE_CONSUMER_KEY=your_consumer_key
   ```

The backend watches `.env`, so this takes effect without a restart.

### Link

1. **Accounts** tab → **Connect a brokerage**. A SnapTrade window opens.
2. Pick your brokerage and log in there. Your credentials go to the brokerage,
   not to SnapTrade and not to this app.
3. Close the window. The app imports the accounts automatically when it closes;
   if anything is missed, **Finish linking** does the same thing and is safe to
   press twice.

You get positions, quantities, prices, and cost basis in the **Investments** tab.

### How this differs from the bank links

**There is no user to register.** SnapTrade has two kinds of key, and they work
differently. A **Personal** key — the free tier, with a client id prefixed
`PERS-` — *is* the user: calls are signed with it and nothing else. A
**Commercial** key identifies an application whose end users are registered
separately, each issued a user id and secret.

The app picks the mode from the client id prefix. Set `SNAPTRADE_MODE=personal`
or `SNAPTRADE_MODE=commercial` in `backend/.env` to override that, which you
only need if your id does not follow the prefix convention.

The login also happens on SnapTrade's page rather than in an embedded widget,
and nothing is handed back here when it finishes. That is why linking is two
steps instead of one.

### If your brokerage will not link

Neither fallback blocks the rest of the app:

- **Manual investment account.** Accounts tab → *Add an account by hand* → type
  **Investment**, and enter the portfolio value. Net worth, the house plan, and
  every savings figure stay correct. You lose only per-position detail, and you
  update the balance when you check it.
- **Robinhood's own export.** In the Robinhood app: **Account → menu → Reports
  and Statements → Reports → Generate report**, choose *Account activity* and a
  date range, and pick CSV. Import it from the Accounts tab. That gives you the
  cash-movement history; holdings still need the manual balance above.

---

## 4. Apple Card and Apple Savings — CSV and by hand

Apple Savings and Apple Card are issued by Goldman Sachs, and **Apple permits no
third-party aggregation at all** — not Plaid, not MX, not Yodlee. This is a
policy decision on Apple's side, not a missing feature here. Nobody's app
connects to it.

So it is entered by hand, and the app treats that as a real account rather than
a second-class one.

### Set it up once

**Accounts** tab → **Add an account by hand**:

| Field | Value |
|---|---|
| Institution | `Apple` |
| Account name | `Apple Savings` |
| Type | Cash (checking or savings) |
| Subtype | `savings` |
| Account number | your account number, if you want it recorded |
| Current balance | today's balance from the Wallet app |
| APY | the rate Apple is currently paying |

The account number is stored only in the local SQLite file and is never sent
anywhere; listings show just the last four digits.

Getting the APY right matters more than it looks — it drives the down-payment
projection on the house tab and the "idle cash" finding on Find Savings.

### Keep it current

Two things to do when you check the account, both on the Accounts tab:

- **Balance changed?** Edit it inline in the accounts table. Each edit records a
  net-worth snapshot, so the trend chart stays honest.
- **Interest posted?** Use **Record a transaction**: pick the account, enter the
  amount, leave the category as *Income*, and keep "move the account balance"
  checked. Interest then counts as income rather than vanishing, and your
  savings rate reflects it.

Recording the same amount on the same date twice is detected and skipped, so
there's no harm in being unsure whether you already logged it.

### Apple Card

If you want Apple Card spending in here too: Wallet → the card → **Card
Balance** → pick a month → **Export Transactions**. Import the CSV from the
Accounts tab. The importer recognises Apple's format automatically, including
the fact that Apple signs purchases *positive* where every other bank signs them
negative — check the preview before committing, and purchases should show as
negative amounts.

Overlapping months are safe to re-import; rows already present are skipped.

---

## If it fails

| Symptom | Cause |
|---|---|
| First bank sync returns no transactions | Plaid is still assembling the initial history. The connection is saved. Press **Sync** again in a minute. |
| "The institution requires you to log in again" | The bank invalidated the connection, usually after a password change or an expired consent. Re-link that institution from the Accounts tab; your history is kept. |
| SnapTrade window does not open | The browser blocked the pop-up. Allow pop-ups for localhost and press Connect again. |
| `Authentication credentials were not provided` (403) | The wrong key mode. A personal key cannot register a user; set `SNAPTRADE_MODE=personal` if the prefix on your client id is not `PERS-`. |
| Connected on SnapTrade's page but nothing appeared | Press **Finish linking**. Nothing is sent back to this app when that window closes, so the import is a separate step. |
| Either card still says "Not set up" with the keys filled in | The backend is running from before you edited `.env`. `make dev` now watches the file, but a backend started the old way needs a restart. |
| `PLAID_CLIENT_ID and PLAID_SECRET are not set` | Exactly what it says — check `backend/.env`, not the repo-root `.env.example`. |

---

## What it costs

| | Cost | Notes |
|---|---|---|
| Plaid | Free | Trial plan: 10 Items, includes transactions and investments |
| SnapTrade | Free | Personal tier, one household, read-only |
| Apple / CSV | Free | Your own time, monthly |

---

## Security notes

- Set `FINANCE_MASTER_KEY` in `backend/.env` before linking anything. Without
  it, the key that encrypts your access tokens is stored *in the database it
  protects*, so a copied database file decrypts itself. Generate one with:

  ```bash
  python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
  ```

- Never commit `backend/.env`. It is already gitignored.
- Banks and brokerages that support OAuth take your password on their own
  pages, never in this app.
- Each link asks for one product only — a checking account is never asked for
  brokerage consent, and vice versa. The SnapTrade connection is read-only:
  it can see positions and can never place a trade.
- SnapTrade's user secret is encrypted at rest with the same key as the Plaid
  tokens.
- Disconnecting an account from the Accounts tab destroys the stored token
  immediately. History is kept unless you explicitly delete the account.
