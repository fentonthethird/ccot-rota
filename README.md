# CCOT consultant rota

Self-rostering for the Critical Care Outreach Team consultant rota.

Three separate pieces, on the principle that the hosted site holds code, never data:

1. `docs/` — the static site published by GitHub Pages.
   - `docs/index.html` is the preference capture app. A consultant opens a personalised link,
     marks the days they can work, and gets a short code to send back. Nothing is uploaded.
   - `docs/rota/` is the published dashboard. It is uploaded as ciphertext and decrypted in the
     browser with a shared passphrase.
2. `engine/` — the allocation engine and admin command line tool. Python, runs only on the
   administrator's machine. Decodes the codes, solves the allocation, exports the workbook and
   builds the encrypted dashboard payload.
3. Admin data lives outside this repository (default `~/Documents/Claude/CCOT Rota App/CCOT Rota Data`), because the
   repository is public.

See `docs/README.md` and `engine/README.md` for details.
