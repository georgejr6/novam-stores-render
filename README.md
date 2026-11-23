# novam-stores-render

Product-photo worker for NOVAM Stores and DIGITVL Stores. For each draft product it makes photos of the brand's logo on the exact product the customer will receive.
Public repository on purpose: standard GitHub Actions runners are free for public repos. It holds **no keys, no brand data, no client names**.
Secrets live in the repo's Actions secrets: `RENDER_WORKER_SECRET` (shared HMAC secret with the store API) and `PRINTFUL_API_TOKEN` (Mockup Generator only; never an order). The list of store origins is the Actions variable `RENDER_API_BASES`.

## How it works
1. `render.yml` runs every 10 minutes and calls `POST /api/internal/render/claim` on each store origin (signed, see `worker/signing.py`).
2. A claimed job is a **recipe** (v2): product type, the provider's catalog product, per colour the provider variant id and the shots wanted, and the public logo URL.
3. For each colour the worker asks **Printful's Mockup Generator (API v2)** for the shots: one task per colour, logo placed at the real print position (`worker/plans.py`: contain-fit inside the print area, true inches, aspect ratio exact). These are the provider's own catalog photographs, so they match the product by definition. No product is drawn or simulated here.
4. Every photo passes `worker/gate.py` (resolution, not blank, the logo's own colours are present in the picture). A failing photo fails the job; it is never uploaded.
5. Photos are converted to WebP (1000x1000, the provider's native size, never upscaled) and uploaded (`/upload`), then `/complete` finishes the lease. The store attaches them to the draft product.

Rate limits and retries: HTTP 429 and 5xx are retried with the server's `Retry-After` (else exponential back-off); failed jobs are retried by the queue with back-off (5, 20, 80 min) and a per-brand daily cap.

Run a sample by hand: Actions -> render -> Run workflow -> `samples: tee,hoodie,mug` (artifact `renders` holds the images). Samples use a fictional brand (`samples/make_logos.py`). Never run on a laptop (`require_ci`).

## Product types and shots (all looked at by eye; see `worker/plans.py`)
tee, hoodie, crewneck, tote, dad-hat, mug, poster. Shots: `flat`, `angle` (hanger / side), `detail`, `styled` (props or room), and `model` for tee, hoodie and crewneck only.
Types without a reviewed photo plan (heavy tee, long sleeve, snapback, beanie, sticker, ...) get no branded photos: the plain provider photo stays, rather than a weaker image.
A type is only *sellable* after the owner has checked a physical sample; the photos are mockups until then.

## People
Only Printful styles that were reviewed as showing Black or Latino models are used for `model`; never a white model. Everything else is product-only. `RENDER_ON_MODEL=0` on the store switches model photos off.

## Inside labels
Not shown in product photos. Labels are applied at fulfilment, only when the brand has its own; there is never a default tag.

## experimental/blender-procedural
The earlier procedural Blender renders. They looked like plain blanks, not photographs, so **they are not used and must never be shown to customers**. Kept only for reference.
